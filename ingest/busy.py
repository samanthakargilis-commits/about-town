"""When you're busy and where you'll be, so the one-a-day calendar only suggests what fits.

Two inputs, both optional:
  - your weekly routine in data/profile.json ("week"): which office or home you're at each
    weekday, when the workday ends, and where your evening starts
  - your own calendars, read from private calendar links kept in the CALENDAR_LINKS secret
    (one link per line; put "work " before a link whose events are all fixed)

Official-looking events (other people invited, a place, a meeting link, a fixed calendar,
words like appointment or flight) block their time plus travel. Casual ones (gym, errands,
focus time, a hold, anything tentative or untitled-looking) don't: an idea may sit over them.

Privacy: the repo and its run log are public. Nothing from your calendars is printed, saved
or published; the only trace is which idea a day ends up with. Spots for your calendar's
places are cached under hashed keys in the job's private cache, never in the site.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time

import requests

from .core import CACHE_DIR, TZ, short_hash, to_local

TRAVEL = dt.timedelta(minutes=30)       # around a fixed event: getting there and back
NEAR_BEFORE = dt.timedelta(hours=3)     # a placed event this close before an idea says where you'll be
NEAR_AFTER = dt.timedelta(hours=2)
LONG_EVENT = dt.timedelta(hours=3)    # longer than this is drop-in: you needn't stay the whole time
DROP_IN = dt.timedelta(minutes=90)
AWAY_MILES = 40                         # an all-day event this far from home means you're out of town
LOOKUPS = 25                            # new place lookups per run
GEO_CACHE = CACHE_DIR / "busy-geo.json"

SOFT = re.compile(r"\b(gym|work ?out|run|running|walk|errands?|chores?|laundry|groceries|focus|deep work|hold|"
                  r"block(ed)?|maybe|tentative|tbd|optional|free|personal|me time|read(ing)?|nap|todo|to-do|"
                  r"reminder|clean(ing)?|meal prep|commute|travel time)\b|\?$", re.I)
FIRM = re.compile(r"\b(appointment|appt|doctor|dr\.?|dentist|therapy|therapist|vet|haircut|flight|fly|"
                  r"interview|wedding|funeral|tickets?|reservation|rsvp|class|lesson|concert|show|game|"
                  r"party|birthday|dinner|brunch|date|meeting|call|1:1|sync|standup|review|with)\b", re.I)
MEETING = re.compile(r"zoom\.us|meet\.google|teams\.microsoft|webex|whereby", re.I)


def miles(a, b):
    from .feed import miles as m      # feed doesn't import this module, so no cycle
    return m(a, b)


class Block:
    __slots__ = ("start", "end", "firm", "spot", "buffer")

    def __init__(self, start, end, firm, spot=None, buffer=TRAVEL):
        self.start, self.end, self.firm, self.spot, self.buffer = start, end, firm, spot, buffer


def is_firm(title: str, location: str, attendees: int, tentative: bool, fixed_calendar: bool) -> bool:
    """Would you keep this, or happily do something else instead?"""
    if fixed_calendar or attendees > 0:
        return True
    if SOFT.search(title or "") or tentative:
        return False
    if MEETING.search(location or "") or (location or "").strip():
        return True
    return bool(FIRM.search(title or ""))


class Plan:
    """Your week: routine plus calendar. Ask it whether an idea clashes and where you'll be."""

    def __init__(self, profile: dict, blocks=(), all_day=()):
        self.profile = profile
        self.home = profile.get("home")
        self.week = profile.get("week") or {}
        self.places = self.week.get("places") or {}
        self.blocks = sorted(blocks, key=lambda b: b.start)
        self.away = set()
        for start_day, end_day, spot in all_day:      # out of town: an all-day event far from home
            if spot and self.home and miles(self.home, spot) > AWAY_MILES:
                d = start_day
                while d < end_day:
                    self.away.add(d)
                    d += dt.timedelta(days=1)

    def place(self, name):
        if name == "home" or not name:
            return self.home
        return self.places.get(name) or self.home

    def day(self, d: dt.date) -> dict:
        days = self.week.get("days") or []
        return days[d.weekday()] if d.weekday() < len(days) else {}

    def routine(self, d: dt.date):
        """Work hours outside the lunch window, as fixed blocks with no travel buffer."""
        rule = self.day(d)
        if not rule.get("work", d.weekday() < 5) or not self.week.get("days"):
            return []
        lunch = self.profile.get("weekday_daytime") or {}
        hours = [(self.week.get("work_from", 9), lunch.get("from_hour", 10.5)),
                 (lunch.get("to_hour", 15), rule.get("work_until", self.week.get("work_until", 17.5)))]
        at = lambda h: dt.datetime.combine(d, dt.time(int(h), int(round(h % 1 * 60))), TZ)
        return [Block(at(a), at(b), True, self.place(rule.get("day")), dt.timedelta(0)) for a, b in hours if b > a]

    @staticmethod
    def span(ev):
        s, e = to_local(ev["start"]), to_local(ev.get("end"))
        if not e or e <= s or (e - s) > dt.timedelta(hours=12):
            e = s + dt.timedelta(hours=2)
        return s, e

    def timed(self, ev) -> bool:
        s, e = to_local(ev["start"]), to_local(ev.get("end"))
        return not ev.get("all_day") and not (e and (e - s).total_seconds() > 1.5 * 86400)

    def clashes(self, ev) -> bool:
        """Short events need their whole time free. Long open ones (a street fair, an exhibit,
        a night market) only need an hour and a half of it: you can arrive after work."""
        if not self.timed(ev):
            return False                    # a fair or a long run fits around whatever you have
        s, e = self.span(ev)
        need = e - s if e - s <= LONG_EVENT else DROP_IN
        busy = sorted(((b.start - b.buffer, b.end + b.buffer) for b in self.routine(s.date()) + self.blocks
                       if b.firm and s < b.end + b.buffer and e > b.start - b.buffer), key=lambda x: x[0])
        free_from = s
        for a, b in busy:
            if a - free_from >= need:
                return False
            free_from = max(free_from, b)
        return e - free_from < need

    def is_away(self, d: dt.date) -> bool:
        return d in self.away

    def base(self, ev):
        """Where you'll be coming from: a placed event just before (or right after) the idea,
        else your routine: the office until the workday ends, then the evening's place."""
        s, e = self.span(ev)
        near = [b for b in self.blocks if b.spot and b.start.date() == s.date()
                and (s - NEAR_BEFORE <= b.end <= s or e <= b.start <= e + NEAR_AFTER)]
        if near:
            return min(near, key=lambda b: min(abs((s - b.end).total_seconds()), abs((b.start - e).total_seconds()))).spot
        rule = self.day(s.date())
        if not rule:
            return self.home
        until = rule.get("work_until", self.week.get("work_until", 17.5))
        if self.timed(ev) and s.hour + s.minute / 60 < until:
            return self.place(rule.get("day"))
        return self.place(rule.get("evening"))


# ---- reading your calendars ------------------------------------------------------------

def links(secret: str):
    """CALENDAR_LINKS: one link per line, "work " in front of a calendar whose events are all fixed."""
    out = []
    for line in (secret or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fixed = bool(re.match(r"(work|fixed)\s*:?\s+", line, re.I))
        url = re.sub(r"^(work|fixed)\s*:?\s+", "", line, flags=re.I).strip()
        out.append((re.sub(r"^webcal://", "https://", url, flags=re.I), fixed))
    return out


class Geo:
    """Spots for your calendar's places, cached by hash so the cache never holds the address."""

    def __init__(self, profile):
        self.profile = profile
        try:
            self.cache = json.loads(GEO_CACHE.read_text())
        except (OSError, ValueError):
            self.cache = {}
        self.left = LOOKUPS
        self.session = requests.Session()
        from .geocode import UA
        self.session.headers["User-Agent"] = UA

    def spot(self, text: str):
        text = (text or "").strip()
        if not text or MEETING.search(text) or text.lower().startswith("http"):
            return None
        for p in ((self.profile.get("week") or {}).get("places") or {}).values():
            if any(w.lower() in text.lower() for w in p.get("match") or []):
                return p
        key = short_hash("busy-geo", text.lower())
        hit = self.cache.get(key)
        if hit is None and self.left > 0:
            self.left -= 1
            from .geocode import nominatim
            try:
                got = nominatim(self.session, text.split("\n")[0])
                hit = self.cache[key] = got or False
            except Exception:                      # asked again next run
                hit = None
            time.sleep(1.1)
        return {"lat": hit[0], "lng": hit[1]} if hit else None

    def save(self):
        try:
            GEO_CACHE.parent.mkdir(parents=True, exist_ok=True)
            GEO_CACHE.write_text(json.dumps(self.cache))
        except OSError:
            pass


def read(ics_text: str, fixed: bool, geo, start: dt.date, end: dt.date):
    """Busy blocks and all-day spans from one calendar file, repeats expanded."""
    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(ics_text)
    blocks, all_day = [], []
    for ve in recurring_ical_events.of(cal).between(start, end):
        if str(ve.get("STATUS", "")).upper() == "CANCELLED" or str(ve.get("TRANSP", "")).upper() == "TRANSPARENT":
            continue
        s, e = ve.get("DTSTART"), ve.get("DTEND")
        s = s.dt if s else None
        e = e.dt if e else None
        if s is None:
            continue
        title, location = str(ve.get("SUMMARY", "")), str(ve.get("LOCATION", ""))
        if not isinstance(s, dt.datetime):          # all day: only matters if it's far away
            if not SOFT.search(title):
                all_day.append((s, e if isinstance(e, dt.date) else s + dt.timedelta(days=1), geo.spot(location)))
            continue
        s, e = to_local(s), to_local(e) if isinstance(e, dt.datetime) else None
        e = e or s + dt.timedelta(hours=1)
        people = ve.get("ATTENDEE") or []
        people = people if isinstance(people, list) else [people]
        organizer = str(ve.get("ORGANIZER", "")).lower()
        others = [x for x in people if str(x).lower() != organizer] if organizer else people[1:]
        firm = is_firm(title, location + " " + str(ve.get("URL", "")), len(others),
                       str(ve.get("STATUS", "")).upper() == "TENTATIVE", fixed)
        blocks.append(Block(s, e, firm, geo.spot(location)))
    return blocks, all_day


def load(profile: dict, secret: str | None = None, today: dt.date | None = None, days: int = 70):
    """Your Plan, plus a one-line note for the run log that says nothing about your events."""
    secret = os.environ.get("CALENDAR_LINKS", "") if secret is None else secret
    today = today or dt.datetime.now(TZ).date()
    found = links(secret)
    if not found:
        return Plan(profile), "your calendars: none linked (weekly routine only)"
    geo = Geo(profile)
    blocks, all_day, ok = [], [], 0
    for url, fixed in found:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "about-town/1.0"})
            r.raise_for_status()
            b, a = read(r.content, fixed, geo, today, today + dt.timedelta(days=days))
            blocks += b
            all_day += a
            ok += 1
        except Exception:                          # never print the link or the error: both can carry the link
            pass
    geo.save()
    bad = len(found) - ok
    return Plan(profile, blocks, all_day), f"your calendars: {ok} of {len(found)} read" + \
        (f" ({bad} couldn't be read: check the link in CALENDAR_LINKS)" if bad else "")
