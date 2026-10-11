"""Partiful Explore (SF). Public explore page only; private invites are invisible."""
from ..core import geo_of, Event, clean, iso, next_data, to_local
from ..heuristics import find_dicts

NAME, LABEL = "partiful", "Partiful Explore"
URL = "https://partiful.com/explore/sf"


def fetch(f, start, end):
    soup = f.soup(URL)
    data = next_data(soup) or {}
    out, seen = [], set()
    for d in find_dicts(data, ("title", "startDate")):
        st = to_local(d.get("startDate"))
        eid = d.get("id") or d.get("eventId")
        if not st or not eid or eid in seen:
            continue
        seen.add(eid)
        loc = d.get("location") or d.get("locationInfo") or {}
        out.append(Event(source=NAME, source_id=str(eid), source_url=f"https://partiful.com/e/{eid}",
                         title=clean(d["title"]), start=iso(st), end=iso(to_local(d.get("endDate"))),
                         description=clean(d.get("description") or "")[:800],
                         image_url=(d.get("image") or {}).get("url") if isinstance(d.get("image"), dict) else None,
                         venue=clean(loc.get("name") if isinstance(loc, dict) else ""),
                         city=clean(loc.get("city") if isinstance(loc, dict) else ""),
                         lat=geo_of(loc)[0], lng=geo_of(loc)[1]))
    return out
