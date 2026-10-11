"""The Presidio (presidio.gov): the park's own calendar, including the Presidio
Chapel's Saturday concerts and shows at the Presidio Theatre. The site runs The
Events Calendar for WordPress, whose REST feed lists events as JSON. The feed
leaves the venue blank, so it's read from the title ("... at Presidio Theatre")."""
import re

from ..core import Event, clean, html_to_text, iso, to_local

NAME, LABEL = "presidio", "The Presidio"
API = "https://wp.presidio.gov/wp-json/tribe/events/v1/events"
MAX_PAGES = 8
# the feed has no places; these are the park's own (mapped from the address like any other)
PLACES = [
    (re.compile(r"presidio chapel|interfaith center", re.I), "Presidio Chapel", "130 Fisher Loop"),
    (re.compile(r"presidio theat(re|er)", re.I), "Presidio Theatre", "99 Moraga Ave"),
    (re.compile(r"tunnel tops|campfire", re.I), "Presidio Tunnel Tops", "210 Lincoln Blvd"),
    (re.compile(r"fort point", re.I), "Fort Point", "201 Marine Dr"),
    (re.compile(r"sports basement", re.I), "Sports Basement Presidio", "610 Old Mason St"),
]
CHORES = re.compile(r"^volunteer\b|stewards|litter pickup|landscaping and maintenance|nursery", re.I)


def place(title):
    for pattern, venue, address in PLACES:
        if pattern.search(title):
            return venue, address
    m = re.search(r"\bat (?:the )?([A-Z][\w’' .&-]{3,40})$", title)
    return (m.group(1), "") if m else ("The Presidio", "")


def to_event(it):
    utc = lambda k: to_local(it[k].replace(" ", "T") + "Z") if it.get(k) else None
    st = utc("utc_start_date") or to_local(it.get("start_date"))
    title = html_to_text(it.get("title") or "")
    if not st or not title or CHORES.search(title):
        return None
    venue, address = place(title)
    cost = clean(it.get("cost") or "")
    img = it.get("image") if isinstance(it.get("image"), dict) else {}
    return Event(
        source=NAME, source_id=str(it.get("id") or it.get("slug")) + "@" + st.date().isoformat(),
        source_url=it.get("url") or "https://www.presidio.gov/explore/events/",
        title=title, start=iso(st), end=iso(utc("utc_end_date")), all_day=it.get("all_day") in (True, "True", "true"),
        description=html_to_text(it.get("description") or it.get("excerpt") or "")[:1000],
        image_url=img.get("url"), venue=venue, address=address, city="San Francisco",
        price="free" if cost.lower() in ("free", "$0", "0") else cost,
        tags=[clean(c.get("name")) for c in it.get("categories") or [] if isinstance(c, dict)],
    )


def fetch(f, start, end):
    out = []
    for page in range(1, MAX_PAGES + 1):
        data = f.get(API, params={"start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"),
                                  "per_page": 50, "page": page}, as_json=True)
        out += [e for e in (to_event(it) for it in data.get("events", [])) if e]
        if page >= int(data.get("total_pages") or 1):
            break
    if not out:
        raise RuntimeError("no events in the park's feed")
    return out
