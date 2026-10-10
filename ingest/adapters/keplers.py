"""Kepler's Books (Menlo Park): author talks, readings and signings.
The site is Squarespace, so the events collection is readable as JSON."""
import re
from ..core import Event, clean, html_to_text, iso, to_local
from ..heuristics import listing_page

NAME, LABEL = "keplers", "Kepler's Books"
BASE = "https://www.keplers.org"
COLLECTION = BASE + "/upcoming-events-internal"


def from_json(f):
    data = f.get(COLLECTION, params={"format": "json"}, as_json=True)
    items = data.get("upcoming") or data.get("items") or []
    out = []
    for it in items:
        start = to_local(it.get("startDate"))
        if not start or not it.get("title"):
            continue
        loc = it.get("location") or {}
        venue = clean(loc.get("addressTitle") or "")
        out.append(Event(
            source=NAME, source_id=it.get("urlId") or it.get("id"), source_url=BASE + it.get("fullUrl", ""),
            title=clean(it["title"]), start=iso(start), end=iso(to_local(it.get("endDate"))),
            description=html_to_text(it.get("excerpt") or it.get("body") or "")[:1000],
            image_url=it.get("assetUrl"), venue=venue or "Kepler's Books",
            address=clean(" ".join(filter(None, [loc.get("addressLine1"), loc.get("addressLine2")]))),
            city="Menlo Park" if not loc.get("addressLine2") else clean(loc["addressLine2"].split(",")[0]),
        ))
    return out


def fetch(f, start, end):
    try:
        events = from_json(f)
        if events:
            return events
    except Exception as exc:
        print(f"  keplers json: {exc}")
    for url in (BASE + "/events-in-person", BASE + "/"):
        events, _ = listing_page(f, url, NAME, lambda u: "/upcoming-events-internal/" in u,
                                 city="Menlo Park", default_hour=19)
        if events:
            for e in events:
                e.venue = e.venue or "Kepler's Books"
            return events
    return []
