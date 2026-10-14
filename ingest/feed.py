"""Subscribed calendars: About Town as calendars you switch on and off in Apple Calendar.

Two feeds, each its own calendar with its own checkbox:
  calendar.ics       "About Town": the one best idea for each day, at its own time, in gray; its
                     link row is the event's .ics, so one tap offers "Add to Calendar"
  calendar-more.ics  "About Town · At their times": the same ideas as separate events at their times

Ranking here mirrors the app's day view before your phone's learned taste: the job's
score, distance by day from home, long runs yield to one-offs, no early weekend mornings.
Every event is marked free (TRANSP) so it never blocks time in your real calendar.

Your phone's taste reaches the feeds through "Update my calendars" in the app: it opens a
GitHub issue titled "Calendar taste" holding your interests, learned tag weights, hidden
tags and choices; only the repo's own people count. Added and Not for me events both leave
the feeds: one is already in your own calendar, the other you passed on.
"""
import datetime as dt
import json
import math
import re
from urllib.parse import quote

from .core import TZ, short_hash, to_local
from .ics import VTIMEZONE, esc, fold

PER_DAY = 2            # top picks on any one day
MORE_PER_DAY = 3       # extra options per day in the More calendar
MORE_MIN = 2.5         # same bar as a dot on the app's month grid
LONG_RUN_DAYS = 4
LONG_RUN_PENALTY = 3


def miles(a, b):
    rad = math.pi / 180
    d_lat, d_lng = (b["lat"] - a["lat"]) * rad, (b["lng"] - a["lng"]) * rad
    h = math.sin(d_lat / 2) ** 2 + math.cos(a["lat"] * rad) * math.cos(b["lat"] * rad) * math.sin(d_lng / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def run_days(ev):
    s, e = to_local(ev["start"]), to_local(ev.get("end"))
    return (e - s).total_seconds() / 86400 if e else 0


def dist_penalty(ev, home):
    """Same shape as distPenalty in app.js: a short hop on a weeknight, a day trip on the weekend."""
    if ev.get("lat") is None or ev.get("lng") is None or not home:
        return 0
    mi = miles(home, ev)
    s = to_local(ev["start"])
    far_ok = -min(2, max(0, mi - 5) * 0.04)
    if ev.get("followed") or run_days(ev) > 1.5:
        return far_ok
    fri_night = s.weekday() == 4 and s.hour >= 17
    if s.weekday() >= 5:
        return far_ok
    if fri_night:
        return -min(4, max(0, mi - 3) * 0.25)
    return -min(5, max(0, min(mi, 3) - 1.5) * 0.6 + max(0, mi - 3) * 1.0)


def too_early(ev, first):
    if first is None or ev.get("all_day") or ev.get("followed"):
        return False
    s, e = to_local(ev["start"]), to_local(ev.get("end"))
    if s.weekday() < 5:
        return False
    h = s.hour + s.minute / 60
    if h >= first or h < 4:
        return False
    long = (e - s).total_seconds() / 3600 if e else 0
    return h + long <= first + 2


TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}   # anyone can open an issue on a public repo
INTEREST_LEVELS = {2: 1.5, 1: 0, 0: -1.5}       # love / like / not into, as in app.js


def taste_from(issues):
    """Your taste from the "Calendar taste" issues, or {}."""
    sent = []
    for it in issues or []:
        if it.get("pull_request") or it.get("author_association") not in TRUSTED:
            continue
        if not re.match(r"\s*calendar taste", it.get("title") or "", re.I):
            continue
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", it.get("body") or "", re.S)
        if not m:
            continue
        try:
            taste = json.loads(m.group(1))
        except ValueError:
            continue
        sent.append((it.get("number", 0), taste))
    if not sent:
        return {}
    # the newest send sets your interests and weights; yeses and noes add up across sends
    # (Safari and the home-screen app keep separate copies of your choices)
    sent.sort(key=lambda x: x[0])
    out = dict(sent[-1][1])
    for key in ("added", "not"):
        out[key] = sorted({i for _, t in sent for i in t.get(key) or []})
    return out


def load_taste(path):
    try:
        return taste_from(json.loads(open(path).read()))
    except (OSError, ValueError):
        return {}


def learn_tags(ev):
    """Same keys as learnTags in app.js: tags, weekday + time of day, source."""
    out = list(ev.get("tags") or [])
    if not ev.get("all_day"):
        s = to_local(ev["start"])
        slot = "evening" if s.hour >= 17 else "afternoon" if s.hour >= 12 else "morning"
        out.append(f"t:{s.strftime('%a').lower()}-{slot}")
    return out + [f"src:{ev.get('source')}"]


def taste_boost(ev, taste):
    weights, interests = taste.get("tagW") or {}, taste.get("interests") or {}
    s = sum(max(-3, min(3, weights.get(t, 0))) for t in learn_tags(ev))
    return s + sum(INTEREST_LEVELS.get(interests[t], 0) for t in ev.get("tags") or [] if t in interests)


def rank(ev, home, taste=None):
    long_run = run_days(ev) > LONG_RUN_DAYS and not ev.get("followed")
    return ((ev.get("score") or 0) + dist_penalty(ev, home) - (LONG_RUN_PENALTY if long_run else 0)
            + taste_boost(ev, taste or {}))


def words(title):
    return set(re.findall(r"[a-z]{3,}", title.lower())) - {"the", "and", "annual", "with", "free"}


def same_thing(a, b, today):
    """The same festival listed twice ("2026 Half Moon Bay Pumpkin Festival", "54th Annual ...")."""
    if abs((day_of(a, today) - day_of(b, today)).days) > 1:
        return False
    wa, wb = words(a["title"]), words(b["title"])
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.7


def day_of(ev, today):
    """The day an event sits on: its start, or today for a run already underway."""
    return max(to_local(ev["start"]).date(), today)


def upcoming(events, profile, today, taste):
    """(rank, event) for every event still ahead that you haven't added, passed on or hidden, best first."""
    skipped = set(taste.get("added") or []) | set(taste.get("not") or [])
    hidden = set(taste.get("hiddenTags") or [])
    home = profile.get("home")
    live = []
    for ev in events:
        s, e = to_local(ev["start"]), to_local(ev.get("end"))
        if (e or s).date() < today or ev["id"] in skipped or hidden & set(ev.get("tags") or []):
            continue
        if too_early(ev, profile.get("weekend_earliest_hour")):
            continue
        live.append((rank(ev, home, taste), ev))
    live.sort(key=lambda x: -x[0])
    return live


def choose(events, profile, today=None, taste=None):
    """Split upcoming events into (picks, more), each a list of events."""
    today = today or dt.datetime.now(TZ).date()
    taste = taste or {}
    per_week = profile.get("events_per_week", 7)
    live = upcoming(events, profile, today, taste)

    picks, more = [], []
    week_n, day_n, more_n = {}, {}, {}
    for r, ev in live:
        if any(same_thing(ev, p, today) for p in picks + more):
            continue
        d = day_of(ev, today)
        wk = d.isocalendar()[:2]
        if week_n.get(wk, 0) < per_week and day_n.get(d, 0) < PER_DAY and r > 0:
            week_n[wk] = week_n.get(wk, 0) + 1
            day_n[d] = day_n.get(d, 0) + 1
            picks.append(ev)
        elif r >= MORE_MIN and more_n.get(d, 0) < MORE_PER_DAY:
            more_n[d] = more_n.get(d, 0) + 1
            more.append(ev)
    key = lambda e: e["start"]
    return sorted(picks, key=key), sorted(more, key=key)


def price_text(ev):
    p = ev.get("price")
    if p in (None, ""):
        return ""
    if isinstance(p, (int, float)):
        return "Free" if p == 0 else f"${p:g}"
    return str(p)


def vevent(ev, stamp, app_url, today):
    start, end = to_local(ev["start"]), to_local(ev.get("end"))
    title = ("⭐ " if ev.get("followed") else "") + ev["title"]
    run = run_days(ev) > 1.5
    if ev.get("all_day") or run:
        # a long run or a fair goes on its first day ahead as one all-day block, not weeks of them
        d = day_of(ev, today)
        if run and end:
            title += f" (through {end:%b} {end.day})"
        when = [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}"]
    else:
        if not end or end <= start or (end - start) > dt.timedelta(hours=12):
            end = start + dt.timedelta(hours=2)
        when = [f"DTSTART;TZID=America/Los_Angeles:{start:%Y%m%dT%H%M%S}",
                f"DTEND;TZID=America/Los_Angeles:{end:%Y%m%dT%H%M%S}"]
    link = ev.get("ticket_url") or ev["source_url"]
    where = ", ".join(x for x in [ev.get("venue"),
                                 ev.get("address") if ev.get("address") != ev.get("venue") else "",
                                 ev.get("city")] if x)
    notes = [ev.get("why") or ""]
    facts = " · ".join(x for x in [price_text(ev), ev.get("venue")] if x)
    if facts:
        notes.append(facts)
    notes += ["", f"Tickets / RSVP: {link}"]
    if ev.get("description"):
        notes += ["", ev["description"][:300]]
    # the link row is the event's own .ics: one tap and iPhone offers "Add to Calendar",
    # with nothing in between (subscribed events can't be copied in Calendar itself)
    open_url = app_url + ev["ics"] if app_url and ev.get("ics") else link
    lines = ["BEGIN:VEVENT", f"UID:{short_hash(ev['id'])}@about-town", f"DTSTAMP:{stamp}", *when,
             f"SUMMARY:{esc(title)}", f"LOCATION:{esc(where)}", f"URL:{open_url}",
             f"DESCRIPTION:{esc(chr(10).join(notes))}", "TRANSP:TRANSPARENT"]
    if ev.get("lat") is not None and ev.get("lng") is not None and where:
        # lets Apple Calendar show the map and travel time
        lines.append(f'X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-APPLE-RADIUS=70;'
                     f'X-TITLE="{(ev.get("venue") or where).replace(chr(34), "")}":geo:{ev["lat"]},{ev["lng"]}')
    lines.append("END:VEVENT")
    return lines


def header(name, about, color):
    return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//About Town//Feed//EN", "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH", f"X-WR-CALNAME:{esc(name)}", f"X-WR-CALDESC:{esc(about)}",
            "X-WR-TIMEZONE:America/Los_Angeles", f"X-APPLE-CALENDAR-COLOR:{color}",
            "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"] + VTIMEZONE


def calendar(events, name, about, color, app_url="", today=None):
    today = today or dt.datetime.now(TZ).date()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = header(name, about, color)
    for ev in events:
        lines += vevent(ev, stamp, app_url, today)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def one_a_day(picks, more, home, taste, today, plan=None, rest=()):
    """The single best idea for each day: a pick when the day has one, else its best other option.
    With a plan (your routine and calendars), ideas that clash with something fixed are left out,
    days you're away stay empty, distance counts from where you'll be, and a day whose picks
    all clash falls back to the best other idea that fits."""
    best = {}
    for tier, evs in ((2, picks), (1, more), (0, rest)):
        for ev in evs:
            d = day_of(ev, today)
            if plan and (plan.is_away(d) or plan.clashes(ev)):
                continue
            r = rank(ev, plan.base(ev) if plan else home, taste)
            if tier == 0 and (d in best or r < MORE_MIN):
                continue
            key = (tier, r)
            if d not in best or key > best[d][0]:
                best[d] = (key, ev)
    return [best[d][1] for d in sorted(best)]


def write(events, profile, folder, app_url="", today=None, taste=None, plan=None):
    taste = taste or {}
    today = today or dt.datetime.now(TZ).date()
    picks, more = choose(events, profile, today, taste)
    chosen = {id(ev) for ev in picks + more}
    rest = [ev for _, ev in upcoming(events, profile, today, taste) if id(ev) not in chosen] if plan else []
    # calendar.ics: one idea a day, at its own time; calendar-more.ics: every idea at its own time
    (folder / "calendar.ics").write_text(
        calendar(one_a_day(picks, more, profile.get("home"), taste, today, plan, rest), "About Town",
                 "One idea a day, picked for you", "#8E8E93", app_url, today), encoding="utf-8")
    (folder / "calendar-more.ics").write_text(
        calendar(picks + more, "About Town · At their times", "Every idea at its own time", "#A8C48C", app_url,
                 today), encoding="utf-8")
    note = f" (your taste from {taste['sent']})" if taste.get("sent") else " (no taste sent from the app yet)"
    return f"calendar feeds: {len(picks)} top picks, {len(more)} more{note}"
