"""BroadwaySF: touring musicals at the Orpheum, Golden Gate and Curran."""
import datetime as dt
import re

from ..core import TZ, find_dates, iso, now, to_local
from ..heuristics import listing_page

# each show card's data: "title":"Oh, Mary!","dates":"Tue, Oct 13 - Sun, Nov 1, 2026"
RUN = re.compile(r'\\?"title\\?":\\?"(.{2,120}?)\\?",\\?"dates\\?":\\?"([^"\\]{6,80})')


def runs(html: str) -> dict:
    """Show title -> (first day, last day) from the cards' data."""
    out = {}
    for title, dates in RUN.findall(html):
        found = find_dates(dates.replace(" - ", " to "), now().date())
        if found:
            first, last = found[0][0], (found[-1][1] or found[-1][0])
            out[title.lower()] = (first, last)
    return out

NAME, LABEL = "broadwaysf", "BroadwaySF"
URL = "https://www.broadwaysf.com/events/"


def fetch(f, start, end):
    events, soup = listing_page(f, URL, NAME,
                             lambda u: "broadwaysf.com/events/" in u and u.rstrip("/") != URL.rstrip("/"),
                             city="San Francisco", default_hour=19)
    span = runs(str(soup))
    out = []
    for e in events:
        if re.fullmatch(r"(sold out|buy tickets|more info|on sale.*|tickets|learn more|limited.*)", e.title.strip(), re.I):
            # the link text was a button: name it from the URL (/events/<show>/<venue>/)
            parts = [x for x in e.source_url.split("/") if x]
            e.title = parts[parts.index("events") + 1].replace("-", " ").title() if "events" in parts else e.title
        e.description = ""          # listing text is mostly page chrome
        parts = [x for x in e.source_url.split("/") if x]
        if "events" in parts and len(parts) > parts.index("events") + 2:
            e.venue = parts[parts.index("events") + 2].replace("-", " ").title()
        run = span.get(e.title.lower())
        if run and run[1] > run[0] and not e.end:
            # one listing for the whole run, on opening night, ending the last night
            last = run[1]
            e.end = iso(dt.datetime(last.year, last.month, last.day, 22, 30, tzinfo=TZ))
        out.append(e)
    return out
