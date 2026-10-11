"""San Francisco Fleet Week (fleetweeksf.org): the air show, the Parade of
Ships, Fleet Fest and the rest, from the official events page. It's one week
each October; the rest of the year the page shows next year's dates or none.
Funcheap carries the side events but not the air show itself."""
import calendar
import datetime as dt
import re

from ..core import TZ, Event, clean, find_dates, iso, short_hash
from ..heuristics import at_time, end_time

NAME, LABEL = "fleetweek", "SF Fleet Week"
URL = "https://fleetweeksf.org/events/"
MONTH_DAY = re.compile(r"\b(1[0-2]|0?[1-9])/([0-3]?\d)\b")
RUN_DAYS = 3        # longer than this (ship tours all week) is listed once, as a run


def spelled(text):
    """'Friday 10/9' -> 'Friday October 9', so the usual date finder reads it."""
    return MONTH_DAY.sub(lambda m: f"{calendar.month_name[int(m.group(1))]} {int(m.group(2))}", text)


def days_in(line, ref):
    found = find_dates(spelled(line), ref)
    days = [d for pair in found for d in pair if d]
    return (min(days), max(days)) if days else None


def parse(soup, ref: dt.date):
    out, seen = [], set()
    for post in soup.select(".pp-content-carousel-post"):
        head = post.find(["h3", "h4"])
        link = head.find("a", href=True) if head else None
        excerpt = post.select_one(".pp-content-grid-post-excerpt")
        if not head or not excerpt:
            continue
        title = clean(head.get_text(" "))
        lines = [clean(x) for x in excerpt.get_text("\n").split("\n") if clean(x)]
        url = link["href"] if link else URL
        if (title, url) in seen:
            continue
        seen.add((title, url))
        blurb = " ".join(clean(p.get_text(" ")) for p in excerpt.find_all("p"))
        # lines run date, time[, place]; Fleet Fest lists a date and time per day
        slots, place = [], ""
        for i, line in enumerate(lines):
            span = days_in(line, ref)
            if span and i + 1 < len(lines) and re.search(r"\d\s*[ap]\.?m", lines[i + 1], re.I):
                slots.append((span, lines[i + 1]))
            elif not span and not re.search(r"\d\s*[ap]\.?m|vary", line, re.I) and line not in blurb and not place and len(line) <= 40:
                place = line
        if not place and " at " in title:
            place = title.split(" at ", 1)[1]
        for (first, last), hours in slots:
            if (last - first).days >= RUN_DAYS:
                days = [(first, last)]
            else:
                days = [(first + dt.timedelta(n), None) for n in range((last - first).days + 1)]
            for day, until in days:
                start, all_day = at_time(day, hours)
                end = end_time(start, hours) if not all_day else None
                if until and end:
                    end = dt.datetime.combine(until, end.time(), tzinfo=TZ)
                out.append(Event(
                    source=NAME, source_id=short_hash(url, title, day.isoformat()), source_url=url,
                    title=f"Fleet Week {title}" if "fleet" not in title.lower() else title,
                    start=iso(start), end=iso(end), all_day=all_day,
                    description=blurb[:500], venue=place[:70], city="San Francisco",
                    tags=["annual"],
                ))
    return out


def fetch(f, start, end):
    events = parse(f.soup(URL), start.date())
    return [e for e in events if start.isoformat() <= e.start <= end.isoformat() or (e.end and e.end >= start.isoformat() and e.start <= end.isoformat())]
