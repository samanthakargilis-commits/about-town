"""Luma: the public discover feed for San Francisco (paginated JSON)."""
import datetime as dt

from ..core import Event, clean, iso, to_local
from ..heuristics import find_dicts
from ..core import next_data

NAME, LABEL = "luma", "Luma"
API = "https://api.lu.ma/discover/get-paginated-events"
PLACES = ["sf"]
MAX_PAGES = 12


def place_id(f, place):
    soup = f.soup(f"https://luma.com/{place}")
    data = next_data(soup) or {}
    for d in find_dicts(data, ("api_id",)):
        if str(d.get("api_id", "")).startswith("discplace-"):
            return d["api_id"], data
    return None, data


def to_event(entry):
    ev = entry.get("event") or entry
    start = to_local(ev.get("start_at"))
    if not ev.get("name") or not start:
        return None
    geo = ev.get("geo_address_info") or {}
    url = ev.get("url") or ""
    hosts = [clean(h.get("name")) for h in entry.get("hosts") or [] if h.get("name")]
    ticket = entry.get("ticket_info") or {}
    price = "free" if ticket.get("is_free") else ""
    return Event(
        source=NAME, source_id=ev.get("api_id") or url,
        source_url=url if url.startswith("http") else f"https://luma.com/{url}",
        title=clean(ev["name"]), start=iso(start), end=iso(to_local(ev.get("end_at"))),
        image_url=ev.get("cover_url"), venue=clean(geo.get("address") or ""),
        address=clean(geo.get("full_address") or geo.get("short_address") or ""),
        city=clean(geo.get("city") or geo.get("city_state") or ""), price=price, people=hosts,
        description=clean((entry.get("calendar") or {}).get("name") or ""),
    )


def fetch(f, start, end):
    out = []
    for place in PLACES:
        pid, page_data = place_id(f, place)
        if not pid:
            out += [e for e in (to_event(d) for d in find_dicts(page_data, ("event",))) if e]
            continue
        cursor = None
        for _ in range(MAX_PAGES):
            params = {"discover_place_api_id": pid, "pagination_limit": 50}
            if cursor:
                params["pagination_cursor"] = cursor
            data = f.get(API, params=params, as_json=True)
            for entry in data.get("entries", []):
                e = to_event(entry)
                if e:
                    out.append(e)
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
            if out and to_local(out[-1].start) > end:
                break
    return out
