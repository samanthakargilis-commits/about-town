"""The 4 Star Theater (2200 Clement St): repertory films, festivals and live
music. The theater sells tickets through Veezi, whose public showtimes page
lists every film with its rating, synopsis and session times. One event per
film per day; the other times that day go in the description."""
import datetime as dt
import re

from ..core import Event, clean, find_dates, iso
from ..heuristics import at_time

NAME, LABEL = "fourstar", "4 Star Theater"
SITE = "https://www.4-star-movies.com/calendar"
SESSIONS = "https://ticketing.uswest.veezi.com/sessions/?siteToken=d2atbcege5knqsavntt91g1250"
VEEZI = "https://ticketing.uswest.veezi.com"
VENUE, ADDRESS = "4 Star Theater", "2200 Clement St"
DAY = re.compile(r"(\w+day)\s+(\d{1,2}),\s+(\w+)")       # "Friday 30, October"


def parse(soup, ref: dt.date):
    out = []
    box = soup.find(id="sessionsByFilmConent") or soup
    for film in box.select("div.film"):
        head = film.select_one("h3.title")
        if not head:
            continue
        title = clean(head.get_text(" "))
        rating = film.select_one(".censor")
        rating_line = clean(rating.parent.get_text(" ")) if rating else ""
        desc = film.select_one(".film-desc")
        blurb = clean(desc.get_text(" ")) if desc else ""
        music = bool(re.match(r"(live )?music\b", title, re.I))
        for day_box in film.select(".date-container"):
            m = DAY.search(clean(day_box.select_one(".date").get_text(" ")) if day_box.select_one(".date") else "")
            days = find_dates(f"{m.group(3)} {m.group(2)}", ref) if m else []
            times = [clean(t.get_text(" ")) for t in day_box.select("time")]
            if not days or not times:
                continue
            day = days[0][0]
            start, _ = at_time(day, times[0])
            buy = day_box.select_one("a[href]")
            also = f"Also at {', '.join(times[1:])}. " if len(times) > 1 else ""
            out.append(Event(
                source=NAME, source_id=f"{film.get('id') or title}@{day.isoformat()}",
                source_url=SITE, ticket_url=VEEZI + buy["href"] if buy else SESSIONS,
                title=title, start=iso(start),
                description=(also + (f"Rated {rating_line}. " if rating_line else "") + blurb)[:600],
                venue=VENUE, address=ADDRESS, city="San Francisco",
                tags=["cinema-concert"] if music else ["film"],
            ))
    return out


def fetch(f, start, end):
    events = parse(f.soup(SESSIONS), start.date())
    if not events:
        raise RuntimeError("no showtimes on the ticketing page")
    return [e for e in events if start.isoformat() <= e.start <= end.isoformat()]
