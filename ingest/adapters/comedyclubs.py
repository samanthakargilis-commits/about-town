"""Cobb's Comedy Club (North Beach) and the Punch Line (Battery St): the city's
two big stand-up rooms. Both are Live Nation venues whose home pages carry
schema.org Event data for the upcoming shows (about the next 25 each); each
show links to its ticket page."""
from ..core import event_from_jsonld, jsonld_events

NAME, LABEL = "comedyclubs", "Cobb's & Punch Line"
CLUBS = {
    "https://www.cobbscomedy.com/": ("Cobb's Comedy Club", "915 Columbus Avenue"),
    "https://www.punchlinecomedyclub.com/": ("Punch Line Comedy Club", "444 Battery Street"),
}


def fetch(f, start, end):
    out, seen = [], set()
    for url, (venue, address) in CLUBS.items():
        try:
            soup = f.soup(url)
        except Exception as exc:          # one club down doesn't lose the other
            print(f"  {venue}: {exc}")
            continue
        for node in jsonld_events(soup):
            e = event_from_jsonld(node, NAME, url)
            if not e or e.id in seen:
                continue
            seen.add(e.id)
            e.venue, e.address, e.city = venue, address, "San Francisco"
            e.tags = sorted(set(e.tags) | {"comedy"})
            out.append(e)
    if not out:
        raise RuntimeError("neither club page had show data")
    return out
