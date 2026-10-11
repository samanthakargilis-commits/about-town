"""Eventbrite. Its search pages (/d/...) refuse automated reads, but its
category pages (/b/<city>/<category>/) carry schema.org data for the events
they show. Those give dates without times, so each in-window event's own page
is read (cached a day) for its start and end time, price and whether it's sold
out. Kids' and tech events are dropped later by the usual rules."""
import datetime as dt

from ..core import BudgetExceeded, event_from_jsonld, jsonld_events

NAME, LABEL = "eventbrite", "Eventbrite"
BROWSE = [("ca--san-francisco", c) for c in ("arts", "music", "hobbies", "community", "spirituality", "health",
                                             "food-and-drink", "film-and-media", "holiday")] + \
         [("ca--palo-alto", c) for c in ("arts", "hobbies", "community")]
PAGES = 2
MAX_EVENT_PAGES = 80


def listed(soup, start: dt.date, end: dt.date):
    """(url, day) for each event a category page shows within the window."""
    for node in jsonld_events(soup):
        url, day = node.get("url"), str(node.get("startDate") or "")[:10]
        if url and day and start.isoformat() <= day <= end.isoformat():
            yield url.split("?")[0], day


def from_page(soup, url):
    for node in jsonld_events(soup):
        e = event_from_jsonld(node, NAME, url)
        if not e:
            continue
        offers = node.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
        e.sold_out = any("SoldOut" in str(o.get("availability", "")) for o in offers if isinstance(o, dict))
        e.source_url = url
        return e
    return None


def fetch(f, start, end):
    urls = {}
    for place, cat in BROWSE:
        for page in range(1, PAGES + 1):
            q = f"https://www.eventbrite.com/b/{place}/{cat}/" + (f"?page={page}" if page > 1 else "")
            try:
                soup = f.soup(q)
            except BudgetExceeded:
                raise
            except Exception as exc:       # one category down doesn't lose the rest
                print(f"  eventbrite {place}/{cat} p{page}: {exc}")
                break
            found = list(listed(soup, start.date(), end.date()))
            for url, day in found:
                urls.setdefault(url, (day, cat))
            if not found:
                break
    out = []
    for url, (day, cat) in sorted(urls.items(), key=lambda kv: kv[1][0])[:MAX_EVENT_PAGES]:
        try:
            e = from_page(f.soup(url, cache_hours=24), url)
        except BudgetExceeded:
            break
        except Exception:
            continue
        if e:
            e.tags = sorted(set(e.tags) | {cat.replace("-", " ")})
            out.append(e)
    print(f"  eventbrite: {len(urls)} listed, {len(out)} event pages read")
    if not urls:
        raise RuntimeError("no events on the category pages")
    return out
