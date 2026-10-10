"""Newsletters with public RSS feeds (Substack /feed). Each recent post is read
like a roundup article. The newsletter list lives in data/newsletters.json."""
import datetime as dt
import json
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..core import ROOT, html_to_text, now
from ..heuristics import article_events
from .. import ai

NAME, LABEL = "newsletters", "Newsletters"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
MAX_AGE_DAYS = 21


def newsletters():
    return json.loads((ROOT / "data" / "newsletters.json").read_text())


def fetch(f, start, end):
    out = []
    for nl in newsletters():
        try:
            root = ET.fromstring(f.get(nl["feed"]).encode())
        except Exception as exc:   # one newsletter down doesn't stop the others
            print(f"  {nl['name']}: {exc}")
            continue
        for item in root.iter("item"):
            pub = parsedate_to_datetime(item.findtext("pubDate"))
            if (now() - pub).days > MAX_AGE_DAYS:
                continue
            html = item.findtext(CONTENT) or item.findtext("description") or ""
            link = item.findtext("link")
            ref = pub.date()
            src = nl["id"]
            if ai.enabled():
                evs = ai.extract_events(src, link, item.findtext("title") or "", html, ref)
            else:
                evs = article_events(html, src, link, ref)
            for e in evs:
                e.source = src
            out += evs
    return out
