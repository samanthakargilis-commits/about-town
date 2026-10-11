"""Presidio Theatre (99 Moraga Ave): music, dance, comedy, film and family
shows. The shows page carries schema.org data for each production, with one
offer per performance giving its start time. A production with many
performances (a holiday musical) is listed once, as a run."""
import datetime as dt
import re
from urllib.parse import parse_qs, urlparse

from ..core import Event, clean, html_to_text, iso, jsonld_events, to_local

NAME, LABEL = "presidiotheatre", "Presidio Theatre"
URL = "https://www.presidiotheatre.org/shows"
DETAILS = "https://www.presidiotheatre.org/show-details/"
VENUE, ADDRESS = "Presidio Theatre", "99 Moraga Ave"
RUN = 3          # more performances than this become one listing


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse(soup):
    out = []
    pages = sorted({a["href"] for a in soup.find_all("a", href=True) if a["href"].startswith(DETAILS)})
    for node in jsonld_events(soup):
        title = clean(html_to_text(node.get("name") or ""))
        offers = node.get("offers") or []
        offers = offers if isinstance(offers, list) else [offers]
        shows = sorted({(t, o.get("url") or "") for o in offers if isinstance(o, dict)
                        for t in [to_local(o.get("validFrom"))] if t})
        times = [t for t, _ in shows]
        if not title or not times:
            continue
        show = (parse_qs(urlparse(shows[0][1]).query).get("ShowName") or [""])[0]
        page = DETAILS + show if show else next((u for u in pages if u[len(DETAILS):][:14] == slug(title)[:14]), URL)
        image = node.get("image")
        common = dict(source=NAME, source_url=page, title=title, venue=VENUE, address=ADDRESS, city="San Francisco",
                      description=html_to_text(node.get("description") or "")[:1000],
                      image_url=image if isinstance(image, str) else None,
                      sold_out=all("SoldOut" in str(o.get("availability", "")) for o in offers if isinstance(o, dict)))
        if len(times) > RUN:
            out.append(Event(source_id=f"{show or title}@run", start=iso(times[0]),
                             end=iso(times[-1] + dt.timedelta(hours=2)), ticket_url=page,
                             **common))
            continue
        for t, buy in shows:
            out.append(Event(source_id=f"{show or slug(title)}@{iso(t)}", start=iso(t), ticket_url=buy or page, **common))
    return out


def fetch(f, start, end):
    events = parse(f.soup(URL))
    if not events:
        raise RuntimeError("no shows on the shows page")
    return [e for e in events if (e.end or e.start) >= start.isoformat() and e.start <= end.isoformat()]
