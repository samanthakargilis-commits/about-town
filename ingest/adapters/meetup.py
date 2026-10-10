"""Meetup: public event search for recurring groups that fit a weekly habit."""
from urllib.parse import quote

from ..core import Event, clean, event_from_jsonld, iso, jsonld_events, next_data, to_local
from ..heuristics import find_dicts

NAME, LABEL = "meetup", "Meetup"
KEYWORDS = ["meditation", "craft night", "writing group", "book club", "choir", "improv", "queer", "salon"]
LOCATION = "us--ca--San Francisco"


def fetch(f, start, end):
    out, seen = [], set()
    for kw in KEYWORDS:
        url = f"https://www.meetup.com/find/?keywords={quote(kw)}&location={quote(LOCATION)}&source=EVENTS"
        soup = f.soup(url)
        found = [e for e in (event_from_jsonld(n, NAME) for n in jsonld_events(soup)) if e]
        data = next_data(soup) or {}
        for d in find_dicts(data, ("title", "dateTime", "eventUrl")):
            start_dt = to_local(d.get("dateTime"))
            if not start_dt:
                continue
            venue = d.get("venue") or {}
            if isinstance(venue, dict) and venue.get("__ref"):
                venue = {}
            group = d.get("group") or {}
            found.append(Event(
                source=NAME, source_id=str(d.get("id") or d["eventUrl"]), source_url=d["eventUrl"],
                title=clean(d["title"]), start=iso(start_dt), end=iso(to_local(d.get("endTime"))),
                description=clean(d.get("description") or "")[:800],
                venue=clean(venue.get("name") if isinstance(venue, dict) else ""),
                address=clean(venue.get("address") if isinstance(venue, dict) else ""),
                city=clean(venue.get("city") if isinstance(venue, dict) else ""),
                recurring=bool(d.get("series")), image_url=(d.get("featuredEventPhoto") or {}).get("highResUrl")
                if isinstance(d.get("featuredEventPhoto"), dict) else None,
                people=[clean(group.get("name"))] if isinstance(group, dict) and group.get("name") else [],
            ))
        for e in found:
            if e.source_url not in seen:
                seen.add(e.source_url)
                out.append(e)
    return out
