"""Where is it? Many listings (Funcheap day pages, Partiful, Meetup) carry no
address, but each event's own page does, in its schema.org data. This reads
those pages once and remembers the answer in .cache/places.json, so the app
can say how far away each event is (and out-of-area events get dropped)."""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from .core import CACHE_DIR, BudgetExceeded, geo_of, jsonld_events, place_of

CACHE = CACHE_DIR / "places.json"
RETRY_DAYS = 7          # a page with no location is tried again after this
SKIP_HOSTS = ("secretsanfrancisco.com", "substack.com", "ma.to")   # Mato: its adapter already read the page
STREET = re.compile(r"^\d+\s+\w")


def needs_place(ev: dict) -> bool:
    if ev.get("lat") is not None or ev.get("city") == "Online":
        return False
    host = urlparse(ev.get("source_url") or "").netloc
    if not host or any(host.endswith(h) for h in SKIP_HOSTS):
        return False
    return not STREET.match(ev.get("address") or "")


def place_from_soup(soup) -> dict:
    for node in jsonld_events(soup):
        loc = node.get("location")
        venue, address, city = place_of(loc)
        lat, lng = geo_of(loc if isinstance(loc, dict) else {})
        if venue or address or lat is not None:
            return {"venue": venue, "address": address, "city": city, "lat": lat, "lng": lng}
    return {}


def apply(ev: dict, place: dict):
    if not place:
        return
    if place.get("venue") and not ev.get("venue"):
        ev["venue"] = place["venue"][:70]
    if place.get("address") and not STREET.match(ev.get("address") or ""):
        ev["address"] = place["address"]
    if place.get("city") and not ev.get("city"):
        ev["city"] = place["city"]
    if place.get("lat") is not None and ev.get("lat") is None:
        ev["lat"], ev["lng"] = place["lat"], place["lng"]


def locate(events: list[dict], fetcher) -> dict:
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    read = found = 0
    for ev in events:
        if not needs_place(ev):
            continue
        url = ev["source_url"]
        hit = cache.get(url)
        if hit is None or (not hit.get("place") and time.time() - hit.get("t", 0) > RETRY_DAYS * 86400):
            try:
                soup = fetcher.soup(url)
            except BudgetExceeded:
                break
            except Exception:
                continue
            read += 1
            hit = cache[url] = {"place": place_from_soup(soup), "t": int(time.time())}
        if hit.get("place"):
            apply(ev, hit["place"])
            found += 1
    old = time.time() - 60 * 86400
    cache = {k: v for k, v in cache.items() if v.get("t", 0) > old}
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0))
    return {"pages_read": read, "placed": found}
