"""San Francisco Public Library, Presidio branch (3150 Sacramento St).
The events page is a Drupal view; its location filter works as a URL
parameter, and each event links to /events/YYYY/MM/DD/<slug>."""
import datetime as dt
import re
from urllib.parse import urljoin

from ..core import TZ, Event, clean, iso, parse_time
from ..heuristics import end_time, price_from

NAME, LABEL = "sfpl", "SF Public Library (Presidio)"
BASE = "https://sfpl.org"
LOCATION_ID = 59          # Presidio branch
LINK = re.compile(r"^/events/(\d{4})/(\d{2})/(\d{2})/[^/?#]+$")


def fetch(f, start, end):
    out, seen = [], set()
    for page in range(0, 6):
        soup = f.soup(f"{BASE}/events", params={"field_event_location_target_id": LOCATION_ID, "page": page})
        rows = soup.select(".views-row") or [soup]
        added = 0
        for row in rows:
            for a in row.find_all("a", href=True):
                href = a["href"].split("?")[0]
                m = LINK.match(href)
                if not m or href in seen:
                    continue
                title = clean(a.get_text(" "))
                if len(title) < 4:
                    continue
                seen.add(href)
                block = a
                for parent in a.parents:      # the smallest block holding this event's details
                    if parent.name in ("body", "html"):
                        break
                    links = {x["href"].split("?")[0] for x in parent.find_all("a", href=True) if LINK.match(x["href"].split("?")[0])}
                    if len(links) > 1:
                        break
                    block = parent
                text = clean(block.get_text(" "))
                if re.search(r"\b(online|virtual|zoom)\b", text, re.I) and not re.search(r"presidio", text, re.I):
                    continue
                if not re.search(r"presidio", text, re.I) and rows != [soup]:
                    continue              # the filter wasn't applied: keep only Presidio
                day = dt.date(int(m[1]), int(m[2]), int(m[3]))
                t = parse_time(text)
                st = dt.datetime(day.year, day.month, day.day, *(t or (0, 0)), tzinfo=TZ)
                out.append(Event(
                    source=NAME, source_id=href.rsplit("/", 1)[-1] + "@" + day.isoformat(), source_url=urljoin(BASE, href),
                    title=re.sub(r"^Canceled:\s*", "Canceled: ", title), start=iso(st), all_day=t is None,
                    end=iso(end_time(st, text)) if t else None, description=text[:600],
                    venue="Presidio Branch Library", address="3150 Sacramento St", city="San Francisco",
                    price=price_from(text) or "free",
                ))
                added += 1
        if not added:
            break
    return [e for e in out if not e.title.lower().startswith("canceled")]
