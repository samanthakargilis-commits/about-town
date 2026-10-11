"""Map spots for venues, so the app can show how far each event is.

Uses OpenStreetMap's Nominatim (free) at its 1-request-a-second limit, with
every answer cached in .cache/geo.json, so each venue is looked up once.
Events whose source already gave coordinates are left alone."""
from __future__ import annotations

import json
import re
import time

import requests

from .core import CACHE_DIR, clean

URL = "https://nominatim.openstreetmap.org/search"
UA = "bay-events/1.0 (personal event planner; github.com/samanthakargilis-commits/bay-events)"
VIEWBOX = "-123.0,38.2,-121.7,37.1"   # SF Bay Area, west,north,east,south
CACHE = CACHE_DIR / "geo.json"


def queries(ev: dict) -> list[str]:
    city = ev.get("city") or ""
    if not city or city.lower() in ("sf", "online"):
        city = "San Francisco"
    venue = re.sub(r"\(.*?\)", "", ev.get("venue") or "").strip(" ,-")
    addr = ev.get("address") or ""
    out = []
    if re.match(r"^\d+\s+\w", addr):                  # a street address
        out.append(f"{addr}, {city}" if city.lower() not in addr.lower() else addr)
    if venue and len(venue) > 3:
        out.append(f"{venue}, {city}")
    return [clean(q) for q in out]


def fill(events: list[dict], max_lookups: int = 350) -> dict:
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    session = requests.Session()
    session.headers["User-Agent"] = UA
    looked = found = 0
    for ev in events:
        if ev.get("lat") is not None or ev.get("city") == "Online":
            continue
        for q in queries(ev):
            key = q.lower()
            if key not in cache:
                if looked >= max_lookups:
                    continue
                looked += 1
                try:
                    r = session.get(URL, params={"q": q, "format": "json", "limit": 1, "viewbox": VIEWBOX,
                                                 "bounded": 1, "countrycodes": "us"}, timeout=20)
                    hits = r.json() if r.ok else []
                    cache[key] = [round(float(hits[0]["lat"]), 5), round(float(hits[0]["lon"]), 5)] if hits else None
                except (requests.RequestException, ValueError, KeyError, IndexError):
                    cache[key] = None
                time.sleep(1.1)
            if cache.get(key):
                ev["lat"], ev["lng"] = cache[key]
                found += 1
                break
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0))
    have = sum(1 for e in events if e.get("lat") is not None)
    return {"lookups": looked, "matched_now": found, "with_spot": have, "total": len(events)}
