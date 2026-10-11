"""One .ics file per event, served as a static file so iPhone opens the
"Add to Calendar" sheet straight from the installed app."""
import datetime as dt
import pathlib

from .core import short_hash, to_local


def esc(text):
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    out, b = [], line.encode()
    while len(b) > 74:
        cut = 74
        while (b[cut] & 0xC0) == 0x80:   # don't split a UTF-8 character
            cut -= 1
        out.append(b[:cut].decode())
        b = b" " + b[cut:]
    out.append(b.decode())
    return "\r\n".join(out)


def vevent(ev, stamp):
    start = to_local(ev["start"])
    end = to_local(ev["end"]) if ev.get("end") else None
    if ev.get("all_day"):
        s = f"DTSTART;VALUE=DATE:{start:%Y%m%d}"
        e = f"DTEND;VALUE=DATE:{(start + dt.timedelta(days=1)):%Y%m%d}"
    else:
        if not end or (end - start) > dt.timedelta(hours=12):
            end = start + dt.timedelta(hours=2)   # long runs: book this one performance
        s = f"DTSTART;TZID=America/Los_Angeles:{start:%Y%m%dT%H%M%S}"
        e = f"DTEND;TZID=America/Los_Angeles:{end:%Y%m%dT%H%M%S}"
    link = ev.get("ticket_url") or ev["source_url"]
    where = ", ".join(x for x in [ev.get("venue"), ev.get("address") if ev.get("address") != ev.get("venue") else "",
                                 ev.get("city")] if x)
    desc = f"{ev.get('why', '')}\n{link}\n\n{(ev.get('description') or '')[:400]}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{short_hash(ev['id'])}@bay-events",
        f"DTSTAMP:{stamp}",
        s, e,
        f"SUMMARY:{esc(ev['title'])}",
        f"LOCATION:{esc(where)}",
        f"URL:{link}",
        f"DESCRIPTION:{esc(desc)}",
        "END:VEVENT",
    ]
    return lines


VTIMEZONE = [
    "BEGIN:VTIMEZONE", "TZID:America/Los_Angeles",
    "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0800", "TZOFFSETTO:-0700", "TZNAME:PDT", "DTSTART:19700308T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
    "BEGIN:STANDARD", "TZOFFSETFROM:-0700", "TZOFFSETTO:-0800", "TZNAME:PST", "DTSTART:19701101T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD", "END:VTIMEZONE",
]


def calendar(events):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Fogbook//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    lines += VTIMEZONE
    for ev in events:
        lines += vevent(ev, stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def write_ics(ev, folder: pathlib.Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    name = short_hash(ev["id"]) + ".ics"
    (folder / name).write_text(calendar([ev]), encoding="utf-8")
    return f"ics/{name}"
