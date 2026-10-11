"""City Lights Booksellers (SF): readings, poetry, literary and political talks."""
import re
from ..heuristics import listing_page

NAME, LABEL = "citylights", "City Lights"
URL = "https://citylights.com/events/"


def fetch(f, start, end):
    events, soup = listing_page(f, URL, NAME, lambda u: bool(re.match(r"https://citylights\.com/events/[^/]+/?$", u)) and u.rstrip("/") != URL.rstrip("/"),
                                city="San Francisco")
    if not events and "sucuri" in str(soup).lower():
        raise RuntimeError("blocked by the site's bot protection (Sucuri JavaScript check)")
    for e in events:
        txt = (e.description or "").lower()
        if re.search(r"\bvirtual\b|\bonline\b|zoom", txt) and "instore" not in txt and "in-store" not in txt:
            e.city = "Online"
        if not e.venue:
            e.venue = "City Lights Booksellers, 261 Columbus Ave" if "offsite" not in txt else ""
    return events
