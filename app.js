// About Town: reads events.json (written by the daily job) and keeps all of
// David's choices, home spot and learned taste on the phone (localStorage).

const TZ = 'America/Los_Angeles';
const STORE = 'bay-events-v1';
const LEARN = { added: 0.6, maybe: 0.25, not: -0.5, shared: 0.3 };
const INTEREST_LEVELS = { 2: 1.5, 1: 0, 0: -1.5 };  // love / like / not into
const DOT_MIN = 2.5;        // a day gets a dot for each kind of event scoring at least this
const DAY_SHOW = 6;         // events listed per day before "show more"
const RADIUS = { home: 15, near: 10 };  // miles

// the header color follows the season
const SEASONS = [
  { bg: '#9DB4CF', ink: '#2B2F3D', em: '#F4F8FC', sub: '#3A4558' },  // Jan
  { bg: '#D98A9A', ink: '#3D2B26', em: '#FFF1F3', sub: '#5A2C35' },  // Feb
  { bg: '#A8C48C', ink: '#2E3A22', em: '#F7FBEF', sub: '#3F5530' },  // Mar
  { bg: '#EBAEC0', ink: '#3D2B26', em: '#FFF4F7', sub: '#6A3442' },  // Apr
  { bg: '#EFC75E', ink: '#3D2B26', em: '#FFF8E2', sub: '#5E4710' },  // May
  { bg: '#F2A760', ink: '#3D2B26', em: '#FFF2E2', sub: '#5A3420' },  // Jun
  { bg: '#E5745F', ink: '#3D1F1A', em: '#FFEDE6', sub: '#5A2318' },  // Jul
  { bg: '#E9B05A', ink: '#3D2B26', em: '#FFF5E3', sub: '#5A3D14' },  // Aug
  { bg: '#D4A440', ink: '#3D2B26', em: '#FFF6DE', sub: '#574012' },  // Sep
  { bg: '#E9874B', ink: '#3D2B26', em: '#FFF1DE', sub: '#5A3424' },  // Oct: pumpkin
  { bg: '#A9502F', ink: '#FFF1E6', em: '#F6C99B', sub: '#F3D9C8' },  // Nov: rust
  { bg: '#3F6B4E', ink: '#FBF5EC', em: '#F2C6C2', sub: '#D6E3D6' },  // Dec: pine
];

// one pastel per kind of event
const COLOR = { animals: 'sage', fairs: 'butter', vintage: 'peach', music: 'rose', dance: 'lav', comedy: 'butter', musical_theatre: 'rose', theatre: 'rose', singing: 'rose', art: 'sage', museums: 'sage', craft: 'peach', weird: 'peach', reading: 'robin', writing: 'robin', discourse: 'robin', meditation: 'lav', spirituality: 'lav', queer: 'lav' };
const SHORT = { animals: 'Animals', fairs: 'Fairs', vintage: 'Sales', music: 'Concerts', dance: 'Dancing', comedy: 'Comedy', musical_theatre: 'Musicals', theatre: 'Theatre', singing: 'Singing', art: 'Art', museums: 'Museums', craft: 'Craft', weird: 'Weird', reading: 'Books', writing: 'Writing', discourse: 'Talks', meditation: 'Meditation', spirituality: 'Spiritual', queer: 'Queer' };
const colorOf = (ev) => COLOR[(ev.tags || []).find((t) => COLOR[t])] || 'peach';

const PENINSULA = /\b(palo alto|menlo park|redwood city|mountain view|los altos|stanford|san carlos|belmont|atherton|portola valley|woodside|half moon bay|sunnyvale|foster city|san mateo|burlingame|millbrae|cupertino)\b/i;
const SHOW = /\b(comed\w*|stand-?up|improv|show|tour|live|concert|perform\w*|musical|theat\w*|cabaret|sketch|open mic|special|taping|podcast)\b/i;

let data = { events: [], sources: [] };
let profile = null;
let weather = null;   // weather.json: the 16-day forecast for SF and the sunny escapes
let follow = null;
let tab = 'cal';
let monthOffset = 0;
let selDay = null;
let nearPos = null;
let expanded = new Set();

// ------------------------------------------------------------------ state

const blank = () => ({
  status: {},          // id -> added | maybe | not | shared
  tagW: {},            // learned tag weights
  notCount: {},        // tag -> times skipped
  addCount: {},        // tag -> times added
  interests: {},       // interest key -> level 0/1/2
  people: [],          // names typed in
  igHandles: [],       // from the Instagram export
  igConfirmed: {},     // handle -> real name ("patreegs" -> "Pat Regan")
  igRejected: [],      // "handle|name" pairs answered no
  blockedPeople: [],   // "not this person"
  authorsExtra: [],    // from a Goodreads CSV imported on the phone
  hiddenTags: [],
  dismissedNudges: [],
  lastReview: null,
  decidedAt: {},
  home: null,          // { label, lat, lng } set on this phone
  where: 'home',
  homeTipOff: false,
  swipeTipOff: false,
});
let S = load();

function load() {
  try { return Object.assign(blank(), JSON.parse(localStorage.getItem(STORE) || '{}')); }
  catch { return blank(); }
}
function save() {
  try { localStorage.setItem(STORE, JSON.stringify(S)); } catch { /* private mode */ }
}

// ------------------------------------------------------------------ helpers

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// Intl formatters are slow to build, so each one is made once
const fmtCache = new Map();
const formatter = (o) => {
  const k = JSON.stringify(o);
  if (!fmtCache.has(k)) fmtCache.set(k, new Intl.DateTimeFormat('en-US', { timeZone: TZ, ...o }));
  return fmtCache.get(k);
};
const fmt = (d, o) => formatter(o).format(d);
const PARTS = { year: 'numeric', month: 'numeric', day: 'numeric', weekday: 'short', hour: 'numeric', hourCycle: 'h23' };
const parts = (d) => Object.fromEntries(formatter(PARTS).formatToParts(d).map((p) => [p.type, p.value]));
const keyMemo = new Map();
const dayKey = (d) => {
  const t = d.getTime();
  let k = keyMemo.get(t);
  if (!k) {
    const p = parts(d);
    k = `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`;
    if (keyMemo.size > 5000) keyMemo.clear();
    keyMemo.set(t, k);
  }
  return k;
};
const norm = (s) => (s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[.'’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
let todayMemo = { at: 0, d: null };
const today0 = () => {
  if (Date.now() - todayMemo.at > 60e3) {
    const k = dayKey(new Date());
    todayMemo = { at: Date.now(), d: new Date(`${k}T00:00:00${offsetFor(k)}`) };
  }
  return todayMemo.d;
};
const atNoon = (k) => new Date(`${k}T12:00:00${offsetFor(k)}`);
const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const offsetMemo = new Map();
function offsetFor(k) {
  if (!offsetMemo.has(k)) offsetMemo.set(k, offsetOf(k));
  return offsetMemo.get(k);
}
function offsetOf(k) {
  // Pacific offset for a local date (handles DST)
  const d = new Date(`${k}T12:00:00Z`);
  const tz = formatter({ timeZoneName: 'shortOffset' }).formatToParts(d).find((p) => p.type === 'timeZoneName').value;
  const m = tz.match(/GMT([+-]\d+)/);
  const h = m ? parseInt(m[1], 10) : -8;
  return `${h < 0 ? '-' : '+'}${String(Math.abs(h)).padStart(2, '0')}:00`;
}

const clock = (ev) => fmt(new Date(ev.start), { hour: 'numeric', minute: '2-digit' }).replace(':00', '');
function when(ev) {
  const s = new Date(ev.start);
  const day = fmt(s, { weekday: 'short', month: 'short', day: 'numeric' });
  return ev.all_day ? day : `${day} · ${clock(ev).replace(' ', '').toLowerCase()}`;
}
function runText(ev) {
  if (!ev.end) return '';
  const s = new Date(ev.start), e = new Date(ev.end);
  if (e - s < 36 * 3600e3) return '';
  const md = (d) => fmt(d, { month: 'short', day: 'numeric' });
  // opening day: show the whole run; once it's on, just when it closes
  return s >= today0() ? `${md(s)} – ${md(e)}` : `through ${md(e)}`;
}
function displayDate(ev) {
  // a run that started already shows up today
  const s = new Date(ev.start);
  const t = today0();
  return s < t && ev.end && new Date(ev.end) >= t ? t : s;
}
const linkOf = (ev) => ev.ticket_url || ev.source_url;
const sourceLabel = (id) => (data.sources.find((s) => s.name === id) || {}).label || id;

function toast(msg, undo) {
  const el = $('#toast');
  el.innerHTML = `<span>${esc(msg)}</span>${undo ? '<button id="undo">Undo</button>' : ''}`;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 3200);
  if (undo) $('#undo').onclick = () => { undo(); el.hidden = true; };
}

// ------------------------------------------------------------------ where

const homePos = () => S.home || profile?.home || { label: 'San Francisco', lat: 37.7749, lng: -122.4194 };
const origin = () => (S.where === 'near' && nearPos ? nearPos : homePos());

function miles(a, b) {
  const R = 3958.8, rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
const distOf = (ev) => (ev.lat != null && ev.lng != null ? miles(origin(), ev) : null);
function distText(mi) {
  if (mi == null) return '';
  if (mi < 0.95) return `${mi.toFixed(1)} mi · ${Math.max(2, Math.round(mi * 20))} min walk`;
  return mi < 10 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`;
}
const shortDist = (mi) => (mi < 0.95 ? `${Math.max(2, Math.round(mi * 20))} min walk` : mi < 10 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`);
const fromWhere = () => (S.where === 'near' && nearPos ? 'from you' : 'from home');
const TRIP_MILES = 90;   // Friday evening and weekend day trips (Sonoma, the East Bay), and shows by people you follow
const slotMemo = new Map();
function weekendSlot(ev) {
  if (!slotMemo.has(ev.id)) slotMemo.set(ev.id, slotOf(ev));
  return slotMemo.get(ev.id);
}
function slotOf(ev) {
  if (ev.end && new Date(ev.end) - new Date(ev.start) > 36 * 3600e3) return true;   // a run: pick a weekend day
  const p = parts(new Date(ev.start));
  return p.weekday === 'Sat' || p.weekday === 'Sun' || (p.weekday === 'Fri' && (Number(p.hour) >= 17 || ev.all_day));
}
function inRange(ev) {
  const d = distOf(ev);
  const trip = S.where === 'home' && (weekendSlot(ev) || !!followInfo(ev));
  if (d != null) return d <= (RADIUS[S.where] || 15) || (trip && d <= TRIP_MILES);
  if (ev.trip) return trip;
  // no map spot: go by the city name
  const south = (o) => o.lat < 37.6;
  return south(origin()) === PENINSULA.test(`${ev.city || ''} ${ev.venue || ''}`);
}

function findMe() {
  if (!navigator.geolocation) { toast("This phone can't share its location"); return; }
  $('#subline').textContent = 'Finding you…';
  navigator.geolocation.getCurrentPosition(
    (p) => { nearPos = { label: 'you', lat: p.coords.latitude, lng: p.coords.longitude }; render(); },
    () => { S.where = 'home'; save(); render(); toast('Location is off, so distances are from home'); },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
  );
}

async function setHome(address) {
  const q = new URLSearchParams({ format: 'json', limit: '1', q: address, countrycodes: 'us' });
  const r = await fetch(`https://nominatim.openstreetmap.org/search?${q}`, { headers: { Accept: 'application/json' } });
  const [hit] = await r.json();
  if (!hit) throw new Error("couldn't find that address");
  S.home = { label: address, lat: Number(hit.lat), lng: Number(hit.lon) };
  save();
}

// ------------------------------------------------------------------ taste

let followIndex = null;
function buildFollowIndex() {
  const list = [];
  const add = (name, kind) => { if (norm(name).length >= 4) list.push({ name, kind }); };
  if (follow) {
    for (const n of follow.authors_favorite || []) add(n, 'author');
    for (const n of follow.authors_new_books || []) add(n, 'author');
    for (const n of follow.performers || []) add(n, 'performer');
  }
  for (const n of S.people) add(n, 'you');
  for (const n of S.authorsExtra) add(n, 'author');
  for (const n of Object.values(S.igConfirmed)) add(n, 'instagram');
  // "gus.heagerty" and "cat_cohen" spell out a name
  const handles = S.igHandles.map((h) => h.toLowerCase().replace(/^@/, ''));
  for (const h of handles) {
    const bits = h.split(/[._]+/).filter(Boolean);
    if (bits.length >= 2 && bits.length <= 3 && bits.every((b) => /^[a-z]{2,}$/.test(b))) add(bits.join(' '), 'instagram');
  }
  const blocked = new Set(S.blockedPeople.map(norm));
  followIndex = list.filter((f) => !blocked.has(norm(f.name)))
    .map((f, order) => ({ ...f, order, re: new RegExp(`(?<![a-z0-9])${reEsc(norm(f.name))}(?![a-z0-9])`) }));
  // "John Mulaney" in a listing matches the handle @johnmulaney
  followIndex.joined = new Set(handles.map((h) => h.replace(/[^a-z]/g, '')).filter((x) => x.length >= 8));
  followIndex.raw = new Set(handles);
  followIndex.bare = handles.map((h) => [h, h.replace(/[^a-z]/g, '')]).filter(([, b]) => b.length >= 5);
  followIndex.blocked = blocked;
  // look names up by their first word, so each event only tests the few names it could hold
  followIndex.byFirst = new Map();
  for (const f of followIndex) {
    const k = norm(f.name).split(' ')[0];
    if (!followIndex.byFirst.has(k)) followIndex.byFirst.set(k, []);
    followIndex.byFirst.get(k).push(f);
  }
  followMemo = new Map();
  scoreMemo = new Map();
  earlyMemo = new Map();
}
let followMemo = new Map();   // event id -> followInfo answer (reset when the follow list changes)
let scoreMemo = new Map();    // event id -> personalScore (reset on every render)

const isShow = (ev) => ['comedy', 'theatre', 'musical_theatre', 'singing'].some((t) => (ev.tags || []).includes(t)) || SHOW.test(ev.title);
const namesIn = (text) => [...new Set(text.match(/\b[A-Z][a-zA-Z'’-]+(?:\s+[A-Z][a-zA-Z'’-]+){1,2}\b/g) || [])];

function followInfo(ev) {
  if (!followIndex) buildFollowIndex();
  if (followMemo.has(ev.id)) return followMemo.get(ev.id);
  const f = findFollow(ev);
  followMemo.set(ev.id, f);
  return f;
}

function findFollow(ev) {
  if (ev.followed && !followIndex.blocked.has(norm(ev.followed))) {
    return { name: ev.followed, kind: ev.followed_kind === 'performer' ? 'performer' : 'author' };
  }
  const text = norm(`${ev.title} ${ev.description} ${(ev.people || []).join(' ')}`);
  const show = isShow(ev);
  const words = new Set(text.split(' '));
  let best = null, bestAt = Infinity;
  for (const w of words) {
    for (const f of followIndex.byFirst.get(w) || []) {
      if (f.kind === 'instagram' && !show) continue;   // friends rarely headline; performers do
      const at = f.order;
      if (at < bestAt && f.re.test(text)) { best = f; bestAt = at; }
    }
  }
  if (best) return best;
  if (!show) return null;
  const raw = `${ev.title} ${ev.description}`;
  for (const m of raw.matchAll(/@([A-Za-z0-9._]{3,30})/g)) if (followIndex.raw.has(m[1].toLowerCase())) return { name: '@' + m[1], kind: 'instagram' };
  for (const n of namesIn(raw)) {
    if (followIndex.joined.has(norm(n).replace(/ /g, '')) && !followIndex.blocked.has(norm(n))) return { name: n, kind: 'instagram' };
  }
  return null;
}

// usernames that might be a performer named in a listing ("patreegs" ~ "Pat Regan")
function igSuggestions() {
  if (!followIndex) buildFollowIndex();
  if (!followIndex.bare.length) return [];
  const known = new Set(Object.keys(S.igConfirmed));
  const out = [], seen = new Set();
  for (const ev of upcomingAll()) {
    if (!isShow(ev) || followInfo(ev)) continue;
    for (const n of namesIn(`${ev.title} ${ev.description}`)) {
      const w = norm(n).split(' ');
      if (w.length !== 2) continue;
      const [first, last] = w;
      if (first.length < 3 || last.length < 3) continue;
      for (const [h, b] of followIndex.bare) {
        const key = `${h}|${n}`;
        if (known.has(h) || seen.has(key) || S.igRejected.includes(key)) continue;
        const rest = b.slice(first.length);
        if (b.startsWith(first) && rest.length >= 2 && rest.startsWith(last.slice(0, 2)) && b.length <= first.length + last.length + 3) {
          seen.add(key);
          out.push({ handle: h, name: n, ev });
        }
      }
    }
    if (out.length >= 8) break;
  }
  return out;
}

function timeTags(ev) {
  if (ev.all_day) return [];
  const p = parts(new Date(ev.start));
  const h = Number(p.hour);
  const slot = h >= 17 ? 'evening' : h >= 12 ? 'afternoon' : 'morning';
  return [`t:${p.weekday.toLowerCase()}-${slot}`];
}
const learnTags = (ev) => [...(ev.tags || []), ...timeTags(ev), `src:${ev.source}`];

function personalScore(ev) {
  let s = scoreMemo.get(ev.id);
  if (s === undefined) { s = scoreOf(ev); scoreMemo.set(ev.id, s); }
  return s;
}

// How far you'll go depends on the day: a short hop on a weeknight, a day trip on the weekend.
function distPenalty(ev) {
  const mi = distOf(ev);
  if (mi == null) return 0;
  const run = ev.end && new Date(ev.end) - new Date(ev.start) > 36 * 3600e3;   // you pick the day
  const p = parts(new Date(ev.start));
  if (followInfo(ev)) return -Math.min(2, Math.max(0, mi - 5) * 0.04);   // you'd cross the bay for them, any night
  const friNight = !run && p.weekday === 'Fri' && Number(p.hour) >= 17;
  const weekend = weekendSlot(ev);
  if (weekend && !friNight) return -Math.min(2, Math.max(0, mi - 5) * 0.04);
  if (friNight) return -Math.min(4, Math.max(0, mi - 3) * 0.25);
  // a weeknight: walkable or a short ride is fine, across town costs a lot
  return -Math.min(5, Math.max(0, Math.min(mi, 3) - 1.5) * 0.6 + Math.max(0, mi - 3) * 1.0);
}

function scoreOf(ev) {
  let s = (ev.score || 0) + distPenalty(ev) + (sunEscape(ev) ? 1.5 : 0);
  for (const t of learnTags(ev)) s += Math.max(-3, Math.min(3, S.tagW[t] || 0));
  for (const t of ev.tags || []) if (S.interests[t] !== undefined) s += INTEREST_LEVELS[S.interests[t]];
  const f = followInfo(ev);
  if (ev.followed && !f) s -= 6;                 // "not this person"
  if (f && !ev.followed) s += f.kind === 'instagram' ? 5 : 6;
  return s;
}

const isHidden = (ev) => (ev.tags || []).some((t) => S.hiddenTags.includes(t));

function decide(ev, status) {
  const prev = S.status[ev.id];
  if (prev === status) status = null;      // tap again to undo
  // un-learn the previous choice, learn the new one
  for (const t of learnTags(ev)) {
    if (prev) S.tagW[t] = (S.tagW[t] || 0) - LEARN[prev];
    if (status) S.tagW[t] = (S.tagW[t] || 0) + LEARN[status];
    if (status === 'not') S.notCount[t] = (S.notCount[t] || 0) + 1;
    if (prev === 'not') S.notCount[t] = Math.max(0, (S.notCount[t] || 0) - 1);
    if (status === 'added') S.addCount[t] = (S.addCount[t] || 0) + 1;
    if (prev === 'added') S.addCount[t] = Math.max(0, (S.addCount[t] || 0) - 1);
  }
  if (status) { S.status[ev.id] = status; S.decidedAt[ev.id] = Date.now(); }
  else { delete S.status[ev.id]; delete S.decidedAt[ev.id]; }
  save();
  return prev;
}

// ------------------------------------------------------------------ calendar + share

function googleCal(ev) {
  const f = (d) => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const s = new Date(ev.start);
  let e = ev.end ? new Date(ev.end) : new Date(s.getTime() + 2 * 3600e3);
  if (e - s > 12 * 3600e3) e = new Date(s.getTime() + 2 * 3600e3);
  const q = new URLSearchParams({ action: 'TEMPLATE', text: ev.title, dates: `${f(s)}/${f(e)}`, location: [ev.venue, ev.address, ev.city].filter(Boolean).join(', '), details: `${linkOf(ev)}\n\n${ev.why || ''}` });
  return `https://calendar.google.com/calendar/render?${q}`;
}

function icsFor(evs) {
  const local = (d) => { const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(d).map((x) => [x.type, x.value])); return `${p.year}${p.month}${p.day}T${p.hour}${p.minute}${p.second}`; };
  const e = (s) => String(s || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//About Town//EN', 'METHOD:PUBLISH'];
  for (const ev of evs) {
    const s = new Date(ev.start);
    let en = ev.end ? new Date(ev.end) : new Date(s.getTime() + 2 * 3600e3);
    if (en - s > 12 * 3600e3) en = new Date(s.getTime() + 2 * 3600e3);
    lines.push('BEGIN:VEVENT', `UID:${ev.id.replace(/[^a-z0-9]/gi, '')}@bay-events`, `DTSTAMP:${stamp}`);
    if (ev.all_day) { const k = dayKey(s).replace(/-/g, ''); const n = new Date(s.getTime() + 86400e3); lines.push(`DTSTART;VALUE=DATE:${k}`, `DTEND;VALUE=DATE:${dayKey(n).replace(/-/g, '')}`); }
    else lines.push(`DTSTART;TZID=${TZ}:${local(s)}`, `DTEND;TZID=${TZ}:${local(en)}`);
    lines.push(`SUMMARY:${e(ev.title)}`, `LOCATION:${e([ev.venue, ev.city].filter(Boolean).join(', '))}`, `URL:${linkOf(ev)}`, `DESCRIPTION:${e(linkOf(ev))}`, 'END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  return lines.join('\r\n');
}

async function addAllToCalendar() {
  const evs = picks().filter((e) => S.status[e.id] === 'added' && new Date(e.start) >= today0());
  if (!evs.length) return toast('No picks to add yet');
  const file = new File([icsFor(evs)], 'my-picks.ics', { type: 'text/calendar' });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: 'My picks' }); return; } catch (err) { if (err.name === 'AbortError') return; }
  }
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(file), download: 'my-picks.ics' });
  document.body.append(a); a.click(); a.remove();
}

function shareText(ev) {
  const where = ev.venue || ev.city || '';
  return `Want to go? ${ev.title}, ${when(ev).replace(' · ', ', ')}${where ? `, ${where}` : ''}`;
}

async function share(ev) {
  const url = linkOf(ev);
  if (navigator.share) {
    try {
      await navigator.share({ title: ev.title, text: shareText(ev), url });
      if (S.status[ev.id] !== 'added') { for (const t of learnTags(ev)) S.tagW[t] = (S.tagW[t] || 0) + LEARN.shared; save(); }
      return;
    } catch (err) { if (err.name === 'AbortError') return; }
  }
  copyLink(ev);
}
async function copyLink(ev) {
  try { await navigator.clipboard.writeText(`${shareText(ev)} · ${linkOf(ev)}`); toast('Link copied'); }
  catch { prompt('Copy this:', `${shareText(ev)} · ${linkOf(ev)}`); }
}

// ------------------------------------------------------------------ rendering: one event

// Fog: when SF is grey and Marin (or the Peninsula, East Bay, Sonoma) is sunny,
// daytime events there move up. The forecast reaches 16 days out.
const AREA_NAME = { marin: 'in Marin', peninsula: 'on the Peninsula', eastbay: 'in the East Bay', sonoma: 'in Sonoma' };
const OUTDOORS = /outdoor|open[- ]air|garden|park\b|hike|hiking|trail|beach|picnic|farm\b|farms|orchard|vineyard|winery|wine country|fair\b|faire|festival|market|zoo\b|plaza|block party|street|canoe|kayak|paddle|lawn|on the green|pumpkin patch|corn maze/i;
function areaOf(ev) {
  const { lat, lng } = ev;
  if (lat == null) return null;
  if (lat >= 38.1) return lng < -122.2 ? 'sonoma' : null;
  if (lat >= 37.83 && lng < -122.4) return 'marin';
  if (lat < 37.62 && lat > 37.2 && lng < -121.95) return 'peninsula';
  if (lng > -122.33 && lat > 37.6 && lat < 38.05 && lng < -121.9) return 'eastbay';
  return null;
}
const sunMemo = new Map();
function sunEscape(ev) {
  if (!weather) return null;
  if (!sunMemo.has(ev.id)) sunMemo.set(ev.id, sunOf(ev));
  return sunMemo.get(ev.id);
}
function sunOf(ev) {
  const area = areaOf(ev);
  if (!area || !OUTDOORS.test(`${ev.title} ${ev.venue || ''} ${(ev.description || '').slice(0, 400)}`)) return null;   // sun matters outside
  if (ev.end && new Date(ev.end) - new Date(ev.start) > 36 * 3600e3) return null;   // a run: no single day
  if (!ev.all_day && Number(parts(new Date(ev.start)).hour) >= 17) return null;      // after dark, sun doesn't matter
  const day = weather.days[dayKey(new Date(ev.start))];
  const sf = day?.sf, there = day?.[area];
  if (!sf || !there) return null;
  if (sf.sun < 0.45 && there.sun >= 0.7 && (there.rain ?? 0) < 40) return { area, hi: there.hi, sfHi: sf.hi };
  return null;
}
function sunLine(ev) {
  const w = sunEscape(ev);
  if (!w) return '';
  return `☀️ Sunny ${AREA_NAME[w.area]}${w.hi != null ? ` (${w.hi}°)` : ''}, grey in SF`;
}

function starLine(ev) {
  const f = followInfo(ev);
  if (!f) return '';
  const why = { instagram: 'you follow them', author: 'an author you love', performer: 'on your list', you: 'on your list' }[f.kind] || '';
  return `⭐ ${esc(f.name)}${why ? ` · ${why}` : ''}`;
}

function evRow(ev, { showDay = false } = {}) {
  const st = S.status[ev.id];
  const c = colorOf(ev);
  const t = ev.all_day ? 'All<small>DAY</small>' : esc(clock(ev)).replace(/ (AM|PM)/, '<small>$1</small>');
  const mi = distOf(ev);
  const meta = [
    esc(ev.venue || (ev.city && !/san francisco/i.test(ev.city) ? ev.city : '')),
    ev.price ? esc(ev.price === 'free' ? 'Free' : ev.price) : '',
  ].filter(Boolean).join(' · ');
  const labels = (ev.tags || []).filter((x) => SHORT[x]).slice(0, 2)
    .map((x) => `<span style="background:var(--${COLOR[x]});color:var(--${COLOR[x]}-ink)">${SHORT[x]}</span>`);
  if (/thursday evening/i.test(ev.why || '')) labels.push('<span>Thursday night</span>');
  if (mi != null && mi > RADIUS.home) labels.push('<span>Day trip</span>');
  const run = runText(ev);
  if (run) labels.push(`<span>${esc(run)}</span>`);
  const star = starLine(ev);
  return `<article class="ev" data-id="${esc(ev.id)}">
    <div class="side"><div class="chip" style="background:var(--${c});color:var(--${c}-ink)">${t}</div>${mi != null ? `<div class="mi ${mi < 0.95 ? 'walk' : ''}">${esc(shortDist(mi))}</div>` : ''}</div>
    <div class="body" data-open>
      ${showDay ? `<div class="day">${esc(fmt(displayDate(ev), { weekday: 'short', month: 'short', day: 'numeric' }))}</div>` : ''}
      <h3>${esc(ev.title)}</h3>
      <div class="meta">${meta}</div>
      ${star ? `<div class="star">${star}</div>` : ''}
      ${sunEscape(ev) ? `<div class="sun">${esc(sunLine(ev))}</div>` : ''}
      ${labels.length ? `<div class="tags">${labels.join('')}</div>` : ''}
    </div>
    <button class="plus ${st === 'added' ? 'on' : st === 'maybe' ? 'maybe' : ''}" data-act="added" aria-label="${st === 'added' ? 'In your plan' : 'Add to plan'}">${st === 'added' ? '✓' : st === 'maybe' ? '?' : '+'}</button>
  </article>`;
}

function byId(id) { return data.events.find((e) => e.id === id); }

function onEventClick(e) {
  const row = e.target.closest('[data-id]');
  if (!row) return;
  const ev = byId(row.dataset.id);
  if (!ev) return;
  const btn = e.target.closest('[data-act]');
  if (btn) {
    const act = btn.dataset.act;
    if (act === 'share') return share(ev);
    if (act === 'block') { const f = followInfo(ev); if (f) { S.blockedPeople.push(f.name); save(); buildFollowIndex(); toast(`Okay, ${f.name} isn't who you follow`); } closeSheet(); return render(); }
    const prev = decide(ev, act);
    const now = S.status[ev.id];
    if (now === 'added') toast('In your plan · open it for your calendar');
    if (now === 'not') toast("Hidden. We'll show fewer like this", () => { decide(ev, prev || 'not'); render(); });
    if (btn.closest('.sheet')) closeSheet();
    render();
    const el = document.querySelector(`.ev[data-id="${CSS.escape(ev.id)}"] .plus`);
    if (el && now === 'added') el.classList.add('pop');
    return;
  }
  if (e.target.closest('[data-cal]')) {
    // opening the .ics also counts as a yes
    if (S.status[ev.id] !== 'added') { decide(ev, 'added'); setTimeout(render, 300); }
    return;
  }
  if (e.target.closest('[data-open]')) openSheet(ev);
}

function openSheet(ev) {
  const st = S.status[ev.id];
  const img = ev.image_url ? '<div class="img" hidden></div>' : '';   // shown only once a real photo loads
  const links = [
    `<a href="${esc(ev.source_url)}" target="_blank" rel="noopener">Open on ${esc(sourceLabel(ev.source))} ↗</a>`,
    ev.ticket_url && ev.ticket_url !== ev.source_url ? `<a href="${esc(ev.ticket_url)}" target="_blank" rel="noopener">Tickets / RSVP ↗</a>` : '',
    ev.parent_event ? `<a href="${esc(ev.parent_event.url)}" target="_blank" rel="noopener">Part of ${esc(ev.parent_event.title)} ↗</a>` : '',
    ...(ev.also_on || []).map((a) => `<a href="${esc(a.url)}" target="_blank" rel="noopener">Also on ${esc(sourceLabel(a.source))} ↗</a>`),
    ev.lat != null ? `<a href="https://maps.apple.com/?daddr=${ev.lat},${ev.lng}&q=${encodeURIComponent(ev.venue || ev.title)}" target="_blank" rel="noopener">Directions ↗</a>` : '',
    `<a href="${esc(googleCal(ev))}" target="_blank" rel="noopener">Add to Google Calendar ↗</a>`,
    '<a href="#" data-copy>Copy link</a>',
  ].join('');
  const star = starLine(ev);
  const where = [ev.venue, ev.address !== ev.venue ? ev.address : '', ev.city].filter(Boolean).join(' · ');
  $('#sheet').innerHTML = `<div class="grab"></div><button class="x" data-close aria-label="Close">✕</button>${img}
    <div data-id="${esc(ev.id)}">
      <div class="when">${esc(when(ev))}${runText(ev) ? ` · ${esc(runText(ev))}` : ''}</div>
      <h2>${esc(ev.title)}</h2>
      <div class="where">${esc(where)}${distText(distOf(ev)) ? ` · <b>${esc(distText(distOf(ev)))} ${fromWhere()}</b>` : ''}${ev.price ? ` · ${esc(ev.price === 'free' ? 'Free' : ev.price)}` : ''}</div>
      ${star ? `<div class="star">${star}<a href="#" data-act="block">Not this person</a></div>` : ''}
      ${sunEscape(ev) ? `<div class="sun">${esc(sunLine(ev))}</div>` : ''}
      <div class="acts">
        <button class="btn ${st === 'added' ? 'on' : 'cherry'}" data-act="added">${st === 'added' ? '✓ In your plan' : '＋ Add to plan'}</button>
        <button class="btn maybe ${st === 'maybe' ? 'on' : ''}" data-act="maybe">Maybe</button>
        <button class="btn" data-act="not">Not for me</button>
        <a class="btn" href="${esc(ev.ics)}" data-cal>📅 Calendar</a>
        <button class="btn" data-act="share">Share</button>
      </div>
      ${ev.people && ev.people.length ? `<div class="small">With ${esc(ev.people.slice(0, 6).join(', '))}</div>` : ''}
      <p class="desc">${esc(ev.description || '')}</p>
    </div>
    <div class="links">${links}</div>`;
  const sheet = $('#sheet');
  sheet.style.transform = ''; sheet.scrollTop = 0;
  const box = $('.img', sheet);
  if (box) {
    const im = new Image();
    im.onload = () => {
      // skip broken links and tiny logos rather than showing an empty grey box
      if (im.naturalWidth >= 200 && box.isConnected) { box.style.backgroundImage = `url("${im.src}")`; box.hidden = false; }
    };
    im.src = ev.image_url;
  }
  $('#sheetWrap').hidden = false;
  document.documentElement.classList.add('locked');
  $('#sheet [data-copy]').onclick = (e) => { e.preventDefault(); copyLink(ev); };
  $('#sheet').onclick = (e) => { if (e.target.closest('[data-act],[data-cal]')) { if (e.target.closest('[data-act="block"]')) e.preventDefault(); onEventClick(e); } };
}
function closeSheet() {
  const wrap = $('#sheetWrap');
  if (wrap.hidden || wrap.classList.contains('closing')) return;
  wrap.classList.add('closing');
  $('#sheet').style.transform = '';
  setTimeout(() => { wrap.hidden = true; wrap.classList.remove('closing'); document.documentElement.classList.remove('locked'); }, 220);
}

// drag the sheet down to put it away (from the grab bar, or anywhere once it's scrolled to the top)
function bindSheetDrag() {
  const sheet = $('#sheet'), bg = $('#sheetWrap .sheet-bg');
  let y0 = null, t0 = 0, dy = 0, dragging = false;
  sheet.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return;
    y0 = e.touches[0].clientY; t0 = Date.now(); dy = 0;
    dragging = sheet.scrollTop <= 0 || !!e.target.closest('.grab');
  }, { passive: true });
  sheet.addEventListener('touchmove', (e) => {
    if (y0 == null || !dragging) return;
    dy = e.touches[0].clientY - y0;
    if (dy <= 0) { sheet.style.transform = ''; return; }   // pulling up: let it scroll
    e.preventDefault();
    sheet.style.transition = 'none';
    sheet.style.transform = `translateY(${dy}px)`;
    bg.style.opacity = String(Math.max(0.2, 1 - dy / 400));
  }, { passive: false });
  const end = () => {
    if (y0 == null) return;
    const fast = dy > 40 && dy / Math.max(1, Date.now() - t0) > 0.5;
    sheet.style.transition = ''; bg.style.opacity = '';
    if (dragging && (dy > 110 || fast)) closeSheet();
    else sheet.style.transform = '';
    y0 = null; dy = 0; dragging = false;
  };
  sheet.addEventListener('touchend', end);
  sheet.addEventListener('touchcancel', end);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSheet(); });
}

// ------------------------------------------------------------------ which events

function monthRange(offset) {
  const p = parts(new Date());
  let y = Number(p.year), m = Number(p.month) + offset;
  while (m > 12) { m -= 12; y++; }
  const k = `${y}-${String(m).padStart(2, '0')}-01`;
  const start = new Date(`${k}T00:00:00${offsetFor(k)}`);
  const nm = m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`;
  const end = new Date(`${nm}T00:00:00${offsetFor(nm)}`);
  return { start, end, y, m, label: fmt(atNoon(k), { month: 'long' }) };
}

function upcomingAll() {
  const t = today0();
  const now = new Date();
  return data.events.filter((ev) => {
    const s = new Date(ev.start);
    const e = ev.end ? new Date(ev.end) : null;
    // timed events that already started today drop off; all-day ones and runs stay
    const live = ev.all_day ? s >= t || (e && e >= t) : (s >= now || (e && e >= now));
    return live && !isHidden(ev) && !tooEarly(ev);
  });
}

// Weekend mornings are for sleeping in: nothing that starts before 9 (profile.json),
// unless it carries on late enough to show up after 9, or it's someone you follow.
let earlyMemo = new Map();     // reset with scoreMemo: it depends on your choices
function tooEarly(ev) {
  if (!earlyMemo.has(ev.id)) earlyMemo.set(ev.id, earlyOf(ev));
  return earlyMemo.get(ev.id);
}
function earlyOf(ev) {
  const first = profile?.weekend_earliest_hour;
  if (first == null || ev.all_day || S.status[ev.id] || followInfo(ev)) return false;
  const s = new Date(ev.start);
  const p = parts(s);
  if (p.weekday !== 'Sat' && p.weekday !== 'Sun') return false;
  const h = Number(p.hour) + s.getMinutes() / 60;
  if (h >= first || h < 4) return false;                       // 4am is the tail of a Friday night out
  const hoursLong = ev.end ? (new Date(ev.end) - s) / 3600e3 : 0;
  return h + hoursLong <= first + 2;                          // on past 11: go late
}
const upcoming = () => upcomingAll().filter(inRange);

function byDay(evs) {
  const m = new Map();
  for (const ev of evs) {
    const k = dayKey(displayDate(ev));
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(ev);
  }
  for (const list of m.values()) list.sort((a, b) => personalScore(b) - personalScore(a));
  return m;
}

function nudgeHTML() {
  for (const [tag, n] of Object.entries(S.notCount)) {
    if (n >= 4 && !(S.addCount[tag] > 0) && !S.hiddenTags.includes(tag) && !S.dismissedNudges.includes(tag) && !tag.startsWith('src:')) {
      const label = tag.startsWith('t:') ? `${tag.slice(2).replace('-', ' ')} events` : (profile?.interests?.[tag]?.label || tag) + ' events';
      return `<div class="nudge" data-tag="${esc(tag)}"><p>You've skipped ${n} ${esc(label.toLowerCase())}. Hide those?</p>
        <div class="row"><button class="btn primary" data-nudge="hide">Hide them</button><button class="btn" data-nudge="keep">Keep showing</button></div></div>`;
    }
  }
  return '';
}

function tipHTML(n) {
  if (!S.home && S.where === 'home' && !S.homeTipOff) {
    return `<p class="hint">Miles are from the middle of ${esc(homePos().label)}. <a href="#" data-tip="home">Add your street address</a> for exact ones, or <a href="#" data-tip="nohome">skip</a>.</p>`;
  }
  if (n && !S.swipeTipOff) return '<p class="hint">Swipe left on anything that’s not for you. Your picks learn from it.</p>';
  return '';
}

function dayList(list, key) {
  const picked = list.filter((ev) => S.status[ev.id] === 'added' || S.status[ev.id] === 'maybe');
  const rest = list.filter((ev) => !picked.includes(ev));
  const all = expanded.has(key);
  const shown = [...picked, ...(all ? rest : rest.slice(0, Math.max(0, DAY_SHOW - picked.length)))]
    .sort((a, b) => (a.all_day - b.all_day) || new Date(a.start) - new Date(b.start));
  const more = rest.length - Math.max(0, DAY_SHOW - picked.length);
  return shown.map((ev) => evRow(ev)).join('') +
    (more > 0 ? `<button class="more-btn" data-more="${key}">${all ? 'Show fewer' : `Show ${more} more`}</button>` : '');
}

// ------------------------------------------------------------------ views

function renderCal(v) {
  const { start, end, y, m } = monthRange(monthOffset);
  const t = today0(), tk = dayKey(t);
  const days = byDay(upcoming().filter((ev) => S.status[ev.id] !== 'not'));
  const nDays = Math.round((end - start) / 86400e3);
  const keys = Array.from({ length: nDays }, (_, i) => `${y}-${String(m).padStart(2, '0')}-${String(i + 1).padStart(2, '0')}`);
  if (!selDay || !keys.includes(selDay) || selDay < tk) selDay = keys.find((k) => k >= tk && days.get(k)?.length) || keys.find((k) => k >= tk) || keys[0];
  const lead = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(parts(atNoon(keys[0])).weekday);
  let grid = '<div></div>'.repeat(lead);
  let planned = 0;
  for (const k of keys) {
    const list = days.get(k) || [];
    const past = k < tk;
    const picked = list.some((ev) => S.status[ev.id] === 'added');
    if (picked) planned += list.filter((ev) => S.status[ev.id] === 'added').length;
    const colors = [];
    for (const ev of list) {
      if (personalScore(ev) < DOT_MIN) break;
      const c = colorOf(ev);
      if (!colors.includes(c)) colors.push(c);
      if (colors.length === 3) break;
    }
    const cls = ['d', past && 'past', k === tk && 'today', k === selDay && 'sel', picked && 'picked'].filter(Boolean).join(' ');
    grid += `<button class="${cls}" data-day="${k}" ${past ? 'disabled' : ''}><span class="n">${Number(k.slice(8))}</span><span class="dots">${past ? '' : colors.map((c) => `<i style="background:var(--${c})"></i>`).join('')}</span></button>`;
  }
  $('#subline').innerHTML = planned ? `<b>${planned} plan${planned > 1 ? 's' : ''}</b> on your calendar this month` : 'Tap a day to see what’s good';
  const list = days.get(selDay) || [];
  const sd = atNoon(selDay);
  v.innerHTML = `<div class="cal"><div class="dow">${['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((x) => `<span>${x}</span>`).join('')}</div><div class="grid">${grid}</div></div>
    <div class="dayhead"><h2>${esc(fmt(sd, { weekday: 'long' }))}, <em>${esc(fmt(sd, { month: 'short', day: 'numeric' }))}</em></h2><small>${list.length ? `${list.length} option${list.length > 1 ? 's' : ''}` : ''}</small></div>
    ${nudgeHTML() || tipHTML(list.length)}
    ${list.length ? dayList(list, selDay) : `<p class="hint">Nothing near ${S.where === 'near' ? 'you' : 'home'} yet. Lots of events are posted 1 to 2 weeks out, so check back.</p>`}`;
}

function renderTonight(v) {
  const now = new Date();
  const t = today0();
  const cutoff = new Date(t.getTime() + 27 * 3600e3);  // 3am
  const evs = upcoming().filter((ev) => S.status[ev.id] !== 'not');
  const pick = (from, to) => evs.filter((ev) => {
    const s = new Date(ev.start), e = ev.end ? new Date(ev.end) : null;
    if (ev.all_day) return dayKey(displayDate(ev)) === dayKey(from);
    return (s >= new Date(from.getTime() - 30 * 60e3) && s < to) || (e && s < from && e > from && e - s < 12 * 3600e3);
  });
  let list = pick(now, cutoff), label = 'Tonight';
  if (!list.filter((ev) => !ev.all_day).length) {
    const tm = new Date(t.getTime() + 24 * 3600e3 + 3600e3);
    list = pick(new Date(`${dayKey(tm)}T00:00:00${offsetFor(dayKey(tm))}`), new Date(t.getTime() + 51 * 3600e3));
    label = 'Tomorrow';
  }
  // good and close beats great and far for a last-minute plan
  const rank = (ev) => personalScore(ev) - 0.2 * (distOf(ev) ?? 4);   // distance by day is already in the score
  const timed = list.filter((ev) => !ev.all_day).sort((a, b) => rank(b) - rank(a));
  const allDay = list.filter((ev) => ev.all_day).sort((a, b) => rank(b) - rank(a));
  $('#title').innerHTML = `${label} <em>${esc(fmt(label === 'Tonight' ? now : new Date(now.getTime() + 86400e3), { weekday: 'short' }))}</em>`;
  $('#subline').textContent = `${timed.length} thing${timed.length === 1 ? '' : 's'} near ${S.where === 'near' && nearPos ? 'you' : 'home'}, best and closest first`;
  const k = `tonight-${label}`;
  const top = expanded.has(k) ? timed : timed.slice(0, 10);
  v.innerHTML = `${top.map((ev) => evRow(ev)).join('') || `<p class="hint">Nothing good left ${label.toLowerCase()}. The calendar has the rest of the month.</p>`}
    ${timed.length > 10 ? `<button class="more-btn" data-more="${k}">${expanded.has(k) ? 'Show fewer' : `Show ${timed.length - 10} more`}</button>` : ''}
    ${allDay.length ? `<div class="dayhead"><h2>All day <em>&amp; ongoing</em></h2></div>${allDay.slice(0, 6).map((ev) => evRow(ev)).join('')}` : ''}`;
}

function isNew(ev) {
  if (S.status[ev.id]) return false;
  const since = S.lastReview || (Date.now() - 7 * 86400e3);
  return new Date(ev.first_seen).getTime() > since;
}
function newQueue() {
  return upcoming().filter((ev) => isNew(ev) && personalScore(ev) >= 1.5)
    .map((ev) => ({ ev, s: personalScore(ev) })).sort((a, b) => b.s - a.s).slice(0, 8).map((x) => x.ev);
}

function renderNew(v) {
  const q = newQueue();
  $('#subline').textContent = 'Fresh since you last looked';
  if (!q.length) {
    v.innerHTML = `<div class="empty"><div class="big">🎂</div><h2>You're all caught up</h2><p>Fresh events show up here as they're posted. Your calendar has the rest.</p>
      <button class="btn primary" data-goto="cal">See my calendar</button></div>`;
    if (S.lastReview == null || newQueue.lastShown) { S.lastReview = Date.now(); save(); }
    return;
  }
  newQueue.lastShown = true;
  v.innerHTML = `<div class="deck-head"><h2>${q.length} new thing${q.length > 1 ? 's' : ''} popped up</h2>
      <p>Swipe right to add, left to skip</p></div>
    <div class="deck" id="deck">${q.slice(0, 2).reverse().map((ev, i, arr) => swipeHTML(ev, i < arr.length - 1)).join('')}</div>
    <div class="deck-btns">
      <button class="round no" data-swipe="not" aria-label="Not for me">✕</button>
      <button class="round sm" data-swipe="maybe" aria-label="Maybe">?</button>
      <button class="round yes" data-swipe="added" aria-label="Add">♥</button>
    </div>
    <p class="small" style="text-align:center;margin-top:14px"><a href="#" data-skipall>Mark all as seen</a></p>`;
  bindSwipe();
}

function swipeHTML(ev, behind) {
  const c = colorOf(ev);
  const img = ev.image_url ? `style="background-image:url('${esc(ev.image_url)}');background-color:var(--${c})"` : `style="background-color:var(--${c})"`;
  const star = starLine(ev);
  const d = distText(distOf(ev));
  return `<div class="swipe ${behind ? 'behind' : ''}" data-id="${esc(ev.id)}">
    <div class="img" ${img}><span class="stamp yes">ADD</span><span class="stamp no">NOPE</span><span class="stamp mb">MAYBE</span></div>
    <div class="body">
      <div class="when">${esc(when(ev))}${runText(ev) ? ` · ${esc(runText(ev))}` : ''}</div>
      <h3>${esc(ev.title)}</h3>
      <div class="small">${esc([ev.venue, d, ev.price === 'free' ? 'Free' : ev.price].filter(Boolean).join(' · '))}</div>
      ${star ? `<div class="small" style="color:var(--butter-ink);font-weight:700;margin-top:6px">${star}</div>` : ''}
    </div></div>`;
}

function bindSwipe() {
  const deck = $('#deck');
  const top = deck && deck.lastElementChild;
  if (!top) return;
  let x0 = 0, y0 = 0, dx = 0, dy = 0, drag = false;
  const stamps = { yes: $('.stamp.yes', top), no: $('.stamp.no', top), mb: $('.stamp.mb', top) };
  top.onpointerdown = (e) => { drag = true; x0 = e.clientX; y0 = e.clientY; top.setPointerCapture(e.pointerId); top.style.transition = 'none'; };
  top.onpointermove = (e) => {
    if (!drag) return;
    dx = e.clientX - x0; dy = e.clientY - y0;
    top.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`;
    stamps.yes.style.opacity = Math.max(0, dx / 100);
    stamps.no.style.opacity = Math.max(0, -dx / 100);
    stamps.mb.style.opacity = Math.max(0, -dy / 120 - Math.abs(dx) / 200);
  };
  top.onpointerup = () => {
    if (!drag) return;
    drag = false; top.style.transition = '';
    if (dx > 100) return fling('added');
    if (dx < -100) return fling('not');
    if (dy < -110) return fling('maybe');
    if (Math.abs(dx) < 6 && Math.abs(dy) < 6) { const ev = byId(top.dataset.id); if (ev) openSheet(ev); }
    top.style.transform = ''; Object.values(stamps).forEach((s) => (s.style.opacity = 0));
    dx = dy = 0;
  };
}

// swipe an event row left to say "not for me" (it hides and teaches the picks)
function bindRowSwipe(view) {
  let row = null, x0 = 0, y0 = 0, dx = 0, mode = null;
  view.addEventListener('touchstart', (e) => {
    row = e.touches.length === 1 && !e.target.closest('.plus') ? e.target.closest('.ev') : null;
    if (!row) return;
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; dx = 0; mode = null;
  }, { passive: true });
  view.addEventListener('touchmove', (e) => {
    if (!row) return;
    const mx = e.touches[0].clientX - x0, my = e.touches[0].clientY - y0;
    if (!mode && Math.abs(mx) + Math.abs(my) > 10) mode = Math.abs(mx) > Math.abs(my) * 1.3 && mx < 0 ? 'swipe' : 'scroll';
    if (mode !== 'swipe') return;
    e.preventDefault();
    dx = Math.min(0, mx);
    row.style.transition = 'none';
    row.style.transform = `translateX(${dx}px)`;
    row.classList.toggle('nope', dx < -90);
    row.style.setProperty('--nope', Math.min(1, -dx / 90));
  }, { passive: false });
  const end = () => {
    if (!row) return;
    const r = row; row = null;
    if (mode !== 'swipe') return;
    mode = 'swiped'; setTimeout(() => (mode = null), 50);
    r.style.transition = '';
    if (dx < -90) {
      const ev = byId(r.dataset.id);
      r.style.transform = 'translateX(-110%)'; r.style.opacity = '0';
      setTimeout(() => {
        if (!ev) return render();
        const prev = decide(ev, 'not');
        if (!S.swipeTipOff) { S.swipeTipOff = true; save(); }
        toast("Skipped. We'll show fewer like this", () => { decide(ev, prev || 'not'); render(); });
        render();
      }, 210);
    } else {
      r.style.transform = ''; r.classList.remove('nope');
    }
  };
  view.addEventListener('touchend', end);
  view.addEventListener('touchcancel', end);
  // a swipe shouldn't also open the event
  view.addEventListener('click', (e) => { if (mode === 'swiped') { e.stopPropagation(); e.preventDefault(); } }, true);
}

function fling(status) {
  const top = $('#deck') && $('#deck').lastElementChild;
  if (!top) return;
  const ev = byId(top.dataset.id);
  const out = { added: 'translate(140%, -10%) rotate(20deg)', not: 'translate(-140%, -10%) rotate(-20deg)', maybe: 'translate(0, -140%)' }[status];
  top.style.transform = out; top.style.opacity = 0;
  decide(ev, status);
  if (status === 'added') toast('In your plan');
  setTimeout(() => {
    if (!newQueue().length) { S.lastReview = Date.now(); save(); }
    render();
  }, 260);
}

function picks() {
  return data.events.filter((ev) => S.status[ev.id] === 'added' || S.status[ev.id] === 'maybe')
    .sort((a, b) => displayDate(a) - displayDate(b));
}

function renderPicks(v) {
  const t = today0();
  const list = picks().filter((ev) => displayDate(ev) >= t || (ev.end && new Date(ev.end) >= t));
  const added = list.filter((ev) => S.status[ev.id] === 'added');
  const maybe = list.filter((ev) => S.status[ev.id] === 'maybe');
  $('#subline').innerHTML = added.length ? `<b>${added.length} going</b>${maybe.length ? ` · ${maybe.length} maybe` : ''}` : '';
  if (!list.length) {
    v.innerHTML = `<div class="empty"><div class="big">🧁</div><h2>No picks yet</h2><p>Tap + on anything that sounds fun.</p><button class="btn primary" data-goto="cal">Browse my month</button></div>`;
    return;
  }
  v.innerHTML = `${added.length ? `<button class="btn cherry block" data-addall>📅 Add all ${added.length} to my calendar</button>` : ''}
    ${added.length ? `<div class="dayhead"><h2>Going</h2><small>${added.length}</small></div>${added.map((ev) => evRow(ev, { showDay: true })).join('')}` : ''}
    ${maybe.length ? `<div class="dayhead"><h2>Maybe</h2><small>${maybe.length}</small></div>${maybe.map((ev) => evRow(ev, { showDay: true })).join('')}` : ''}`;
}

function renderMe(v) {
  const ints = profile ? Object.entries(profile.interests) : [];
  const lv = (k) => (S.interests[k] === undefined ? 1 : S.interests[k]);
  const learned = Object.entries(S.tagW).filter(([t, w]) => Math.abs(w) >= 0.5 && !t.startsWith('src:'))
    .sort((a, b) => b[1] - a[1]);
  const authors = follow ? (follow.authors_favorite || []).length + (follow.authors_new_books || []).length : 0;
  const gen = data.generated ? new Date(data.generated) : null;
  const ago = gen ? Math.round((Date.now() - gen) / 3600e3) : null;
  const sugg = igSuggestions();
  const home = homePos();
  const mapped = data.events.filter((e) => e.lat != null).length;
  $('#subline').textContent = 'Your taste, your people, your home spot';
  v.innerHTML = `
  <div class="section"><h2>Home</h2>
    <p class="sub">Distances are from ${S.home ? esc(S.home.label) : `${esc(home.label)} (roughly)`}. Your address stays on this phone. It's looked up once on OpenStreetMap to find the spot.</p>
    <form class="field" id="homeForm"><input id="homeAddr" placeholder="Your street address" autocomplete="street-address" value="${S.home ? esc(S.home.label) : ''}"><button class="btn primary">Save</button></form>
    <p class="small" style="margin:10px 0 0">${mapped} of ${data.events.length} events have a map spot so far.</p>
  </div>
  <div class="section"><h2>People you follow</h2>
    <p class="sub">Events naming them get a ⭐. ${authors} authors from Goodreads${S.igHandles.length ? ` · ${S.igHandles.length} Instagram follows` : ''}${S.authorsExtra.length ? ` · ${S.authorsExtra.length} from your latest Goodreads import` : ''}. Instagram follows only count for shows, since most are friends.</p>
    ${sugg.length ? `<div style="margin:0 0 12px">${sugg.map((s) => `<div class="suggest"><span>Is <b>@${esc(s.handle)}</b> ${esc(s.name)}? <span class="small">(${esc(s.ev.title.slice(0, 48))})</span></span><button class="btn cherry" data-ig-yes="${esc(s.handle)}" data-name="${esc(s.name)}">Yes</button><button class="btn" data-ig-no="${esc(s.handle)}|${esc(s.name)}">No</button></div>`).join('')}</div>` : ''}
    <div class="chips">${S.people.map((p, i) => `<button class="pchip" data-rmp="${i}">${esc(p)}<span class="x">✕</span></button>`).join('')}${Object.entries(S.igConfirmed).map(([h, n]) => `<button class="pchip" data-rmig="${esc(h)}">${esc(n)} <span class="small">@${esc(h)}</span><span class="x">✕</span></button>`).join('')}</div>
    <form class="field" id="addPerson"><input id="personName" placeholder="Add a comedian, performer, artist…" autocomplete="off"><button class="btn primary">Add</button></form>
    <div class="row-btns" style="margin-top:10px">
      <label class="btn file-btn">Import Instagram follows<input type="file" accept=".json,.html,.htm,application/json,text/html" id="igFile"></label>
      <label class="btn file-btn">Import Goodreads CSV<input type="file" accept=".csv,text/csv" id="grFile"></label>
    </div>
    <p class="small">Instagram: pick <b>following.html</b> (or following.json) from your Instagram download. The app only reads usernames from it and never contacts Instagram.${S.blockedPeople.length ? ` Not followed: ${S.blockedPeople.map((p) => `<a href="#" data-unblock="${esc(p)}">${esc(p)} ✕</a>`).join(', ')}` : ''}</p>
  </div>
  <div class="section"><h2>Interests</h2><p class="sub">Tap to cycle: ♥ love it, like it, not into it. These boost ranking; they never hide events.</p>
    <div class="chips">${ints.map(([k, s]) => `<button class="pchip lv${lv(k)}" data-int="${k}">${lv(k) === 2 ? '♥ ' : ''}${esc(s.label)}</button>`).join('')}</div>
    <p class="small" style="margin:12px 0 0">Favorite time: ${esc((profile?.favorite_times || []).map((t) => t.label).join(', ') || 'none')}</p>
  </div>
  ${learned.length ? `<div class="section"><h2>What it's learned</h2><p class="sub">From your Add, Maybe and Not for me taps.</p>
    <div class="chips">${learned.slice(0, 14).map(([t, w]) => `<span class="pchip">${w > 0 ? '▲' : '▼'} ${esc(t.startsWith('t:') ? t.slice(2).replace('-', ' ') : profile?.interests?.[t]?.label || t)}</span>`).join('')}</div>
    ${S.hiddenTags.length ? `<p class="small" style="margin-top:10px">Hidden: ${S.hiddenTags.map((t) => `<a href="#" data-unhide="${esc(t)}">${esc(profile?.interests?.[t]?.label || t)} ✕</a>`).join(', ')}</p>` : ''}
  </div>` : ''}
  <div class="section"><h2>Backup</h2><p class="sub">Your choices live on this phone. Save a backup now and then.</p>
    <div class="row-btns"><button class="btn primary" data-export>Export backup</button><label class="btn file-btn">Restore<input type="file" accept=".json" id="restoreFile"></label></div>
  </div>
  <div class="section"><h2>Sources</h2><p class="sub">${gen ? `Updated ${ago < 1 ? 'just now' : ago < 24 ? `${ago}h ago` : `${Math.round(ago / 24)}d ago`}` : 'Not updated yet'} · ${data.events.length} events${data.ai ? ' · AI tagging on' : ''}</p>
    ${data.sources.map((s) => `<div class="src"><span>${esc(s.label)}</span><span class="${s.ok ? 'good' : 'bad'}">${s.ok ? s.count : (s.error || '').includes('zero') ? '0 events' : 'not working'}</span></div>`).join('')}
  </div>`;
}

// ------------------------------------------------------------------ imports

async function importInstagram(file) {
  const text = await file.text();
  const handles = [];
  if (/^\s*[[{]/.test(text)) {
    const json = JSON.parse(text);
    const list = Array.isArray(json) ? json : (json.relationships_following || json.following || []);
    for (const item of list) {
      for (const d of item.string_list_data || []) if (d.value) handles.push(d.value);
      if (item.title && !(item.string_list_data || []).length) handles.push(item.title);
    }
  } else {
    // the HTML export links each account as instagram.com/_u/<handle>
    for (const m of text.matchAll(/instagram\.com\/(?:_u\/)?([A-Za-z0-9._]{2,30})/g)) {
      if (!/^(accounts|explore|p|reel|reels|stories|direct|_u)$/i.test(m[1])) handles.push(m[1]);
    }
  }
  const fresh = [...new Set(handles.map((h) => h.toLowerCase()))];
  if (!fresh.length) throw new Error('no usernames found');
  S.igHandles = [...new Set([...S.igHandles, ...fresh])];
  save(); buildFollowIndex();
  toast(`Imported ${fresh.length} follows`);
}

function parseCSV(text) {
  const rows = []; let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; }
    else if (c !== '\r') cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [head, ...body] = rows;
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] || ''])));
}

async function importGoodreads(file) {
  const rows = parseCSV(await file.text());
  const loved = {}, five = new Set(), newb = new Set();
  const year = new Date().getFullYear();
  for (const r of rows) {
    const a = (r.Author || '').replace(/\s+/g, ' ').trim();
    if (!a) continue;
    const rating = parseInt(r['My Rating'] || '0', 10);
    if (rating >= 4) loved[a] = (loved[a] || 0) + 1;
    if (rating === 5) five.add(a);
    const y = parseInt(r['Original Publication Year'] || r['Year Published'] || '0', 10);
    if (r['Exclusive Shelf'] === 'to-read' && y >= year - 1) newb.add(a);
  }
  const fav = Object.keys(loved).filter((a) => loved[a] >= 2 || five.has(a));
  S.authorsExtra = [...new Set([...fav, ...newb])];
  save(); buildFollowIndex();
  toast(`${S.authorsExtra.length} authors from ${rows.length} books`);
}

function exportBackup() {
  const blob = new Blob([JSON.stringify(S, null, 1)], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `bay-events-backup-${dayKey(new Date())}.json` });
  document.body.append(a); a.click(); a.remove();
}

// ------------------------------------------------------------------ shell

function applySeason(month) {
  const s = SEASONS[month - 1];
  const r = document.documentElement.style;
  r.setProperty('--season', s.bg); r.setProperty('--season-ink', s.ink);
  r.setProperty('--season-em', s.em); r.setProperty('--season-sub', s.sub);
  $('#themeColor')?.setAttribute('content', s.bg);
}

function renderHeader() {
  const { y, m, label } = monthRange(tab === 'cal' ? monthOffset : 0);
  applySeason(m);
  $('#where').hidden = !['cal', 'tonight'].includes(tab);
  document.querySelectorAll('#where [data-where]').forEach((b) => b.classList.toggle('on', b.dataset.where === S.where));
  $('#arrows').hidden = tab !== 'cal';
  $('[data-month="-1"]').disabled = monthOffset <= 0;
  $('[data-month="1"]').disabled = monthOffset >= 1;
  $('#title').innerHTML = {
    cal: `${esc(label)} <em>${y}</em>`,
    tonight: 'Tonight',
    new: 'New <em>for you</em>',
    picks: 'Your <em>picks</em>',
    me: 'You',
  }[tab];
  const n = newQueue().length;
  const b = $('#newBadge');
  b.hidden = !n; b.textContent = n;
}

function render() {
  scoreMemo = new Map();
  earlyMemo = new Map();
  renderHeader();
  const v = $('#view');
  ({ cal: renderCal, tonight: renderTonight, new: renderNew, picks: renderPicks, me: renderMe })[tab](v);
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.dataset.tab === tab));
}

function bind() {
  document.querySelector('.tabs').onclick = (e) => {
    const t = e.target.closest('[data-tab]');
    if (!t) return;
    if (tab === 'new' && t.dataset.tab !== 'new') newQueue.lastShown = false;
    tab = t.dataset.tab; render(); window.scrollTo({ top: 0 });
  };
  $('#arrows').onclick = (e) => {
    const b = e.target.closest('[data-month]');
    if (!b) return;
    monthOffset = Math.max(0, Math.min(1, monthOffset + Number(b.dataset.month)));
    selDay = null; render();
  };
  $('#where').onclick = (e) => {
    const b = e.target.closest('[data-where]');
    if (!b) return;
    S.where = b.dataset.where; save();
    if (S.where === 'near' && !nearPos) findMe();
    render();
  };
  $('#sheetWrap').onclick = (e) => { if (e.target.closest('[data-close]')) closeSheet(); };
  bindSheetDrag();
  const v = $('#view');
  bindRowSwipe(v);
  v.addEventListener('click', (e) => {
    const tip = e.target.closest('[data-tip]');
    if (tip) {
      e.preventDefault();
      if (tip.dataset.tip === 'nohome') { S.homeTipOff = true; save(); render(); return; }
      document.querySelector('[data-tab="me"]').click();
      setTimeout(() => { const i = $('#homeAddr'); if (i) { i.scrollIntoView({ block: 'center' }); i.focus(); } }, 50);
      return;
    }
    const day = e.target.closest('[data-day]');
    if (day) { selDay = day.dataset.day; render(); return; }
    const g = e.target.closest('[data-goto]'); if (g) { tab = g.dataset.goto; return render(); }
    const more = e.target.closest('[data-more]');
    if (more) { const k = more.dataset.more; expanded.has(k) ? expanded.delete(k) : expanded.add(k); return render(); }
    const n = e.target.closest('[data-nudge]');
    if (n) {
      const tag = n.closest('.nudge').dataset.tag;
      if (n.dataset.nudge === 'hide') { S.hiddenTags.push(tag); toast('Hidden. Undo any time under You', () => { S.hiddenTags = S.hiddenTags.filter((t) => t !== tag); save(); render(); }); }
      else S.dismissedNudges.push(tag);
      save(); return render();
    }
    const sw = e.target.closest('[data-swipe]'); if (sw) return fling(sw.dataset.swipe);
    if (e.target.closest('[data-skipall]')) { e.preventDefault(); S.lastReview = Date.now(); save(); return render(); }
    if (e.target.closest('[data-addall]')) return addAllToCalendar();
    const ic = e.target.closest('[data-int]');
    if (ic) { const k = ic.dataset.int; const cur = S.interests[k] === undefined ? 1 : S.interests[k]; S.interests[k] = (cur + 2) % 3; save(); return render(); }
    const rm = e.target.closest('[data-rmp]'); if (rm) { S.people.splice(Number(rm.dataset.rmp), 1); save(); buildFollowIndex(); return render(); }
    const rmig = e.target.closest('[data-rmig]'); if (rmig) { delete S.igConfirmed[rmig.dataset.rmig]; save(); buildFollowIndex(); return render(); }
    const yes = e.target.closest('[data-ig-yes]');
    if (yes) { S.igConfirmed[yes.dataset.igYes] = yes.dataset.name; save(); buildFollowIndex(); toast(`⭐ ${yes.dataset.name}`); return render(); }
    const no = e.target.closest('[data-ig-no]'); if (no) { S.igRejected.push(no.dataset.igNo); save(); return render(); }
    const ub = e.target.closest('[data-unblock]'); if (ub) { e.preventDefault(); S.blockedPeople = S.blockedPeople.filter((p) => p !== ub.dataset.unblock); save(); buildFollowIndex(); return render(); }
    const uh = e.target.closest('[data-unhide]'); if (uh) { e.preventDefault(); S.hiddenTags = S.hiddenTags.filter((t) => t !== uh.dataset.unhide); save(); return render(); }
    if (e.target.closest('[data-export]')) return exportBackup();
    onEventClick(e);
  });
  v.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (e.target.id === 'addPerson') {
      const name = $('#personName').value.trim();
      if (name) { S.people.push(name); save(); buildFollowIndex(); render(); toast(`Following ${name}`); }
    }
    if (e.target.id === 'homeForm') {
      const addr = $('#homeAddr').value.trim();
      if (!addr) { S.home = null; save(); return render(); }
      try { await setHome(addr); toast('Home saved'); } catch (err) { toast(`Couldn't find that (${err.message})`); }
      render();
    }
  });
  v.addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      if (e.target.id === 'igFile') await importInstagram(file);
      if (e.target.id === 'grFile') await importGoodreads(file);
      if (e.target.id === 'restoreFile') { S = Object.assign(blank(), JSON.parse(await file.text())); save(); buildFollowIndex(); toast('Backup restored'); }
    } catch (err) { toast(`Couldn't read that file (${err.message})`); }
    render();
  });
}

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

async function start() {
  bind();
  try {
    [data, profile, follow] = await Promise.all([getJSON('events.json'), getJSON('profile.json'), getJSON('follow.json')]);
  } catch (err) {
    $('#view').innerHTML = `<div class="empty"><div class="big">📡</div><h2>Couldn't load events</h2><p>${esc(err.message)}</p></div>`;
    return;
  }
  buildFollowIndex();
  render();
  getJSON('weather.json').then((w) => { weather = w; sunMemo.clear(); render(); }).catch(() => {});   // optional
  if (S.where === 'near') findMe();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
}

start();
