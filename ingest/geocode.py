"""Map spots for venues, so the app can show how far each event is.

Uses OpenStreetMap's Nominatim (free) at its 1-request-a-second limit, with
every answer cached in .cache/geo.json, so each venue is looked up once.
Events whose source already gave coordinates are left alone."""
from __future__ import annotations

import html
import json
import re
import time

import requests

from .core import CACHE_DIR, clean

URL = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"     # free; for street corners, which Nominatim can't find
UA = "bay-events/1.0 (personal event planner; github.com/samanthakargilis-commits/bay-events)"
VIEWBOX = "-123.2,38.6,-121.3,36.8"   # Bay Area out to Sonoma and Santa Cruz, west,north,east,south
CACHE = CACHE_DIR / "geo.json"


def street_of(addr: str) -> str:
    """The street part of a listing's address: "3201 Ulloa St, San Francisco, CA 94116, USA, ..."
    gives "3201 Ulloa St"; asides like "(btwn 25th and 26th)" are dropped."""
    first = re.sub(r"\(.*?\)", "", addr).split(",")[0].strip(" .")
    m = re.match(r"^(\d+[A-Za-z]?\s+[A-Za-z0-9 .'-]+?)(?:\s+(?:#|suite|ste|unit|apt|floor)\b.*)?$", first, re.I)
    return clean(m.group(1)) if m else ""


def town_of(addr: str) -> str:
    """The town after the street, if the address names one ("..., Rohnert Park, CA")."""
    bits = [clean(b) for b in re.sub(r"\(.*?\)", "", addr).split(",")[1:]]
    for b in bits:
        b = re.sub(r"\b(CA|California|USA|United States)\b|\d{5}", "", b, flags=re.I).strip(" .")
        if b and not re.search(r"\d", b) and len(b) > 2:
            return b
    return ""


SUFFIX = re.compile(r"\s+(st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|way|pl|place|ln|lane|ter|terrace|ct|court)\.?$", re.I)


def corner_of(addr: str):
    """Two cross streets ("Steiner & Hermann", "Haight and Ashbury St") as a
    pair of street names, or None."""
    first = re.sub(r"\(.*?\)", "", html.unescape(addr or "")).split(",")[0].strip(" .")
    m = re.match(r"^([A-Za-z][A-Za-z0-9 .'-]{1,30}?)\s+(?:&|and|at|@|/)\s+([A-Za-z0-9][A-Za-z0-9 .'-]{1,30})$", first, re.I)
    if not m or re.match(r"^\d+\s", first):
        return None
    return tuple(SUFFIX.sub("", clean(x)) for x in m.groups())


def corner_spot(session, a: str, b: str, city: str):
    """Where two streets meet, from OpenStreetMap's Overpass API."""
    name = lambda x: "^" + re.escape(x).replace("\\ ", " ") + "( |$)"
    q = (f'[out:json][timeout:25];area["name"="{city}"]["boundary"="administrative"]->.c;'
         f'way(area.c)[highway][name~"{name(a)}",i]->.a;way(area.c)[highway][name~"{name(b)}",i]->.b;'
         f'node(w.a)(w.b);out 1;')
    r = session.post(OVERPASS, data={"data": q}, timeout=40)
    nodes = r.json().get("elements", []) if r.ok else []
    return [round(nodes[0]["lat"], 5), round(nodes[0]["lon"], 5)] if nodes else None


def queries(ev: dict) -> list[str]:
    city = ev.get("city") or ""
    if not city or city.lower() in ("sf", "online"):
        city = "San Francisco"
    venue = re.sub(r"\(.*?\)", "", ev.get("venue") or "").strip(" ,-")
    addr = html.unescape(ev.get("address") or "")
    out = []
    street = street_of(addr)
    if street and re.search(r"\b(CA|California)\s+9\d{4}\b", street, re.I):
        out.append(street)                             # "628 2nd Avenue Crockett California 94525"
    elif street:                                       # "3201 Ulloa St", "1191 Pine Street"
        out.append(f"{street}, {town_of(addr) or city}")
    if venue and len(venue) > 3:
        out.append(f"{venue}, {city}")
        first = venue.split(",")[0].strip()          # "SFPL Main Library, 4th floor"
        if first != venue and len(first) > 3:
            out.append(f"{first}, {city}")
    # a place in the title: "Ghost Hunt (Haight-Ashbury)", "Picnic (Golden Gate Park)"
    for hint in re.findall(r"\(([A-Z][A-Za-z.' -]{3,40})\)", ev.get("title") or ""):
        if not re.search(r"\d|\bw/|\bends\b|\bonly\b|\bfree\b|summer|winter|spring|fall|friday|sunday|saturday", hint, re.I):
            out.append(f"{hint}, {city}")
    return [clean(q) for q in out]


def fresh(hit) -> bool:
    """A cached answer we trust: a spot, or a miss from the last two weeks."""
    if isinstance(hit, list):
        return True
    return isinstance(hit, dict) and time.time() - hit.get("miss", 0) < 14 * 86400


def fill(events: list[dict], max_lookups: int = 350) -> dict:
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    session = requests.Session()
    session.headers["User-Agent"] = UA
    looked = found = corners = 0
    for ev in events:
        if ev.get("lat") is not None or ev.get("city") == "Online":
            continue
        corner = corner_of(ev.get("address") or "")
        if corner:
            city = ev.get("city") if ev.get("city") and ev["city"].lower() not in ("sf",) else "San Francisco"
            key = f"corner:{corner[0]}&{corner[1]}|{city}".lower()
            if not fresh(cache.get(key)) and looked < max_lookups:
                looked += 1
                try:
                    cache[key] = corner_spot(session, *corner, city) or {"miss": int(time.time())}
                except (requests.RequestException, ValueError, KeyError):
                    cache[key] = {"miss": int(time.time())}
                time.sleep(1.1)
            if isinstance(cache.get(key), list):
                ev["lat"], ev["lng"] = cache[key]
                found += 1
                corners += 1
                continue
        for q in queries(ev):
            key = q.lower()
            if not fresh(cache.get(key)):
                if looked >= max_lookups:
                    continue
                looked += 1
                try:
                    r = session.get(URL, params={"q": q, "format": "json", "limit": 1, "viewbox": VIEWBOX,
                                                 "bounded": 1, "countrycodes": "us"}, timeout=20)
                    hits = r.json() if r.ok else []
                    cache[key] = [round(float(hits[0]["lat"]), 5), round(float(hits[0]["lon"]), 5)] if hits else {"miss": int(time.time())}
                except (requests.RequestException, ValueError, KeyError, IndexError):
                    cache[key] = {"miss": int(time.time())}
                time.sleep(1.1)
            if isinstance(cache.get(key), list):
                ev["lat"], ev["lng"] = cache[key]
                found += 1
                break
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0))
    have = sum(1 for e in events if e.get("lat") is not None)
    return {"lookups": looked, "matched_now": found, "corners": corners, "with_spot": have, "total": len(events)}
