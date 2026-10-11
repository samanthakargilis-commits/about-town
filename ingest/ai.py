"""Optional AI step (brief: "An AI model reads my profile and each event's
description, tags the event, scores it, and writes the one-line why").

Runs only when ANTHROPIC_API_KEY is set. Without it, the rule-based scorer in
score.py does the tagging and the article adapters fall back to reading headings.
Results are cached by event id so each event is sent to the model once.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

from .core import CACHE_DIR, TZ, Event, clean, html_to_text, iso, short_hash

MODEL = os.environ.get("AI_MODEL", "claude-opus-5-5")
TAG_CACHE = CACHE_DIR / "ai_tags.json"
_client = None


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("AI_DISABLED") != "1"


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def _ask(system: str, user: str, schema: dict, max_tokens=16000) -> dict | None:
    resp = client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason in ("refusal", "max_tokens"):
        print(f"  ai: stopped ({resp.stop_reason})", file=sys.stderr)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


# ---------------------------------------------------------------- article extraction

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {"events": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD of the first (or next) occurrence"},
            "end_date": {"type": ["string", "null"], "description": "YYYY-MM-DD last day, for multi-day runs"},
            "time": {"type": ["string", "null"], "description": "24h HH:MM start time if stated"},
            "venue": {"type": "string"},
            "city": {"type": "string"},
            "price": {"type": "string"},
            "description": {"type": "string"},
            "link": {"type": ["string", "null"], "description": "the event's own page or tickets link from the article"},
            "sponsored": {"type": "boolean"},
        },
        "required": ["title", "date", "end_date", "time", "venue", "city", "price", "description", "link", "sponsored"],
        "additionalProperties": False,
    }}},
    "required": ["events"],
    "additionalProperties": False,
}


def extract_events(source: str, url: str, title: str, html: str, ref: dt.date) -> list[Event]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        a.replace_with(f"{a.get_text(' ')} <{a['href']}>")
    text = clean(soup.get_text(" "))[:60000]
    system = ("You extract events from Bay Area 'things to do' articles and newsletters. "
              "Return only items with a clear date; drop items with no date. Use short, plain event names, "
              "not headlines. Mark items whose link goes to a ticket seller the article promotes (e.g. Fever) as sponsored.")
    user = f"Article published {ref.isoformat()}: {title}\nURL: {url}\n\n{text}"
    try:
        data = _ask(system, user, EXTRACT_SCHEMA) or {"events": []}
    except Exception as exc:  # one bad article must not break the run
        print(f"  ai extract failed for {url}: {exc}", file=sys.stderr)
        return []
    out = []
    for item in data["events"]:
        try:
            day = dt.date.fromisoformat(item["date"])
        except ValueError:
            continue
        hh, mm, all_day = 0, 0, True
        if item.get("time"):
            try:
                hh, mm = [int(x) for x in item["time"].split(":")[:2]]
                all_day = False
            except ValueError:
                pass
        start = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
        end = None
        if item.get("end_date"):
            try:
                e = dt.date.fromisoformat(item["end_date"])
                if e > day:
                    end = dt.datetime(e.year, e.month, e.day, 23, 0, tzinfo=TZ)
            except ValueError:
                pass
        out.append(Event(
            source=source, source_id=short_hash(url, item["title"]), source_url=url,
            ticket_url=item.get("link"), title=clean(item["title"]), start=iso(start), end=iso(end),
            all_day=all_day, description=clean(item["description"])[:1000], venue=clean(item["venue"]),
            city=clean(item["city"]), price=clean(item["price"]), sponsored=bool(item["sponsored"]),
        ))
    return out


# ---------------------------------------------------------------- tagging + why

TAG_SCHEMA_ITEM = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "interests": {"type": "array", "items": {"type": "string"}},
        "fit": {"type": "integer", "description": "0-10 how much David would enjoy this"},
        "why": {"type": "string", "description": "one short line, e.g. 'Musical theatre + queer · drag sing-along'"},
        "is_tech": {"type": "boolean"},
        "kids_only": {"type": "boolean"},
        "people": {"type": "array", "items": {"type": "string"}, "description": "performers/authors named"},
        "sub_event": {"type": ["object", "null"], "properties": {
            "title": {"type": "string"}, "time": {"type": ["string", "null"]}},
            "required": ["title", "time"], "additionalProperties": False,
            "description": "for fairs/festivals: the best-matching piece of the lineup, if one is named"},
    },
    "required": ["id", "interests", "fit", "why", "is_tech", "kids_only", "people", "sub_event"],
    "additionalProperties": False,
}


def _load_cache():
    try:
        return json.loads(TAG_CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def tag_events(events: list[dict], profile: dict, batch=25) -> dict:
    """Returns {event_id: tags}. Only events not seen before are sent."""
    cache = _load_cache()
    todo = [e for e in events if e["id"] not in cache]
    interest_list = ", ".join(f"{k} ({v['label']})" for k, v in profile["interests"].items())
    system = (
        "You tag Bay Area events for one person, David, who lives between San Francisco and Palo Alto. "
        f"His interests (use these keys): {interest_list}. He loves Thursday evenings, weird events, "
        "and author talks by writers he reads (romantasy, rom-coms, funny essays, myth retellings, sharp literary fiction). "
        "Interests boost; never invent facts. For fairs and festivals, if the description names a lineup item that "
        "fits him (e.g. 'Elvis Impersonator Contest'), return it as sub_event with its time if given."
    )
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        lines = [json.dumps({"id": e["id"], "title": e["title"], "when": e["start"], "venue": e["venue"],
                             "price": e["price"], "description": e["description"][:600]}, ensure_ascii=False)
                 for e in chunk]
        schema = {"type": "object", "properties": {"events": {"type": "array", "items": TAG_SCHEMA_ITEM}},
                  "required": ["events"], "additionalProperties": False}
        try:
            data = _ask(system, "Tag each event:\n" + "\n".join(lines), schema)
        except Exception as exc:
            print(f"  ai tagging failed: {exc}", file=sys.stderr)
            break
        for t in (data or {}).get("events", []):
            cache[t["id"]] = t
        TAG_CACHE.write_text(json.dumps(cache))
    return cache
