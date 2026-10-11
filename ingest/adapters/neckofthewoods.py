"""Neck of the Woods (406 Clement St, Inner Richmond): concerts, comedy and
dance nights. Its calendar pages (/calendar/page/N/, 18 shows each) come from
the TicketWeb plugin, with the date, show time, price and ticket link."""
import datetime as dt
import re

from ..core import Event, clean, find_dates, iso
from ..heuristics import at_time, price_from

NAME, LABEL = "neckofthewoods", "Neck of the Woods"
BASE = "https://www.neckofthewoodssf.com/calendar/"
MAX_PAGES = 6
VENUE, ADDRESS = "Neck of the Woods", "406 Clement St"


def parse(soup, ref: dt.date):
    out = []
    for sec in soup.select(".tw-plugin-upcoming-event-list .tw-section"):
        name = sec.select_one(".tw-name a")
        date = sec.select_one(".tw-event-date")
        if not name or not date:
            continue
        days = find_dates(clean(date.get_text(" ")), ref)
        if not days:
            continue
        show = sec.select_one(".tw-event-time")
        start, all_day = at_time(days[0][0], clean(show.get_text(" ")) if show else "", default_hour=20)
        buy = sec.select_one(".tw-buy-tix-btn")
        price = sec.select_one(".tw-price")
        url = name["href"]
        cost = price_from(clean(price.get_text(" "))) if price else ""
        if re.fullmatch(r"\$0(\.00)?", cost):
            cost = "free"
        out.append(Event(
            source=NAME, source_id=url.rstrip("/").rsplit("/", 1)[-1] + "@" + days[0][0].isoformat(),
            source_url=url, ticket_url=buy["href"] if buy and buy.get("href") else None,
            title=clean(name.get_text(" ")), start=iso(start), all_day=all_day,
            venue=VENUE, address=ADDRESS, city="San Francisco",
            price=cost,
            sold_out=bool(buy and re.search(r"sold\s*out", buy.get_text(" "), re.I)),
        ))
    return out


def fetch(f, start, end):
    out = []
    for n in range(1, MAX_PAGES + 1):
        page = parse(f.soup(BASE if n == 1 else f"{BASE}page/{n}/"), start.date())
        if not page:
            break
        out += [e for e in page if start.isoformat() <= e.start <= end.isoformat()]
        if page[-1].start > end.isoformat():
            break
    if not out:
        raise RuntimeError("no shows on the calendar pages")
    return out
