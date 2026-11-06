/* Inspectra service worker: the field app opens instantly, even with no signal, and wakes the phone for offers.
   - app shell (pages and every script/style they need): cached at install, versioned by BUILD so old and new files never mix
   - /inspect pages: network first, cached copy when offline
   - map tiles: cache first (bounded, kept across versions)
   - /api/*: never cached, always live
   - push: shows a notification for a new offer or the end of a break */
const BUILD = '__BUILD__';
const SHELL = `inspectra-shell-${BUILD}`;
const TILES = 'inspectra-tiles';
const MAX_TILES = 250;
const PAGES = ['/inspect', '/inspect/stats'];

const V = `?v=${BUILD}`;
const LOCAL_ASSETS = [
  '/static/css/tokens.css' + V, '/static/css/i18n.css' + V, '/static/css/inspector.css' + V, '/static/css/inspector-flow.css' + V,
  '/static/css/inspector-stats.css' + V,
  '/static/js/i18n-strings.js' + V, '/static/js/i18n-strings-auth.js' + V, '/static/js/i18n-strings-admin.js' + V, '/static/js/i18n.js' + V,
  '/static/js/inspector.js' + V, '/static/js/inspector-stats.js' + V,
  '/static/img/inspectra-logo.png', '/static/img/inspectra-mark.png', '/static/img/icon-192.png',
];
const CDN_ASSETS = [
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL);
    // Best effort: one missing file must not stop the worker from installing.
    await Promise.allSettled([
      ...LOCAL_ASSETS.map((u) => cache.add(u)),
      ...CDN_ASSETS.map((u) => cache.add(new Request(u, { mode: 'no-cors' }))),
      ...PAGES.map((u) => cache.add(u)),
    ]);
  })());
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== SHELL && key !== TILES) await caches.delete(key);
    await self.clients.claim();
  })());
});

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - max; i += 1) await cache.delete(keys[i]);
}

self.addEventListener('message', (event) => {
  // After log out the cached pages (they hold the person's name) are removed.
  if (event.data === 'logout') event.waitUntil(caches.open(SHELL).then((c) => Promise.all(PAGES.map((p) => c.delete(p)))));
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (url.origin === location.origin && url.pathname.startsWith('/api/')) return;   // live data only

  if (/tile\.openstreetmap\.org$/.test(url.hostname)) {
    // The a/b/c subdomains serve identical tiles: one cache entry per tile, not three.
    const key = new Request(`https://tile.openstreetmap.org${url.pathname}`);
    event.respondWith((async () => {
      const cache = await caches.open(TILES);
      const hit = await cache.match(key);
      if (hit) return hit;
      try {
        const res = await fetch(req);
        if (res.ok) event.waitUntil(cache.put(key, res.clone()).then(() => trim(TILES, MAX_TILES)));
        return res;
      } catch (e) { return Response.error(); }
    })());
    return;
  }

  if (req.mode === 'navigate' && url.origin === location.origin) {
    if (!PAGES.includes(url.pathname)) return;                                  // other pages: ordinary browsing
    event.respondWith((async () => {
      const cache = await caches.open(SHELL);
      try {
        const res = await fetch(req);
        if (res.ok && !res.redirected) event.waitUntil(cache.put(url.pathname, res.clone()));
        return res;
      } catch (e) {
        return (await cache.match(url.pathname)) || Response.error();
      }
    })());
    return;
  }

  const cacheable = url.origin === location.origin ? url.pathname.startsWith('/static/')
    : /(unpkg\.com|cdnjs\.cloudflare\.com|fonts\.googleapis\.com|fonts\.gstatic\.com)$/.test(url.hostname);
  if (!cacheable) return;
  event.respondWith((async () => {
    const cache = await caches.open(SHELL);
    const hit = await cache.match(req);
    if (hit) {   // versioned files never change; the rest refresh quietly for next time
      if (!url.search) event.waitUntil(fetch(req).then((res) => { if (res.ok || res.type === 'opaque') return cache.put(req, res); return null; }).catch(() => null));
      return hit;
    }
    try {
      const res = await fetch(req);
      if (res.ok || res.type === 'opaque') event.waitUntil(cache.put(req, res.clone()));
      return res;
    } catch (e) { return Response.error(); }
  })());
});

// ---- push: an offer or the end of a break while the app is closed or the phone is locked ----
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { /* plain text push */ }
  const title = data.title || 'Inspectra';
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || '',
    tag: data.tag || 'inspectra',
    renotify: true,
    icon: '/static/img/icon-192.png',
    badge: '/static/img/icon-192.png',
    vibrate: [200, 100, 200, 100, 200],
    data: { url: data.url || '/inspect' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/inspect';
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of open) {
      if (new URL(client.url).pathname === target && 'focus' in client) return client.focus();
    }
    return self.clients.openWindow(target);
  })());
});
