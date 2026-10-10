"""SF Funcheap. The site's RSS feed only carries the 10 newest posts with no
event details, so this reads the day pages (sf.funcheap.com/YYYY/MM/DD/)."""
import datetime as dt
import re
from urllib.parse import urlparse

from ..core import Event, clean, iso, short_hash
from ..heuristics import at_time, end_time, link_blocks, price_from

NAME, LABEL = "funcheap", "SF Funcheap"
BASE = "https://sf.funcheap.com"
SKIP = re.compile(r"^/(category|tag|author|page|\d{4}|wp-|feed|submit|about|contact|newsletter|search|region|city-guide)", re.I)
DAYS_AHEAD = 35


def is_event_url(url):
    p = urlparse(url)
    if p.netloc != "sf.funcheap.com":
        return False
    parts = [x for x in p.path.split("/") if x]
    return len(parts) == 1 and not SKIP.match(p.path) and "-" in parts[0]


def tidy_title(title):
    title = re.sub(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s*[-–]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?)?:\s*", "", title)
    title = re.sub(r"\s*[-–]\s*(FREE|\$\d+.*)$", "", title, flags=re.I)
    return clean(title)


def parse_day(html_soup, day: dt.date):
    events = []
    for url, title, text, _ in link_blocks(html_soup, BASE, is_event_url):
        title = tidy_title(title)
        recurring = bool(re.search(r"\bevery (mon|tue|wed|thu|fri|sat|sun)", text, re.I))
        start, all_day = at_time(day, text.split(title, 1)[-1] or text)
        end = end_time(start, text) if not all_day else None
        venue = ""
        m = re.search(r"cost:[^|]*\|\s*([^|]{3,90})", text, re.I)
        if m:
            venue = clean(m.group(1))
        elif "|" in title:
            title, venue = [clean(x) for x in title.split("|", 1)]
        events.append(Event(
            source=NAME,
            source_id=urlparse(url).path.strip("/") + "@" + day.isoformat(),
            source_url=url,
            title=title.split("|")[0].strip() if "|" in title else title,
            start=iso(start), end=iso(end), all_day=all_day,
            description="", venue=venue, city="San Francisco",
            price=price_from(text), recurring=recurring,
        ))
    return events


def fetch(f, start: dt.datetime, end: dt.datetime):
    out = []
    day = start.date()
    last = min(end.date(), day + dt.timedelta(days=DAYS_AHEAD))
    while day <= last:
        soup = f.soup(f"{BASE}/{day:%Y/%m/%d}/")
        out += parse_day(soup, day)
        day += dt.timedelta(days=1)
    return out
