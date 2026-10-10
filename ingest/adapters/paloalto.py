"""Destination Palo Alto. Its calendar is a CitySpark widget; the widget script
carries the listings as JSON, which this reads."""
import json
import re

from ..core import Event, clean, html_to_text, iso, to_local

NAME, LABEL = "paloalto", "Destination Palo Alto"
SCRIPT = "https://portal.cityspark.com/PortalScripts/DestinationPA"
PAGE = "https://www.destinationpaloalto.com/calendar"


def objects_with(text, key):
    dec = json.JSONDecoder()
    out, seen = [], set()
    for m in re.finditer(r'\{"[^"]+":', text):
        if key not in text[m.start(): m.start() + 400]:
            continue
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and key.strip('":') in obj and id(obj) not in seen:
            out.append(obj)
    return out


def pick(d, *names):
    for n in names:
        for k, v in d.items():
            if k.lower() == n.lower() and v:
                return v
    return None


def fetch(f, start, end):
    text = f.get(SCRIPT)
    if "\\u0022" in text or "\\u003C" in text:
        text = text.encode().decode("unicode_escape", errors="ignore")
    objs = objects_with(text, '"PId":')
    if objs:
        print("  cityspark keys:", sorted(objs[0].keys())[:40])
    out, seen = [], set()
    for o in objs:
        pid = o.get("PId")
        title = clean(o.get("Name"))
        st = to_local(pick(o, "DateStart", "StartUTC", "StartDate", "Start", "DateStartUTC", "StartTime"))
        if not pid or not title or not st or pid in seen:
            continue
        seen.add(pid)
        links = o.get("Links") or []
        link = next((l.get("url") or l.get("Url") for l in links if isinstance(l, dict) and (l.get("url") or l.get("Url"))), None)
        out.append(Event(
            source=NAME, source_id=str(pid), source_url=f"{PAGE}#/details/{pid}", ticket_url=link,
            title=title, start=iso(st), end=iso(to_local(pick(o, "DateEnd", "EndUTC", "EndDate", "End"))),
            all_day=bool(o.get("AllDay")),
            description=html_to_text(o.get("Summary") or o.get("Description") or o.get("Short") or "")[:1000],
            venue=clean(pick(o, "Venue", "VenueName", "Location") or ""),
            address=clean(pick(o, "Address", "Street") or ""),
            city=clean((pick(o, "CityState", "City") or "").split(",")[0]),
            image_url=(o.get("LargeImg") or o.get("MediumImg") or o.get("SmallImg")),
            price=clean(str(pick(o, "Price", "Cost") or "")),
        ))
    return out
