# Bay Area Event Planner — Project Brief

Oct 10, 2026 · @David

## Problem and user

One app replaces the monthly ritual of scanning four event sites by hand and building a calendar from them.

**The user (V1):** me. I live between San Francisco and Palo Alto. On the 1st of every month I open Partiful, Luma, SF Funcheap and Destination Palo Alto, scan for cool events, and build my calendar by hand.

**The pain:** each source is a walled garden. Partiful only shows Partiful, Luma only shows Luma. Nothing combines them, knows my taste, or checks my existing plans. The scan is slow, and I still miss things.

**The goal:** planning my month feels easy and fun, and I end up with real plans.

## Core loop

The app runs on two rhythms: a big monthly plan on the 1st, plus small weekly top-ups. Many Partiful and Luma events are posted only 1 to 2 weeks out, so a scan on the 1st alone misses much of the month.

**Monthly plan (the 1st):**

1. The app has already gathered upcoming events from every source.
2. It ranks them by my preferences and shows the best ones in a week-by-week view, with events I'll probably love highlighted.
3. I pick what I want, and the picks go to my calendar in one step.
4. My yes / no choices teach it my taste for next time.

**Weekly top-up:**

1. Once a week, the app shows only events that are new since my last review, such as "3 new things popped up for next weekend."
2. Swipe cards: only a few new events, so it stays quick and fun.

## Review format and event actions

The monthly plan is a week-by-week view, not swipes; adding to calendar and texting a friend each take one tap.

**Monthly view:**

- Events grouped by week, so options competing for the same evening sit side by side.
- **"You'll love this" highlights:** a few events the app is most confident about get special emphasis at the top of each week (bigger card, badge).
- One-tap buttons on every event: **Add**, **Maybe**, **Not for me**.
- My month visibly fills in as I add things.

**Weekly top-up:** swipe cards for the 3 to 8 new events since my last review.

**After I like an event, the next two steps must be effortless:**

1. **Add to calendar, one tap.** Opens a ready-made calendar event (title, time, place, link) that I confirm in my calendar app. Optional: add all my picks for the month at once.
2. **Share with a friend, one tap.** Opens my phone's share sheet (iMessage, text, anything) with a ready-to-send message, for example: "Want to go? Craft night, Thu Oct 16, 7pm, Mission District · \[link\]". The link goes to the original event page so my friend can RSVP. Fallback: a **Copy link** button.

Technical note: the PWA can open the phone's share sheet with the Web Share API. Test "Add to calendar" from the installed PWA on iPhone early, since calendar files can behave differently there than in Safari.

## Preference learning

The app learns my taste in three layers: a profile I set once, every choice I make, and a visible reason on each card.

1. **Starting profile (set once, editable any time):**
   - Interests: craft events, meditation, spirituality, musical theatre, theatre, comedy, singing (karaoke, open mics, sing-alongs), art, reading (book clubs, author talks), writing (workshops, readings), discourse (salons, debates, talks), gay / queer events, and weird, unusual events (more to add)
   - Favorite times: Thursday evenings
   - **People I follow:** comedians, performers and artists I like, imported from my Instagram follow list (Instagram's "Download your information" export) or typed in by hand, plus authors from my Goodreads shelves
   - How far I'll travel, budget, solo or with friends
   - Things I never want to see
2. **Learning from my choices.** Every Add, Maybe, Not for me, swipe and share updates the profile. Skips teach it as much as yeses.
3. **Showing its reasoning.** Each card has a one-line why, such as "Musical theatre · Thursday evening · 10 min away". Sometimes it checks a guess: "You've skipped 4 tech meetups. Hide those?"

**Rules:**

- Favorite times and interests **boost** ranking; they never filter. A great Saturday craft fair still shows up.
- The strongest matches become the "You'll love this" highlights.

**People I follow:** any event that names someone on my follow list (a comedian, performer or artist) gets a "⭐ Someone you follow" badge and ranks near the top. The app doesn't read Instagram; it matches names against the event listings it already pulls. Shows announced only on Instagram (such as a surprise drop-in set) won't be caught.

**Goodreads:** Goodreads no longer offers an API to new developers, so V1 uses my library export (My Books → Import and export) and, if my shelves are public, their RSS feeds so new books are picked up automatically. Authors I've read or want to read join my follow list, so their talks, readings and signings get the "⭐ Someone you follow" badge. Genres and themes on my shelves boost related book clubs, panels and talks. A starter reading profile built from my export (favorite authors, authors with new books, tastes, and authors to down-rank) is in `reading-profile.md`.

**Events inside bigger events:** for multi-part events (fairs, festivals, street fairs, conventions), the app also reads the schedule or lineup and puts the best-matching piece in the headline, with the parent event underneath. Example: "Elvis Impersonator Contest, at Sonoma County Fair · Sat 2pm · you love singing". Add to calendar uses that specific time slot. If the organizer hasn't published a schedule, the card falls back to the parent event.

**How to build it in V1:** no custom machine learning. An AI model reads my profile and each event's description, tags the event, scores it, and writes the one-line why. The profile is plain text I can read and edit.

## V1 scope

V1 is a phone-installable PWA that aggregates fourteen sources, ranks events by my taste, and makes adding to my calendar and texting a friend one tap each. The app itself does not read my calendar; the daily job reads it only to fit the one-a-day Apple Calendar feed around my week (pulled forward from V2 on 2026-10-14).

**Sources:**

| Source | What it covers | Access notes |
| --- | --- | --- |
| [Partiful](https://partiful.com) Explore (SF) | Social events, parties, community events | Public Explore pages only; private invites are not visible |
| [Luma](https://lu.ma) | Tech, startup and community events | Public event and calendar pages |
| [SF Funcheap](https://sf.funcheap.com) | Free and cheap SF events | Check for an RSS or calendar feed before parsing pages |
| [Destination Palo Alto](https://www.destinationpaloalto.com) | Palo Alto and Peninsula events | Check for a feed before parsing pages |
| Eventbrite | Huge volume: craft workshops, meditation classes, sound baths | Noisy; needs strong filtering by my preferences |
| Meetup | Recurring groups (meditation circles, craft nights) that fit a weekly habit | Public group event pages; recurring events need care when merging |
| BroadwaySF | Touring Broadway musicals at the Orpheum, Golden Gate and Curran | Few listings, posted months ahead; easy |
| DoTheBay | Curated Bay Area music, art, food, theater and comedy | Check for a feed before parsing pages |
| [Secret San Francisco](https://secretsanfrancisco.com) | Monthly and weekend "things to do" roundups, plus an SF events calendar page | Articles, not listings: AI extraction from the this-month, next-month and this-weekend roundups (a natural fit for the monthly plan and weekly top-ups); some items are sponsored, so weigh them accordingly |
| Dice | Ticketed concerts, DJ nights, club and live-music events | Public event pages; check for a feed first |
| [Kepler's Books](https://www.keplers.org) (Menlo Park) | Author talks, readings and signings on the Peninsula | Bookstore events calendar; check for a feed first |
| [City Lights](https://citylights.com) (SF) | Readings, poetry, literary and political talks | Bookstore events calendar; check for a feed first |
| [Green Apple Books](https://www.greenapplebooks.com) (SF) | Author events and book launches | Bookstore events calendar; check for a feed first |
| Newsletters (Substack): [Eddie's List](https://www.eddies-list.com), [SF Girl Chronicle](https://sfgirlchronicle.substack.com) | Weekly curated Bay Area event roundups; a list I can add more newsletters to | Read each newsletter's public RSS feed (Substack: /feed), not my inbox; AI extraction like Secret San Francisco. SF Girl Chronicle's feed has full text; Eddie's List feed not yet confirmed |

**Features in V1:**

- [ ] Pull events from all fourteen sources on a schedule, and merge duplicates
- [ ] Filter to my area (SF to Palo Alto corridor)
- [ ] Monthly week-by-week view on the 1st, with "You'll love this" highlights
- [ ] Weekly swipe-card top-ups of new events
- [ ] Preference profile I set once, plus learning from every choice, with a one-line why on each card; "⭐ Someone you follow" badge for people on my follow list; best-matching sub-event highlighted for fairs and festivals
- [ ] One-tap Add to calendar for any event, plus an option to add all my picks at once
- [ ] One-tap Share to iMessage or text via the phone's share sheet, plus Copy link
- [ ] About Town inside Apple Calendar: a subscribed calendar I tick on or off that shows the one best idea for each day at its own time; its notes give the blurb, then tickets, then why it's picked, the price and miles from home, and its link opens the event's own page; an optional second calendar shows every idea
- [ ] The one-a-day idea fits my week: my weekly routine (which office each weekday, when I head home) plus my own calendars, read from private calendar links. It skips ideas that clash with fixed plans, may sit over casual ones, and judges distance from where I'll be
- [ ] Installable on my phone home screen as a PWA
- [ ] Every event links back to its original page for RSVP or tickets

## Out of scope for V1, and V2

V2's main addition is flagging conflicts on the app's own cards. (Calendar reading for the one-a-day feed moved into V1.) Everything below stays out of V1 to keep it small.

**Not in V1:**

- Reading my calendar in the app itself, or conflict flags on its cards. A web app can't read Apple Calendar directly; only the daily job reads it, for the one-a-day feed
- A native iOS or Android app
- Private Partiful invites, which aren't publicly visible
- Reddit (r/SFbitcheswithtaste): needs Reddit API access and yields few events; revisit later. Reading Instagram directly is also out: apps can't read posts from accounts I follow, so V1 matches my follow list against event listings instead
- Social features beyond sharing a link (friend accounts, seeing who's going, group plans)
- Other users, accounts, or monetization
- RSVP or ticket purchase inside the app; it links out instead

**V2 plan:**

- Flag conflicts on the app's event cards instead of hiding them (see Product principles), using the same calendar reading the feed does.
- Optional Gmail source for newsletters with no public feed: a Gmail filter labels event newsletters, and the app reads only that label, read-only.
- Revisit more sources and smarter preference learning once V1 has a few months of my choices.

## Product principles

These are the rules every design and build decision should follow.

1. **Flag conflicts, never hide great events.** A really cool event that clashes with an existing plan still appears, marked as a conflict (for example, "clashes with dinner with Sam. Worth moving?"). Conflicts are a tradeoff for me to decide, not a filter.
2. **Curation over volume.** Show the best 20 to 40 events a month, not every listing. If I have to scroll through hundreds, the app has failed.
3. **Planning should feel fun.** The monthly review should feel like a treat, not a chore. Great UI and a smooth, quick flow on a phone are core to the product, not polish.
4. **Fresh beats complete.** Weekly top-ups show only what's new, so I never re-review events I've already seen.
5. **Respect the sources.** Link back to the original page for every event, fetch gently, and prefer official feeds over page scraping.
6. **Built for me first.** V1 is a personal tool. Business questions wait until it has proven itself to me over a few months.

## Technical guidelines

Proposed V1 architecture: a scheduled job gathers events into one file, and a static PWA reads it. No server to run, and it can be free to host.

**Architecture at a glance:**

```
14 sources ──► Scheduled job (daily, e.g. GitHub Actions) ──► events.json (static file, free HTTPS host)
               - one adapter per source                            │
               - AI pulls events out of articles                   ▼
               - normalize, merge duplicates              PWA on my phone
               - filter to SF–Palo Alto                   - week view on the 1st + highlights
               - score and tag for my taste               - swipe top-ups, new only
                                                          - one-tap add and share
                                                          - learns my preferences
                                                             │            │
                                               add (.ics) ◄──┘            └──► share (iMessage/text + link)
                                               My calendar ┄┄ private links (secret) ┄┄► job
```

The dashed line is the job reading my own calendars through private links, only to fit the one-a-day feed around my week. The same job also writes two subscribed calendar feeds that Apple Calendar shows as switchable calendars (see Calendar overlay below).

**Why fetching can't happen in the PWA itself:** browsers block a web page from reading other sites' content (CORS). Fetching from Partiful, Luma and the others has to happen in a separate scheduled job.

**Proposed stack (open to change):**

- **Ingestion:** a scheduled job (for example, a GitHub Actions workflow running daily) runs one adapter per source, normalizes and merges events, and writes `events.json`.
- **Hosting:** the PWA and `events.json` are served as static files (for example, GitHub Pages, Netlify or Cloudflare Pages) over HTTPS.
- **App:** a PWA with a manifest (name, icon, full-screen) and a service worker (offline cache), installed via Add to Home Screen.
- **Preferences and history:** stored on my phone in V1 (browser storage). Note: this can be wiped if browser data is cleared, so add an export / backup option.
- **Calendar output:** generate standard `.ics` calendar files, which Apple Calendar and Google Calendar both accept.
- **Calendar overlay:** the daily job also publishes two subscribed calendar feeds (`calendar.ics`, `calendar-more.ics`) next to `events.json`. Apple Calendar shows them as their own calendars to switch on and off; events are marked free so they never block time. Apple Calendar can't show photos, buttons or expandable lists in a subscribed calendar, and its events can't be copied. Each event's link row is the event's own page, so the About Town site stays out of my calendar. Apple Calendar picks a subscribed calendar's color when you subscribe; the feed asks for gray, but changing it later is done in Calendar itself.
- **Taste for the feeds:** the feeds are built by the job, but choices live on the phone, so the app's "Update my calendars" button opens a GitHub issue titled "Calendar taste" holding my interests, learned weights and choices (the same pattern as Add a source). The job reads only issues from the repo's own people. Added and Not for me events leave the feeds. The repo is public, so these choices are visible there.
- **Fitting my week:** `data/profile.json` holds my weekly routine. My own calendars come in as private calendar links (iCloud's Public Calendar link, or Outlook's and Google's secret iCal address) saved in the repo secret `CALENDAR_LINKS`, one per line, with `work ` in front of a calendar whose events are all fixed. The job reads them each run and never prints, saves or publishes anything from them; the only trace is which idea a day gets. Fixed-looking events (others invited, a place, a meeting link, appointment-type words) block their time plus 30 minutes of travel; casual ones (gym, errands, holds, tentative) don't. Events longer than 3 hours only need 90 free minutes. An all-day event more than 40 miles from home empties those days. Anyone holding a calendar link can read that calendar, so the links stay in the secret only.

**Source adapters:** each source gets its own small adapter that outputs the shared event format below. When one source breaks, only its adapter needs fixing, and the others keep working. Two kinds of adapter: listing sites (Partiful, Luma, Eventbrite, Dice…) give structured events, while articles and newsletters (Secret San Francisco, Substack roundups) need an AI step to pull out the event details, and items with no clear date are dropped.

**Event data model:**

| Field | Purpose |
| --- | --- |
| `id` | Stable ID per event (source + source's event ID) |
| `source`, `source_url` | Where it came from; the link out for RSVP or tickets |
| `title`, `description`, `image_url` | What's shown on the card |
| `start`, `end`, `timezone` | When; used for calendar export and conflicts |
| `venue`, `address`, `city` | Where; used for the SF to Palo Alto area filter |
| `price` | Free / cheap / paid, when known |
| `tags` | Category (music, tech, food, art, outdoors…) for preference matching |
| `first_seen` | When the app first saw it; powers "new this week" top-ups |
| `dedupe_key` | Normalized title + date + venue, to merge the same event listed on two sites |
| `score` | How well it matches my profile; sets ranking and highlights |
| `why` | One-line reason shown on the card |
| `my_status` | Added / Maybe / Not for me / Shared; stored on my phone and fed back into learning |
| `people` | Performers named in the listing; matched against my follow list |
| `parent_event` | Name and link of the bigger event when the card is a sub-event (e.g. the fair) |

## Risks and mitigations

The biggest risk is data access: most sources have no official API, so adapters will break when sites change.

| Risk | Mitigation |
| --- | --- |
| Sites change their pages and an adapter breaks | One adapter per source; the job alerts me when a source returns zero events; other sources keep working |
| Scraping may break a site's terms of use | Prefer official feeds (RSS, calendar files); fetch gently; personal use only in V1; revisit before any public launch |
| Best Partiful events are private invites | Accept it: V1 covers public events only |
| Events posted late are missed | Weekly top-ups driven by `first_seen` |
| The same event appears on two sites | Merge using `dedupe_key` |
| Recommendations feel generic early on | Start with a few explicit preferences, then learn from every yes / no |
| Preferences stored on the phone get wiped | Export / backup option; move to a synced store later if needed |
| No conflict checking in the app | The one-a-day feed avoids clashes from my linked calendars; V2 flags them on the app's cards |
| Fairs and festivals publish schedules late or not at all | Fall back to the parent event; re-check the schedule page on each daily run |

## Validation plan and success criteria

V1 succeeds if it replaces my manual monthly scan for three months in a row.

**For me:**

- [ ] I use the monthly review on the 1st for 3 months straight
- [ ] I stop opening the four sites by hand
- [ ] I attend events I found through the app and wouldn't have found otherwise
- [ ] Weekly top-ups surface events my monthly scan would have missed

**Beyond me (before thinking about other users):**

- [ ] Ask 5 friends in SF or the Peninsula whether they do a similar planning ritual, and how
- [ ] If 2 or more do, share the app with them and watch whether they come back on their own

**Optional cheap first test:** before building the UI, run a monthly and weekly scheduled task that scans the sources and sends me a ranked shortlist. It tests whether the curation is good, which is the riskiest part.

## Open questions

- [ ] Name for the app
- [ ] Exact area: which cities count between SF and Palo Alto? A distance limit from home or work?
- [x] V1 conflicts: decided 2026-10-14. The one-a-day feed reads my calendars through private links and fits around my weekly routine
- [ ] Rest of the starting profile: budget and travel distance
- [ ] How many "You'll love this" highlights per week before they stop feeling special?
- [ ] Default wording of the share message
- [ ] Which day and time should weekly top-ups arrive, and how (open the app, a notification, or an email)?
- [ ] Which free host for the PWA and the scheduled job?
