/* Inspectra service worker: the field app opens instantly and keeps working through short signal drops.
   - app shell and static files: stale-while-revalidate
   - /inspect page: network first, cached copy when offline
   - map tiles: cache first (bounded)
   - /api/*: never cached, always live */
const VERSION = 'inspectra-v2';
const SHELL = `${VERSION}-shell`;
const TILES = `${VERSION}-tiles`;
const MAX_TILES = 250;

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/static/css/tokens.css', '/static/img/inspectra-logo.png'])).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (!key.startsWith(VERSION)) await caches.delete(key);
    await self.clients.claim();
  })());
});

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - max; i += 1) await cache.delete(keys[i]);
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (url.origin === location.origin && url.pathname.startsWith('/api/')) return;   // live data only

  if (/tile\.openstreetmap\.org$/.test(url.hostname)) {
    event.respondWith((async () => {
      const cache = await caches.open(TILES);
      const hit = await cache.match(req);
      if (hit) return hit;
      try {
        const res = await fetch(req);
        if (res.ok) { cache.put(req, res.clone()); trim(TILES, MAX_TILES); }
        return res;
      } catch (e) { return Response.error(); }
    })());
    return;
  }

  if (req.mode === 'navigate' && url.origin === location.origin) {
    if (url.pathname !== '/inspect' && url.pathname !== '/inspect/stats') return;                          // other pages: ordinary browsing
    event.respondWith((async () => {
      const cache = await caches.open(SHELL);
      try {
        const res = await fetch(req);
        if (res.ok && !res.redirected) cache.put(req, res.clone());
        return res;
      } catch (e) {
        return (await cache.match(req)) || Response.error();
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
    const refresh = fetch(req).then((res) => { if (res.ok || res.type === 'opaque') cache.put(req, res.clone()); return res; }).catch(() => null);
    return hit || (await refresh) || Response.error();
  })());
});
