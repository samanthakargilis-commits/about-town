"""SF Funcheap. The site's RSS feed only carries the 10 newest posts with no
event details, so this reads the day pages (sf.funcheap.com/YYYY/MM/DD/, and
their page 2, 3... on a busy day: a Saturday runs to three pages), plus
the city guides on its home page and guide index: the big ones (Fleet Week, Terror
Vault, October street fairs) live there, with a section per event."""
import datetime as dt
import html
import json
import re
from urllib.parse import urlparse

from ..core import BudgetExceeded, Event, clean, find_dates, iso, short_hash
from ..heuristics import article_events, at_time, end_time, link_blocks, price_from

NAME, LABEL = "funcheap", "SF Funcheap"
BASE = "https://sf.funcheap.com"
SKIP = re.compile(r"^/(category|tag|author|page|\d{4}|wp-|feed|submit|about|contact|newsletter|search|region|city-guide)", re.I)
DAYS_AHEAD = 35
PAGES_PER_DAY = 5
MAX_REQUESTS = 260     # 36 days, their extra pages, and the guides
MAX_GUIDES = 25        # read at most twice a day (cached 12 hours)
GUIDE = re.compile(r"^https://sf\.funcheap\.com/city-guide/[^/]+/$")
# a guide's housekeeping sections, not events of their own
NOT_EVENT = re.compile(r"\b(opening week|week (one|two|three|four|five|\d)|halloween week|discount nights?|"
                       r"schedule|tickets?|hours|getting there|transportation|parking|faq|map)\b", re.I)
PHOTO_HOSTS = ("flickr.com", "instagram.com", "facebook.com", "youtube.com", "funcheap.com")
# Funcheap's categories (CSS classes on each post) worth keeping as tags. "Top
# pick" is on most posts, sponsored ones included, so it says little; its annual
# events are the city's big traditions (Fleet Week, the Italian Heritage parade).
CATEGORY_TAGS = {"category-annual-event-2": "annual", "category-top-annual-events": "annual",
                 "category-halloween": "halloween", "category-movies": "film",
                 "category-comedy-event-types-event": "comedy"}


def is_event_url(url):
    p = urlparse(url)
    if p.netloc != "sf.funcheap.com":
        return False
    parts = [x for x in p.path.split("/") if x]
    return len(parts) == 1 and not SKIP.match(p.path) and "-" in parts[0]


def tidy_title(title):
    title = re.sub(r"^(\$\d+ off( tix| tickets)?|free tix|promo code)\s*:\s*", "", title, flags=re.I)
    title = re.sub(r"\s*\((?:SF|San Francisco|oct|nov|dec|jan|feb|mar|apr|may|jun|jul|aug|sep|every|\w+ \d{1,2}[-–]\d{1,2})[^)]*\)\s*$", "", title, flags=re.I)
    title = re.sub(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s*[-–]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?)?:\s*", "", title)
    title = re.sub(r"\s*[-–]\s*(FREE|\$\d+.*)$", "", title, flags=re.I)
    return clean(title)


def blurbs(html_soup) -> dict:
    """Each post's description, from the schema.org data on the day page."""
    out = {}
    for tag in html_soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "Event" and node.get("url"):
                out[node["url"]] = clean(html.unescape(node.get("description") or ""))[:500]
    return out


def category_tags(block) -> list:
    for el in [block, *block.parents]:
        if el.name == "div" and str(el.get("id", "")).startswith("post-"):
            return sorted({CATEGORY_TAGS[c] for c in el.get("class") or [] if c in CATEGORY_TAGS})
    return []


def parse_day(html_soup, day: dt.date):
    events = []
    about = blurbs(html_soup)
    for url, title, text, block in link_blocks(html_soup, BASE, is_event_url):
        title = tidy_title(title)
        recurring = bool(re.search(r"\bevery (mon|tue|wed|thu|fri|sat|sun)", text, re.I))
        start, all_day = at_time(day, text.split(title, 1)[-1] or text)
        end = end_time(start, text) if not all_day else None
        venue = ""
        # read the venue from the element holding "Cost:", not the whole block (the blurb follows it)
        node = block.find(string=re.compile(r"Cost:", re.I))
        meta, el = text, node.parent if node is not None else None
        for _ in range(3):
            if el is None or el is block:
                break
            t = clean(el.get_text(" "))
            if re.search(r"cost:[^|]*\|\s*\S", t, re.I):
                meta = t
                break
            el = el.parent
        m = re.search(r"cost:[^|]*\|\s*([^|]{3,90})", meta, re.I)
        if m:
            venue = clean(m.group(1))
            # the listing's blurb follows the venue with no separator
            venue = re.split(r"(?<=\))\s|\s(?=(?:From|Join|Come|Get|Celebrate|Enjoy|Experience|This|The|Each|Every|Free|Grab|Head|Learn|Watch|See|Don't|It's|Spend|Bring|Take)\b)", venue)[0]
            venue = re.sub(r"\s*\((SF|San Francisco)\)$", "", venue)[:70]
        elif "|" in title:
            title, venue = [clean(x) for x in title.split("|", 1)]
        events.append(Event(
            source=NAME,
            source_id=urlparse(url).path.strip("/") + "@" + day.isoformat(),
            source_url=url,
            title=title.split("|")[0].strip() if "|" in title else title,
            start=iso(start), end=iso(end), all_day=all_day,
            description=about.get(url, ""), venue=venue,
            price=price_from(text), recurring=recurring,
            tags=category_tags(block),
        ))
    return events


def guide_events(html_soup, url, ref: dt.date):
    """One guide's sections that are events: a date-only heading (the air
    show's per-day lineup) is part of the section above it, not an event."""
    entry = html_soup.select_one("div.entry")
    if entry is None:
        return []
    out = []
    subject = guide_subject(html_soup)
    for ev in article_events(str(entry), NAME, url, ref):
        bare = re.sub(r"\b(mon|tues|wednes|thurs|fri|satur|sun)day\b|\d{4}|[,.]", "", ev.title, flags=re.I)
        if find_dates(ev.title, ref) and len(bare.split()) <= 2 or NOT_EVENT.search(ev.title):
            continue
        if ev.ticket_url and any(h in urlparse(ev.ticket_url).netloc for h in PHOTO_HOSTS):
            ev.ticket_url = None
        if subject and not set(subject.lower().split()) & set(ev.title.lower().split()):
            ev.title = f"{subject}: {ev.title}"       # "Air Show" alone says little in a list
        if not ev.venue:
            ev.venue, ev.address, city = guide_place(ev.description)
            ev.city = ev.city or city
        ev.tags = ["featured"]
        out.append(ev)
    return out


STREET = re.compile(r"^\d+ [\w .'-]+? (st|street|ave|avenue|rd|road|blvd|way|dr|drive|ln|lane|hwy|highway|pl|ct)\b", re.I)
SF_NAMES = {"sf", "san francisco"}


def guide_place(text: str) -> tuple[str, str, str]:
    """(venue, address, city) from a guide line. Roundups write
    "Sunday, October 4 – SF (Castro) – FREE – ..."; single-event guides
    "October 10 | 9 AM-5 PM | Duboce Park | FREE"; farm guides
    "North Berkeley | 1272 Gilman Ave, Berkeley | September 18 ..."."""
    head = text[:300]
    when = re.compile(r"\$|^free\b|\d\s*[ap]\.?m|\bnoon\b|\d{4}|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.? \d", re.I)
    if " | " in head:
        parts = [clean(p) for p in head.split(" | ")][:5]
        for p in parts:
            if STREET.match(p):
                street, _, town = p.partition(",")
                return "", clean(street), clean(town)
        for p in parts:
            if p and len(p) <= 70 and not when.search(p):
                name, _, rest = p.partition(",")
                rest = clean(rest).rstrip(".")
                return clean(name), rest if STREET.match(rest) else "", ""
        return "", "", ""
    parts = [clean(p) for p in re.split(r"\s+–\s+", head)]
    if len(parts) > 2 and len(parts[1]) <= 60 and not when.search(parts[1]):
        m = re.fullmatch(r"([^()]+?)\s*\(([^()]+)\)", parts[1])
        town, spot = (m.group(1), m.group(2)) if m else (parts[1], "")
        return spot, "", "San Francisco" if town.lower() in SF_NAMES else town
    return "", "", ""


def guide_subject(html_soup) -> str:
    """What a single-event guide is about: the quoted name in its headline
    (SF's "Fleet Week" 2026 Air Show...). A roundup of many fairs has none."""
    h1 = html_soup.find("h1")
    m = re.search(r"[“\"]([^”\"]{3,40})[”\"]", clean(h1.get_text(" ")) if h1 else "")
    return m.group(1) if m else ""


def guides(f, ref: dt.date) -> tuple[list, set]:
    """The featured guides' events, and the names of the events they're about."""
    urls = []
    for index in (BASE + "/", BASE + "/city-guide/"):        # home page first: what it features most
        try:
            page = f.soup(index)
        except Exception as exc:
            print(f"  funcheap {index}: {exc}")
            continue
        for a in page.find_all("a", href=True):
            if GUIDE.match(a["href"]) and a["href"] not in urls:
                urls.append(a["href"])
    out, subjects = [], set()
    for url in urls[:MAX_GUIDES]:
        try:
            soup = f.soup(url, cache_hours=12)
        except Exception as exc:          # one guide down doesn't lose the day pages
            print(f"  funcheap guide {url}: {exc}")
            continue
        out += guide_events(soup, url, ref)
        if guide_subject(soup):
            subjects.add(guide_subject(soup).lower())
    print(f"  funcheap guides: {len(urls[:MAX_GUIDES])} read, {len(out)} events, featuring {sorted(subjects)}")
    return out, subjects


def next_page(html_soup):
    link = html_soup.find("link", rel="next")
    href = link.get("href", "") if link else ""
    return href if re.match(r"^https://sf\.funcheap\.com/\d{4}/\d{2}/\d{2}/page/\d+/$", href) else None


def fetch(f, start: dt.datetime, end: dt.datetime):
    featured, subjects = guides(f, start.date())
    out = [e for e in featured if e.start <= end.isoformat() and (e.end or e.start) >= start.isoformat()]
    day = start.date()
    last = min(end.date(), day + dt.timedelta(days=DAYS_AHEAD))
    pages = 0
    while day <= last:
        url = f"{BASE}/{day:%Y/%m/%d}/"
        for _ in range(PAGES_PER_DAY):
            try:
                soup = f.soup(url)
            except BudgetExceeded:
                print(f"  funcheap: request budget spent at {url}")
                return out
            pages += 1
            for ev in parse_day(soup, day):
                # a day post about a featured guide's event (a Terror Vault night) is featured too
                if any(sub in ev.title.lower() for sub in subjects):
                    ev.tags = sorted(set(ev.tags) | {"featured"})
                out.append(ev)
            url = next_page(soup)
            if not url:
                break
        day += dt.timedelta(days=1)
    print(f"  funcheap: {pages} day pages read")
    return out
