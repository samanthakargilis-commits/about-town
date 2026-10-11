"""San Francisco Public Library, Presidio branch (3150 Sacramento St).
The events page is a Drupal view; its location filter works as a URL
parameter. Each teaser has the date and a time range like "2:00 - 3:00",
usually without am/pm."""
import datetime as dt
import re
from urllib.parse import urljoin

from ..core import TZ, Event, clean, iso

NAME, LABEL = "sfpl", "SF Public Library (Presidio)"
BASE = "https://sfpl.org"
LOCATION_ID = 59          # Presidio branch
WHEN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:,\s*(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?(?:\s*-\s*(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?)?)?", re.I)


def clock(h, m, mer, fallback_pm=None):
    h, m = int(h), int(m)
    if mer:
        pm = mer.lower().startswith("p")
    elif fallback_pm is not None:
        pm = fallback_pm
    else:
        pm = h < 9 or h == 12  # branch hours are about 10am to 8pm, so "2:00" is 2pm
    if pm and h < 12:
        h += 12
    if not pm and h == 12:
        h = 0
    return h, m


def parse_when(text):
    m = WHEN.search(text)
    if not m:
        return None, None, True
    mo, d, y = int(m[1]), int(m[2]), int(m[3])
    if not m[4]:
        return dt.datetime(y, mo, d, tzinfo=TZ), None, True
    end_mer = m[9]
    sh, sm = clock(m[4], m[5], m[6] or (end_mer if m[7] and int(m[4]) <= int(m[7]) < 12 else None))
    start = dt.datetime(y, mo, d, sh, sm, tzinfo=TZ)
    end = None
    if m[7]:
        eh, em = clock(m[7], m[8], end_mer, fallback_pm=sh >= 12 or None)
        end = dt.datetime(y, mo, d, eh, em, tzinfo=TZ)
        if end <= start:
            end = None
    return start, end, False


def fetch(f, start, end):
    out, seen = [], set()
    for page in range(0, 6):
        soup = f.soup(f"{BASE}/events", params={"field_event_location_target_id": LOCATION_ID, "page": page})
        teasers = soup.select("article.event")
        for art in teasers:
            a = art.select_one(".event__title a") or art.find("a", href=re.compile(r"^/events/\d{4}/"))
            if not a:
                continue
            href = a["href"].split("?")[0]
            loc = clean(art.select_one(".event__location").get_text(" ")) if art.select_one(".event__location") else ""
            if href in seen or (loc and "presidio" not in loc.lower()):
                continue
            seen.add(href)
            title = clean(a.get_text(" "))
            date_el = art.select_one(".event__date")
            st, en, all_day = parse_when(clean(date_el.get_text(" ")) if date_el else "")
            if not st or title.lower().startswith("canceled"):
                continue
            audience = [clean(x.get_text(" ")) for x in art.select(".event__audience .field__item")]
            topics = [clean(x.get_text(" ")) for x in art.select(".event__topics .field__item")]
            img = art.select_one(".event__image img")
            out.append(Event(
                source=NAME, source_id=href.rsplit("/", 1)[-1] + "@" + st.date().isoformat(),
                source_url=urljoin(BASE, href), title=title, start=iso(st), end=iso(en), all_day=all_day,
                description=" · ".join(audience + topics), tags=topics,
                image_url=urljoin(BASE, img["src"]) if img and img.get("src") else None,
                venue="Presidio Branch Library", address="3150 Sacramento St", city="San Francisco", price="free",
            ))
        if not teasers:
            break
    return out
