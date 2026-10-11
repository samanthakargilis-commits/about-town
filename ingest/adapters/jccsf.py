"""JCC San Francisco (3200 California St): talks, music, arts and holidays.
The site runs The Events Calendar for WordPress, whose REST feed lists events
as JSON; the month pages' JSON-LD are the fallback."""
from ..core import Event, clean, event_from_jsonld, geo_of, html_to_text, iso, jsonld_events, to_local

NAME, LABEL = "jccsf", "JCC San Francisco"
BASE = "https://www.jccsf.org"
API = BASE + "/wp-json/tribe/events/v1/events"


def from_api(f, start, end):
    out, page = [], 1
    while page <= 8:
        data = f.get(API, params={"start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"),
                                  "per_page": 50, "page": page}, as_json=True)
        for it in data.get("events", []):
            st = to_local(it.get("utc_start_date") and it["utc_start_date"].replace(" ", "T") + "Z") or to_local(it.get("start_date"))
            if not st or not it.get("title"):
                continue
            v = it.get("venue") if isinstance(it.get("venue"), dict) else {}
            img = it.get("image") if isinstance(it.get("image"), dict) else {}
            cost = clean(it.get("cost") or "")
            lat, lng = geo_of({"lat": v.get("geo_lat"), "lng": v.get("geo_lng")})
            out.append(Event(
                source=NAME, source_id=str(it.get("id") or it.get("slug")), source_url=it.get("url") or BASE + "/events/",
                title=html_to_text(it["title"]), start=iso(st),
                end=iso(to_local(it.get("utc_end_date") and it["utc_end_date"].replace(" ", "T") + "Z")),
                all_day=bool(it.get("all_day")),
                description=html_to_text(it.get("description") or it.get("excerpt") or "")[:1000],
                image_url=img.get("url"), venue=clean(v.get("venue") or "JCC San Francisco"),
                address=clean(v.get("address") or "3200 California St"), city=clean(v.get("city") or "San Francisco"),
                # JCC's feed says "Free" for most events, including ticketed ones sold
                # through an Eventbrite widget ($20-40 talks), so "Free" means unknown
                price="" if cost.lower() in ("free", "$0", "0") else cost,
                tags=[clean(c.get("name")) for c in it.get("categories") or [] if isinstance(c, dict)],
                ticket_url=it.get("website") or None, lat=lat, lng=lng,
            ))
        if page >= int(data.get("total_pages") or 1):
            break
        page += 1
    return out


def fetch(f, start, end):
    try:
        events = from_api(f, start, end)
        if events:
            return events
    except Exception as exc:
        print(f"  jccsf api: {exc}")
    out, seen = [], set()
    for month in sorted({start.strftime("%Y-%m"), end.strftime("%Y-%m")}):
        soup = f.soup(f"{BASE}/events/month/{month}/")
        for node in jsonld_events(soup):
            e = event_from_jsonld(node, NAME, BASE + "/events/")
            if e and e.id not in seen:
                seen.add(e.id)
                e.venue = e.venue or "JCC San Francisco"
                e.price = "" if e.price == "free" else e.price     # same unreliable "Free" as the feed
                e.city = e.city or "San Francisco"
                out.append(e)
    return out
