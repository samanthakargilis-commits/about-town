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

from . import area
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
    text = re.sub(r"\(.*?\)", "", html.unescape(addr or ""))
    # "Mission St. between 3rd & 4th Sts." is the corner of the street and the first cross street
    m = re.search(r"([A-Za-z0-9][A-Za-z0-9 .'-]{1,30}?)\s+between\s+([A-Za-z0-9][A-Za-z0-9.'-]{0,20}(?: [A-Za-z0-9.'-]{1,20})?)\s+(?:&|and)\s", text, re.I)
    if m:
        return tuple(SUFFIX.sub("", clean(x)) for x in m.groups())
    first = text.split(",")[0].strip(" .")
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9 .'-]{1,30}?)\s+(?:&|and|at|@|/)\s+([A-Za-z0-9][A-Za-z0-9 .'-]{1,30})$", first, re.I)
    if not m or re.match(r"^\d+\s", first):
        return None
    return tuple(SUFFIX.sub("", clean(x)) for x in m.groups())


def corner_spot(session, a: str, b: str, city: str):
    """Where two streets meet, from OpenStreetMap's Overpass API."""
    # "Mission" is Mission Street, not Mission Bay Boulevard, which also crosses 3rd
    kinds = "Street|Avenue|Boulevard|Way|Road|Drive|Place|Lane|Terrace|Court|Alley|Plaza"
    name = lambda x: "^" + re.escape(x).replace("\\ ", " ") + f"( ({kinds}))?$"
    q = (f'[out:json][timeout:25];area["name"="{city}"]["boundary"="administrative"]->.c;'
         f'way(area.c)[highway][name~"{name(a)}",i]->.a;way(area.c)[highway][name~"{name(b)}",i]->.b;'
         f'node(w.a)(w.b);out 1;')
    r = session.post(OVERPASS, data={"data": q}, timeout=40)
    nodes = r.json().get("elements", []) if r.ok else []
    return [round(nodes[0]["lat"], 5), round(nodes[0]["lon"], 5)] if nodes else None


TOWNS = sorted(area.IN_AREA | set(area.OUT_OF_AREA), key=len, reverse=True)
TOWN_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in TOWNS if len(t) > 3 and t != "pacheco") + r")\b", re.I)
STREET_RE = re.compile(r"\b(\d{1,5}[A-Za-z]?\s+(?:[NSEW]\.?\s+)?[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,3}?\s+"
                       r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Way|Pl|Place|Ln|Lane|Ter|Terrace|"
                       r"Ct|Court|Hwy|Highway|Loop|Sq|Square|Plaza|Pkwy|Parkway|Alameda|Circle|Cir)\b\.?(?:\s+[NSEW]\b)?)", re.I)
NOT_A_PLACE = re.compile(r"secret location|multiple venues|all over|online|tba\b|^every |^first |^sf$", re.I)


def town_in(*texts) -> str:
    """The last Bay Area town a text names ("229 Water St., Petaluma" gives Petaluma;
    "37th Ave and Pacheco, San Francisco" gives San Francisco)."""
    for text in texts:
        hits = TOWN_RE.findall(html.unescape(text or ""))
        if hits:
            return hits[-1].title()
    return ""


def town_of_event(ev: dict) -> str:
    city = ev.get("city") or ""
    if city.lower() in ("sf", "san franciaco"):
        city = "San Francisco"
    return town_in(ev.get("address"), ev.get("venue")) or (city if TOWN_RE.fullmatch(city) else "") or \
        town_in(ev.get("title")) or city


def queries(ev: dict) -> list[str]:
    town = town_of_event(ev)
    city = town if town and town.lower() != "online" else "San Francisco"
    venue = re.sub(r"\(.*?\)", "", html.unescape(ev.get("venue") or "")).strip(" ,-")
    addr = re.sub(r"\(.*?\)", "", html.unescape(ev.get("address") or ""))
    out = []
    # a street number anywhere: "Thornton Hall, 10th Floor ... 1600 Holloway Avenue San Francisco, CA"
    for text in (addr, venue):
        m = STREET_RE.search(text)
        if m:
            out.append(f"{clean(m.group(1)).rstrip('.')}, {city}")
            break
    street = street_of(addr)
    if street and re.search(r"\b(CA|California)\s+9\d{4}\b", street, re.I):
        out.append(street)                             # "628 2nd Avenue Crockett California 94525"
    elif street:                                       # "3201 Ulloa St", "1191 Pine Street"
        out.append(f"{street}, {town_of(addr) or city}")
    if venue and len(venue) > 3 and not NOT_A_PLACE.search(venue):
        out.append(f"{venue}, {city}")
        first = venue.split(",")[0].strip()          # "SFPL Main Library, 4th floor"
        if first != venue and len(first) > 3:
            out.append(f"{first}, {city}")
    # a place in the title: "Ghost Hunt (Haight-Ashbury)", "Picnic (Golden Gate Park)"
    for hint in re.findall(r"\(([A-Z][A-Za-z.' -]{3,40})\)", ev.get("title") or ""):
        if not re.search(r"\d|\bw/|\bends\b|\bonly\b|\bfree\b|summer|winter|spring|fall|friday|sunday|saturday", hint, re.I):
            out.append(f"{hint}, {city}")
    seen, uniq = set(), []
    for q in (clean(q) for q in out):
        if q.lower() not in seen:
            seen.add(q.lower())
            uniq.append(q)
    return uniq


def town_query(ev: dict) -> str:
    """When nothing closer is found: the middle of the town, for towns outside SF
    (a few miles off doesn't matter at Petaluma's distance; inside SF it would)."""
    town = town_of_event(ev)
    if not town or town.lower() in ("san francisco", "online") or not TOWN_RE.fullmatch(town):
        return ""
    return f"{town}, California"


def fresh(hit) -> bool:
    """A cached answer we trust: a spot, or a real no-match from the last two weeks.
    Older misses didn't tell a refused request from no match, so they're asked again."""
    if isinstance(hit, list):
        return True
    return isinstance(hit, dict) and hit.get("v") == 2 and time.time() - hit.get("miss", 0) < 14 * 86400


def miss():
    return {"miss": int(time.time()), "v": 2}


class Refused(Exception):
    pass


def nominatim(session, q):
    r = session.get(URL, params={"q": q, "format": "json", "limit": 1, "viewbox": VIEWBOX,
                                 "bounded": 1, "countrycodes": "us"}, timeout=20)
    if r.status_code != 200:
        raise Refused(r.status_code)
    hits = r.json()
    return [round(float(hits[0]["lat"]), 5), round(float(hits[0]["lon"]), 5)] if hits else None


PHOTON = "https://photon.komoot.io/api/"
GENERIC = set("the a an and at of in on sf san francisco ca california bar theater theatre cafe restaurant club hall house "
              "room center centre gallery studio park street st avenue ave road rd way market shop store new old".split())


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in GENERIC and len(w) > 2}


def photon_ok(q: str, props: dict) -> bool:
    """Photon matches loosely ("Roxie Theater" came back as the Great Star Theater),
    so keep its answer only if it shares a real word with what was asked."""
    asked = words(q.split(",")[0])
    named = words(" ".join(str(props.get(k) or "") for k in ("name", "street")))
    return bool(asked & named) or bool(asked & {w + "s" for w in named}) or bool({w + "s" for w in asked} & named)


def photon(session, q):
    r = session.get(PHOTON, params={"q": q.replace(",", " "), "limit": 1, "bbox": "-123.2,36.8,-121.3,38.6"}, timeout=20)
    if r.status_code != 200:
        raise Refused(r.status_code)
    feats = r.json().get("features") or []
    if not feats or not photon_ok(q, feats[0].get("properties") or {}):
        return None
    lng, lat = feats[0]["geometry"]["coordinates"][:2]
    return [round(float(lat), 5), round(float(lng), 5)]


def fill(events: list[dict], max_lookups: int = 350) -> dict:
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    session = requests.Session()
    session.headers["User-Agent"] = UA
    looked = found = corners = towns = refused = 0
    for ev in events:
        if ev.get("lat") is not None or ev.get("city") == "Online":
            continue
        corner = corner_of(ev.get("address") or "")
        if corner:
            city = ev.get("city") if ev.get("city") and ev["city"].lower() not in ("sf",) else "San Francisco"
            key = f"corner2:{corner[0]}&{corner[1]}|{city}".lower()
            if not fresh(cache.get(key)) and looked < max_lookups:
                looked += 1
                try:
                    cache[key] = corner_spot(session, *corner, city) or miss()
                except (requests.RequestException, ValueError, KeyError):
                    pass                                   # asked again next run
                time.sleep(1.1)
            if isinstance(cache.get(key), list):
                ev["lat"], ev["lng"] = cache[key]
                found += 1
                corners += 1
                continue
        town = town_query(ev)
        qs = queries(ev)
        # Nominatim wants the map's exact name ("Castro Theatre", not "The Castro Theatre");
        # Photon forgives spelling ("Black Bird Bookstore") but guesses, so its answer has to share a real word
        tries = [("n", q) for q in qs] + [("n", q[4:]) for q in qs if q.lower().startswith("the ")] + \
                [("p", q) for q in qs[:2]] + ([("n", town)] if town else [])
        for kind, q in tries:
            key = q.lower() if kind == "n" else "photon:" + q.lower()
            if not fresh(cache.get(key)):
                if looked >= max_lookups or refused >= 5:
                    continue
                looked += 1
                try:
                    got = nominatim(session, q) if kind == "n" else photon(session, q)
                    cache[key] = got or miss()
                except Refused:
                    refused += 1                       # turned away, not "no such place": ask again next run
                except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
                    refused += 1
                time.sleep(1.1)
            if isinstance(cache.get(key), list):
                ev["lat"], ev["lng"] = cache[key]
                if kind == "n" and q == town:
                    ev["near_town"] = True             # the app says "~31 mi"
                    towns += 1
                found += 1
                break
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0))
    have = sum(1 for e in events if e.get("lat") is not None)
    return {"lookups": looked, "refused": refused, "matched_now": found, "corners": corners, "town_only": towns, "with_spot": have, "total": len(events)}
