"""Mato (ma.to): a city guide of things to do, built partly from venues' own
posts. Its San Francisco and Palo Alto pages (and their category pages) link
to event pages, and each event page carries schema.org data with the time,
place and price. Event pages are read once a day (cached).

Its schema.org place often says "San Francisco" for anywhere in the Bay
("Downtown Danville"), so a town named in the place wins."""
import re

from .. import area
from ..core import BudgetExceeded, event_from_jsonld, find_dates, jsonld_events

NAME, LABEL = "mato", "Mato"
BASE = "https://ma.to"
CATEGORIES = ["comedy", "markets", "visual-arts", "performing-arts", "workshops", "community", "party",
              "live-music", "film", "talks", "food-and-drinks"]
LISTINGS = ([f"{BASE}/events/san-francisco", f"{BASE}/events/san-francisco/this-weekend"]
            + [f"{BASE}/events/san-francisco/anytime/{c}" for c in CATEGORIES] + [f"{BASE}/events/palo-alto"])
MAX_EVENT_PAGES = 100
TOWNS = sorted(area.IN_AREA | set(area.OUT_OF_AREA) - set(area.FAR_OR_ONLINE), key=len, reverse=True)
TOWN = re.compile(r"\b(" + "|".join(re.escape(t) for t in TOWNS if len(t) > 3) + r")\b", re.I)


def day_of(url, ref):
    """The date in the slug: ...-2026-10-11 or ...-23-oct-2026."""
    slug = url.rsplit("/", 1)[-1]
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})$", slug)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})-([a-z]{3})-(\d{4})$", slug)
    found = find_dates(f"{m.group(2)} {m.group(1)} {m.group(3)}", ref) if m else []
    return found[0][0].isoformat() if found else None


def from_page(soup, url):
    for node in jsonld_events(soup):
        e = event_from_jsonld(node, NAME, url)
        if not e:
            continue
        e.source_url = url
        town = TOWN.search(" ".join([e.venue or "", e.address or ""]))
        if town:
            e.city = town.group(1).title()
        offers = node.get("offers")
        offers = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
        e.sold_out = bool(offers) and all("SoldOut" in str(o.get("availability", "")) for o in offers if isinstance(o, dict))
        return e
    return None


def fetch(f, start, end):
    urls = {}
    for page in LISTINGS:
        try:
            soup = f.soup(page)
        except BudgetExceeded:
            raise
        except Exception as exc:          # one listing down doesn't lose the rest
            print(f"  mato {page}: {exc}")
            continue
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("/event/"):
                url = BASE + a["href"].split("?")[0]
                day = day_of(url, start.date())
                if not day or start.date().isoformat() <= day <= end.date().isoformat():
                    urls.setdefault(url, day or "9999")
    out = []
    for url, _ in sorted(urls.items(), key=lambda kv: kv[1])[:MAX_EVENT_PAGES]:
        try:
            e = from_page(f.soup(url, cache_hours=24), url)
        except BudgetExceeded:
            break
        except Exception:
            continue
        if e:
            out.append(e)
    print(f"  mato: {len(urls)} listed, {len(out)} event pages read")
    if not urls:
        raise RuntimeError("no events on the city pages")
    return out
