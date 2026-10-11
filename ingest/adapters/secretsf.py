"""Secret San Francisco: monthly / weekend roundup articles (WordPress REST API),
turned into events by the AI extractor when a key is set, else by headings."""
import datetime as dt
import re

from ..core import clean, html_to_text, now
from ..heuristics import article_events
from .. import ai

NAME, LABEL = "secretsf", "Secret San Francisco"
API = "https://secretsanfrancisco.com/wp-json/wp/v2/posts"
ROUNDUP = re.compile(r"things to do|this weekend|events? (in|this)|best .*(october|november|december|january|february|march|april|may|june|july|august|september)|halloween|holiday|guide to|calendar|festivals?|what's on", re.I)


def roundups(f):
    today = now()
    month = today.strftime("%B").lower()
    nxt = (today.replace(day=1) + dt.timedelta(days=32)).strftime("%B").lower()
    posts, seen = [], set()
    queries = [{"slug": s} for s in (f"things-to-do-{month}", f"things-to-do-{nxt}", "things-to-do-this-weekend",
                                      "things-to-do-this-weekend-san-francisco", "sf-events-calendar")]
    queries.append({"search": "things to do", "after": (today - dt.timedelta(days=35)).strftime("%Y-%m-%dT00:00:00")})
    queries.append({"search": "this weekend", "after": (today - dt.timedelta(days=10)).strftime("%Y-%m-%dT00:00:00")})
    for q in queries:
        params = {"per_page": 20, "_fields": "id,link,title,date,modified,content", **q}
        try:
            batch = f.get(API, params=params, as_json=True)
        except Exception:
            continue
        for p in batch:
            if p["id"] in seen or "/es/" in p["link"]:
                continue
            title = html_to_text(p["title"]["rendered"])
            if "slug" in q or ROUNDUP.search(title):
                seen.add(p["id"])
                posts.append(p)
    return posts


def fetch(f, start, end):
    out = []
    for p in roundups(f):
        html = p["content"]["rendered"]
        ref = dt.date.fromisoformat(p["date"][:10])
        if ai.enabled():
            out += ai.extract_events(NAME, p["link"], html_to_text(p["title"]["rendered"]), html, ref)
        else:
            out += article_events(html, NAME, p["link"], ref)
    return out
