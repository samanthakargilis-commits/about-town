"""Filoli (86 Cañada Rd, Woodside): Nightfall, its Halloween-season night walk,
plus garden days, tours and tastings. There's no feed, but each event page under
/whats-on/events/ carries schema.org Event data, so the listing pages give the
links and each event page gives the dates."""
import re
from urllib.parse import urljoin

from ..core import BudgetExceeded, event_from_jsonld, jsonld_events

NAME, LABEL = "filoli", "Filoli"
BASE = "https://filoli.org"
LIST = BASE + "/whats-on/events/"
EVENT = re.compile(r"^https://filoli\.org/whats-on/events/[a-z0-9-]+/$")
MAX_PAGES, MAX_EVENTS = 6, 40


def event_links(soup) -> list[str]:
    out = []
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"]).split("#")[0].split("?")[0]
        if EVENT.match(url) and url not in out:
            out.append(url)
    return out


def fetch(f, start, end):
    links = []
    for page in range(1, MAX_PAGES + 1):
        found = [u for u in event_links(f.soup(f"{LIST}?p={page}")) if u not in links]
        if not found:
            break
        links += found
    out = []
    for url in links[:MAX_EVENTS]:
        try:
            soup = f.soup(url)
        except BudgetExceeded:
            break
        except Exception as exc:
            print(f"  filoli {url}: {exc}")
            continue
        for node in jsonld_events(soup):
            e = event_from_jsonld(node, NAME, url)
            if not e:
                continue
            e.source_url = url
            e.venue = e.venue or "Filoli"
            e.address = e.address or "86 Cañada Rd"
            e.city = "Woodside"
            out.append(e)
            break
    return out
