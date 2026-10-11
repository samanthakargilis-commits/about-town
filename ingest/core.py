"""Shared pieces for every adapter: the event shape, a polite HTTP client, and date helpers."""
from __future__ import annotations

import datetime as dt
import hashlib
import html as htmllib
import json
import os
import pathlib
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

TZ = ZoneInfo("America/Los_Angeles")
ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_DIR = pathlib.Path(os.environ.get("INGEST_CACHE", ROOT / ".cache"))
USER_AGENT = (
    "Mozilla/5.0 (compatible; BayEventsPersonalPlanner/1.0; one-person event planner; "
    "+https://github.com/) python-requests"
)


@dataclass
class Event:
    source: str
    source_id: str
    source_url: str
    title: str
    start: str                      # ISO 8601 with offset
    end: Optional[str] = None
    all_day: bool = False
    timezone: str = "America/Los_Angeles"
    description: str = ""
    image_url: Optional[str] = None
    venue: str = ""
    address: str = ""
    city: str = ""
    price: str = ""                 # "free", "$25", "$30-45", ...
    tags: list = field(default_factory=list)       # source-provided categories
    people: list = field(default_factory=list)     # performers / authors named
    parent_event: Optional[dict] = None             # {"title":..., "url":...}
    recurring: bool = False
    sponsored: bool = False
    ticket_url: Optional[str] = None                # tickets / RSVP link when it differs from source_url
    lat: Optional[float] = None                     # venue map spot, for distance in the app
    lng: Optional[float] = None
    sold_out: bool = False                          # no tickets left: dropped, since you can't go

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d


# ---------------------------------------------------------------- text utils

def clean(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    if "&" in text and ";" in text:          # "Kepler&#39;s" from feeds that escape twice
        text = htmllib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = text.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def short_hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def html_to_text(html: str) -> str:
    return clean(BeautifulSoup(html or "", "lxml").get_text(" "))


# ---------------------------------------------------------------- dates

def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def to_local(value) -> Optional[dt.datetime]:
    """Parse anything date-like into an aware datetime in Pacific time."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # epoch seconds or milliseconds
        if value > 1e11:
            value = value / 1000
        return dt.datetime.fromtimestamp(value, TZ)
    if isinstance(value, dt.datetime):
        d = value
    elif isinstance(value, dt.date):
        d = dt.datetime(value.year, value.month, value.day)
    else:
        try:
            d = dateparser.parse(str(value))
        except (ValueError, OverflowError):
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(TZ)


def iso(d: Optional[dt.datetime]) -> Optional[str]:
    return d.isoformat(timespec="minutes") if d else None


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b", re.I)


def parse_time(text: str):
    """Return (hour, minute) of the first clock time in text, or None."""
    m = TIME_RE.search(text or "")
    if not m:
        if re.search(r"\bnoon\b", text or "", re.I):
            return 12, 0
        return None
    h, mnt, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if h > 12:
        return None
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return h, mnt


def find_dates(text: str, ref: dt.date):
    """Find month-day mentions like 'Oct 17', 'October 22-25', 'Nov. 14 & 15'.

    Returns a list of (start_date, end_date) tuples. Years are inferred so the date
    is not more than ~2 months in the past relative to ref.
    """
    out = []
    pattern = re.compile(
        MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s*(?:-|–|—|to|through|&|and)\s*(?:" + MONTH_RE + r"\s+)?(\d{1,2})(?:st|nd|rd|th)?)?"
        r"(?:,?\s*(20\d\d))?",
        re.I,
    )
    for m in pattern.finditer(text or ""):
        mon = MONTHS[m.group(1)[:3].lower()]
        day = int(m.group(2))
        mon2 = MONTHS[m.group(3)[:3].lower()] if m.group(3) else mon
        day2 = int(m.group(4)) if m.group(4) else None
        year = int(m.group(5)) if m.group(5) else None
        try:
            start = _infer_year(mon, day, ref, year)
            end = _infer_year(mon2, day2, ref, year or start.year) if day2 else None
            if end and end < start:
                end = end.replace(year=end.year + 1)
        except ValueError:
            continue
        out.append((start, end))
    return out


def _infer_year(month, day, ref: dt.date, year=None) -> dt.date:
    if year:
        return dt.date(year, month, day)
    d = dt.date(ref.year, month, day)
    if (ref - d).days > 60:
        d = dt.date(ref.year + 1, month, day)
    return d


# ---------------------------------------------------------------- HTTP

class Fetcher:
    """Gentle HTTP: one request at a time per host, a pause between requests,
    an on-disk cache for detail pages, and a per-source request budget."""

    def __init__(self, delay: float = 1.5, max_requests: int = 120):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.delay = delay
        self.max_requests = max_requests
        self.count = 0
        self._last = 0.0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url, *, params=None, headers=None, cache_hours: float = 0, as_json=False, timeout=30):
        key = None
        if cache_hours:
            key = CACHE_DIR / (short_hash(url, json.dumps(params, sort_keys=True)) + (".json" if as_json else ".html"))
            if key.exists() and time.time() - key.stat().st_mtime < cache_hours * 3600:
                text = key.read_text(encoding="utf-8")
                return json.loads(text) if as_json else text
        if self.count >= self.max_requests:
            raise BudgetExceeded(url)
        self._wait()
        self.count += 1
        resp = self.session.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        text = resp.text
        if key:
            key.write_text(text, encoding="utf-8")
        return resp.json() if as_json else text

    def soup(self, url, **kw) -> BeautifulSoup:
        return BeautifulSoup(self.get(url, **kw), "lxml")


class BudgetExceeded(Exception):
    pass


# ---------------------------------------------------------------- structured data helpers

def jsonld_events(soup: BeautifulSoup) -> list[dict]:
    """All schema.org Event objects in a page's JSON-LD blocks."""
    found = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            t = node.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(isinstance(x, str) and x.endswith("Event") for x in types):
                found.append(node)
            for k in ("@graph", "itemListElement", "item", "subEvent", "mainEntity"):
                if k in node:
                    walk(node[k])

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(tag.string or tag.get_text() or "null"))
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def place_of(loc) -> tuple[str, str, str]:
    """(venue, address, city) from a schema.org Place."""
    venue = address = city = ""
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if isinstance(loc, dict):
        venue = clean(loc.get("name"))
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            address = clean(" ".join(filter(None, [addr.get("streetAddress"), addr.get("addressLocality")])))
            city = clean(addr.get("addressLocality"))
        elif isinstance(addr, str):
            address = clean(addr)
            # "1398 Haight Street, San Francisco" / "2 Orinda Theatre Sq, Orinda, CA 94563"
            bits = [b.strip() for b in re.sub(r",?\s*(CA|California)\b.*$", "", address).split(",")]
            if len(bits) > 1 and not re.search(r"\d", bits[-1]):
                city = bits[-1]
        if loc.get("@type") == "VirtualLocation":
            city = "Online"
    return venue, address, city


def money(v) -> Optional[float]:
    try:
        return float(str(v).replace("$", "").replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def event_from_jsonld(node: dict, source: str, fallback_url: str = "") -> Optional[Event]:
    title = clean(node.get("name"))
    start = to_local(node.get("startDate"))
    if not title or not start:
        return None
    loc = node.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    venue, address, city = place_of(loc)
    offers = node.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = ""
    if isinstance(offers, dict):
        p = money(offers.get("price")) if offers.get("price") not in (None, "") else money(offers.get("lowPrice"))
        high = money(offers.get("highPrice"))
        if p == 0 and not high:
            price = "free"
        elif p == 0:
            price = f"free–${high:g}"             # free RSVP with paid tiers
        elif p:
            price = f"${p:.2f}".replace(".00", "")
    image = node.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    url = node.get("url") or fallback_url
    performers = node.get("performer") or []
    if isinstance(performers, dict):
        performers = [performers]
    people = [clean(p.get("name")) for p in performers if isinstance(p, dict) and p.get("name")]
    end = to_local(node.get("endDate"))
    return Event(
        source=source,
        source_id=slug(url)[-80:] or short_hash(title, iso(start)),
        source_url=url,
        title=title,
        start=iso(start),
        end=iso(end) if end and end > start else None,
        description=html_to_text(node.get("description") or "")[:1200],
        image_url=image if isinstance(image, str) else None,
        venue=venue,
        address=address,
        city=city,
        price=price,
        people=people,
        lat=geo_of(loc)[0] if isinstance(loc, dict) else None,
        lng=geo_of(loc)[1] if isinstance(loc, dict) else None,
    )


def geo_of(*nodes) -> tuple[Optional[float], Optional[float]]:
    """Find a latitude/longitude pair in source data (any of the usual key names,
    one level of nesting under geo/coordinate/location), inside the Bay Area."""
    lat_keys = ("latitude", "lat", "geo_latitude", "Latitude", "Lat")
    lng_keys = ("longitude", "lng", "lon", "geo_longitude", "Longitude", "Lng", "Lon")
    stack = [n for n in nodes if isinstance(n, dict)]
    for node in list(stack):
        for k in ("geo", "coordinate", "coordinates", "location", "Location", "venue", "geo_address_info"):
            if isinstance(node.get(k), dict):
                stack.append(node[k])
    for node in stack:
        la = next((node[k] for k in lat_keys if node.get(k) not in (None, "")), None)
        ln = next((node[k] for k in lng_keys if node.get(k) not in (None, "")), None)
        try:
            la, ln = float(la), float(ln)
        except (TypeError, ValueError):
            continue
        if 36.8 < la < 38.6 and -123.2 < ln < -121.3:
            return round(la, 5), round(ln, 5)
    return None, None


def next_data(soup: BeautifulSoup) -> Optional[dict]:
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag:
        return None
    try:
        return json.loads(tag.string or "")
    except json.JSONDecodeError:
        return None


def og(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", property=f"og:{prop}") or soup.find("meta", attrs={"name": f"og:{prop}"})
    return tag.get("content") if tag else None
