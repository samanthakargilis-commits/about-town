# About Town

A personal event planner for the San Francisco to Palo Alto corridor. A daily
GitHub Actions job gathers events from 14 sources, merges duplicates, keeps the
corridor, scores everything against `data/profile.json`, and publishes a static
PWA plus `events.json` to GitHub Pages. The spec is [brief.md](brief.md).

## Use it

Open `https://<your-github-name>.github.io/<repo>/` in Safari on your iPhone,
then Share → Add to Home Screen.

- **Plan**: this month and next, week by week. "You'll love this" cards lead each
  week. Tap ＋ Add / Maybe / Not for me; 📅 opens the calendar sheet; ↗︎ opens the
  share sheet (Copy link is in the event's details).
- **New**: swipe cards for events first seen since your last review.
- **Picks**: everything you added, plus "Add all to my calendar".
- **You**: interests (love / like / not into), people you follow (type names or
  import your Instagram export), Goodreads CSV import, what it has learned,
  backup/restore, and which sources worked on the last run.

- **In Apple Calendar**: the You tab has two Subscribe buttons. "One a day" adds
  the single best idea for each day, at its own time. Its notes give the blurb,
  tickets, then why it's picked, the price and miles from home; Location shows
  just the venue. "Every idea" shows all the day's ideas at their
  times. Both are calendars you tick on or off and never block time.
  "Update my calendars" sends your taste (a "Calendar taste" GitHub issue) so the
  feeds learn too. The daily job writes them as `calendar.ics` and
  `calendar-more.ics` next to `events.json`.
- **Fits your week**: the one-a-day calendar skips ideas during work hours and
  ones that clash with fixed plans in your own calendars, and measures distance
  from where you'll be (your routine is `week` in `data/profile.json`). To link
  calendars, save their private links in the repo secret `CALENDAR_LINKS`, one
  per line (`work ` in front of a calendar whose events are all fixed).

Choices and learned taste stay on the phone (localStorage). Export a backup now and then.

## How it's built

```
ingest/adapters/*.py   one adapter per source; a broken one never stops the rest
ingest/heuristics.py   fallback parsing for pages without feeds
ingest/score.py        interest + time boosts, follow-list badge, one-line why
ingest/feed.py         the two subscribed Apple Calendar feeds
ingest/busy.py         your routine and calendars: what clashes, where you'll be
ingest/ai.py           optional: AI tagging and article extraction (needs ANTHROPIC_API_KEY)
ingest/__main__.py     run all → window → area filter → merge → enrich → score → events.json + .ics
app/                   the PWA (no build step)
data/profile.json      starting profile (edit freely)
data/follow.json       people you follow; authors rebuilt from Goodreads by tools/build_follow_list.py,
                       musicians and podcast comedians from Spotify by tools/build_music_list.py
data/newsletters.json  newsletter RSS feeds (add more here)
```

Run locally: `pip install -r requirements.txt && python -m ingest && python -m http.server -d app`.
Tests: `python -m unittest discover -s tests`.

Rebuild authors from a new Goodreads export:
`python tools/build_follow_list.py path/to/goodreads_library_export.csv`.
Rebuild musicians from a new Spotify export (the zip stays on your computer):
`python tools/build_music_list.py path/to/my_spotify_data.zip`.

### Sources

| Source | How |
|---|---|
| SF Funcheap | day pages (the RSS feed only has 10 items with no details) |
| Secret San Francisco | WordPress API roundups → events (AI, or headings without AI) |
| Luma | public discover feed for SF, paginated |
| City Lights, Green Apple, Kepler's | bookstore event pages |
| BroadwaySF | events page |
| DoTheBay | day pages, next 3 weeks |
| Eventbrite | keyword searches from the profile (craft, meditation, comedy…) |
| Meetup | keyword searches for recurring groups |
| Dice, Partiful Explore | public browse pages |
| Destination Palo Alto | calendar page (best effort: it loads with JavaScript) |
| Newsletters | Substack RSS: SF Girl Chronicle, Eddie's List |

The Actions run summary shows each source's count and the top 30 events.
