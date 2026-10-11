"""Print what a page offers an adapter: JSON-LD events, __NEXT_DATA__, microdata,
feed links and the most common link patterns. Used to fix adapters."""
import collections
import json
import re
import sys
from urllib.parse import urljoin, urlparse

sys.path.insert(0, ".")
from ingest.core import Fetcher, jsonld_events, next_data  # noqa: E402

f = Fetcher(delay=1)
for url in sys.argv[1:]:
    print("=" * 80, "\n", url)
    if url.startswith("raw:"):
        url, _, needle = url.partition("|")     # raw:<url>|<text+to+show+the+page+around>
        needle = needle.replace("+", " ")
        try:
            text = f.get(url[4:])
            for m in re.finditer(r"https?://[^\s'\"<>]+|/api/[^\s'\"<>]+|/v\d/[^\s'\"<>]+", text):
                print("  url:", m.group(0)[:200])
            dec = text.encode().decode("unicode_escape", errors="ignore") if "\\u003C" in text else text
            i = max(0, dec.find(needle or "ticketmaster") - 3000)
            print(dec[i:i + 6000])
        except Exception as exc:
            print("  FETCH FAILED:", exc)
        continue
    try:
        html = f.get(url)
    except Exception as exc:
        print("  FETCH FAILED:", exc)
        continue
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    print(f"  bytes={len(html)} title={soup.title.string if soup.title else None!r}")
    print(f"  jsonld events={len(jsonld_events(soup))}  next_data={'yes' if next_data(soup) else 'no'}  "
          f"microdata={len(soup.find_all(attrs={'itemtype': re.compile('Event')}))}")
    for l in soup.find_all("link", type=re.compile("rss|atom|calendar|json")):
        print("  feed:", l.get("type"), urljoin(url, l.get("href", "")))
    for a in soup.find_all("a", href=re.compile(r"ical|\.ics|webcal|/feed|rss", re.I))[:8]:
        print("  feed link:", urljoin(url, a["href"]))
    for a in soup.find_all("a", href=True):
        if re.search(r"event|calendar", a["href"] + a.get_text(), re.I):
            print("  event-ish link:", urljoin(url, a["href"]), "|", a.get_text(" ", strip=True)[:60])
    pats = collections.Counter()
    for a in soup.find_all("a", href=True):
        p = urlparse(urljoin(url, a["href"]))
        pats[p.netloc + re.sub(r"/[^/]+", "/*", p.path, count=0)[:60]] += 1
    print("  link patterns:", pats.most_common(8))
    classes = collections.Counter(c for t in soup.find_all(True) for c in t.get("class", []))
    print("  classes:", [c for c, _ in classes.most_common(40)])
    scripts = [s.get("src") or (s.string or "")[:80] for s in soup.find_all("script")][:15]
    print("  scripts:", scripts)
    body = soup.get_text(" ")
    i = body.find(" pm")
    print("  text sample:", re.sub(r"\s+", " ", body[max(0, i - 600): i + 600]))
    nd = next_data(soup)
    if nd:
        print("  next_data keys:", list(nd.get("props", {}).get("pageProps", {}).keys())[:20])
