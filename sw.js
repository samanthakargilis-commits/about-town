// The app's own files come from the network first, so a new version shows up
// on the next open; the cached copy is only for when the phone is offline or
// the network is slow. events.json and calendar files work the same way.
const VERSION = 'v18';
const SHELL = ['./', 'index.html', 'styles.css', 'app.js', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/apple-touch-icon.png'];
const SLOW_MS = 2500;

self.addEventListener('install', (e) => {
  // cache: 'reload' skips the browser's HTTP cache, so the shell is really this version
  e.waitUntil(caches.open(`shell-${VERSION}`)
    .then((c) => Promise.all(SHELL.map((u) => fetch(u, { cache: 'reload' }).then((r) => r.ok && c.put(u, r)))))
    .then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => !k.endsWith(VERSION)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  const bucket = /\.(json|ics)$/.test(url.pathname) ? `data-${VERSION}` : `shell-${VERSION}`;
  e.respondWith(new Promise((resolve) => {
    let done = false;
    const fallback = () => caches.match(e.request).then((hit) => { if (hit && !done) { done = true; resolve(hit); } });
    const timer = setTimeout(fallback, SLOW_MS);
    fetch(e.request, { cache: 'no-cache' }).then((r) => {
      clearTimeout(timer);
      if (r.ok) { const copy = r.clone(); caches.open(bucket).then((c) => c.put(e.request, copy)); }
      if (!done) { done = true; resolve(r); }
    }).catch(() => {
      clearTimeout(timer);
      caches.match(e.request).then((hit) => { if (!done) { done = true; resolve(hit || Response.error()); } });
    });
  }));
});
