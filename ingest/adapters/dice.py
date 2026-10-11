"""Dice: ticketed concerts, DJ nights and live-music events in SF."""
from ..core import geo_of, Event, clean, event_from_jsonld, iso, jsonld_events, next_data, to_local
from ..heuristics import find_dicts

NAME, LABEL = "dice", "Dice"
URLS = ["https://dice.fm/browse/san_francisco", "https://dice.fm/browse/san-francisco"]


def fetch(f, start, end):
    for url in URLS:
        try:
            soup = f.soup(url)
        except Exception:
            continue
        events = [e for e in (event_from_jsonld(n, NAME) for n in jsonld_events(soup)) if e]
        data = next_data(soup) or {}
        for d in find_dicts(data, ("name", "dates")):
            dates = d.get("dates") or {}
            st = to_local(dates.get("event_start_date") if isinstance(dates, dict) else None)
            if not st:
                continue
            venues = d.get("venues") or [{}]
            v = venues[0] if venues and isinstance(venues[0], dict) else {}
            perm = d.get("perm_name") or d.get("id")
            artists = [clean(a.get("name")) for a in d.get("summary_lineup", {}).get("top_artists", [])
                       if isinstance(a, dict)] if isinstance(d.get("summary_lineup"), dict) else []
            events.append(Event(source=NAME, source_id=str(perm), source_url=f"https://dice.fm/event/{perm}",
                                title=clean(d["name"]), start=iso(st),
                                end=iso(to_local(dates.get("event_end_date"))), venue=clean(v.get("name")),
                                city=clean((v.get("city") or {}).get("name") if isinstance(v.get("city"), dict) else ""),
                                people=artists, tags=["music"], lat=geo_of(v)[0], lng=geo_of(v)[1]))
        if events:
            return events
    return []
