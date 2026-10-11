"""Each listing site's own small icon (the Partiful P, the DICE figure), so a
row can show where it came from. Read from the site's home page <link rel=icon>
and kept in the cache for a month; a site that won't serve one gets none."""
import hashlib
import re
import time
from urllib.parse import urljoin, urlparse

from .core import CACHE_DIR, BudgetExceeded

TYPES = {"image/png": "png", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico", "image/svg+xml": "svg",
         "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
KEEP_DAYS = 30
MAX_BYTES = 60_000


def host_of(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def candidates(soup, base):
    """Icon links, the ones nearest 32px first; a big apple-touch icon is the fallback."""
    out = []
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        if "icon" not in rel or "mask" in rel:
            continue
        sizes = [int(n) for n in re.findall(r"(\d+)x\d+", link.get("sizes") or "")] or [180 if "apple" in rel else 32]
        out.append((abs(max(sizes) - 32) + (40 if "apple" in rel else 0), urljoin(base, link["href"])))
    out.sort()
    return [u for _, u in out] + [urljoin(base, "/favicon.ico")]


def fetch_icon(f, host):
    base = f"https://{host}/"
    try:
        soup = f.soup(base, cache_hours=24 * KEEP_DAYS)
    except BudgetExceeded:
        raise
    except Exception:
        soup = None
    for url in (candidates(soup, base) if soup else [urljoin(base, "/favicon.ico")])[:3]:
        if url.startswith("data:"):
            continue
        try:
            f._wait()
            f.count += 1
            resp = f.session.get(url, timeout=20)
        except Exception:
            continue
        kind = TYPES.get(resp.headers.get("content-type", "").split(";")[0].strip())
        if resp.ok and kind and 0 < len(resp.content) <= MAX_BYTES:
            return resp.content, kind
    return None


def write(events, f, out_dir, limit=40):
    """{host: "icons/src/<file>"} for the sites behind the most events."""
    counts = {}
    for ev in events:
        for url in [ev.get("source_url")] + [a.get("url") for a in ev.get("also_on") or []]:
            h = host_of(url)
            if h:
                counts[h] = counts.get(h, 0) + 1
    folder = out_dir / "icons" / "src"
    folder.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "icons"
    cache.mkdir(parents=True, exist_ok=True)
    found, read = {}, 0
    for host in sorted(counts, key=lambda h: -counts[h])[:limit]:
        stem = re.sub(r"[^a-z0-9]+", "-", host)
        hit = [p for p in cache.glob(stem + ".*") if time.time() - p.stat().st_mtime < KEEP_DAYS * 86400]
        if hit:
            body, kind = hit[0].read_bytes(), hit[0].suffix[1:]
        else:
            miss = cache / (stem + ".none")
            if miss.exists() and time.time() - miss.stat().st_mtime < 7 * 86400:
                continue
            try:
                got = fetch_icon(f, host)
            except BudgetExceeded:
                break
            read += 1
            if not got:
                miss.write_text("")
                continue
            body, kind = got
            if kind == "none":
                continue
            (cache / f"{stem}.{kind}").write_bytes(body)
        if kind == "none" or not body:
            continue
        name = f"{stem}-{hashlib.sha1(body).hexdigest()[:6]}.{kind}"
        (folder / name).write_bytes(body)
        found[host] = f"icons/src/{name}"
    return found, f"site icons: {len(found)} of {min(limit, len(counts))} sites ({read} fetched)"
