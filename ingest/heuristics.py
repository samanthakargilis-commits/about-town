"""Fallback parsers for pages that have no feed: find event links and read the
date, time, cost and venue from the text around each link."""
from __future__ import annotations

import datetime as dt
import re
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .core import (Event, TZ, clean, find_dates, iso, parse_time, short_hash, slug,
                   to_local, TIME_RE)

CHROME = re.compile(r"sidebar|widget|footer|header|nav|menu|popular|related|newsletter|cookie|share", re.I)


def in_chrome(tag: Tag) -> bool:
    for parent in tag.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in ("nav", "footer", "header", "aside"):
            return True
        ident = " ".join(parent.get("class", [])) + " " + (parent.get("id") or "")
        if CHROME.search(ident):
            return True
    return False


def link_blocks(soup: BeautifulSoup, base_url: str, is_event_url: Callable[[str], bool],
                needs: Callable[[str], bool] = lambda t: bool(TIME_RE.search(t))):
    """Yield (url, title, block_text, block_tag) for each event link.

    The block is the smallest ancestor of the link that passes `needs` (by default:
    contains a clock time) and links to only one distinct event.
    """
    seen = set()
    for a in soup.find_all("a", href=True):
        url = urljoin(base_url, a["href"]).split("#")[0]
        if url in seen or not is_event_url(url) or in_chrome(a):
            continue
        title = clean(a.get_text(" ")) or clean(a.get("title"))
        if len(title) < 4:
            continue
        block = None
        for parent in a.parents:
            if not isinstance(parent, Tag) or parent.name in ("body", "html"):
                break
            urls = {urljoin(base_url, x["href"]).split("#")[0] for x in parent.find_all("a", href=True)}
            if len({u for u in urls if is_event_url(u)}) > 1:
                break
            if needs(parent.get_text(" ")):
                block = parent
                break
        if block is None:
            continue
        seen.add(url)
        yield url, title, clean(block.get_text(" ")), block


def microdata_events(soup: BeautifulSoup, source: str, base_url: str) -> list[Event]:
    """schema.org Event microdata (itemtype=.../Event)."""
    out = []
    for item in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/\w*Event", re.I)}):
        def prop(name):
            t = item.find(attrs={"itemprop": name})
            if not t:
                return ""
            return t.get("content") or t.get("datetime") or t.get("href") or clean(t.get_text(" "))
        title, start = clean(prop("name")), to_local(prop("startDate"))
        if not title or not start:
            continue
        url = urljoin(base_url, prop("url") or (item.find("a", href=True) or {}).get("href", "") or base_url)
        loc = item.find(attrs={"itemprop": "location"})
        venue = ""
        if loc:
            n = loc.find(attrs={"itemprop": "name"})
            venue = clean(n.get_text(" ")) if n else clean(loc.get_text(" "))[:80]
        img = prop("image")
        out.append(Event(source=source, source_id=slug(urlparse(url).path)[-80:] or short_hash(title, iso(start)),
                         source_url=url, title=title, start=iso(start), venue=venue,
                         image_url=urljoin(base_url, img) if img else None,
                         end=iso(to_local(prop("endDate"))) if prop("endDate") else None))
    return out


PRICE_RE = re.compile(r"(free(?: with rsvp)?|\$\s?\d+(?:\.\d\d)?(?:\s?[-–]\s?\$?\d+(?:\.\d\d)?)?)", re.I)


def price_from(text: str) -> str:
    m = re.search(r"cost:\s*([^|]+)", text, re.I)
    chunk = m.group(1) if m else text
    p = PRICE_RE.search(chunk)
    if not p:
        return ""
    val = p.group(1)
    return "free" if val.lower().startswith("free") else val.replace(" ", "")


def at_time(day: dt.date, text: str, default_hour: Optional[int] = None):
    """Combine a date with the first time found in text."""
    t = parse_time(text)
    if t is None:
        if default_hour is None:
            return dt.datetime(day.year, day.month, day.day, tzinfo=TZ), True
        t = (default_hour, 0)
    return dt.datetime(day.year, day.month, day.day, t[0], t[1], tzinfo=TZ), False


def end_time(start: dt.datetime, text: str) -> Optional[dt.datetime]:
    t_re = r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)"
    m = re.search(r"(?:ends at|until)\s*" + t_re, text, re.I) or \
        re.search(t_re + r"\s*(?:-|–|—|to)\s*" + t_re, text, re.I)
    if not m:
        return None
    t = parse_time(m.groups()[-1])
    if not t:
        return None
    end = start.replace(hour=t[0], minute=t[1])
    if end <= start:
        if t[0] < 6:            # ends after midnight
            end += dt.timedelta(days=1)
        else:
            return None
    return end


def sections_by_heading(html_soup: BeautifulSoup) -> Iterable[tuple[str, str, list]]:
    """Split an article body into (heading, text, links) chunks by h2/h3/h4,
    falling back to bold-led paragraphs when there are no headings."""
    heads = html_soup.find_all(["h2", "h3", "h4"])
    if not heads:
        heads = [p for p in html_soup.find_all("p") if p.find(["strong", "b"]) and
                 len(clean(p.find(["strong", "b"]).get_text())) > 6 and
                 clean(p.get_text()).startswith(clean(p.find(["strong", "b"]).get_text())[:10])]
    for h in heads:
        texts, links = [], []
        if h.name == "p":
            strong = h.find(["strong", "b"])
            heading = clean(strong.get_text(" "))
            rest = clean(h.get_text(" "))[len(heading):]
            texts.append(rest)
            links += [a["href"] for a in h.find_all("a", href=True)]
            sib = h.next_sibling
            nodes = []
        else:
            heading = clean(h.get_text(" "))
            nodes = []
            sib = h.next_sibling
            while sib is not None and not (isinstance(sib, Tag) and sib.name in ("h1", "h2", "h3", "h4")):
                nodes.append(sib)
                sib = sib.next_sibling
        for n in nodes:
            if isinstance(n, Tag):
                texts.append(clean(n.get_text(" ")))
                links += [a["href"] for a in n.find_all("a", href=True)]
                if n.name == "a" and n.get("href"):
                    links.append(n["href"])
        heading = re.sub(r"^\s*\d{1,2}[.)]\s*", "", heading)
        yield heading, clean(" ".join(texts)), links


def article_events(html: str, source: str, article_url: str, ref: dt.date,
                   sponsored_hosts=("feverup.com", "fever")) -> list[Event]:
    """Rule-based extraction for roundup articles: each heading is an event;
    the first date in its section is when. Sections with no clear date are dropped."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for heading, text, links in sections_by_heading(soup):
        if not heading or len(heading) > 140 or len(text) < 20:
            continue
        dates = find_dates(heading + " " + text, ref)
        if not dates:
            continue
        start_day, end_day = dates[0]
        start, all_day = at_time(start_day, text)
        external = [l for l in links if l.startswith("http") and urlparse(l).netloc not in urlparse(article_url).netloc]
        ticket = external[0] if external else None
        venue = ""
        m = re.search(r"(?:where|location|address|venue):\s*([^.|\n]{3,90})", text, re.I)
        if m:
            venue = clean(m.group(1))
        out.append(Event(
            source=source,
            source_id=short_hash(article_url, heading),
            source_url=article_url,
            ticket_url=ticket,
            title=heading,
            start=iso(start),
            end=iso(dt.datetime(end_day.year, end_day.month, end_day.day, 23, 0, tzinfo=TZ)) if end_day else None,
            all_day=all_day,
            description=text[:1000],
            venue=venue,
            price=price_from(text),
            sponsored=bool(ticket and any(h in ticket for h in sponsored_hosts)),
        ))
    return out


def find_dicts(obj, required: tuple[str, ...], limit=2000):
    """Depth-first search for dicts that contain all `required` keys."""
    out, stack = [], [obj]
    while stack and len(out) < limit:
        node = stack.pop()
        if isinstance(node, dict):
            if all(k in node for k in required):
                out.append(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def listing_page(f, url, source, is_event_url, city="", ref=None, default_hour=None, date_from_url=None):
    """Events from a calendar/listing page: JSON-LD, then microdata, then links
    with a date nearby. `date_from_url(url) -> date|None` helps when the URL
    carries the date (e.g. /event/2026-10-01/slug)."""
    from .core import jsonld_events, event_from_jsonld, now
    ref = ref or now().date()
    soup = f.soup(url)
    events = [e for e in (event_from_jsonld(n, source, url) for n in jsonld_events(soup)) if e]
    if not events:
        events = microdata_events(soup, source, url)
    if not events:
        def has_date(t):
            return bool(find_dates(t, ref)) or bool(re.search(r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b", t))
        for link, title, text, _ in link_blocks(soup, url, is_event_url, needs=lambda t: has_date(t) or (date_from_url and TIME_RE.search(t))):
            day = date_from_url(link) if date_from_url else None
            if not day:
                d = find_dates(text, ref)
                if not d:
                    continue
                day = d[0][0]
            start, all_day = at_time(day, text, default_hour)
            events.append(Event(source=source, source_id=slug(urlparse(link).path)[-80:], source_url=link,
                                title=title, start=iso(start), all_day=all_day, end=iso(end_time(start, text)),
                                description=text[:600], city=city, price=price_from(text)))
    for e in events:
        if city and not e.city:
            e.city = city
    return events, soup
