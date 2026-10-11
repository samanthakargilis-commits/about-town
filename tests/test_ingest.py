"""Parser and scoring checks on small hand-written pages (shaped like the
real sites). Real-source runs happen in the daily workflow."""
import datetime as dt
import json
import pathlib
import unittest

from bs4 import BeautifulSoup

from ingest import area, ics
from ingest.__main__ import collapse_recurring, merge
from ingest.adapters import funcheap, greenapple
from ingest.core import TZ, find_dates, parse_time
from ingest.heuristics import article_events
from ingest.score import Scorer

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / "data" / "profile.json").read_text())
FOLLOW = json.loads((ROOT / "data" / "follow.json").read_text())

FUNCHEAP_DAY = """
<html><body><div id="content">
 <div class="tanbox"><span class="title"><a href="https://sf.funcheap.com/big-gay-halloween/" title="Big Gay Halloween">Big Gay Halloween</a></span>
   <div class="meta">Thursday, October 15 – 8:00 pm - Ends at 10:00 pm | Cost: $30-45 | Great Star Theater</div></div>
 <div class="tanbox"><span class="title"><a href="https://sf.funcheap.com/crazy-karaoke-sf-3/">Crazy Karaoke: SF's Wild Thursday Party</a></span>
   <div class="meta">Every Thursday – 9:00 pm | Cost: FREE w/ RSVP | The Function</div></div>
 <table><tr><td>6:00 pm</td><td><a href="https://sf.funcheap.com/lake-merritt-lantern-walk/">Lantern Walk (Oakland)</a></td><td>FREE</td></tr></table>
</div>
<div id="sidebar"><a href="https://sf.funcheap.com/most-popular-thing/">Popular thing 7:00 pm</a></div>
<a href="https://sf.funcheap.com/category/event/">Category 8pm</a>
</body></html>"""

ARTICLE = """
<h2>1. Exploratorium After Dark: Día de los Muertos</h2>
<p>The museum's adults-only night returns on Thursday, October 22, from 6pm to 10pm with talks and altars.</p>
<p>Where: Exploratorium, Pier 15</p>
<h2>2. A cozy new bakery</h2><p>Open daily with great croissants and no date at all, sadly.</p>
<h2>3. Renegade Craft Fair</h2><p>More than 250 makers fill Fort Mason November 14 & 15. <a href="https://feverup.com/x">Tickets</a></p>
"""


class Parsing(unittest.TestCase):
    def test_times_and_dates(self):
        self.assertEqual(parse_time("doors 7:30 pm"), (19, 30))
        self.assertEqual(parse_time("12am"), (0, 0))
        ref = dt.date(2026, 10, 10)
        self.assertEqual(find_dates("Nov. 14 & 15", ref)[0], (dt.date(2026, 11, 14), dt.date(2026, 11, 15)))
        self.assertEqual(find_dates("January 3", ref)[0][0], dt.date(2027, 1, 3))
        self.assertEqual(find_dates("Oct 22–25, 2026", ref)[0], (dt.date(2026, 10, 22), dt.date(2026, 10, 25)))

    def test_funcheap_day_page(self):
        evs = funcheap.parse_day(BeautifulSoup(FUNCHEAP_DAY, "lxml"), dt.date(2026, 10, 15))
        titles = [e.title for e in evs]
        self.assertIn("Big Gay Halloween", titles)
        self.assertNotIn("Popular thing", titles)          # sidebar ignored
        self.assertNotIn("Category", " ".join(titles))     # category links ignored
        bgh = next(e for e in evs if e.title == "Big Gay Halloween")
        self.assertEqual(bgh.start, "2026-10-15T20:00-07:00")
        self.assertEqual(bgh.end, "2026-10-15T22:00-07:00")
        self.assertEqual(bgh.price, "$30-45")
        self.assertEqual(bgh.venue, "Great Star Theater")
        karaoke = next(e for e in evs if "Karaoke" in e.title)
        self.assertTrue(karaoke.recurring)
        self.assertEqual(karaoke.price, "free")

    def test_article_extraction_drops_undated(self):
        evs = article_events(ARTICLE, "secretsf", "https://secretsanfrancisco.com/things-to-do-october/", dt.date(2026, 10, 1))
        self.assertEqual([e.title for e in evs], ["Exploratorium After Dark: Día de los Muertos", "Renegade Craft Fair"])
        self.assertEqual(evs[0].start, "2026-10-22T18:00-07:00")
        self.assertEqual(evs[0].venue, "Exploratorium, Pier 15")
        self.assertTrue(evs[1].sponsored)
        self.assertEqual(evs[1].end[:10], "2026-11-15")

    def test_article_price_from_other_day_is_ignored(self):
        html = """<article><h2>Italian Heritage Festival and Parade</h2>
        <p>On Sunday, October 11, the annual Italian Heritage Parade returns to North Beach at 12:30 p.m.
        On October 10, you can check out the Il Gran Ballo, a black-tie ball at the Westin St. Francis.
        The celebration will feature live music, and tickets are on sale now for $325.00 at 8 p.m.</p></article>"""
        e = article_events(html, "secretsf", "https://secretsanfrancisco.com/x/", dt.date(2026, 10, 1))[0]
        self.assertEqual(e.start, "2026-10-11T12:30-07:00")
        self.assertEqual(e.price, "")

    def test_greenapple_date_from_url(self):
        self.assertEqual(greenapple.date_from_url("https://greenapplebooks.com/event/2026-10-06/offsite-ayad-akhtar"), dt.date(2026, 10, 6))


def ev(title, start="2026-10-15T20:00-07:00", **kw):
    base = dict(id=f"x:{title}", source="funcheap", source_url="https://sf.funcheap.com/x/", title=title, start=start,
                end=None, all_day=False, description="", venue="", address="", city="", price="", tags=[], people=[],
                recurring=False, sponsored=False)
    base.update(kw)
    return base


class Scoring(unittest.TestCase):
    s = Scorer(PROFILE, FOLLOW)

    def test_price_matters(self):
        party = "826 Valencia\u2019s \u201cWriter\u2019s Block Party\u201d: $40 for Unlimited Beer & Wine"
        paid = self.s.score(ev(party, price="$40", description="unlimited beer & wine for writers"))
        free = self.s.score(ev(party, price="free", description="unlimited beer & wine for writers"))
        self.assertGreater(free["score"] - paid["score"], 5)
        show = self.s.score(ev("Broadway musical sing-along cabaret", price="$40"))
        self.assertGreater(show["score"], paid["score"])

    def test_no_tech_or_networking(self):
        self.assertIsNone(self.s.score(ev("Founders Panel: The Agentic Stack", source="luma")))
        self.assertIsNone(self.s.score(ev("Free 2026 South Bay Transit Summit + Networking")))
        self.assertIsNotNone(self.s.score(ev("Sudo Choir Annual Concert", description="by developers who sing")))

    def test_no_kids_events(self):
        self.assertIsNone(self.s.score(ev("Storytime: For Toddlers", source="sfpl")))
        self.assertIsNone(self.s.score(ev("Performance: Mariela's Music Time", description="Babies, Toddlers or Preschoolers · Dance & Music")))
        self.assertIsNone(self.s.score(ev("SF \u201cHalloween Hoopla\u201d Kids\u2019 Festival in the Park")))
        self.assertIsNotNone(self.s.score(ev("Aquarium of the Bay: Underwater Pumpkin Carving w/ Kids Free")))
        self.assertIsNotNone(self.s.score(ev("\u201cMortified Live\u201d Embarrassing Teen Diary Storytelling")))

    def test_paid_partiful_painting_is_never(self):
        title = "golden gate bridge/fleet week picnic & watercolor workshop"
        self.assertIsNone(self.s.score(ev(title, source="partiful", price="$25")))
        self.assertIsNotNone(self.s.score(ev(title, source="partiful", price="free")))
        self.assertIsNotNone(self.s.score(ev(title, source="funcheap", price="$25")))

    def test_sold_out_titles(self):
        from ingest.__main__ import SOLD_OUT
        self.assertTrue(SOLD_OUT.search("Comedy Night (SOLD OUT)"))
        self.assertFalse(SOLD_OUT.search("After a sold-out run, Wicked returns"))

    def test_interests_boost_and_thursday(self):
        thu = self.s.score(ev("Drag show-tune sing-along"))
        sat = self.s.score(ev("Drag show-tune sing-along", start="2026-10-17T20:00-07:00"))
        self.assertGreater(thu["score"], sat["score"])
        self.assertIn("Thursday evening", thu["why"])
        self.assertTrue({"queer", "musical_theatre", "singing"} <= set(thu["tags"]))
        self.assertGreater(sat["score"], 2)       # boosts never filter: Saturday still scores well

    def test_followed_author_badge(self):
        r = self.s.score(ev("An evening with David Sedaris", source="citylights"))
        self.assertEqual(r["followed"], "David Sedaris")
        self.assertTrue(r["why"].startswith("⭐ David Sedaris"))
        plain = self.s.score(ev("An evening with Jane Doe", source="citylights"))
        self.assertGreaterEqual(r["score"], plain["score"] + 6)

    def test_kids_author_event_hidden(self):
        # a children's storytime is hidden outright now, even with an author you follow
        self.assertIsNone(self.s.score(ev("Storytime for kids with Jeff Kinney")))

    def test_tech_downranked_and_never(self):
        # a tech title is hidden; tech words only in the body still cost points
        self.assertIsNone(self.s.score(ev("Founders demo day: AI agents", start="2026-10-17T18:00-07:00")))
        tech = self.s.score(ev("Thursday mixer", description="for founders and engineers", start="2026-10-17T18:00-07:00"))
        self.assertIn("tech", tech["tags"])
        self.assertLess(tech["score"], 0)
        self.assertIsNone(self.s.score(ev("Crypto networking mixer")))


class Pipeline(unittest.TestCase):
    def test_area(self):
        self.assertTrue(area.in_area(ev("Big Gay Halloween", venue="Great Star Theater")))
        self.assertFalse(area.in_area(ev("Lantern Walk (Oakland)")))
        self.assertTrue(area.in_area(ev("Talk", source="keplers", city="Menlo Park")))
        self.assertFalse(area.in_area(ev("Talk", source="citylights", city="Online")))
        self.assertFalse(area.in_area(ev("Comedy", source="eventbrite", city="Berkeley")))

    def test_merge_duplicates_across_sources(self):
        a = ev("Renegade Craft Fair", source="secretsf", start="2026-11-14T10:00-08:00", description="short")
        b = ev("Renegade Craft Fair at Fort Mason", source="funcheap", start="2026-11-14T10:00-08:00", source_url="https://sf.funcheap.com/renegade/")
        out = merge([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "funcheap")       # listing site wins over the article
        self.assertEqual(out[0]["also_on"][0]["source"], "secretsf")

    def test_recurring_one_per_week(self):
        items = [ev("Crazy Karaoke", start=f"2026-10-{d}T21:00-07:00", recurring=True, id=f"k{d}") for d in (15, 16, 22)]
        self.assertEqual(len(collapse_recurring(items)), 2)

    def test_ics(self):
        text = ics.calendar([dict(ev("Big Gay Halloween; drag, acrobats", end="2026-10-15T22:00-07:00"), why="Queer · Thursday evening")])
        self.assertIn("DTSTART;TZID=America/Los_Angeles:20261015T200000", text)
        self.assertIn(r"SUMMARY:Big Gay Halloween\; drag\, acrobats", text)
        self.assertTrue(all(len(l.encode()) <= 75 for l in text.split("\r\n")))


if __name__ == "__main__":
    unittest.main()


class FakeFetcher:
    """Serves canned pages/JSON instead of the network."""
    def __init__(self, pages):
        self.pages, self.count = pages, 0

    def get(self, url, params=None, as_json=False, **kw):
        key = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items())) if params else "")
        for k, v in self.pages.items():
            if key.startswith(k):
                return v
        raise RuntimeError("no page for " + key)

    def soup(self, url, **kw):
        return BeautifulSoup(self.get(url, **kw), "lxml")


class BigEvents(unittest.TestCase):
    """Fleet Week, Terror Vault and the other things a list shouldn't bury."""
    def test_funcheap_promo_title_categories_and_blurb(self):
        page = """<div id="post-1" class="tanbox post category-top-pick category-halloween category-sponsored">
          <span class="title entry-title"><a href="https://sf.funcheap.com/10-off-tix-sfs-terror-vault-2026/">$10 Off Tix: SF’s “Terror Vault” Halloween Haunt (2026)</a></span>
          <div class="meta">Thursday, October 15 &#150; 6:00 pm - Ends at 9:30 pm | Cost: $10 off* | San Francisco Mint</div></div>
          <div id="post-2" class="tanbox post category-annual-event-2"><span class="title"><a href="https://sf.funcheap.com/italian-heritage-parade-2026/">Italian Heritage Parade</a></span>
          <div class="meta">Sunday, October 11 &#150; 12:30 pm | Cost: FREE | North Beach</div></div>
          <script type="application/ld+json">[{"@type":"Event","name":"x","url":"https://sf.funcheap.com/10-off-tix-sfs-terror-vault-2026/",
          "description":"San Francisco’s premiere haunted attraction returns"}]</script>"""
        evs = {e.title: e for e in funcheap.parse_day(BeautifulSoup(page, "lxml"), dt.date(2026, 10, 15))}
        tv = evs["SF’s “Terror Vault” Halloween Haunt (2026)"]
        self.assertEqual(tv.price, "")                     # "$10 off" is a discount, not the price
        self.assertEqual(tv.tags, ["halloween"])           # "top pick" is on most posts: not kept
        self.assertIn("haunted attraction", tv.description)
        self.assertEqual(evs["Italian Heritage Parade"].tags, ["annual"])

    def test_funcheap_city_guide(self):
        guide = """<h1>SF’s “Fleet Week” 2026 Air Show + Full Schedule (Oct. 4-12)</h1><div class="entry">
          <h2>Air Show</h2><p>The Blue Angels fly October 9-11, 12pm-4pm at Marina Green. Free to watch.</p>
          <h2>Thursday, October 8, 2026</h2><p>Practice day: the Blue Angels fly at 1pm on October 8.</p>
          <h2>Ship Tours</h2><p>Tour Navy ships October 7-12 at Piers 27 and 35. Free.</p>
          <h3>Fleet Week Transportation</h3><p>Muni runs extra trains October 9-11.</p></div>
          <div id="sidebar"><h3>Most Popular Upcoming Events</h3><p>Lots on October 10.</p></div>"""
        home = '<a href="https://sf.funcheap.com/city-guide/sfs-fleet-week-festival-guide/">Fleet Week</a>'
        day = """<div id="post-3" class="post"><span class="title"><a href="https://sf.funcheap.com/fleet-week-at-pier-39/">Fleet Week at PIER 39</a></span>
          <div class="meta">Saturday, October 10 &#150; 10:00 am | Cost: FREE | Pier 39</div></div>"""
        f = FakeFetcher({"https://sf.funcheap.com/city-guide/": guide, "https://sf.funcheap.com/2026/": day, "https://sf.funcheap.com/": home})
        evs = funcheap.fetch(f, dt.datetime(2026, 10, 10, tzinfo=TZ), dt.datetime(2026, 10, 10, 23, tzinfo=TZ))
        titles = {e.title: e for e in evs}
        self.assertEqual(sorted(titles), ["Fleet Week at PIER 39", "Fleet Week: Air Show", "Fleet Week: Ship Tours"])
        self.assertEqual(titles["Fleet Week: Air Show"].tags, ["featured"])
        self.assertIn("featured", titles["Fleet Week at PIER 39"].tags)     # a day post about the featured event

    def test_fleet_week_official_schedule(self):
        from ingest.adapters import fleetweek
        page = """<div class="pp-content-post pp-content-carousel-post"><h3><a href="https://fleetweeksf.org/air-show/">Air Show</a></h3>
          <div class="pp-content-grid-post-excerpt"><div><strong>October 9 &#8211; 11<br/> 12:00 PM &#8211; 4:00 PM</strong></div>
          <div><strong>Marina Green</strong></div><p>World-class aviation.</p></div></div>
          <div class="pp-content-post pp-content-carousel-post"><h3><a href="https://fleetweeksf.org/events/ship-tours/">Ship Tours</a></h3>
          <div class="pp-content-grid-post-excerpt"><div><strong>Tuesday 10/6-Monday 10/12<br/>10:00 AM &#8211; 4:00 PM</strong></div>
          <div><strong>Piers 27 &amp; 35</strong></div><p>Climb aboard.</p></div></div>"""
        evs = fleetweek.parse(BeautifulSoup(page, "lxml"), dt.date(2026, 10, 1))
        shows = [e for e in evs if "Air Show" in e.title]
        self.assertEqual([e.start for e in shows], ["2026-10-09T12:00-07:00", "2026-10-10T12:00-07:00", "2026-10-11T12:00-07:00"])
        self.assertEqual((shows[0].title, shows[0].venue, shows[0].end), ("Fleet Week Air Show", "Marina Green", "2026-10-09T16:00-07:00"))
        tours = [e for e in evs if "Ship Tours" in e.title]
        self.assertEqual([(e.start, e.end) for e in tours], [("2026-10-06T10:00-07:00", "2026-10-12T16:00-07:00")])   # a week: one run
        r = Scoring.s.score(shows[0].to_dict())
        self.assertIn("traditions", r["tags"])
        self.assertGreater(r["score"], 4)

    def test_neck_of_the_woods(self):
        from ingest.adapters import neckofthewoods
        sec = lambda name, date, time, price, btn: f"""<div class="tw-section"><span class="tw-event-date">{date}</span>
          <div class="tw-name"><a href="https://www.neckofthewoodssf.com/tm-event/{name.lower().replace(' ', '-')}/">{name}</a></div>
          <span class="tw-event-time">Show: {time}</span><span class="tw-price">{price}</span>
          <a class="tw-buy-tix-btn" href="https://www.ticketweb.com/event/x">{btn}</a></div>"""
        page = '<div class="tw-plugin-upcoming-event-list">' + sec("Karaoke Tuesday", "Tue, Oct 27", "9:00 pm", "$0.00", "Buy Tickets") + \
            sec("Big Show", "Sat, Oct 31", "8:00 pm", "$24.66", "Sold Out") + "</div>"
        evs = neckofthewoods.parse(BeautifulSoup(page, "lxml"), dt.date(2026, 10, 11))
        self.assertEqual([(e.title, e.start, e.price, e.sold_out) for e in evs],
                         [("Karaoke Tuesday", "2026-10-27T21:00-07:00", "free", False), ("Big Show", "2026-10-31T20:00-07:00", "$24.66", True)])
        self.assertEqual(evs[0].address, "406 Clement St")

    def test_four_star_films_and_tastes(self):
        from ingest.adapters import fourstar
        film = lambda code, title, rating, desc, day, times: f"""<div class="film" id="{code}"><h3 class="title">{title}</h3>
          <p><span class="censor">{rating}</span></p><p class="film-desc">{desc}</p><div class="sessions"><div class="date-container">
          <h4 class="date">{day}</h4><ul class="session-times">{''.join(f'<li><a href="/purchase/1"><time>{t}</time></a></li>' for t in times)}</ul></div></div></div>"""
        page = '<div id="sessionsByFilmConent">' + \
            film("A", "Wallace &amp; Gromit: The Curse of the Were-Rabbit", "G", "A cozy claymation comedy.", "Saturday 24, October", ["12:30 PM", "5:15 PM"]) + \
            film("B", "Evil Dead II", "R", "A gory horror sequel.", "Saturday 24, October", ["7:30 PM"]) + \
            film("C", "LIVE MUSIC: The Wildwoods", "", "Folk trio.", "Wednesday 28, October", ["8:00 PM"]) + "</div>"
        evs = {e.title: e for e in fourstar.parse(BeautifulSoup(page, "lxml"), dt.date(2026, 10, 11))}
        wg = evs["Wallace & Gromit: The Curse of the Were-Rabbit"]
        self.assertEqual((wg.start, wg.venue, wg.tags), ("2026-10-24T12:30-07:00", "4 Star Theater", ["film"]))
        self.assertTrue(wg.description.startswith("Also at 5:15 PM."))
        good, gory = (Scoring.s.score(evs[t].to_dict()) for t in ("Wallace & Gromit: The Curse of the Were-Rabbit", "Evil Dead II"))
        self.assertGreater(good["score"], 2)
        self.assertLess(gory["score"], 0)
        self.assertNotIn("theatre", good["tags"])            # "4 Star Theater" is a cinema
        self.assertNotIn("theatre", Scoring.s.score(evs["LIVE MUSIC: The Wildwoods"].to_dict())["tags"])

    def test_camp_and_featured_lift_terror_vault(self):
        tv = Scoring.s.score(ev("SF’s “Terror Vault” 1874 Halloween Haunt (2026)", tags=["featured", "halloween"],
                                description="San Francisco’s premiere haunted attraction returns"))
        self.assertIn("camp", tv["tags"])
        self.assertIn("featured", tv["tags"])
        self.assertGreater(tv["score"], 5)

    def test_drink_minimum_is_not_free(self):
        plain = Scoring.s.score(ev("Crazy Funny Asians Comedy Showcase", price="free"))
        minimum = Scoring.s.score(ev("Crazy Funny Asians Comedy Showcase", price="free",
                                     description="There is a two-drink minimum to help support our local bar scene."))
        self.assertGreater(plain["score"] - minimum["score"], 2)

    def test_life_skills_hidden_by_title_only(self):
        self.assertIsNone(Scoring.s.score(ev("Stressless Taxes for Artists, Creatives, and Freelancers")))
        self.assertIsNone(Scoring.s.score(ev("Resume Help for Job Seekers")))
        self.assertIsNotNone(Scoring.s.score(ev("Shut Up & Write!", description="we resume writing after a short break")))


class NewSources(unittest.TestCase):
    def test_comedy_clubs(self):
        from ingest.adapters import comedyclubs
        show = """<script type="application/ld+json">[{"@context":"https://schema.org","@type":"ComedyEvent","name":"Gus Heagerty",
          "startDate":"2026-10-20T19:30:00-07:00","url":"https://www.ticketmaster.com/gus-heagerty/event/1C00",
          "location":{"@type":"Place","name":"Cobb's Comedy Club","address":{"@type":"PostalAddress","streetAddress":"915 Columbus Avenue","addressLocality":"San Francisco"}}}]</script>"""
        f = FakeFetcher({"https://www.cobbscomedy.com/": show, "https://www.punchlinecomedyclub.com/": "<p></p>"})
        evs = comedyclubs.fetch(f, dt.datetime(2026, 10, 10, tzinfo=TZ), dt.datetime(2026, 12, 10, tzinfo=TZ))
        self.assertEqual([(e.title, e.venue) for e in evs], [("Gus Heagerty", "Cobb's Comedy Club")])
        self.assertIn("comedy", evs[0].tags)
        r = Scoring.s.score(evs[0].to_dict())
        self.assertEqual(r["followed"], "Gus Heagerty")
    def test_broadwaysf_run_dates(self):
        from ingest.adapters import broadwaysf
        html = r'x\"title\":\"Oh, Mary!\",\"dates\":\"Tue, Oct 13 - Sun, Nov 1, 2026\",\"infoBarText\"'
        self.assertEqual(broadwaysf.runs(html), {"oh, mary!": (dt.date(2026, 10, 13), dt.date(2026, 11, 1))})

    def test_partiful_offer(self):
        from ingest.adapters import partiful
        page = lambda avail, price=20: BeautifulSoup('<script type="application/ld+json">{"@type":"Event","name":"x","startDate":"2026-10-11T21:00:00.000Z",'
                                     '"offers":[{"@type":"Offer","price":%s,"availability":"https://schema.org/%s"}]}</script>' % (price, avail), "lxml")
        self.assertEqual(partiful.offer_of(page("InStock")), {"price": "$20", "sold_out": False})
        self.assertEqual(partiful.offer_of(page("SoldOut")), {"price": "$20", "sold_out": True})
        self.assertEqual(partiful.offer_of(page("InStock", 0))["price"], "free")
        capped = BeautifulSoup(str(page("InStock")) + '<script id="__NEXT_DATA__" type="application/json">'
                               '{"props":{"pageProps":{"event":{"id":"X18","isCapped":true,"atCapacity":true,"remainingCapacity":0},'
                               '"similar":[{"id":"Y9","atCapacity":false}]}}}</script>', "lxml")
        self.assertTrue(partiful.offer_of(capped, "X18")["sold_out"])
        self.assertFalse(partiful.offer_of(capped, "Y9")["sold_out"])
    def test_filoli_event_pages(self):
        from ingest.adapters import filoli
        listing = """<a href="/whats-on/events/nightfall/">Nightfall</a> <a href="/whats-on/events/?category=tours">Tours</a>
          <a href="/whats-on/events/nightfall/">Find out more</a> <a href="/private-events/">Private</a>"""
        page = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"Event","name":"Nightfall",
          "startDate":"2026-09-26T17:30:00-07:00","endDate":"2026-11-01T22:00:00-08:00",
          "location":{"@type":"Place","address":{"@type":"PostalAddress","streetAddress":"86 Ca\u00f1ada Rd","addressLocality":"Woodside, CA"}}}</script>"""
        f = FakeFetcher({filoli.LIST + "?p=1": listing, filoli.LIST + "?p=2": "<p>none</p>", filoli.BASE + "/whats-on/events/nightfall/": page})
        evs = filoli.fetch(f, dt.datetime(2026, 10, 10, tzinfo=TZ), dt.datetime(2026, 12, 10, tzinfo=TZ))
        self.assertEqual([e.title for e in evs], ["Nightfall"])
        self.assertEqual(evs[0].city, "Woodside")
        self.assertEqual(evs[0].source_url, "https://filoli.org/whats-on/events/nightfall/")
        self.assertTrue(area.in_area(evs[0].to_dict()))
        self.assertFalse(evs[0].all_day)
        day = page.replace("2026-09-26T17:30:00-07:00", "2026-10-17").replace("2026-11-01T22:00:00-08:00", "2026-10-17")
        f.pages[filoli.BASE + "/whats-on/events/nightfall/"] = day
        self.assertTrue(filoli.fetch(f, dt.datetime(2026, 10, 10, tzinfo=TZ), dt.datetime(2026, 12, 10, tzinfo=TZ))[0].all_day)

    def test_sfpl_presidio(self):
        from ingest.adapters import sfpl
        page = """<div class="view-content">
          <div class="views-row"><article class="event"><div class="event__date"><span>Wednesday, 10/14/2026, 6:00 - 7:30</span></div>
            <h2 class="event__title"><a href="/events/2026/10/14/author-talk-new-memoir"><span>Author: A New Memoir</span></a></h2>
            <div class="event__audience"><div class="field__item"><a>Adults</a></div></div>
            <div class="event__location"><div class="field__item">Presidio</div></div></article></div>
          <div class="views-row"><article class="event"><div class="event__date"><span>Thursday, 10/15/2026, 10:30 - 11:00</span></div>
            <h2 class="event__title"><a href="/events/2026/10/15/storytime"><span>Storytime: For Toddlers</span></a></h2>
            <div class="event__location"><div class="field__item">Presidio</div></div></article></div>
          <div class="views-row"><article class="event"><div class="event__date"><span>Thursday, 10/15/2026, 2:00 - 3:00</span></div>
            <h2 class="event__title"><a href="/events/2026/10/15/canceled-social"><span>Canceled: Social Hour</span></a></h2>
            <div class="event__location"><div class="field__item">Presidio</div></div></article></div></div>"""
        f = FakeFetcher({"https://sfpl.org/events?field_event_location_target_id=59&page=0": page,
                         "https://sfpl.org/events": "<html></html>"})
        evs = sfpl.fetch(f, None, None)
        self.assertEqual(len(evs), 2)
        e = evs[0]
        self.assertTrue(evs[1].start.startswith("2026-10-15T10:30"))   # morning stays morning
        self.assertEqual(e.title, "Author: A New Memoir")
        self.assertTrue(e.start.startswith("2026-10-14T18:00"))
        self.assertTrue(e.end.startswith("2026-10-14T19:30"))
        self.assertEqual(e.venue, "Presidio Branch Library")

    def test_jccsf_api(self):
        from ingest.adapters import jccsf
        api = {"events": [{"id": 7, "title": "Comedy &amp; Kugel", "url": "https://www.jccsf.org/event/comedy-kugel/",
                           "utc_start_date": "2026-10-22 02:30:00", "utc_end_date": "2026-10-22 04:00:00",
                           "description": "<p>Stand-up night</p>", "cost": "$25",
                           "venue": {"venue": "JCCSF", "address": "3200 California St", "city": "San Francisco",
                                     "geo_lat": "37.7869", "geo_lng": "-122.4467"}}], "total_pages": 1}
        f = FakeFetcher({jccsf.API: api})
        start = dt.datetime(2026, 10, 1, tzinfo=TZ)
        evs = jccsf.fetch(f, start, start + dt.timedelta(days=60))
        self.assertEqual(len(evs), 1)
        e = evs[0]
        self.assertEqual(e.title, "Comedy & Kugel")
        self.assertTrue(e.start.startswith("2026-10-21T19:30"))   # UTC -> Pacific
        self.assertEqual((e.lat, e.lng), (37.7869, -122.4467))
        self.assertEqual(e.price, "$25")
        api["events"][0]["cost"] = "Free"     # their feed's default, even for ticketed talks
        page = '<div class="single-event-hero__price">$20 - $42 </div>'
        f = FakeFetcher({jccsf.API: api, "https://www.jccsf.org/event/comedy-kugel/": page})
        self.assertEqual(jccsf.fetch(f, start, start + dt.timedelta(days=60))[0].price, "$20-$42")

    def test_geo_and_richmond_district(self):
        from ingest.core import geo_of
        self.assertEqual(geo_of({"location": {"latitude": "37.78", "longitude": "-122.41"}}), (37.78, -122.41))
        self.assertEqual(geo_of({"lat": 40.7, "lng": -74.0}), (None, None))       # not the Bay Area
        self.assertTrue(area.in_area({"city": "San Francisco", "title": "Book club, Richmond District edition"}))
        self.assertFalse(area.in_area({"city": "", "title": "Richmond Art Walk", "source": "funcheap"}))


class Places(unittest.TestCase):
    def test_locate_reads_event_pages(self):
        import tempfile
        from ingest import geocode, place

        def page(loc):
            node = {"@context": "https://schema.org", "@type": "Event", "name": "x", "startDate": "2026-10-10T19:00", "location": loc}
            return f'<script type="application/ld+json">{json.dumps(node)}</script>'
        pages = {
            "https://sf.funcheap.com/ghost/": page({"@type": "Place", "name": "Magnolia's Brewery (IN FRONT)", "address": "1398 Haight Street, San Francisco"}),
            "https://sf.funcheap.com/mix/": page({"@type": "Place", "name": "Orinda Theatre Square", "address": "2 Orinda Theatre Sq, Orinda, CA 94563"}),
            "https://partiful.com/e/abc": page({"@type": "Place", "name": "Thee Stork Club", "address": {
                "@type": "PostalAddress", "streetAddress": "2330 Telegraph Ave", "addressLocality": "Oakland"}}),
        }
        evs = [{"source": "funcheap", "title": "Ghost Hunt (Haight-Ashbury)", "source_url": "https://sf.funcheap.com/ghost/", "venue": ""},
               {"source": "funcheap", "title": "Art of Mixology", "source_url": "https://sf.funcheap.com/mix/", "venue": ""},
               {"source": "partiful", "title": "FUN FUN CLUB", "source_url": "https://partiful.com/e/abc", "venue": ""}]
        with tempfile.TemporaryDirectory() as d:
            place.CACHE = pathlib.Path(d) / "places.json"
            stats = place.locate(evs, FakeFetcher(pages))
            self.assertEqual(stats["placed"], 3)
            # a second run reads nothing new
            self.assertEqual(place.locate(evs, FakeFetcher({}))["pages_read"], 0)
        self.assertEqual(evs[0]["address"], "1398 Haight Street, San Francisco")
        self.assertEqual(evs[0]["city"], "San Francisco")
        self.assertEqual(evs[1]["city"], "Orinda")
        self.assertEqual(evs[2]["city"], "Oakland")
        self.assertEqual([area.in_area(e) for e in evs], [True, False, False])
        self.assertEqual(geocode.queries(evs[0])[0], "1398 Haight Street, San Francisco")
        self.assertIn("Haight-Ashbury, San Francisco",
                      geocode.queries({"title": "Ghost Hunt (Haight-Ashbury)", "venue": ""}))
        self.assertEqual(geocode.queries({"title": "Comedy (7p + 9p)", "venue": ""}), [])
        self.assertFalse(geocode.fresh(None))
        self.assertTrue(geocode.fresh([37.7, -122.4]))


class Distance(unittest.TestCase):
    def test_messy_addresses_and_weekend_trips(self):
        from ingest import geocode
        q = lambda a, city="San Francisco": geocode.queries({"address": a, "city": city, "venue": "", "title": ""})
        self.assertEqual(q("3201 Ulloa St, San Francisco, CA 94116, USA, San Francisco, CA San Francisco"),
                         ["3201 Ulloa St, San Francisco"])
        self.assertEqual(q("2965 Mission St (btwn 25th and 26th), San Francisco, CA")[0], "2965 Mission St, San Francisco")
        self.assertEqual(q("288 Golf Course Dr W, Rohnert Park, CA", ""), ["288 Golf Course Dr W, Rohnert Park"])
        self.assertEqual(q("San Francisco, CA"), [])
        sat, wed = "2026-10-17T11:00:00-07:00", "2026-10-14T19:00:00-07:00"
        fair = lambda start: {"title": "Harvest Fair", "city": "Santa Rosa", "source": "funcheap", "start": start}
        self.assertTrue(area.keep(fair(sat)))
        self.assertTrue(fair(sat) | {"trip": True})
        self.assertFalse(area.keep(fair(wed)))
        show = {"title": "Audrey Hobert", "city": "Oakland", "source": "dice", "start": wed}
        self.assertFalse(area.keep(dict(show)))
        self.assertTrue(area.keep(dict(show), fan=lambda e: "Hobert" in e["title"]))
        self.assertFalse(area.keep({"title": "Talk", "city": "Online", "source": "luma", "start": sat}))
        self.assertFalse(area.keep({"title": "Expo", "city": "Sacramento", "source": "luma", "start": sat}))
        self.assertTrue(area.keep({"title": "Comedy", "city": "San Francisco", "source": "luma", "start": wed}))


class Weather(unittest.TestCase):
    def test_forecast_rows_by_area(self):
        from ingest import weather

        class Resp:
            def raise_for_status(self): pass
            def json(self):
                row = lambda sun: {"daily": {"time": ["2026-10-17"], "sunshine_duration": [sun], "daylight_duration": [40000],
                                             "temperature_2m_max": [71.4], "precipitation_probability_max": [5], "weather_code": [1]}}
                return [row(8000), row(36000), row(30000), row(32000), row(38000)]

        class Session:
            def get(self, url, **kw):
                self.params = kw["params"]
                return Resp()

        s = Session()
        out = weather.forecast(s)
        self.assertEqual(s.params["forecast_days"], 16)
        day = out["days"]["2026-10-17"]
        self.assertEqual(day["sf"]["sun"], 0.2)
        self.assertEqual(day["marin"]["sun"], 0.9)
        self.assertEqual(day["marin"]["hi"], 71)
