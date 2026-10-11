"""Eventbrite: keyword searches tuned to the profile (the full feed is too noisy)."""
from ..core import event_from_jsonld, jsonld_events

NAME, LABEL = "eventbrite", "Eventbrite"
SEARCHES = [
    ("ca--san-francisco", "craft-workshop"), ("ca--san-francisco", "meditation"),
    ("ca--san-francisco", "sound-bath"), ("ca--san-francisco", "comedy"),
    ("ca--san-francisco", "book-club"), ("ca--san-francisco", "drag"),
    ("ca--san-francisco", "karaoke"), ("ca--san-francisco", "writing-workshop"),
    ("ca--san-francisco", "salon"), ("ca--san-francisco", "queer"),
    ("ca--palo-alto", "workshop"), ("ca--palo-alto", "meditation"), ("ca--palo-alto", "comedy"),
]


def fetch(f, start, end):
    out, seen = [], set()
    for place, q in SEARCHES:
        soup = f.soup(f"https://www.eventbrite.com/d/{place}/{q}/")
        for node in jsonld_events(soup):
            e = event_from_jsonld(node, NAME)
            if e and e.source_url not in seen:
                seen.add(e.source_url)
                e.tags.append(q.replace("-", " "))
                out.append(e)
    return out
