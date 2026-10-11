"""Partiful Explore (SF). Public explore page only; private invites are invisible.
The explore page has no ticket info, so each event's own page is read for its
schema.org offer: the price, and whether it's sold out. Answers are cached for
a day so a re-run doesn't read them all again."""
import json
import time

from ..core import CACHE_DIR, BudgetExceeded, geo_of, Event, clean, iso, jsonld_events, next_data, to_local
from ..heuristics import find_dicts

NAME, LABEL = "partiful", "Partiful Explore"
URL = "https://partiful.com/explore/sf"
CACHE = CACHE_DIR / "partiful.json"
MAX_PAGES = 90
SOLD = ("soldout", "outofstock", "discontinued")
VERSION = 2             # bump when what's read off the page changes, so the cache is re-read


def full(soup, eid) -> bool:
    """The page's own data says the guest list is full (the schema.org offer
    still says InStock then, so this is the real sold-out signal)."""
    for d in find_dicts(next_data(soup) or {}, ("id", "atCapacity")):
        if d.get("id") == eid:
            return bool(d.get("atCapacity"))
    return False


def offer_of(soup, eid=None) -> dict:
    """{"price": "free"|"$20"|"", "sold_out": bool} from the page's Event offers."""
    o = _offer(soup)
    if o and eid and full(soup, eid):
        o["sold_out"] = True
    return o


def _offer(soup) -> dict:
    for node in jsonld_events(soup):
        offers = node.get("offers") or []
        offers = offers if isinstance(offers, list) else [offers]
        offers = [o for o in offers if isinstance(o, dict)]
        if not offers:
            return {"price": "", "sold_out": False}
        prices = sorted(float(o["price"]) for o in offers if str(o.get("price", "")).replace(".", "", 1).isdigit())
        avail = [str(o.get("availability", "")).rsplit("/", 1)[-1].lower() for o in offers]
        price = "" if not prices else "free" if prices[-1] == 0 else \
            f"${prices[0]:g}" if prices[0] == prices[-1] else f"${prices[0]:g}-{prices[-1]:g}"
        return {"price": price, "sold_out": bool(avail) and all(a in SOLD for a in avail)}
    return {}


def add_offers(f, events):
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    now, read = time.time(), 0
    for e in events:
        hit = cache.get(e.source_id)
        if hit is None or hit.get("v") != VERSION or now - hit.get("t", 0) > 20 * 3600:
            if read >= MAX_PAGES:
                continue
            try:
                hit = {**offer_of(f.soup(e.source_url), e.source_id), "t": int(now), "v": VERSION}
            except BudgetExceeded:
                break
            except Exception as exc:
                print(f"  partiful {e.source_url}: {exc}")
                continue
            read += 1
            cache[e.source_id] = hit
        e.price = e.price or hit.get("price", "")
        e.sold_out = bool(hit.get("sold_out"))
    print(f"  partiful offers: {read} pages read, {sum(1 for e in events if e.price)} priced, "
          f"{sum(1 for e in events if e.sold_out)} sold out, of {len(events)}")
    cache = {k: v for k, v in cache.items() if now - v.get("t", 0) < 30 * 86400}
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache))


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
    add_offers(f, [e for e in out if start <= to_local(e.start) <= end])
    return out
