"""Rule-based tagging, follow-list matching, scoring and the one-line why.

Interests and favorite times only add points; nothing here filters an event out
except the explicit "never" list in profile.json.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from functools import lru_cache

from .core import to_local

TECH = re.compile(r"\b(startup|start-up|founders?|vc|venture|demo day|pitch|hackathon|saas|gtm|devs?|developers?|"
                  r"engineers?|engineering|ai agents?|llms?|genai|gen ai|machine learning|ml |web3|crypto|blockchain|"
                  r"product managers?|b2b|fundrais\w*|yc|y combinator|networking|ai|nvidia|gpus?|robotics|fireside chat|open source|inference|tech week|sdks?|apis?|devtools|afterparty)\b", re.I)
KIDS = re.compile(r"\b(kids?|children|child|toddlers?|ages \d|grades? \d|family storytime|storytime|teens?|tweens?|young readers|middle grade)\b", re.I)
# events that are for children, not just open to them ("Kids free" stays)
FOR_KIDS_TITLE = re.compile(r"\b(story ?time|toddlers?|bab(y|ies)\b(?! shower)|infants?|preschool\w*|kinder\w*|kids?'?s?\b(?!\s+(eat\s+)?free)|"
                            r"children'?s?|trick[- ]or[- ]treat\w*|sat prep|homework|for teens|teen (night|program|club)|tween|lego)", re.I)
FOR_KIDS_TEXT = re.compile(r"\b(for|ages?)\s+(babies|toddlers|infants|preschoolers|little ones|young children|children|kids|[0-9]{1,2}\s*(-|–|to)\s*([0-9]|1[0-2])\b)", re.I)
FOR_KIDS_AUDIENCE = re.compile(r"^(babies|toddlers|preschoolers|kids|children|teens|tweens)\b", re.I)   # SFPL leads with its audience
# a tech, founder or networking event by its title (the body alone is too noisy:
# a choir concert's page can say "developer")
TECH_TITLE = re.compile(r"\b(AI|A\.I\.|agentic|LLMs?|GPUs?|robotics|founders?|startups?|start-ups?|builders?|engineer(s|ing)?|"
                        r"devs?|developers?|hackathon|demo day|pitch (night|competition)|VCs?|venture|networking|tech ?week|"
                        r"#\w*tech\w*|disrupt|saas|b2b|web3|crypto|product managers?|open source|nvidia|openai|vercel|"
                        r"coreweave|y ?combinator|yc)\b", re.I)
DRINKS = re.compile(r"\b(unlimited (beer|wine|drinks)|open bar|drink tickets?|bottomless|mixer|mingle|mingling|happy hour|social)\b", re.I)
FESTIVAL = re.compile(r"\b(fair|festival|fest|street fair|convention|con\b|expo|carnival|block party|market)\b", re.I)


def for_kids(ev: dict) -> bool:
    """A children's event: storytime, toddler music, a kids' festival. Grown-up
    events that let kids in free, or a teen-diary comedy night, don't count."""
    desc = (ev.get("description") or "").strip()
    return bool(FOR_KIDS_TITLE.search(ev.get("title", "")) or FOR_KIDS_TEXT.search(desc[:400]) or FOR_KIDS_AUDIENCE.match(desc))


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[.'’]", "", text)          # R.F. -> rf, Kepler's -> keplers
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@lru_cache(maxsize=4096)
def kw_regex(keyword: str):
    k = norm(keyword)
    return re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")


def matches(keywords, text_norm):
    return [k for k in keywords if kw_regex(k).search(text_norm)]


class Scorer:
    def __init__(self, profile: dict, follow: dict):
        self.profile = profile
        self.people = {}  # normalized name -> (display, kind)
        for kind, key in (("favorite author", "authors_favorite"), ("new book", "authors_new_books"),
                          ("performer", "performers")):
            for name in follow.get(key, []):
                n = norm(name)
                if len(n) >= 5 and " " in n or (kind == "performer" and len(n) >= 4):
                    self.people.setdefault(n, (name, kind))
        self.downrank = {norm(n): n for n in follow.get("authors_downrank", [])}
        self.kids_authors = {norm(n) for n in follow.get("kids_authors", [])}
        self.never = [norm(x) for x in profile.get("never", [])]
        hosted = profile.get("never_paid_hosted") or {}
        self.hosted_sources = set(hosted.get("sources", []))
        self.hosted_kw = [norm(x) for x in hosted.get("keywords", [])]

    def followed_in(self, text_norm):
        hits = []
        for n, (name, kind) in self.people.items():
            if kw_regex(n).search(text_norm):
                hits.append((name, kind))
        return hits

    def paid_hosted(self, ev: dict, title_n: str) -> bool:
        """A paid painting workshop someone runs through Partiful: never.
        Free ones and museums' or studios' own listings are unaffected."""
        if ev.get("source") not in self.hosted_sources or (ev.get("price") or "").lower() == "free":
            return False
        return any(kw_regex(n).search(title_n) for n in self.hosted_kw)

    def price_points(self, ev: dict, full: str, followed: bool, points: float) -> float:
        """Free is a plus; paying has to be worth it. A ticket costs points by
        the dollar, less for someone you follow or a strong match, and a paid
        drinks-and-mingling party costs the most."""
        p = self.profile.get("price") or {}
        price = (ev.get("price") or "").lower()
        if price == "free":
            return p.get("free_boost", 0.3)
        dollars = [float(x) for x in re.findall(r"\$\s?(\d+(?:\.\d\d)?)", price)]
        if not dollars or not p:
            return 0.0
        cost = min(dollars)
        hit = -min(p.get("max_penalty", 3.0), cost / p.get("dollars_per_point", 15))
        if followed:
            hit *= 0.25
        elif points >= 4:
            hit *= 0.5          # a show squarely in your interests can be worth paying for
        if cost >= 15 and DRINKS.search(full):
            hit -= p.get("paid_party_penalty", 2.5)
        return hit

    def score(self, ev: dict, ai_tags: dict | None = None) -> dict | None:
        """Returns the scoring fields for one event, or None if it's on the never list."""
        title_n = norm(ev["title"])
        body_n = norm(" ".join([ev.get("description", ""), ev.get("venue", ""), " ".join(ev.get("tags", [])),
                                " ".join(ev.get("people", []))]))
        full = title_n + " " + body_n
        if any(kw_regex(n).search(full) for n in self.never):
            return None
        if self.paid_hosted(ev, title_n):
            return None
        if self.profile.get("no_kids_events") and for_kids(ev):
            return None
        if self.profile.get("no_tech_events") and TECH_TITLE.search(ev["title"]) and not self.followed_in(title_n):
            return None

        points, reasons, hits = 0.0, [], []
        for key, spec in self.profile["interests"].items():
            in_title = matches(spec["keywords"], title_n)
            in_body = matches(spec["keywords"], body_n)
            if in_title or in_body:
                factor = 1.0 if in_title else 0.6
                points += spec["weight"] * factor
                hits.append((spec["weight"] * factor, key))
        # strongest match first, so the why leads with what the title is about
        interests = [k for _, k in sorted(hits, key=lambda h: -h[0])]
        if ai_tags:
            for key in ai_tags.get("interests", []):
                if key in self.profile["interests"] and key not in interests:
                    interests.append(key)
                    points += self.profile["interests"][key]["weight"] * 0.8
            points += (ai_tags.get("fit", 5) - 5) * 0.5
        # stacking interests is good, but with diminishing returns
        points = min(points, 8.0)

        rt = self.profile.get("reading_tastes")
        if rt and "reading" in interests and matches(rt["keywords"], full):
            points += rt["weight"]
            reasons.append(rt["label"])

        people = self.followed_in(full)
        kids = bool(KIDS.search(full)) or bool(ai_tags and ai_tags.get("kids_only"))
        badge = None
        if people:
            name, kind = people[0]
            if kids and norm(name) in self.kids_authors:
                points += 1.0
            else:
                points += 6.0 if kind in ("favorite author", "performer") else 4.0
                badge = name
        for n, name in self.downrank.items():
            if kw_regex(n).search(full):
                points -= 2.0

        start = to_local(ev["start"])
        time_label = None
        if start and not ev.get("all_day"):
            for t in self.profile.get("favorite_times", []):
                if start.weekday() == t["weekday"] and t["from_hour"] <= start.hour < t["to_hour"]:
                    points += t["boost"]
                    time_label = t["label"]

        is_tech = bool(TECH.search(full)) or bool(ai_tags and ai_tags.get("is_tech"))
        tags = list(interests)
        if is_tech:
            tags.append("tech")
            points += self.profile.get("downrank_tags", {}).get("tech", -1.0)
        if kids:
            tags.append("kids")
            points -= 1.5
        points += self.price_points(ev, full, bool(badge), points)
        if ev.get("sponsored"):
            points -= 0.5
        if ev.get("recurring"):
            points -= 0.3

        labels = [self.profile["interests"][k]["label"] for k in interests[:2]]
        why_parts = []
        if badge:
            why_parts.append(f"⭐ {badge}")
        if labels:
            why_parts.append(" + ".join(labels))
        why_parts += reasons[:1]
        if time_label:
            why_parts.append(time_label)
        if ev.get("city") and ev["city"].lower() not in ("san francisco", "sf"):
            why_parts.append(ev["city"])
        why = (ai_tags or {}).get("why") or " · ".join(why_parts) or "New in your area"
        if badge and not why.startswith("⭐"):
            why = f"⭐ {badge} · {why}"
        return {
            "score": round(points, 2),
            "tags": tags,
            "why": why,
            "followed": badge,
            "followed_kind": people[0][1] if people else None,
            "is_festival": bool(FESTIVAL.search(title_n)),
        }


def best_sub_event(parent: dict, candidates: list[str], profile: dict):
    """Pick the lineup line that best matches the profile (rule-based)."""
    from .core import parse_time
    best, best_pts = None, 0.0
    for line in candidates:
        line = line.strip(" -•·•")
        if not (6 <= len(line) <= 90):
            continue
        n = norm(line)
        pts = sum(spec["weight"] for spec in profile["interests"].values() if matches(spec["keywords"], n))
        if pts > best_pts:
            best, best_pts = line, pts
    if not best or best_pts < 2.0:
        return None
    t = parse_time(best)
    title = re.sub(r"\s*[-–@|]?\s*\d{1,2}(:\d{2})?\s*[ap]\.?m\.?.*$", "", best, flags=re.I).strip(" :-–")
    return {"title": title, "time": f"{t[0]:02d}:{t[1]:02d}" if t else None, "points": best_pts}
