"""Sources added from the app's You tab. The app opens a GitHub issue titled
"Add source: <site>" with the link in it; each daily run reads the open ones
and gives every site its own reader and its own line on the Sources list, so a
site that can't be read never breaks the others. Closing the issue drops it.

A site is read the gentlest way it allows: its iCal feed if it has one, else
the schema.org event data on the page, else event links with a date nearby."""
import datetime as dt
import json
import re
from urllib.parse import urljoin, urlparse

from .core import Event, clean, iso, short_hash, slug, to_local
from .heuristics import listing_page

# only the repo's own people can add a source (anyone can open an issue on a public repo)
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
NEVER = re.compile(r"(^|\.)(instagram\.com|reddit\.com|facebook\.com|goodreads\.com)$", re.I)
MAX_REQUESTS = 40


def host_of(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def requests_from(issues) -> list[dict]:
    """[{url, host, name, issue}] from the repo's open issues."""
    out, seen = [], set()
    for it in issues or []:
        if it.get("pull_request") or it.get("state", "open") != "open":
            continue
        if not re.match(r"\s*add (a )?source", it.get("title") or "", re.I):
            continue
        if it.get("author_association") not in TRUSTED:
            continue
        m = re.search(r"(?:https?://|webcal://)[^\s<>()\"']+", it.get("body") or "")
        if not m:
            continue
        url = m.group(0).rstrip(".,)").replace("webcal://", "https://", 1)
        host = host_of(url)
        if not host or NEVER.search(host) or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "host": host, "name": "added-" + slug(host)[:40], "issue": it.get("number")})
    return out


def load(path) -> list[dict]:
    try:
        return requests_from(json.loads(open(path).read()))
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------ iCal

def unfold(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def ics_unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def ics_time(params: str, value: str):
    """(datetime, all_day) from a DTSTART/DTEND line."""
    value = value.strip()
    if "VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", value):
        d = dt.datetime.strptime(value[:8], "%Y%m%d")
        return to_local(d.isoformat()), True
    fmt = "%Y%m%dT%H%M%S" if len(value.rstrip("Z")) == 15 else "%Y%m%dT%H%M"
    d = dt.datetime.strptime(value.rstrip("Z"), fmt)
    if value.endswith("Z"):
        return to_local(d.replace(tzinfo=dt.timezone.utc).isoformat()), False
    return to_local(d.isoformat()), False      # TZID or floating: the Bay's own time


def ics_events(text: str, source: str, page_url: str, start, end) -> list[Event]:
    out = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        props = {}
        for line in unfold(block):
            m = re.match(r"([A-Z-]+)((?:;[^:]*)?):(.*)", line)
            if m and m.group(1) not in props:
                props[m.group(1)] = (m.group(2), m.group(3))
        if "DTSTART" not in props or "SUMMARY" not in props:
            continue
        try:
            s, all_day = ics_time(*props["DTSTART"])
            e = ics_time(*props["DTEND"])[0] if "DTEND" in props else None
        except ValueError:
            continue
        if not s or not (start <= s <= end or (e and s < start <= e)):
            continue
        if all_day and e and (e - s).days <= 1:
            e = None
        loc = clean(ics_unescape(props.get("LOCATION", ("", ""))[1]))
        venue, _, address = loc.partition(",")
        uid = props.get("UID", ("", ""))[1] or f"{props['SUMMARY'][1]}{props['DTSTART'][1]}"
        out.append(Event(
            source=source, source_id=short_hash(uid), title=clean(ics_unescape(props["SUMMARY"][1])),
            source_url=props.get("URL", ("", ""))[1].strip() or page_url,
            start=iso(s), end=iso(e), all_day=all_day,
            description=clean(ics_unescape(props.get("DESCRIPTION", ("", ""))[1]))[:600],
            venue=clean(venue)[:80], address=clean(address)))
    return out


def feed_link(soup, base):
    """The page's own iCal feed, if it offers one."""
    for link in soup.find_all("link", href=True):
        if "calendar" in (link.get("type") or ""):
            return urljoin(base, link["href"])
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if re.search(r"\.ics(\?|$)|^webcal:|[?&]ical=1", h, re.I):
            return urljoin(base, h.replace("webcal://", "https://", 1))
    return None


# ------------------------------------------------------------------ one site

def fetch(f, req: dict, start, end) -> list[Event]:
    url, name = req["url"], req["name"]
    if re.search(r"\.ics(\?|$)", url, re.I):
        return ics_events(f.get(url), name, url, start, end)
    base_path = urlparse(url).path.rstrip("/")
    host = req["host"]

    def is_event_url(u):
        p = urlparse(u)
        return host_of(u) == host and p.path.rstrip("/") != base_path and len(p.path.strip("/")) > 3 and \
            bool(re.search(r"event|show|calendar|program|whats-on|/\d{4}/", p.path, re.I) or p.path.startswith(base_path + "/"))

    events, soup = listing_page(f, url, name, is_event_url)
    if not events:
        feed = feed_link(soup, url)
        if feed:
            events = ics_events(f.get(feed), name, url, start, end)
    if not events:
        raise RuntimeError("no events found on that page (no calendar feed or event listings)")
    keep = []
    for e in events:
        s = to_local(e.start)
        en = to_local(e.end) if e.end else None
        if s and (start <= s <= end or (en and s < start <= en)):
            keep.append(e)
    return keep
