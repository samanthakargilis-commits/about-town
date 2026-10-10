"""Rebuild data/follow.json from a Goodreads library export (CSV).

Rules (same as reading-profile.md):
  - favorite authors: any 5-star book, or two or more books rated 4-5
  - new-book authors: a to-read book first published this year or last year
  - down-rank: did-not-finish or rated 1-2, with no loved book
Deceased authors listed in data/deceased.txt are left off the follow lists.

Usage: python tools/build_follow_list.py data/goodreads_library_export.csv
"""
import csv
import datetime as dt
import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent


def norm_author(name):
    return " ".join(name.split())


def build(csv_path):
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    deceased_file = ROOT / "data" / "deceased.txt"
    deceased = set()
    if deceased_file.exists():
        deceased = {l.strip() for l in deceased_file.read_text().splitlines() if l.strip() and not l.startswith("#")}

    loved = defaultdict(list)       # author -> titles rated 4-5
    five = set()
    disliked = set()
    new_books = {}
    this_year = dt.date.today().year
    for r in rows:
        author = norm_author(r["Author"])
        if not author:
            continue
        rating = int(float(r["My Rating"] or 0))
        shelf = r["Exclusive Shelf"]
        title = r["Title"].split(":")[0].strip()
        if rating >= 4:
            loved[author].append(title)
        if rating == 5:
            five.add(author)
        if shelf == "did-not-finish" or rating in (1, 2):
            disliked.add(author)
        year = r["Original Publication Year"] or r["Year Published"]
        if shelf == "to-read" and year.isdigit() and int(year) >= this_year - 1:
            new_books.setdefault(author, title)

    favorites = sorted(
        (a for a, t in loved.items() if (len(t) >= 2 or a in five) and a not in deceased),
        key=lambda a: -len(loved[a]),
    )
    new_authors = [a for a in new_books if a not in deceased]
    down = sorted(a for a in disliked if a not in loved and a not in deceased)
    return {
        "generated": dt.date.today().isoformat(),
        "source": "goodreads export",
        "authors_favorite": favorites,
        "authors_new_books": new_authors,
        "authors_downrank": down,
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "goodreads_library_export.csv"
    out = build(src)
    path = ROOT / "data" / "follow.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing.update(out)
    existing.setdefault("performers", [])
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
    print(f"favorites={len(out['authors_favorite'])} new={len(out['authors_new_books'])} downrank={len(out['authors_downrank'])}")
