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
    for e in events:
        e.tags.append("musical")
    return events
