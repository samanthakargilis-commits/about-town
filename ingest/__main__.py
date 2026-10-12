"""Daily job: run every adapter, merge, filter to the corridor, score, write app/events.json.

    python -m ingest                      # all sources
    python -m ingest --only funcheap,luma # some sources
    python -m ingest --previous https://<user>.github.io/<repo>/events.json   # carry first_seen forward
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import re
import shutil
import sys
import time
import traceback
from urllib.parse import urlparse

import requests

from . import added, ai, geocode, icons, place, weather
from .area import keep
from .core import (CACHE_DIR, ROOT, BudgetExceeded, Fetcher, clean, html_to_text, iso, jsonld_events,
                   now, offer_price, og, short_hash, to_local)
from .heuristics import price_in_text
from .ics import write_ics
from .score import Scorer, best_sub_event, norm

# Working sources first (see the shortlist test); the rest are best effort.
ADAPTERS = ["funcheap", "secretsf", "luma", "sfpl", "jccsf", "citylights", "greenapple", "keplers", "broadwaysf",
            "dothebay", "eventbrite", "meetup", "dice", "partiful", "paloalto", "filoli", "comedyclubs", "fleetweek", "neckofthewoods", "fourstar", "presidiotheatre", "presidio", "mato", "substack"]
LISTING_PRIORITY = {"sfpl": 0, "jccsf": 0, "broadwaysf": 0, "citylights": 0, "greenapple": 0, "keplers": 0, "luma": 1, "partiful": 1,
                    "eventbrite": 1, "meetup": 1, "dice": 1, "dothebay": 2, "funcheap": 2, "paloalto": 2, "filoli": 0, "comedyclubs": 0,
                    "fleetweek": 0, "neckofthewoods": 0, "fourstar": 0, "presidiotheatre": 0, "presidio": 1, "mato": 2,
                    "secretsf": 5, "sfgirlchronicle": 5, "eddieslist": 5}
STOP = {"the", "a", "an", "at", "in", "with", "and", "presents", "present", "sf", "san", "francisco", "free", "of", "w"}
OUT = ROOT / "app"
SOLD_OUT = re.compile(r"\bsold[\s-]*out\b(?!\s*(?:show|run|crowd|audience)s?\b)", re.I)


def window():
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    # through the end of next month, so the 1st-of-month plan always covers a full month
    first_next = (start.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    end = (first_next + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(minutes=1)
    return start, end


def title_tokens(title):
    return {t for t in norm(title).split() if t not in STOP and len(t) > 1}


def dedupe_key(ev):
    toks = sorted(title_tokens(ev["title"]))[:6]
    return f"{'-'.join(toks)}|{ev['start'][:10]}"


def merge(events):
    """Merge the same event listed on two sites (same day, similar title)."""
    by_day = {}
    for ev in events:
        by_day.setdefault(ev["start"][:10], []).append(ev)
    merged = []
    for day, items in by_day.items():
        items.sort(key=lambda e: LISTING_PRIORITY.get(e["source"], 3))
        kept = []
        for ev in items:
            toks = title_tokens(ev["title"])
            twin = None
            for k in kept:
                kt = title_tokens(k["title"])
                if toks and kt and len(toks & kt) / len(toks | kt) >= 0.6:
                    twin = k
                    break
            if twin is None:
                ev["also_on"] = []
                kept.append(ev)
                continue
            twin["also_on"].append({"source": ev["source"], "url": ev["source_url"]})
            for f in ("description", "image_url", "venue", "address", "price", "ticket_url", "end", "lat", "lng"):
                if not twin.get(f) and ev.get(f):
                    twin[f] = ev[f]
            if len(ev.get("description") or "") > len(twin.get("description") or ""):
                twin["description"] = ev["description"]
            if twin.get("all_day") and not ev.get("all_day"):
                twin["start"], twin["all_day"] = ev["start"], False
            twin["people"] = sorted(set(twin.get("people", [])) | set(ev.get("people", [])))
            twin["tags"] = sorted(set(twin.get("tags", [])) | set(ev.get("tags", [])))
        merged += kept
    return fold_runs(merged)


def fold_runs(events):
    """A guide's "Air Show, Oct 9-11" is the same thing as the official site's
    three air show days: keep the better source's listings, drop the run."""
    def is_run(e):
        return e.get("end") and (to_local(e["end"]) - to_local(e["start"])).total_seconds() > 36 * 3600
    rank = lambda e: LISTING_PRIORITY.get(e["source"], 3)
    drop = set()
    for r in events:
        if not is_run(r):
            continue
        rt = title_tokens(r["title"])
        for o in events:
            if o is r or o["id"] in drop or rank(o) >= rank(r):
                continue
            ot = title_tokens(o["title"])
            overlap = o["start"][:10] <= r["end"][:10] and (o.get("end") or o["start"])[:10] >= r["start"][:10]
            if overlap and rt and ot and len(rt & ot) / len(rt | ot) >= 0.6:
                o.setdefault("also_on", []).append({"source": r["source"], "url": r["source_url"]})
                o["tags"] = sorted(set(o.get("tags") or []) | set(r.get("tags") or []))   # featured by the guide
                drop.add(r["id"])
    return [e for e in events if e["id"] not in drop]


def collapse_recurring(events, per_week=1):
    """A weekly karaoke night shouldn't fill every slot: keep one per week."""
    seen = {}
    out = []
    counts = {}
    for ev in events:
        k = " ".join(sorted(title_tokens(ev["title"])))
        counts[k] = counts.get(k, 0) + 1
    for ev in events:
        if {"annual", "featured"} & set(ev.get("tags") or []):
            continue                    # a three-day air show isn't a weekly karaoke night
        if counts[" ".join(sorted(title_tokens(ev["title"])))] >= 3:
            ev["recurring"] = True      # e.g. Funcheap posts a weekly show as separate listings
    for ev in sorted(events, key=lambda e: e["start"]):
        if not ev.get("recurring"):
            out.append(ev)
            continue
        week = to_local(ev["start"]).isocalendar()[:2]
        key = (" ".join(sorted(title_tokens(ev["title"]))), week)
        if seen.get(key, 0) < per_week:
            seen[key] = seen.get(key, 0) + 1
            out.append(ev)
    return out


def enrich(events, fetcher, limit):
    """Fill descriptions, places and images from each event's own page
    (cached for 3 days), and read fair/festival pages for a lineup to headline
    the best piece. A roundup page that several events share is about all of
    them, so it never stands in for one event's blurb or picture."""
    shared = {}
    for ev in events:
        shared[ev["source_url"]] = shared.get(ev["source_url"], 0) + 1
    done = 0
    # a missing blurb or place first, a missing picture after
    lacking = lambda ev: len(ev.get("description") or "") < 80 or not (ev.get("venue") or ev.get("address"))
    for ev in sorted(events, key=lambda ev: not lacking(ev)):
        if done >= limit:
            break
        short = len(ev.get("description") or "") < 80
        need = short or not ev.get("image_url") or not (ev.get("venue") or ev.get("address")) or ev.get("_festival") or not ev.get("price")
        host = urlparse(ev["source_url"]).netloc
        if not need or shared[ev["source_url"]] > 1 or host.endswith("secretsanfrancisco.com") or "substack" in host:
            continue
        try:
            soup = fetcher.soup(ev["source_url"], cache_hours=72)
        except BudgetExceeded:
            break
        except Exception:
            continue
        done += 1
        desc = og(soup, "description") or ""
        for node in jsonld_events(soup):
            if not ev.get("price") and node.get("offers"):
                ev["price"] = offer_price(node["offers"])
            if node.get("description"):
                desc = html_to_text(node["description"]) if len(html_to_text(node["description"])) > len(desc) else desc
            loc = node.get("location")
            loc = loc[0] if isinstance(loc, list) and loc else loc
            if isinstance(loc, dict) and not (ev.get("venue") or ev.get("address")):
                addr = loc.get("address")
                street = clean(addr.get("streetAddress") or "") if isinstance(addr, dict) else clean(addr or "")
                ev["venue"] = clean(loc.get("name") or "")[:80]
                ev["address"] = street if street != ev["venue"] else ""
                if isinstance(addr, dict) and addr.get("addressLocality") and not ev.get("city"):
                    ev["city"] = clean(addr["addressLocality"])
        main = soup.find(class_=re.compile("entry-content|post-content|event-description|eventitem-column-content")) or soup.find("article")
        body = clean(main.get_text(" "))[:1500] if main else ""
        found = clean(desc if len(desc) > 120 else (desc + " " + body))[:1200]
        if short and len(found) > len(ev.get("description") or ""):
            ev["description"] = found
        ev["image_url"] = ev.get("image_url") or og(soup, "image")
        if ev.get("_festival") and main:
            lines = [clean(li.get_text(" ")) for li in main.find_all(["li", "h3", "h4", "strong"])]
            ev["_lineup"] = [l for l in lines if l]
    print(f"detail pages read: {done}")


def load_previous(src) -> dict:
    if not src:
        return {}
    try:
        if src.startswith("http"):
            return requests.get(src, timeout=30).json()
        return json.loads(open(src).read())
    except Exception as exc:
        print(f"(no previous events.json: {exc})", file=sys.stderr)
        return {}


def previous_first_seen(data: dict) -> dict:
    seen = {}
    for e in data.get("events", []):
        seen[e["id"]] = e["first_seen"]
        seen[e["dedupe_key"]] = e["first_seen"]
    return seen


PAST_DAYS = 31


def past_events(data: dict, start: dt.datetime, current_ids: set) -> list[dict]:
    """Last month's events, carried from run to run, so the calendar can show
    what was on (greyed) and what you starred. Sources only list what's ahead."""
    cutoff = start - dt.timedelta(days=PAST_DAYS)
    out = []
    for e in data.get("events", []):
        s = to_local(e.get("start"))
        end = to_local(e.get("end")) if e.get("end") else s
        if not s or e.get("id") in current_ids or not (cutoff <= s and end < start):
            continue
        e = dict(e, past=True, description=(e.get("description") or "")[:300])
        out.append(e)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated adapters")
    ap.add_argument("--previous", help="previous events.json (URL or path) for first_seen")
    ap.add_argument("--enrich", type=int, default=160, help="max detail pages to read per run")
    ap.add_argument("--out", default=str(OUT / "events.json"))
    ap.add_argument("--geocode", type=int, default=350, help="max new venue lookups per run")
    ap.add_argument("--no-geocode", action="store_true")
    ap.add_argument("--requests", default="requests.json", help="the repo's open issues (sources added in the app)")
    ap.add_argument("--locate", type=int, default=400, help="max event pages to read for an address per run")
    args = ap.parse_args(argv)

    profile = json.loads((ROOT / "data" / "profile.json").read_text())
    follow = json.loads((ROOT / "data" / "follow.json").read_text())
    scorer = Scorer(profile, follow)
    start, end = window()
    names = args.only.split(",") if args.only else ADAPTERS

    # a show by someone you follow is worth a trip on any night
    fan = lambda ev: bool(scorer.followed_in(norm(" ".join([ev.get("title", ""), ev.get("description", "")]))))
    raw, health = [], []
    for name in names:
        mod = importlib.import_module(f".adapters.{name}", __package__)
        fetcher = Fetcher(max_requests=getattr(mod, "MAX_REQUESTS", 120))   # a source that reads each event page asks for more
        t0 = time.time()
        status = {"name": mod.NAME, "label": mod.LABEL, "count": 0, "ok": True, "error": None}
        try:
            events = mod.fetch(fetcher, start, end)
            status["count"] = len(events)
            raw += [e.to_dict() for e in events]
            if not events:
                status["ok"] = False
                status["error"] = "returned zero events"
        except Exception as exc:  # one broken source never breaks the others
            status["ok"] = False
            status["error"] = f"{type(exc).__name__}: {exc}"[:300]
            traceback.print_exc()
        status["requests"] = fetcher.count
        status["seconds"] = round(time.time() - t0, 1)
        health.append(status)
        print(f"{mod.LABEL:24} {status['count']:4} events  {fetcher.count:3} requests  "
              f"{'OK' if status['ok'] else 'FAIL: ' + str(status['error'])}", flush=True)

    # sites added from the app, each read on its own so one that fails doesn't stop the rest
    for req in ([] if args.only else added.load(args.requests)):
        fetcher = Fetcher(max_requests=added.MAX_REQUESTS)
        t0 = time.time()
        status = {"name": req["name"], "label": req["host"], "count": 0, "ok": True, "error": None,
                  "added": True, "url": req["url"], "issue": req["issue"]}
        try:
            events = added.fetch(fetcher, req, start, end)
            status["count"] = len(events)
            raw += [e.to_dict() for e in events]
            if not events:
                status["ok"], status["error"] = False, "returned zero events"
        except Exception as exc:
            status["ok"], status["error"] = False, f"{type(exc).__name__}: {exc}"[:300]
        status["requests"] = fetcher.count
        status["seconds"] = round(time.time() - t0, 1)
        health.append(status)
        print(f"{'+ ' + req['host']:24} {status['count']:4} events  {fetcher.count:3} requests  "
              f"{'OK' if status['ok'] else 'FAIL: ' + str(status['error'])}", flush=True)

    # window + area, and nothing you can't get into
    events, sold_out = [], 0
    for ev in raw:
        s = to_local(ev["start"])
        e = to_local(ev["end"]) if ev.get("end") else None
        if not s or len(ev["title"]) < 5 or ev["title"].lower() in ("date", "event", "tbd", "sold out"):
            continue
        running = e and s < start <= e   # multi-day run already underway
        if not (start <= s <= end or running):
            continue
        if not keep(ev, fan):
            continue
        if ev.get("sold_out") or SOLD_OUT.search(ev["title"]):
            sold_out += 1
            continue
        events.append(ev)
    print(f"in window and area: {len(events)} of {len(raw)} ({sold_out} sold out)")

    events = collapse_recurring(merge(events))
    print(f"after merging duplicates: {len(events)}")

    # read addresses off event pages for listings that lack them, then re-check the area
    print("places:", place.locate(events, Fetcher(delay=1.0, max_requests=args.locate)), flush=True)
    events = [e for e in events if keep(e, fan)]
    print(f"in area once placed: {len(events)}")

    # first pass score, enrich the most promising, second pass
    for ev in events:
        s = scorer.score(ev)
        ev["_pre"] = s["score"] if s else -99
        ev["_festival"] = bool(s and s["is_festival"])
    events = [e for e in events if e["_pre"] > -99]
    events.sort(key=lambda e: -e["_pre"])
    enrich(events, Fetcher(delay=1.0, max_requests=args.enrich), args.enrich)

    # a price the listing only gave in words ("Tickets $25", "free and open to the public")
    worded = 0
    for ev in events:
        if not ev.get("price"):
            ev["price"] = price_in_text(f"{ev.get('title', '')}. {ev.get('description', '')}")
            worded += bool(ev["price"])
    print(f"prices read from descriptions: {worded}; still unpriced: {sum(1 for e in events if not e.get('price'))}")

    if not args.no_geocode:
        print("map spots:", geocode.fill(events, max_lookups=args.geocode), flush=True)

    ai_tags = ai.tag_events(events, profile) if ai.enabled() else {}
    shutil.rmtree(OUT / "ics", ignore_errors=True)
    previous = load_previous(args.previous)
    seen = previous_first_seen(previous)
    stamp = iso(now())
    out = []
    for ev in events:
        s = scorer.score(ev, ai_tags.get(ev["id"]))
        if s is None:
            continue
        ev.update({k: s[k] for k in ("score", "tags", "why", "followed", "followed_kind")})
        sub = None
        tags_ai = ai_tags.get(ev["id"]) or {}
        if tags_ai.get("sub_event"):
            sub = tags_ai["sub_event"]
        elif ev.get("_lineup"):
            sub = best_sub_event(ev, ev["_lineup"], profile)
        if sub and sub.get("title"):
            ev["parent_event"] = {"title": ev["title"], "url": ev["source_url"]}
            ev["title"] = f"{sub['title']}, at {ev['title']}"
            if sub.get("time"):
                hh, mm = [int(x) for x in sub["time"].split(":")[:2]]
                st = to_local(ev["start"]).replace(hour=hh, minute=mm)
                ev["start"], ev["all_day"], ev["end"] = iso(st), False, iso(st + dt.timedelta(hours=1))
        ev["people"] = sorted(set(ev.get("people", [])) | set(tags_ai.get("people", [])))
        ev["dedupe_key"] = dedupe_key(ev)
        ev["first_seen"] = seen.get(ev["id"]) or seen.get(ev["dedupe_key"]) or stamp
        for k in [k for k in ev if k.startswith("_")]:
            del ev[k]
        ev["description"] = (ev.get("description") or "")[:600]
        ev["ics"] = write_ics(ev, OUT / "ics")
        out.append(ev)

    past = past_events(previous, start, {e["id"] for e in out})
    for ev in past:
        ev["ics"] = write_ics(ev, OUT / "ics")
    print(f"past events kept for the calendar: {len(past)}")
    out += past
    out.sort(key=lambda e: e["start"])
    try:
        site_icons, note = icons.write(out, Fetcher(delay=0.5, max_requests=100), OUT)
        print(note)
    except Exception as exc:          # icons are decoration; never fail a run over them
        site_icons = {}
        print(f"site icons skipped: {exc}")
    payload = {
        "generated": stamp,
        "window": {"start": iso(start), "end": iso(end)},
        "ai": ai.enabled(),
        "sources": health,
        "icons": site_icons,
        "events": out,
    }
    with open(args.out, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    for name in ("profile.json", "follow.json"):   # the app reads these too
        shutil.copy(ROOT / "data" / name, OUT / name)
    print(f"wrote {len(out)} events to {args.out}")
    print(weather.write(OUT / "weather.json"))
    broken = [h["label"] for h in health if not h["ok"]]
    if broken:
        print("::warning::Sources with zero events or errors: " + ", ".join(broken))


if __name__ == "__main__":
    main()
