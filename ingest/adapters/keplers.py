"""Kepler's Books (Menlo Park): author talks, readings and signings."""
import re
from ..heuristics import listing_page

NAME, LABEL = "keplers", "Kepler's Books"
URLS = ["https://www.keplers.org/upcoming-events", "https://keplers.org/upcoming-events"]


def fetch(f, start, end):
    for url in URLS:
        try:
            events, _ = listing_page(f, url, NAME,
                                     lambda u: "keplers.org" in u and bool(re.search(r"/(event|events|upcoming-events)/[^/?#]+", u)),
                                     city="Menlo Park", default_hour=19)
        except Exception:
            continue
        for e in events:
            e.venue = e.venue or "Kepler's Books, 1010 El Camino Real, Menlo Park"
        return events
    return []
