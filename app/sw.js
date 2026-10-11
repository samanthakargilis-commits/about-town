// App shell is cached for instant, offline starts; events.json and calendar
// files always try the network first so the plan is fresh.
const VERSION = 'v8';
const SHELL = ['./', 'index.html', 'styles.css', 'app.js', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/apple-touch-icon.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(`shell-${VERSION}`).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => !k.endsWith(VERSION)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  const fresh = /\.(json|ics)$/.test(url.pathname);
  if (fresh) {
    e.respondWith(fetch(e.request).then((r) => {
      const copy = r.clone();
      caches.open(`data-${VERSION}`).then((c) => c.put(e.request, copy));
      return r;
    }).catch(() => caches.match(e.request)));
  } else {
    e.respondWith(caches.match(e.request).then((hit) => {
      const net = fetch(e.request).then((r) => { const copy = r.clone(); caches.open(`shell-${VERSION}`).then((c) => c.put(e.request, copy)); return r; });
      return hit || net;
    }));
  }
});
