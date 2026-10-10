"""Green Apple Books (SF): author events and launches (IndieCommerce)."""
import datetime as dt
import re
from ..heuristics import listing_page

NAME, LABEL = "greenapple", "Green Apple Books"
URL = "https://greenapplebooks.com/events"
EVENT = re.compile(r"https://(www\.)?greenapplebooks\.com/event/(\d{4})-(\d{2})-(\d{2})/")


def date_from_url(u):
    m = EVENT.match(u)
    return dt.date(int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def fetch(f, start, end):
    out = []
    for page in (URL, URL + "?page=1", URL + "?page=2"):
        try:
            events, _ = listing_page(f, page, NAME, lambda u: bool(EVENT.match(u)), city="San Francisco",
                                     default_hour=19, date_from_url=date_from_url)
        except Exception:
            break
        if not events:
            break
        out += events
    for e in out:
        if "offsite" not in e.title.lower() and not e.venue:
            e.venue = "Green Apple Books"
        e.title = re.sub(r"^(9th Ave|Offsite|Clement St|Inner Sunset):\s*", "", e.title)
    return out
