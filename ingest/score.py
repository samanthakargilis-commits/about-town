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
FESTIVAL = re.compile(r"\b(fair|festival|fest|street fair|convention|con\b|expo|carnival|block party|market)\b", re.I)


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

    def followed_in(self, text_norm):
        hits = []
        for n, (name, kind) in self.people.items():
            if kw_regex(n).search(text_norm):
                hits.append((name, kind))
        return hits

    def score(self, ev: dict, ai_tags: dict | None = None) -> dict | None:
        """Returns the scoring fields for one event, or None if it's on the never list."""
        title_n = norm(ev["title"])
        body_n = norm(" ".join([ev.get("description", ""), ev.get("venue", ""), " ".join(ev.get("tags", [])),
                                " ".join(ev.get("people", []))]))
        full = title_n + " " + body_n
        if any(kw_regex(n).search(full) for n in self.never):
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
        if (ev.get("price") or "").lower() == "free":
            points += 0.3
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
