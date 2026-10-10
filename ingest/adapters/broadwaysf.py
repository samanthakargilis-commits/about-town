"""BroadwaySF: touring musicals at the Orpheum, Golden Gate and Curran."""
import re
from ..core import now
from ..heuristics import listing_page

NAME, LABEL = "broadwaysf", "BroadwaySF"
URL = "https://www.broadwaysf.com/events/"


def fetch(f, start, end):
    events, _ = listing_page(f, URL, NAME,
                             lambda u: "broadwaysf.com/events/" in u and u.rstrip("/") != URL.rstrip("/"),
                             city="San Francisco", default_hour=19)
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
        out.append(e)
    return out
