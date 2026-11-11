"""Add musicians and podcast comedians from a Spotify data export to data/follow.json.

Spotify's API needs a developer key, so this reads the export instead
(Account → Privacy → Download your data). Only names are kept; the raw
listening history, playlists and searches stay on your computer.

Rules:
  - musicians: 30+ minutes of listening in the export's year, or 6+ songs on
    your own playlists, or a saved artist with 4+ saved or playlisted songs
  - left off: names under four letters, names in data/music-skip.txt (background-music projects and
    names that are also everyday words) and data/deceased.txt (their tribute
    shows are boosted by music_tastes in data/profile.json instead)
  - podcast hosts: hosts of shows you've listened to for an hour or more, from
    SHOW_HOSTS below (the export names shows, not hosts)

Usage: python tools/build_music_list.py ~/Downloads/my_spotify_data.zip
"""
import datetime as dt
import json
import pathlib
import re
import sys
import zipfile
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent

# comedians and speakers who tour; tech, sports and therapy shows are left out
SHOW_HOSTS = {
    "Seek Treatment with Cat & Pat": ["Cat Cohen", "Pat Regan"],
    "Poog with Kate Berlant and Jacqueline Novak": ["Kate Berlant", "Jacqueline Novak"],
    "So True with Caleb Hearon": ["Caleb Hearon"],
    "Las Culturistas with Matt Rogers and Bowen Yang": ["Matt Rogers", "Bowen Yang"],
    "That's Enough with Grace Reiter": ["Grace Reiter"],
    "Astrology of the Week Ahead with Chani Nicholas": ["Chani Nicholas"],
    "Sean Carroll's Mindscape: Science, Society, Philosophy, Culture, Arts, and Ideas": ["Sean Carroll"],
}


def read_export(src):
    """{filename: parsed json} for the JSON files in a zip or an unzipped folder."""
    src = pathlib.Path(src).expanduser()
    out = {}
    if src.is_file():
        with zipfile.ZipFile(src) as z:
            for name in z.namelist():
                if name.endswith(".json"):
                    out[pathlib.Path(name).name] = json.loads(z.read(name))
    else:
        for p in src.rglob("*.json"):
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
    return out


def names_file(name):
    path = ROOT / "data" / name
    if not path.exists():
        return set()
    return {l.strip() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")}


def build(src):
    files = read_export(src)
    minutes, podcast = Counter(), Counter()
    for name, rows in files.items():
        if name.startswith("StreamingHistory_music"):
            for r in rows:
                minutes[r["artistName"]] += r["msPlayed"] / 60000
        elif name.startswith("StreamingHistory_podcast"):
            for r in rows:
                podcast[r["podcastName"]] += r["msPlayed"] / 60000
    library = files.get("YourLibrary.json", {})
    saved = {a["name"] for a in library.get("artists", [])}
    saved_songs = Counter(t["artist"] for t in library.get("tracks", []))
    on_playlists = Counter()
    for name, data in files.items():
        if name.startswith("Playlist"):
            for p in data.get("playlists", []):
                for item in p.get("items", []):
                    artist = (item.get("track") or {}).get("artistName")
                    if artist:
                        on_playlists[artist] += 1

    picked = {a for a, m in minutes.items() if m >= 30}
    picked |= {a for a, n in on_playlists.items() if n >= 6}
    picked |= {a for a in saved if on_playlists[a] + saved_songs[a] >= 4}
    left_off = names_file("music-skip.txt") | names_file("deceased.txt")
    # "((( O )))" or "TLC" is too short to find in a listing without false hits
    musicians = sorted((a for a in picked if a not in left_off and len(re.sub(r"[^a-z0-9]", "", a.lower())) >= 4),
                       key=lambda a: -(minutes[a] + 5 * on_playlists[a] + 2 * saved_songs[a]))
    hosts = []
    for show, mins in podcast.most_common():
        if mins >= 60:
            hosts += [h for h in SHOW_HOSTS.get(show, []) if h not in hosts]
    return {"musicians": musicians, "podcast_hosts": hosts}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out = build(sys.argv[1])
    path = ROOT / "data" / "follow.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing.update(out)
    existing["music_generated"] = dt.date.today().isoformat()
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")
    print(f"musicians={len(out['musicians'])} podcast_hosts={len(out['podcast_hosts'])}")
