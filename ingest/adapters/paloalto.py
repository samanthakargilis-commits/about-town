"""Destination Palo Alto calendar. The page loads its events with JavaScript;
this reads whatever structured data the page itself carries."""
from ..heuristics import listing_page

NAME, LABEL = "paloalto", "Destination Palo Alto"
URL = "https://www.destinationpaloalto.com/calendar"


def fetch(f, start, end):
    events, _ = listing_page(f, URL, NAME, lambda u: "destinationpaloalto.com" in u and "/event" in u,
                             city="Palo Alto")
    return events
