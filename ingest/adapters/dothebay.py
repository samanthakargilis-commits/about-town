"""DoTheBay: curated Bay Area music, art, theater and comedy (day pages)."""
import datetime as dt
import re
from ..heuristics import listing_page

NAME, LABEL = "dothebay", "DoTheBay"
DAYS_AHEAD = 21
EVENT = re.compile(r"https://dothebay\.com/events/(\d{4})/(\d{1,2})/(\d{1,2})/[^/]+$|https://dothebay\.com/events/weekly/")


def fetch(f, start, end):
    out = []
    day = start.date()
    last = min(end.date(), day + dt.timedelta(days=DAYS_AHEAD))
    while day <= last:
        url = f"https://dothebay.com/events/{day.year}/{day.month}/{day.day}"
        events, _ = listing_page(f, url, NAME, lambda u: bool(EVENT.match(u)), ref=day,
                                 date_from_url=lambda u, d=day: d)
        out += events
        day += dt.timedelta(days=1)
    return out
