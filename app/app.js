// Bay Events: reads events.json (written by the daily job) and keeps all of
// David's choices and learned taste on the phone (localStorage).

const TZ = 'America/Los_Angeles';
const STORE = 'bay-events-v1';
const LEARN = { added: 0.6, maybe: 0.25, not: -0.5, shared: 0.3 };
const INTEREST_LEVELS = { 2: 1.5, 1: 0, 0: -1.5 };  // love / like / not into
const HERO_MIN = 5;

let data = { events: [], sources: [] };
let profile = null;
let follow = null;
let tab = 'plan';
let monthOffset = 0;
let expanded = new Set();

// ------------------------------------------------------------------ state

const blank = () => ({
  status: {},          // id -> added | maybe | not | shared
  tagW: {},            // learned tag weights
  notCount: {},        // tag -> times skipped
  addCount: {},        // tag -> times added
  interests: {},       // interest key -> level 0/1/2
  people: [],          // names typed in
  igHandles: [],       // from Instagram export
  authorsExtra: [],    // from a Goodreads CSV imported on the phone
  hiddenTags: [],
  dismissedNudges: [],
  lastReview: null,
  decidedAt: {},
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
const fmt = (d, o) => new Intl.DateTimeFormat('en-US', { timeZone: TZ, ...o }).format(d);
const parts = (d) => Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: TZ, year: 'numeric', month: 'numeric', day: 'numeric', weekday: 'short', hour: 'numeric', hourCycle: 'h23' }).formatToParts(d).map((p) => [p.type, p.value]));
const dayKey = (d) => { const p = parts(d); return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`; };
const norm = (s) => (s || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[.'’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
const today0 = () => { const k = dayKey(new Date()); return new Date(`${k}T00:00:00${offsetFor(k)}`); };

function offsetFor(k) {
  // Pacific offset for a local date (handles DST)
  const d = new Date(`${k}T12:00:00Z`);
  const tz = new Intl.DateTimeFormat('en-US', { timeZone: TZ, timeZoneName: 'shortOffset' }).formatToParts(d).find((p) => p.type === 'timeZoneName').value;
  const m = tz.match(/GMT([+-]\d+)/);
  const h = m ? parseInt(m[1], 10) : -8;
  return `${h < 0 ? '-' : '+'}${String(Math.abs(h)).padStart(2, '0')}:00`;
}

function when(ev) {
  const s = new Date(ev.start);
  const day = fmt(s, { weekday: 'short', month: 'short', day: 'numeric' });
  if (ev.all_day) return day;
  const t = fmt(s, { hour: 'numeric', minute: '2-digit' }).replace(':00', '').replace(' ', '').toLowerCase();
  return `${day} · ${t}`;
}
function runText(ev) {
  if (!ev.end) return '';
  const s = new Date(ev.start), e = new Date(ev.end);
  if (e - s < 36 * 3600e3) return '';
  return `through ${fmt(e, { month: 'short', day: 'numeric' })}`;
}
function displayDate(ev) {
  // a run that started already shows up today
  const s = new Date(ev.start);
  const t = today0();
  return s < t && ev.end && new Date(ev.end) >= t ? t : s;
}
const placeOf = (ev) => [ev.venue, ev.city && !/san francisco/i.test(ev.city) && !(ev.venue || '').includes(ev.city) ? ev.city : ''].filter(Boolean).join(' · ');
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

// ------------------------------------------------------------------ taste

function followNames() {
  const list = [];
  if (follow) {
    for (const n of follow.authors_favorite || []) list.push([n, 'author']);
    for (const n of follow.authors_new_books || []) list.push([n, 'author']);
    for (const n of follow.performers || []) list.push([n, 'performer']);
  }
  for (const n of S.people) list.push([n, 'performer']);
  for (const n of S.authorsExtra) list.push([n, 'author']);
  return list.filter(([n]) => norm(n).length >= 4);
}
let followIndex = null;
function buildFollowIndex() {
  followIndex = followNames().map(([name, kind]) => ({ name, kind, re: new RegExp(`(?<![a-z0-9])${norm(name).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![a-z0-9])`) }));
  const handles = S.igHandles.map((h) => h.toLowerCase().replace(/^@/, ''));
  followIndex.handles = new Set(handles.flatMap((h) => {
    const bare = h.replace(/[._\d]+/g, '');
    const trimmed = bare.replace(/^(the|its|real|official)/, '').replace(/(comedy|comic|official|music|art|live|sf|tv)$/, '');
    return [bare, trimmed].filter((x) => x.length >= 6);
  }));
  followIndex.rawHandles = new Set(handles);
}

function followedIn(ev) {
  if (ev.followed) return ev.followed;
  if (!followIndex) buildFollowIndex();
  const text = norm(`${ev.title} ${ev.description} ${(ev.people || []).join(' ')}`);
  for (const f of followIndex) if (f.re.test(text)) return f.name;
  const raw = `${ev.title} ${ev.description}`;
  for (const m of raw.matchAll(/@([A-Za-z0-9._]{3,30})/g)) if (followIndex.rawHandles.has(m[1].toLowerCase())) return '@' + m[1];
  if (followIndex.handles.size) {
    // "John Mulaney" in a listing matches the handle @johnmulaney
    const names = raw.match(/\b[A-Z][a-zA-Z'’-]+(?:\s+[A-Z][a-zA-Z'’-]+){1,2}\b/g) || [];
    for (const n of names) {
      const joined = norm(n).replace(/ /g, '');
      if (followIndex.handles.has(joined)) return n;
    }
  }
  return null;
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
  let s = ev.score || 0;
  for (const t of learnTags(ev)) s += Math.max(-3, Math.min(3, S.tagW[t] || 0));
  for (const t of ev.tags || []) if (S.interests[t] !== undefined) s += INTEREST_LEVELS[S.interests[t]];
  if (!ev.followed && followedIn(ev)) s += 6;
  return s;
}

function whyLine(ev) {
  const f = followedIn(ev);
  let why = ev.why || '';
  if (f && !why.includes(f)) why = `⭐ ${f} · ${why}`;
  return why;
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
  const pad = (n) => String(n).padStart(2, '0');
  const local = (d) => { const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(d).map((x) => [x.type, x.value])); return `${p.year}${p.month}${p.day}T${p.hour}${p.minute}${p.second}`; };
  const e = (s) => String(s || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Bay Events//EN', 'METHOD:PUBLISH'];
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

// ------------------------------------------------------------------ rendering: cards

function cardHTML(ev, { hero = false } = {}) {
  const st = S.status[ev.id];
  const f = followedIn(ev);
  const fresh = isNew(ev);
  const img = ev.image_url ? `style="background-image:url('${esc(ev.image_url)}'), var(--grad)"` : '';
  const run = runText(ev);
  return `<article class="card ${hero ? 'hero' : ''} ${st || ''}" data-id="${esc(ev.id)}">
    ${hero ? `<div class="img ${ev.image_url ? '' : 'noimg'}" ${img}><span class="b love">You'll love this</span></div>` : ''}
    <div class="body" data-open>
      ${!hero && ev.image_url ? `<div class="thumb" ${img}></div>` : ''}
      <div class="when">${esc(when(ev))}${run ? `<span class="dot"></span><span class="run">${esc(run)}</span>` : ''}</div>
      <h3>${esc(ev.title)}</h3>
      ${ev.parent_event ? '' : ''}
      <div class="where">${esc(placeOf(ev))}${ev.price ? ` · ${esc(ev.price === 'free' ? 'Free' : ev.price)}` : ''}</div>
      <div class="why">${esc(whyLine(ev))}</div>
      ${f || fresh || ev.sponsored ? `<div class="badges">${f ? '<span class="b follow">⭐ Someone you follow</span>' : ''}${fresh ? '<span class="b new">New</span>' : ''}${ev.sponsored ? '<span class="b sponsor">May be sponsored</span>' : ''}</div>` : ''}
    </div>
    <div class="actions">
      <button class="act add ${st === 'added' ? 'on' : ''}" data-act="added">${st === 'added' ? '✓ Added' : '＋ Add'}</button>
      <button class="act maybe ${st === 'maybe' ? 'on' : ''}" data-act="maybe">Maybe</button>
      <button class="act" data-act="not" aria-label="Not for me">Not for me</button>
      <span class="sp"></span>
      <a class="act icon" href="${esc(ev.ics)}" data-cal aria-label="Add to calendar">📅</a>
      <button class="act icon" data-act="share" aria-label="Share">↗︎</button>
    </div>
  </article>`;
}

function byId(id) { return data.events.find((e) => e.id === id); }

function onCardClick(e) {
  const card = e.target.closest('.card');
  if (!card) return;
  const ev = byId(card.dataset.id);
  if (!ev) return;
  const btn = e.target.closest('[data-act]');
  if (btn) {
    const act = btn.dataset.act;
    if (act === 'share') return share(ev);
    const prev = decide(ev, act);
    const now = S.status[ev.id];
    if (now === 'added') toast('Added to your plan · tap 📅 for your calendar');
    if (now === 'not') toast('Hidden. We\'ll show fewer like this', () => { decide(ev, prev || 'not'); render(); });
    render();
    const el = document.querySelector(`.card[data-id="${CSS.escape(ev.id)}"]`);
    if (el && now === 'added') el.classList.add('pop');
    return;
  }
  if (e.target.closest('[data-cal]')) {
    // the .ics link opens the calendar sheet; adding it also counts as a yes
    if (S.status[ev.id] !== 'added') { decide(ev, 'added'); setTimeout(render, 300); }
    return;
  }
  if (e.target.closest('[data-open]')) openSheet(ev);
}

function openSheet(ev) {
  const st = S.status[ev.id];
  const img = ev.image_url ? `<div class="img" style="background-image:url('${esc(ev.image_url)}')"></div>` : '';
  const links = [
    `<a href="${esc(ev.source_url)}" target="_blank" rel="noopener">Open on ${esc(sourceLabel(ev.source))} ↗</a>`,
    ev.ticket_url && ev.ticket_url !== ev.source_url ? `<a href="${esc(ev.ticket_url)}" target="_blank" rel="noopener">Tickets / RSVP ↗</a>` : '',
    ev.parent_event ? `<a href="${esc(ev.parent_event.url)}" target="_blank" rel="noopener">Part of ${esc(ev.parent_event.title)} ↗</a>` : '',
    ...(ev.also_on || []).map((a) => `<a href="${esc(a.url)}" target="_blank" rel="noopener">Also on ${esc(sourceLabel(a.source))} ↗</a>`),
    `<a href="${esc(googleCal(ev))}" target="_blank" rel="noopener">Add to Google Calendar ↗</a>`,
    `<a href="#" data-copy>Copy link</a>`,
  ].join('');
  $('#sheet').innerHTML = `<div class="grab"></div>${img}
    <div class="card ${st || ''}" data-id="${esc(ev.id)}" style="box-shadow:none;margin:0">
      <div class="when" style="padding:0 2px">${esc(when(ev))}${runText(ev) ? ` · ${esc(runText(ev))}` : ''}</div>
      <h2>${esc(ev.title)}</h2>
      <div class="where">${esc([ev.venue, ev.address !== ev.venue ? ev.address : '', ev.city].filter(Boolean).join(' · '))}${ev.price ? ` · ${esc(ev.price)}` : ''}</div>
      <div class="why" style="margin:10px 0">${esc(whyLine(ev))}</div>
      ${ev.people && ev.people.length ? `<div class="small">With ${esc(ev.people.slice(0, 6).join(', '))}</div>` : ''}
      <p class="desc">${esc(ev.description || '')}</p>
      <div class="actions" style="padding-left:0">
        <button class="act add ${st === 'added' ? 'on' : ''}" data-act="added">${st === 'added' ? '✓ Added' : '＋ Add'}</button>
        <button class="act maybe ${st === 'maybe' ? 'on' : ''}" data-act="maybe">Maybe</button>
        <button class="act" data-act="not">Not for me</button>
        <a class="act icon" href="${esc(ev.ics)}" data-cal aria-label="Add to calendar">📅</a>
        <button class="act icon" data-act="share" aria-label="Share">↗︎</button>
      </div>
    </div>
    <div class="links">${links}</div>`;
  $('#sheetWrap').hidden = false;
  $('#sheet [data-copy]').onclick = (e) => { e.preventDefault(); copyLink(ev); };
  $('#sheet').onclick = (e) => { if (e.target.closest('[data-act],[data-cal]')) { onCardClick(e); if (e.target.closest('[data-act]')) closeSheet(); } };
}
function closeSheet() { $('#sheetWrap').hidden = true; }

// ------------------------------------------------------------------ views

function monthRange(offset) {
  const p = parts(new Date());
  let y = Number(p.year), m = Number(p.month) + offset;
  while (m > 12) { m -= 12; y++; }
  const k = `${y}-${String(m).padStart(2, '0')}-01`;
  const start = new Date(`${k}T00:00:00${offsetFor(k)}`);
  const nm = m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`;
  const end = new Date(`${nm}T00:00:00${offsetFor(nm)}`);
  return { start, end, label: fmt(start, { month: 'long' }) };
}

function weekStart(d) {
  const k = dayKey(d);
  const base = new Date(`${k}T12:00:00${offsetFor(k)}`);
  const dow = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(parts(base).weekday);
  const ws = new Date(base.getTime() - dow * 86400e3);
  const wk = dayKey(ws);
  return new Date(`${wk}T00:00:00${offsetFor(wk)}`);
}

function upcoming() {
  const t = today0();
  return data.events.filter((ev) => {
    const s = new Date(ev.start);
    return (s >= t || (ev.end && new Date(ev.end) >= t)) && !isHidden(ev);
  });
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

function renderPlan(v) {
  const { start, end, label } = monthRange(monthOffset);
  const t = today0();
  const perWeek = profile?.events_per_week || 10;
  const heroN = profile?.highlights_per_week || 3;
  const evs = upcoming().filter((ev) => S.status[ev.id] !== 'not');
  const weeks = new Map();
  for (const ev of evs) {
    const d = displayDate(ev);
    if (d < start || d >= end || d < t) continue;
    const ws = weekStart(d).getTime();
    if (!weeks.has(ws)) weeks.set(ws, []);
    weeks.get(ws).push(ev);
  }
  $('#eyebrow').textContent = monthOffset === 0 ? 'Your month' : 'Coming up';
  $('#title').textContent = label;
  const keys = [...weeks.keys()].sort((a, b) => a - b);
  if (!keys.length) {
    v.innerHTML = `<div class="empty"><div class="big">🌙</div><h2>Nothing here yet</h2><p>New events land every morning. Many are posted 1 to 2 weeks out, so check back.</p></div>`;
    return;
  }
  let html = nudgeHTML();
  for (const ws of keys) {
    const list = weeks.get(ws).map((ev) => ({ ev, s: personalScore(ev) })).sort((a, b) => b.s - a.s);
    const picked = list.filter((x) => S.status[x.ev.id] === 'added' || S.status[x.ev.id] === 'maybe');
    const rest = list.filter((x) => !picked.includes(x));
    const heroes = rest.filter((x) => x.s >= HERO_MIN).slice(0, heroN);
    const others = rest.filter((x) => !heroes.includes(x));
    const showAll = expanded.has(ws);
    const room = Math.max(0, perWeek - heroes.length - picked.length);
    const shown = showAll ? others : others.slice(0, room);
    shown.sort((a, b) => new Date(displayDate(a.ev)) - new Date(displayDate(b.ev)));
    const pickedSorted = picked.sort((a, b) => displayDate(a.ev) - displayDate(b.ev));
    const wsd = new Date(ws);
    const added = picked.filter((x) => S.status[x.ev.id] === 'added').length;
    html += `<section class="week"><div class="week-head"><h2>${wsd < t ? 'This week' : 'Week of ' + esc(fmt(wsd, { month: 'short', day: 'numeric' }))}</h2>
      <span class="meta">${added ? `${added} planned · ` : ''}${list.length} options</span></div>
      ${heroes.map((x) => cardHTML(x.ev, { hero: true })).join('')}
      ${pickedSorted.map((x) => cardHTML(x.ev)).join('')}
      ${shown.map((x) => cardHTML(x.ev)).join('')}
      ${others.length > room ? `<button class="more-btn" data-more="${ws}">${showAll ? 'Show fewer' : `Show ${others.length - room} more this week`}</button>` : ''}
    </section>`;
  }
  v.innerHTML = html;
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
  $('#eyebrow').textContent = 'Weekly top-up';
  $('#title').textContent = 'New for you';
  const q = newQueue();
  if (!q.length) {
    v.innerHTML = `<div class="empty"><div class="big">🎉</div><h2>You're all caught up</h2><p>Fresh events show up here as they're posted. Your plan has the rest.</p>
      <button class="btn primary" data-goto="plan">See my plan</button></div>`;
    if (S.lastReview == null || newQueue.lastShown) { S.lastReview = Date.now(); save(); }
    return;
  }
  newQueue.lastShown = true;
  const weekend = q.filter((ev) => /Sat|Sun|Fri/.test(fmt(new Date(ev.start), { weekday: 'short' }))).length;
  v.innerHTML = `<div class="deck-head"><h2>${q.length} new thing${q.length > 1 ? 's' : ''} popped up</h2>
      <p>${weekend ? `${weekend} on a weekend · ` : ''}swipe right to add, left to skip</p></div>
    <div class="deck" id="deck">${q.slice(0, 2).reverse().map((ev, i, arr) => swipeHTML(ev, i < arr.length - 1)).join('')}</div>
    <div class="deck-btns">
      <button class="round" data-swipe="not" aria-label="Not for me">✕</button>
      <button class="round sm" data-swipe="maybe" aria-label="Maybe">?</button>
      <button class="round" data-swipe="added" aria-label="Add">♥</button>
    </div>
    <p class="small" style="text-align:center;margin-top:14px"><a href="#" data-skipall>Mark all as seen</a></p>`;
  bindSwipe();
}

function swipeHTML(ev, behind) {
  const img = ev.image_url ? `style="background-image:url('${esc(ev.image_url)}'), var(--grad)"` : '';
  const f = followedIn(ev);
  return `<div class="swipe ${behind ? 'behind' : ''}" data-id="${esc(ev.id)}">
    <div class="img" ${img}><span class="stamp yes">ADD</span><span class="stamp no">NOPE</span><span class="stamp mb">MAYBE</span></div>
    <div class="body">
      <div class="card" style="box-shadow:none;margin:0;background:none"><div class="when">${esc(when(ev))}${runText(ev) ? ` · ${esc(runText(ev))}` : ''}</div></div>
      <h3>${esc(ev.title)}</h3>
      <div class="where small">${esc(placeOf(ev))}${ev.price ? ` · ${esc(ev.price)}` : ''}</div>
      <div class="card" style="box-shadow:none;margin:0;background:none"><div class="why">${esc(whyLine(ev))}</div>
      ${f ? '<div class="badges"><span class="b follow">⭐ Someone you follow</span></div>' : ''}</div>
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

function fling(status) {
  const top = $('#deck') && $('#deck').lastElementChild;
  if (!top) return;
  const ev = byId(top.dataset.id);
  const out = { added: 'translate(140%, -10%) rotate(20deg)', not: 'translate(-140%, -10%) rotate(-20deg)', maybe: 'translate(0, -140%)' }[status];
  top.style.transform = out; top.style.opacity = 0;
  decide(ev, status);
  if (status === 'added') toast('Added · tap 📅 on it in your plan for your calendar');
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
  $('#eyebrow').textContent = 'Your plans';
  $('#title').textContent = 'Picks';
  const t = today0();
  const list = picks().filter((ev) => displayDate(ev) >= t || (ev.end && new Date(ev.end) >= t));
  const added = list.filter((ev) => S.status[ev.id] === 'added');
  const maybe = list.filter((ev) => S.status[ev.id] === 'maybe');
  if (!list.length) {
    v.innerHTML = `<div class="empty"><div class="big">💛</div><h2>No picks yet</h2><p>Tap ＋ Add on anything that sounds fun.</p><button class="btn primary" data-goto="plan">Browse my month</button></div>`;
    return;
  }
  v.innerHTML = `${added.length ? `<button class="btn primary block" data-addall>📅 Add all ${added.length} to my calendar</button>` : ''}
    ${added.length ? `<div class="week"><div class="week-head"><h2>Going</h2><span class="meta">${added.length}</span></div>${added.map((ev) => cardHTML(ev)).join('')}</div>` : ''}
    ${maybe.length ? `<div class="week"><div class="week-head"><h2>Maybe</h2><span class="meta">${maybe.length}</span></div>${maybe.map((ev) => cardHTML(ev)).join('')}</div>` : ''}`;
}

function renderMe(v) {
  $('#eyebrow').textContent = 'Your taste';
  $('#title').textContent = 'You';
  const ints = profile ? Object.entries(profile.interests) : [];
  const lv = (k) => (S.interests[k] === undefined ? 1 : S.interests[k]);
  const learned = Object.entries(S.tagW).filter(([t, w]) => Math.abs(w) >= 0.5 && !t.startsWith('src:'))
    .sort((a, b) => b[1] - a[1]);
  const authors = follow ? (follow.authors_favorite || []).length + (follow.authors_new_books || []).length : 0;
  const gen = data.generated ? new Date(data.generated) : null;
  const ago = gen ? Math.round((Date.now() - gen) / 3600e3) : null;
  v.innerHTML = `
  <div class="section"><h2>Interests</h2><p class="sub">Tap to cycle: ♥ love it, like it, not into it. These boost ranking; they never hide events.</p>
    <div class="chips">${ints.map(([k, s]) => `<button class="chip lv${lv(k)}" data-int="${k}">${lv(k) === 2 ? '♥ ' : ''}${esc(s.label)}</button>`).join('')}</div>
    <p class="small" style="margin:12px 0 0">Favorite time: ${esc((profile?.favorite_times || []).map((t) => t.label).join(', ') || 'none')}</p>
  </div>
  <div class="section"><h2>People you follow</h2>
    <p class="sub">Any event naming them gets ⭐. ${authors} authors from Goodreads${S.igHandles.length ? ` · ${S.igHandles.length} Instagram follows` : ''}${S.authorsExtra.length ? ` · ${S.authorsExtra.length} from your latest Goodreads import` : ''}.</p>
    <div class="chips">${S.people.map((p, i) => `<button class="chip" data-rmp="${i}">${esc(p)}<span class="x">✕</span></button>`).join('') || '<span class="small">No comedians or performers added yet.</span>'}</div>
    <form class="field" id="addPerson"><input id="personName" placeholder="Add a comedian, performer, artist…" autocomplete="off"><button class="btn primary">Add</button></form>
    <div class="row-btns" style="margin-top:10px">
      <label class="btn file-btn">Import Instagram follows<input type="file" accept=".json,application/json" id="igFile"></label>
      <label class="btn file-btn">Import Goodreads CSV<input type="file" accept=".csv,text/csv" id="grFile"></label>
    </div>
    <p class="small">Instagram: Settings → Your activity → Download your information → Followers and following (JSON). The app only reads names from the file; it never contacts Instagram.</p>
  </div>
  ${learned.length ? `<div class="section"><h2>What it's learned</h2><p class="sub">From your Add, Maybe and Not for me taps.</p>
    <div class="chips">${learned.slice(0, 14).map(([t, w]) => `<span class="chip">${w > 0 ? '▲' : '▼'} ${esc(t.startsWith('t:') ? t.slice(2).replace('-', ' ') : profile?.interests?.[t]?.label || t)}</span>`).join('')}</div>
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
  const json = JSON.parse(await file.text());
  const list = Array.isArray(json) ? json : (json.relationships_following || json.following || []);
  const handles = [];
  for (const item of list) {
    for (const d of item.string_list_data || []) if (d.value) handles.push(d.value);
    if (item.title && !(item.string_list_data || []).length) handles.push(item.title);
  }
  S.igHandles = [...new Set([...S.igHandles, ...handles])];
  save(); buildFollowIndex();
  toast(`Imported ${handles.length} follows`);
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

function renderHeader() {
  const sw = $('#monthSwitch');
  if (tab === 'plan') {
    sw.hidden = false;
    sw.innerHTML = [0, 1].map((o) => `<button class="pill ${o === monthOffset ? 'on' : ''}" data-month="${o}">${esc(monthRange(o).label)}</button>`).join('');
  } else sw.hidden = true;
  // "my month visibly fills in": one bar per week, taller with each pick
  const { start, end } = monthRange(monthOffset);
  const weeks = [];
  for (let d = weekStart(start); d < end; d = new Date(d.getTime() + 7 * 86400e3 + 3600e3)) weeks.push(weekStart(d).getTime());
  const counts = Object.fromEntries(weeks.map((w) => [w, 0]));
  for (const ev of data.events) {
    if (S.status[ev.id] !== 'added') continue;
    const w = weekStart(displayDate(ev)).getTime();
    if (w in counts) counts[w]++;
  }
  $('#fill').innerHTML = weeks.map((w) => `<span class="wk ${counts[w] ? 'has' : ''}" style="height:${10 + Math.min(4, counts[w]) * 7}px"></span>`).join('');
  const n = newQueue().length;
  const b = $('#newBadge');
  b.hidden = !n; b.textContent = n;
}

function render() {
  renderHeader();
  const v = $('#view');
  ({ plan: renderPlan, new: renderNew, picks: renderPicks, me: renderMe })[tab](v);
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.dataset.tab === tab));
}

function bind() {
  document.querySelector('.tabs').onclick = (e) => {
    const t = e.target.closest('[data-tab]');
    if (!t) return;
    if (tab === 'new' && t.dataset.tab !== 'new') newQueue.lastShown = false;
    tab = t.dataset.tab; render(); window.scrollTo({ top: 0 });
  };
  $('#monthSwitch').onclick = (e) => { const b = e.target.closest('[data-month]'); if (b) { monthOffset = Number(b.dataset.month); render(); window.scrollTo({ top: 0 }); } };
  $('#sheetWrap').onclick = (e) => { if (e.target.hasAttribute('data-close')) closeSheet(); };
  const v = $('#view');
  v.addEventListener('click', (e) => {
    const g = e.target.closest('[data-goto]'); if (g) { tab = g.dataset.goto; return render(); }
    const more = e.target.closest('[data-more]');
    if (more) { const k = Number(more.dataset.more); expanded.has(k) ? expanded.delete(k) : expanded.add(k); return render(); }
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
    const uh = e.target.closest('[data-unhide]'); if (uh) { e.preventDefault(); S.hiddenTags = S.hiddenTags.filter((t) => t !== uh.dataset.unhide); save(); return render(); }
    if (e.target.closest('[data-export]')) return exportBackup();
    onCardClick(e);
  });
  v.addEventListener('submit', (e) => {
    if (e.target.id !== 'addPerson') return;
    e.preventDefault();
    const name = $('#personName').value.trim();
    if (name) { S.people.push(name); save(); buildFollowIndex(); render(); toast(`Following ${name}`); }
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
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
}

start();
