/* Inspectra field app: splash -> swipe to go online -> search -> assignment offer -> ride flow, with live arrivals. */
(() => {
  'use strict';

  const { t } = window.I18n;

  // ---------------- config ----------------
  const POLL_MS = 20000;            // arrivals refresh; the server caches SIRI per stop so this is cheap
  const SEARCH_MS = 10000;          // how often we look for an assignment while online
  const OFFER_SECONDS = 30;
  const DECLINE_TTL_MS = 3 * 60 * 1000;
  const STALE_AFTER_MS = 60000;
  const REPOSITION_POLL_M = 150;
  const REPORT_POSITION_MS = 30000;
  const BUS_REMOVE_AFTER_MS = 90000;
  const SPLASH_MIN_MS = 600;
  const API_TIMEOUT_MS = 12000;     // a stalled request must never freeze polling or the splash
  const SHIFT_KEY = 'inspectra.online';
  const SHIFT_RESUME_MS = 30 * 60 * 1000;   // a shift is offered back if the app was closed less than this long ago
  const RADIUS_OPTIONS = [300, 500, 666, 1000, 1500];
  const GOAL_OPTIONS = [5, 10, 15, 20];
  const BREAK_PRESETS = [15, 30, 45, 60];
  const BREAK_REASONS = ['lunch', 'rest', 'other'];
  const BREAK_MIN = 5, BREAK_EXTEND = 10;
  const QUEUE_KEY = 'inspectra.queue';
  const DEMO = document.documentElement.dataset.debug === '1' && new URLSearchParams(location.search).has('demo');   // fake position: development only
  const DEMO_POSITION = [32.0880, 34.7898];

  // ---------------- helpers ----------------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const bdi = (s) => `<bdi>${esc(s)}</bdi>`;
  const isRtl = () => document.documentElement.dir === 'rtl';

  async function api(path, method = 'GET', body) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), API_TIMEOUT_MS);
    try {
      const resp = await fetch(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
        signal: ctl.signal,
      });
      if (resp.status === 401) showSessionExpired();
      else setNetDown(false);
      return { ok: resp.ok, status: resp.status, data: await resp.json().catch(() => ({})) };
    } catch (err) {
      setNetDown(true);      // no answer in time counts as no connection: the work is kept and retried
      return { ok: false, status: 0, data: {} };
    } finally {
      clearTimeout(timer);
    }
  }

  function toast(message, kind = '') {
    const el = document.createElement('div');
    el.className = `toast${kind ? ` toast--${kind}` : ''}`;
    el.textContent = message;
    $('toasts').appendChild(el);
    setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3500);
  }

  function distanceM(a, b) {
    const R = 6371000, rad = Math.PI / 180;
    const dLat = (b[0] - a[0]) * rad, dLon = (b[1] - a[1]) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  // ---------------- connection, offline queue, session ----------------
  let netDown = false, netOkTimer = null;

  function renderNet() {
    const bar = $('netBanner'), down = netDown || !navigator.onLine;
    const queued = readQueue().length;
    if (down) {
      clearTimeout(netOkTimer);
      bar.classList.remove('is-ok');
      $('netText').textContent = t('i.net.offline') + (queued ? ` ${t('i.net.queued', { n: queued })}` : '');
      bar.hidden = false;
    } else if (!bar.classList.contains('is-ok')) bar.hidden = true;
  }
  function setNetDown(value) {
    if (value === netDown) return;
    netDown = value;
    if (!value && !$('netBanner').hidden) {                     // reconnected: say so briefly, then sync
      const bar = $('netBanner');
      bar.classList.add('is-ok');
      $('netText').textContent = t('i.net.back');
      clearTimeout(netOkTimer);
      netOkTimer = setTimeout(() => { bar.classList.remove('is-ok'); renderNet(); }, 2500);
      flushQueue();
      return;
    }
    renderNet();
  }

  function showSessionExpired() { const o = $('sessionOverlay'); if (o) o.hidden = false; }

  // Actions that could not reach the server (finishing a ride, the fine counter) wait here and are retried.
  function readQueue() { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); } catch (e) { return []; } }
  function writeQueue(q) { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)); } catch (e) { /* ignore */ } renderNet(); }
  function enqueue(path, method, body) {
    let q = readQueue();
    if (method === 'PATCH') q = q.filter((x) => !(x.path === path && x.method === 'PATCH'));  // only the latest count matters
    if (/\/complete$/.test(path)) q = q.filter((x) => !x.path.startsWith(path.replace(/\/complete$/, '/progress')));
    q.push({ path, method, body });
    writeQueue(q);
  }
  let flushing = false;
  async function flushQueue() {
    if (flushing) return;
    flushing = true;
    try {
      let q = readQueue(), done = 0;
      while (q.length) {
        const item = q[0];
        const res = await api(item.path, item.method, item.body);
        if (res.status === 0 || res.status === 401 || res.status >= 500) break;   // try again later
        q = readQueue().slice(1);                                                  // delivered, or refused for good
        writeQueue(q);
        if (res.ok) done += 1;
        else toast(t('i.toast.saveFail', { err: res.data.error || '' }), 'error');
      }
      if (done && !readQueue().length) { toast(t('i.net.synced'), 'ok'); refreshMe(); }
    } finally { flushing = false; }
  }

  // ---------------- settings (per device) ----------------
  const settings = (() => {
    const defaults = { radius: 666, sound: true, vibrate: true, awake: true, size: 'm', contrast: false, goal: 10 };
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('inspectra.settings') || '{}'); } catch (e) { /* ignore */ }
    const s = { ...defaults, ...saved };
    if (!RADIUS_OPTIONS.includes(s.radius)) s.radius = defaults.radius;
    if (!['m', 'l', 'xl'].includes(s.size)) s.size = defaults.size;
    if (!GOAL_OPTIONS.includes(s.goal)) s.goal = defaults.goal;
    return s;
  })();
  function saveSettings() {
    try { localStorage.setItem('inspectra.settings', JSON.stringify(settings)); } catch (e) { /* ignore */ }
  }

  // ---------------- state ----------------
  let map, meMarker = null, userLatLng = null;
  let mode = 'offline';                       // offline | searching | offer | ride
  let rideState = 'enroute';                  // enroute | waiting | onride | resumed | completed
  let currentRunId = null, trip = null;
  let me = { name: document.body.dataset.name || '', today_runs: 0, today_fines: 0, total_runs: 0, total_fines: 0 };
  let arrivals = [], selectedKey = null;
  let lastGoodPoll = null, pollError = null, pollTimer = null, pollInFlight = false, lastPolledFrom = null;
  let lastReport = 0, geoStatus = 'waiting';  // waiting | ok | denied | error | unsupported
  let searchTimer = null, searching = false;
  let offer = null, offerTimer = null, offerEndsAt = 0;
  const declined = new Map();                 // "route:stop" -> expiry timestamp
  const snoozedRuns = new Map();              // runId -> until
  const layers = { stop: null, shape: null, walk: null, walkChip: null };
  const buses = new Map();
  let wakeLock = null;
  let rideFines = 0, fineSaveTimer = null;     // running fine count of the current ride

  // ---------------- map ----------------
  function initMap() {
    map = L.map('map', { zoomControl: false, attributionControl: true }).setView([32.0853, 34.7818], 14);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    map.attributionControl.setPrefix(false);
  }

  const meIcon = () => L.divIcon({ className: '', html: '<div class="me-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 11] });
  const stopIcon = () => L.divIcon({ className: '', html: '<div class="stop-pin"><i class="fa-solid fa-bus-simple" aria-hidden="true"></i></div>', iconSize: [36, 36], iconAnchor: [18, 18] });

  function busIcon(arrival, selected) {
    const dir = Number.isFinite(arrival.bearing) ? `<span class="bus-pin__dir" style="transform:rotate(${arrival.bearing}deg)"></span>` : '';
    return L.divIcon({ className: '', html: `<div class="bus-pin${selected ? ' is-selected' : ''}">${dir}${esc(arrival.route_num)}</div>`, iconSize: [40, 40], iconAnchor: [20, 20] });
  }

  function clearRideLayers() {
    for (const key of Object.keys(layers)) {
      if (layers[key]) { map.removeLayer(layers[key]); layers[key] = null; }
    }
  }

  function recenter() {
    if (userLatLng) map.flyTo(userLatLng, Math.max(map.getZoom(), 16), { duration: 0.6 });
    else toast(t('i.toast.noLoc'));
  }

  // ---------------- live buses on the map ----------------
  function animateTo(entry, lat, lon) {
    cancelAnimationFrame(entry.raf);
    const from = entry.marker.getLatLng(), t0 = performance.now(), DURATION = 1200;
    const step = (now) => {
      const k = Math.min(1, (now - t0) / DURATION), e = 1 - Math.pow(1 - k, 3);
      entry.marker.setLatLng([from.lat + (lat - from.lat) * e, from.lng + (lon - from.lng) * e]);
      if (k < 1) entry.raf = requestAnimationFrame(step);
    };
    entry.raf = requestAnimationFrame(step);
  }

  function syncBusMarkers() {
    const now = Date.now(), seen = new Set();
    for (const a of arrivals) {
      const loc = a.vehicle_location;
      if (!a.vehicle_ref || !loc || seen.has(a.vehicle_ref)) continue;
      seen.add(a.vehicle_ref);
      const selected = rowKey(a) === selectedKey;
      let entry = buses.get(a.vehicle_ref);
      if (!entry) {
        const marker = L.marker([loc.lat, loc.lon], { icon: busIcon(a, selected), zIndexOffset: 500, keyboard: false }).addTo(map);
        marker.on('click', () => selectArrival(rowKey(a), false));
        entry = { marker, seen: now, raf: 0 };
        buses.set(a.vehicle_ref, entry);
      } else {
        entry.marker.setIcon(busIcon(a, selected));
        animateTo(entry, loc.lat, loc.lon);
      }
      entry.seen = now;
    }
    for (const [ref, entry] of buses) {
      if (seen.has(ref)) continue;
      if (now - entry.seen > BUS_REMOVE_AFTER_MS) { cancelAnimationFrame(entry.raf); map.removeLayer(entry.marker); buses.delete(ref); }
      else entry.marker.getElement()?.querySelector('.bus-pin')?.classList.add('is-stale');
    }
  }

  // ---------------- arrivals board ----------------
  const rowKey = (a) => `${a.vehicle_ref || a.route_num}@${a.stop_code}`;
  const minText = (n) => t('i.unit.min', { n });

  function etaParts(a) {
    const ms = Date.parse(a.arrival_at) - Date.now();
    if (!Number.isFinite(ms)) return { text: String(Math.max(0, Math.round(a.minutes_until_arrival))), unit: t('i.eta.min'), soon: false, gone: false };
    if (ms < -30000) return { text: '—', unit: '', soon: false, gone: true };
    if (ms < 60000) return { text: t('i.eta.now'), unit: '', soon: true, gone: false };
    return { text: String(Math.floor(ms / 60000)), unit: t('i.eta.min'), soon: ms < 180000, gone: false };
  }

  function renderBoard() {
    const board = $('board');
    if (mode === 'offline' && !userLatLng) { board.innerHTML = `<li class="board__state">${esc(geoMessage() || t('i.board.locWait'))}</li>`; return; }
    if (!userLatLng) { board.innerHTML = `<li class="board__state ${geoStatus === 'waiting' ? '' : 'board__state--error'}">${esc(geoMessage() || t('i.board.locWait'))}</li>`; return; }
    if (!arrivals.length) {
      if (lastGoodPoll === null && !pollError) board.innerHTML = '<li><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></li>';
      else if (pollError) {
        board.innerHTML = `<li class="board__state board__state--error">${esc(t('i.board.error'))} ${esc(pollError)}<br><button type="button" class="btn btn--ghost" id="retryBtn">${esc(t('i.board.retry'))}</button></li>`;
        $('retryBtn')?.addEventListener('click', () => pollArrivals(true));
      } else board.innerHTML = `<li class="board__state">${esc(t('i.board.empty', { r: settings.radius }))}</li>`;
      return;
    }
    board.innerHTML = arrivals.map((a) => {
      const eta = etaParts(a), key = rowKey(a);
      const sub = [a.stop_name ? bdi(a.stop_name) : null, a.stop_distance_m != null ? t('i.unit.m', { n: esc(a.stop_distance_m) }) : null].filter(Boolean).join(' · ');
      const tag = a.is_live
        ? `<span class="arrival__tag"><i class="fa-solid fa-tower-broadcast" aria-hidden="true"></i> ${esc(t('i.board.live'))}</span>`
        : `<span class="arrival__tag arrival__tag--sched"><i class="fa-regular fa-clock" aria-hidden="true"></i> ${esc(t('i.board.sched'))}</span>`;
      const dest = a.destination || t('i.board.destUnknown');
      return `<li><button type="button" class="arrival${key === selectedKey ? ' is-selected' : ''}${eta.soon ? ' is-soon' : ''}${eta.gone ? ' is-gone' : ''}" data-key="${esc(key)}" aria-label="${esc(t('i.board.rowAria', { line: a.route_num, dest, eta: `${eta.text} ${eta.unit}` }))}">
        <span class="route-badge">${esc(a.route_num)}</span>
        <span class="arrival__main"><span class="arrival__dest">${bdi(dest)}</span><span class="arrival__sub">${sub}</span></span>
        <span class="arrival__eta"><span class="arrival__min">${esc(eta.text)}${eta.unit ? `<small>${esc(eta.unit)}</small>` : ''}</span>${tag}</span>
      </button></li>`;
    }).join('');
  }

  function tickCountdowns() {
    $('board').querySelectorAll('.arrival').forEach((row) => {
      const a = arrivals.find((x) => rowKey(x) === row.dataset.key);
      if (!a) return;
      const eta = etaParts(a);
      const html = `${esc(eta.text)}${eta.unit ? `<small>${esc(eta.unit)}</small>` : ''}`;
      const min = row.querySelector('.arrival__min');
      if (min.innerHTML !== html) min.innerHTML = html;
      row.classList.toggle('is-soon', eta.soon);
      row.classList.toggle('is-gone', eta.gone);
    });
    updateChip();
    if (mode === 'ride') updateRideLive();
  }

  function selectArrival(key, openSheet = true) {
    selectedKey = key;
    const a = arrivals.find((x) => rowKey(x) === key);
    renderBoard();
    syncBusMarkers();
    if (!a) return;
    const loc = a.vehicle_location;
    if (loc) map.flyTo([loc.lat, loc.lon], Math.max(map.getZoom(), 16), { duration: 0.6 });
    else toast(t('i.toast.noPos', { line: a.route_num }));
    if (openSheet && sheet.snap === 'full') sheet.go('half');
  }

  const agoText = (ms) => {
    const secs = Math.max(0, Math.round(ms / 1000));
    return secs < 60 ? t('i.ago.s', { n: secs }) : t('i.ago.m', { n: Math.round(secs / 60) });
  };

  function updateChip() {
    const chip = $('liveChip'), text = $('liveChipText'), meta = $('boardMeta');
    chip.hidden = mode === 'offline';
    let cls = 'chip--idle', label = t('i.chip.locating'), metaText = '';
    if (geoStatus === 'denied' || geoStatus === 'error' || geoStatus === 'unsupported') { cls = 'chip--down'; label = t('i.chip.locOff'); }
    else if (userLatLng) {
      if (pollError && lastGoodPoll === null) { cls = 'chip--down'; label = t('i.chip.down'); }
      else if (lastGoodPoll === null) label = t('i.chip.loading');
      else {
        const age = Date.now() - lastGoodPoll, ago = agoText(age);
        if (pollError || age > STALE_AFTER_MS) { cls = 'chip--stale'; label = t('i.chip.delayed', { ago }); }
        else { cls = 'chip--live'; label = t('i.chip.live', { ago }); }
        metaText = t('i.board.updated', { ago });
      }
    }
    chip.className = `chip ${cls}`;
    if (text.textContent !== label) text.textContent = label;
    meta.textContent = metaText;
  }

  async function pollArrivals(force = false) {
    if (!userLatLng || pollInFlight) return;
    if (document.hidden && !force) return;
    pollInFlight = true;
    const [lat, lon] = userLatLng;
    const res = await api(`/api/arrivals?lat=${lat}&lon=${lon}&radius=${settings.radius}`);
    pollInFlight = false;
    lastPolledFrom = [lat, lon];
    if (res.status === 401) return;
    if (!res.ok || res.data.source === 'error' || res.data.source === 'unavailable') {
      pollError = res.status === 0 ? t('i.err.offline') : t('i.err.feed');
    } else {
      pollError = null;
      lastGoodPoll = Date.now();
      arrivals = res.data.arrivals || [];
      if (selectedKey && !arrivals.some((a) => rowKey(a) === selectedKey)) selectedKey = null;
    }
    renderBoard();
    syncBusMarkers();
    updateChip();
    updateRideLive();
  }

  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(() => pollArrivals(), POLL_MS);
    pollArrivals(true);
  }

  // ---------------- geolocation ----------------
  function geoMessage() {
    return { denied: t('i.board.locBlocked'), error: t('i.board.locFail'), unsupported: t('i.board.noGeo') }[geoStatus] || '';
  }

  function onPosition(lat, lon) {
    const first = userLatLng === null;
    userLatLng = [lat, lon];
    geoStatus = 'ok';
    if (!meMarker) meMarker = L.marker(userLatLng, { icon: meIcon(), keyboard: false, zIndexOffset: 1000 }).addTo(map);
    else meMarker.setLatLng(userLatLng);

    if (first) {
      map.setView(userLatLng, 16);
      renderBoard();
      startPolling();
      if (mode === 'searching') scheduleSearch(300);
    } else if (lastPolledFrom && distanceM(lastPolledFrom, userLatLng) > REPOSITION_POLL_M) pollArrivals(true);

    const now = Date.now();
    if (now - lastReport > REPORT_POSITION_MS) {
      lastReport = now;
      api('/api/me/status', 'PUT', { latitude: lat, longitude: lon });
    }
    updateChip();
    updateRideLive();
  }

  let lastGeoToast = 0;
  function startGeolocation() {
    if (DEMO) { onPosition(...DEMO_POSITION); window.__setDemoPosition = (lat, lon) => onPosition(lat, lon); return; }  // demo: fixed position, movable from the console
    if (!navigator.geolocation) { geoStatus = 'unsupported'; renderBoard(); updateChip(); return; }
    navigator.geolocation.watchPosition(
      (pos) => onPosition(pos.coords.latitude, pos.coords.longitude),
      (err) => {
        geoStatus = err.code === 1 ? 'denied' : 'error';
        renderBoard();
        updateChip();
        if (Date.now() - lastGeoToast > 60000) { lastGeoToast = Date.now(); toast(t(err.code === 1 ? 'i.toast.locDenied' : 'i.toast.locFail'), 'error'); }
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    );
  }

  // ---------------- bottom sheet ----------------
  const sheetEl = $('sheet');
  const sheet = {
    snap: 'half',
    offsets: { full: 0, half: 0, peek: 0 },
    desktop: () => window.matchMedia('(min-width: 900px)').matches,
    measure() {
      const h = sheetEl.offsetHeight;
      const peekVisible = $('sheetHandle').offsetHeight + document.querySelector('.sheet__head').offsetHeight;
      const halfVisible = Math.min(h, Math.max(peekVisible + 180, window.innerHeight * 0.52));
      this.offsets = { full: 0, half: Math.max(0, h - halfVisible), peek: Math.max(0, h - peekVisible) };
    },
    apply(offset, animate = true) {
      sheetEl.classList.toggle('is-dragging', !animate);
      if (this.desktop()) {
        sheetEl.style.removeProperty('--sheet-offset');
        document.documentElement.style.removeProperty('--sheet-visible');
        return;
      }
      sheetEl.style.setProperty('--sheet-offset', `${offset}px`);
      document.documentElement.style.setProperty('--sheet-visible', `${sheetEl.offsetHeight - offset}px`);
    },
    go(name) {
      this.snap = name;
      this.measure();
      this.apply(this.offsets[name]);
      $('sheetHandle').setAttribute('aria-expanded', String(name !== 'peek'));
    },
    nearest(offset, velocity) {
      const projected = offset + velocity * 160;
      return Object.keys(this.offsets).reduce((best, n) => (Math.abs(this.offsets[n] - projected) < Math.abs(this.offsets[best] - projected) ? n : best), 'half');
    },
    refresh() { requestAnimationFrame(() => { this.measure(); this.apply(this.offsets[this.snap]); }); },
  };

  function initSheet() {
    const handle = $('sheetHandle');
    let startY = 0, startOffset = 0, lastY = 0, lastT = 0, velocity = 0, moved = false, active = false;
    handle.addEventListener('pointerdown', (e) => {
      active = true; moved = false; startY = lastY = e.clientY; lastT = e.timeStamp; velocity = 0;
      startOffset = sheet.offsets[sheet.snap];
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove', (e) => {
      if (!active) return;
      const dy = e.clientY - startY;
      if (Math.abs(dy) > 4) moved = true;
      velocity = (e.clientY - lastY) / Math.max(1, e.timeStamp - lastT);
      lastY = e.clientY; lastT = e.timeStamp;
      sheet.apply(Math.min(sheet.offsets.peek, Math.max(0, startOffset + dy)), false);
    });
    const end = (e) => {
      if (!active) return;
      active = false;
      if (!moved) { sheet.go({ peek: 'half', half: 'full', full: 'peek' }[sheet.snap]); return; }
      sheet.go(sheet.nearest(Math.min(sheet.offsets.peek, Math.max(0, startOffset + (e.clientY - startY))), velocity));
    };
    handle.addEventListener('click', (e) => { if (e.detail === 0) sheet.go({ peek: 'half', half: 'full', full: 'peek' }[sheet.snap]); });
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowUp') sheet.go(sheet.snap === 'peek' ? 'half' : 'full');
      if (e.key === 'ArrowDown') sheet.go(sheet.snap === 'full' ? 'half' : 'peek');
    });
    window.addEventListener('resize', () => sheet.go(sheet.snap));
    sheet.go('half');
  }

  // ---------------- modes ----------------
  function setMode(next, snap) {
    mode = next;
    const app = $('app');
    app.dataset.mode = next;
    app.classList.toggle('is-offline', next === 'offline');
    $('modeOffline').hidden = next !== 'offline';
    $('modeSearching').hidden = next !== 'searching';
    $('modeBreak').hidden = next !== 'break';
    $('modeRide').hidden = next !== 'ride';
    $('offer').hidden = next !== 'offer';
    const online = next !== 'offline';
    const pill = $('statusPill');
    pill.className = `pill ${next === 'break' ? 'pill--break' : online ? 'pill--on' : 'pill--off'}`;
    $('statusText').textContent = statusLabel();
    if (next !== 'break') stopBreakTimer();
    if (next !== 'ride') sheetEl.classList.remove('is-complete');   // the green "ride saved" look belongs to the ride screen only
    renderModeCopy();
    updateChip();
    sheet.go(snap || (next === 'ride' ? 'peek' : 'half'));
  }

  const statusLabel = () => t(mode === 'break' ? 'i.status.break' : mode === 'offline' ? 'i.status.offline' : 'i.status.online');

  function renderModeCopy() {
    $('statusText').textContent = statusLabel();
    if (mode === 'ride') renderRide();
    $('accountName').textContent = me.name || '';
  }

  // ---------------- swipe sliders (go online / end shift) ----------------
  function initSwipe(track, onDone) {
    const THUMB = 56;   // thumb diameter, see .swipe__thumb
    let startX = 0, max = 0, dragging = false, x = 0, dir = 1, finished = false, buzzed = false;

    const measure = () => { max = Math.max(0, track.clientWidth - THUMB - 8); };
    const set = (px, animate) => {
      x = Math.max(0, Math.min(max, px));
      track.classList.toggle('is-dragging', !animate);
      track.style.setProperty('--x', `${dir * x}px`);
      track.style.setProperty('--w', `${x + THUMB + 8}px`);
      track.style.setProperty('--p', max ? (x / max).toFixed(3) : 0);
      track.setAttribute('aria-valuenow', String(Math.round((max ? x / max : 0) * 100)));
    };
    const reset = () => { finished = false; track.classList.remove('is-done'); measure(); set(0, true); };
    const complete = () => {
      if (finished) return;
      finished = true;
      set(max, true);
      track.classList.add('is-done');
      if (navigator.vibrate) navigator.vibrate(30);
      setTimeout(() => { onDone(); setTimeout(reset, 400); }, 260);
    };

    track.addEventListener('pointerdown', (e) => {
      if (finished) return;
      dir = isRtl() ? -1 : 1;
      measure();
      dragging = true; buzzed = false; startX = e.clientX;
      track.setPointerCapture(e.pointerId);
      track.classList.add('is-dragging');
    });
    track.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      set((e.clientX - startX) * dir, false);
      if (!buzzed && max && x / max >= 0.82) { buzzed = true; if (navigator.vibrate) navigator.vibrate(12); }  // "release now" tick
    });
    const end = () => {
      if (!dragging) return;
      dragging = false;
      if (max && x / max >= 0.82) complete(); else set(0, true);
    };
    track.addEventListener('pointerup', end);
    track.addEventListener('pointercancel', end);
    track.addEventListener('keydown', (e) => {
      if (['Enter', ' ', 'ArrowRight', 'ArrowLeft'].includes(e.key)) { e.preventDefault(); dir = isRtl() ? -1 : 1; measure(); complete(); }
    });
    window.addEventListener('resize', () => { if (!dragging && !finished) reset(); });
    reset();
  }

  // ---------------- going online / offline ----------------
  function rememberShift(on) {
    try { if (on) localStorage.setItem(SHIFT_KEY, String(Date.now())); else localStorage.removeItem(SHIFT_KEY); } catch (e) { /* ignore */ }
  }
  function shiftWasRecent() {
    try { return Date.now() - Number(localStorage.getItem(SHIFT_KEY) || 0) < SHIFT_RESUME_MS; } catch (e) { return false; }
  }
  async function goOnline(silent = false) {
    rememberShift(true);
    setMode('searching');
    if (!silent) toast(t('i.toast.online'), 'ok');
    requestWakeLock();
    const res = await api('/api/me/status', 'PUT', { available: true });
    if (!res.ok) toast(t('i.toast.statusFail'), 'error');
    scheduleSearch(400);
  }

  async function goOffline() {
    rememberShift(false);
    clearTimeout(searchTimer);
    releaseWakeLock();
    clearRideLayers();
    setMode('offline');
    toast(t('i.toast.offlineNow'));
    const res = await api('/api/me/status', 'PUT', { available: false });
    if (!res.ok) toast(t('i.toast.statusFail'), 'error');
    refreshMe();
  }

  async function requestWakeLock() {
    if (!settings.awake || !('wakeLock' in navigator) || wakeLock) return;
    try { wakeLock = await navigator.wakeLock.request('screen'); wakeLock.addEventListener('release', () => { wakeLock = null; }); } catch (e) { /* not allowed */ }
  }
  function releaseWakeLock() { try { wakeLock?.release(); } catch (e) { /* ignore */ } wakeLock = null; }

  // ---------------- searching for an assignment ----------------
  function scheduleSearch(delay = SEARCH_MS) {
    clearTimeout(searchTimer);
    if (mode !== 'searching') return;
    searchTimer = setTimeout(searchTick, delay);
  }

  function pruneDeclined() {
    const now = Date.now();
    for (const [k, until] of declined) if (until < now) declined.delete(k);
    for (const [k, until] of snoozedRuns) if (until < now) snoozedRuns.delete(k);
  }

  async function searchTick() {
    if (mode !== 'searching' || searching) return;
    if (!userLatLng) { scheduleSearch(1500); return; }
    searching = true;
    try {
      // 1) an assignment from the manager waits for the inspector's answer
      const current = await api('/api/runs/current');
      if (current.status === 401) return;
      pruneDeclined();
      const run = current.data?.run;
      if (run && run.status === 'assigned' && !snoozedRuns.has(run.id)) {
        const d = await api(`/api/runs/${run.id}/details`);
        if (mode === 'searching') showOffer({ kind: 'assigned', run, details: d.data?.details || {} });
        return;
      }
      if (run && run.status === 'accepted') { await resumeRun(run); return; }

      // 2) otherwise ask for the best bus right now, skipping what was declined
      const exclude = [...declined.keys()].map((k) => { const [route_id, stop_id] = k.split('|'); return { route_id, stop_id }; });
      const [lat, lon] = userLatLng;
      const res = await api('/api/find_best_trip', 'POST', { lat, lon, buffer: 3, radius: settings.radius, ...(exclude.length ? { exclude } : {}) });
      if (mode !== 'searching') return;
      if (res.status === 401) return;
      if (res.ok && res.data.best_option) showOffer({ kind: 'recommended', json: res.data });
    } finally {
      searching = false;
      if (mode === 'searching') scheduleSearch();
    }
  }

  // ---------------- assignment offer ----------------
  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [660, 880].forEach((freq, i) => {
        const o = ctx.createOscillator(), g = ctx.createGain(), t0 = ctx.currentTime + i * 0.18;
        o.type = 'sine'; o.frequency.value = freq; o.connect(g); g.connect(ctx.destination);
        g.gain.setValueAtTime(0.0001, t0);
        g.gain.exponentialRampToValueAtTime(0.25, t0 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
        o.start(t0); o.stop(t0 + 0.18);
      });
      setTimeout(() => ctx.close(), 800);
    } catch (e) { /* audio blocked */ }
  }

  // the live bus matching an offer (same line at the same stop), from the arrivals board
  // The static timetable and the live feed do not always share route ids (one line has several variants), so fall back to
  // the line number at the same stop (by id, then by name). The soonest upcoming bus wins.
  function matchArrival(routeId, stopId, line, stopName) {
    const upcoming = (a) => !(Date.parse(a.arrival_at) - Date.now() < -30000);
    const pick = (list) => list.filter(upcoming).sort((x, y) => Date.parse(x.arrival_at) - Date.parse(y.arrival_at))[0] || null;
    const same = (x, y) => x != null && y != null && String(x) === String(y);
    return pick(arrivals.filter((a) => same(a.route_id, routeId) && same(a.stop_id, stopId)))
      || (line != null ? pick(arrivals.filter((a) => same(a.route_num, line) && same(a.stop_id, stopId)))
        || (stopName ? pick(arrivals.filter((a) => same(a.route_num, line) && same(a.stop_name, stopName))) : null) : null);
  }

  function offerView(o) {
    if (o.kind === 'recommended') {
      const best = o.json.best_option, props = o.json.stop_feature?.properties || {};
      const arrival = matchArrival(best.route_id, props.stop_id ?? best.stop_id, best.route_num, props.stop_name);
      return {
        line: best.route_num || '?', dest: best.destination || t('i.board.destUnknown'),
        stopName: props.stop_name || '', stopCode: props.stop_code || '',
        walk: Number.isFinite(best.walk_time) ? best.walk_time : null,
        bus: Number.isFinite(best.minutes_until_arrival) ? best.minutes_until_arrival : null,
        fines: Number.isFinite(best.potential_fines) ? best.potential_fines : null,
        source: t(o.json.is_live ? 'i.offer.srcLive' : 'i.offer.srcSched'),
        stopFeature: o.json.stop_feature, walkGeometry: best.route_geometry, shape: o.json.shape_feature,
        vehicle: o.json.vehicle_location || arrival?.vehicle_location || null, arrival,
      };
    }
    const d = o.details || {}, props = d.stop_feature?.properties || {};
    const arrival = matchArrival(d.route_id, o.run.stop_id ?? props.stop_id, d.route_num, props.stop_name);
    const stopLL = d.stop_feature?.geometry?.coordinates ? [d.stop_feature.geometry.coordinates[1], d.stop_feature.geometry.coordinates[0]] : null;
    const walk = stopLL && userLatLng ? Math.max(1, Math.round(distanceM(userLatLng, stopLL) * 1.3 / 80)) : null;  // ~80 m/min, 30% for street layout
    return {
      line: d.route_num || '?', dest: d.destination || t('i.board.destUnknown'),
      stopName: props.stop_name || '', stopCode: props.stop_code || '',
      walk, bus: arrival ? arrival.minutes_until_arrival : null,
      fines: Number.isFinite(o.run.potential_fines) ? o.run.potential_fines : null,
      source: t('i.offer.srcManager'), stopFeature: d.stop_feature, walkGeometry: null, shape: d.shape_feature,
      vehicle: arrival?.vehicle_location || null, arrival, stopLL,
    };
  }

  /** Can the inspector reach the stop before the bus? Returns { kind, margin } or null when a number is missing. */
  function verdictOf(v) {
    if (v.walk == null || v.bus == null) return null;
    const margin = Math.round(v.bus - v.walk);
    return { kind: margin >= 2 ? 'good' : margin >= 0 ? 'tight' : 'miss', margin };
  }

  function renderOffer() {
    if (!offer) return;
    const v = offerView(offer);
    $('offerLine').textContent = v.line;
    $('offerDest').innerHTML = bdi(v.dest);
    $('offerStop').innerHTML = v.stopName ? t('i.offer.stopLine', { stop: bdi(v.stopName), code: esc(v.stopCode) }) : '';
    $('offerWalk').textContent = v.walk != null ? minText(Math.max(1, Math.round(v.walk))) : '—';
    $('offerBus').textContent = v.bus != null ? minText(Math.max(1, Math.round(v.bus))) : '—';
    $('offerFines').textContent = v.fines != null ? v.fines : '—';
    $('offerSource').textContent = v.source;
    const verdict = verdictOf(v), box = $('offerVerdict');
    box.hidden = !verdict;
    if (verdict) {
      box.className = `verdict verdict--${verdict.kind}`;
      $('offerVerdictIcon').className = `fa-solid ${{ good: 'fa-circle-check', tight: 'fa-triangle-exclamation', miss: 'fa-circle-xmark' }[verdict.kind]}`;
      $('offerVerdictText').textContent = t(`i.offer.v.${verdict.kind}`, { n: Math.abs(verdict.margin) });
    }
  }

  // ---- the offer map: me, the stop (labelled), the bus line, the walk (with its time) and the bus itself ----
  function firstLine(geo) {
    const g = geo?.type === 'Feature' ? geo.geometry : geo;
    if (!g) return null;
    if (g.type === 'LineString') return g.coordinates;
    if (g.type === 'MultiLineString') return g.coordinates.reduce((a, b) => (b.length > a.length ? b : a), []);
    if (g.type === 'GeometryCollection') return firstLine(g.geometries.find((x) => /LineString/.test(x.type)));
    return null;
  }

  function drawOfferMap(o, v) {
    clearRideLayers();
    // bus line: white casing under a thick coloured line, so it reads on any map tile
    if (v.shape) {
      const casing = L.geoJSON(v.shape, { style: { color: '#fff', weight: 11, opacity: .95, lineCap: 'round', lineJoin: 'round' } });
      const line = L.geoJSON(v.shape, { style: { color: '#1b74c4', weight: 6, opacity: 1, lineCap: 'round', lineJoin: 'round' } });
      layers.shape = L.layerGroup([casing, line]).addTo(map);
    }
    // walk to the stop, with a chip showing how long it takes
    const coords = firstLine(v.walkGeometry);
    let walkLine = coords ? coords.map(([lon, lat]) => [lat, lon]) : null;
    const stopLL = v.stopLL || (v.stopFeature?.geometry?.coordinates ? [v.stopFeature.geometry.coordinates[1], v.stopFeature.geometry.coordinates[0]] : null);
    if (!walkLine && userLatLng && stopLL) walkLine = [userLatLng, stopLL];
    if (walkLine && walkLine.length > 1) {
      layers.walk = L.polyline(walkLine, { color: '#0f1b2d', weight: 5, dashArray: '2 9', lineCap: 'round' }).addTo(map);
      if (v.walk != null) {
        const mid = walkLine[Math.floor(walkLine.length / 2)];
        layers.walkChip = L.marker(mid, { interactive: false, keyboard: false, icon: L.divIcon({ className: '',
          html: `<div class="map-chip"><i class="fa-solid fa-person-walking" aria-hidden="true"></i>${esc(minText(Math.max(1, Math.round(v.walk))))}</div>`, iconSize: [0, 0] }) }).addTo(map);
      }
    }
    // the stop, with its name
    if (stopLL) {
      layers.stop = L.marker(stopLL, { icon: stopIcon(), keyboard: false, zIndexOffset: 700 }).addTo(map);
      if (v.stopName) layers.stop.bindTooltip(esc(v.stopName), { permanent: true, direction: 'top', offset: [0, -20], className: 'stop-label' });
    }
    // only the offered bus stays visible among the live buses
    selectedKey = v.arrival ? rowKey(v.arrival) : null;
    syncBusMarkers();
  }

  /** Fit me + stop + bus into the part of the map that the offer card does not cover. */
  function fitOffer() {
    const card = $('offerCard');
    if (!offer || !card || !map) return;
    const v = offerView(offer);
    const pts = [];
    if (userLatLng) pts.push(userLatLng);
    const stopLL = v.stopLL || (v.stopFeature?.geometry?.coordinates ? [v.stopFeature.geometry.coordinates[1], v.stopFeature.geometry.coordinates[0]] : null);
    if (stopLL) pts.push(stopLL);
    if (v.vehicle) pts.push([v.vehicle.lat, v.vehicle.lon]);
    if (!pts.length) return;
    const r = card.getBoundingClientRect();
    const wide = window.innerWidth >= 900;
    const pad = 56;
    const left = wide && isRtl() ? r.width + pad : pad;
    const right = wide && !isRtl() ? r.width + pad : pad;
    const bottom = wide ? pad : r.height + pad * 0.7;
    map.invalidateSize();
    map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [left, pad], paddingBottomRight: [right, bottom], maxZoom: 17, animate: true });
  }

  function showOffer(o) {
    offer = o;
    $('breakOverlay').hidden = true;     // an assignment beats a half-chosen break
    const v = offerView(o);
    setMode('offer');
    renderOffer();
    drawOfferMap(o, v);
    requestAnimationFrame(fitOffer);
    if (settings.sound) beep();
    if (settings.vibrate && navigator.vibrate) navigator.vibrate([200, 100, 200]);
    offerEndsAt = Date.now() + OFFER_SECONDS * 1000;
    tickOffer();
    clearInterval(offerTimer);
    offerTimer = setInterval(tickOffer, 250);
    $('offerAccept').focus();
  }

  window.addEventListener('resize', () => { if (offer) fitOffer(); });

  function tickOffer() {
    const left = Math.max(0, offerEndsAt - Date.now());
    const secs = Math.ceil(left / 1000), p = 1 - left / (OFFER_SECONDS * 1000);
    $('offerSecs').textContent = secs;
    $('offerRing').style.setProperty('--off', (p * 100).toFixed(1));
    $('offerAccept').style.setProperty('--p', p.toFixed(3));
    $('offer').classList.toggle('is-urgent', secs <= 8);
    if (left <= 0) closeOffer('expired');
  }

  function closeOffer(reason) {
    clearInterval(offerTimer);
    const o = offer;
    offer = null;
    if (!o) return;
    if (o.kind === 'recommended') {
      const best = o.json.best_option;
      declined.set(`${best.route_id}|${best.stop_id}`, Date.now() + DECLINE_TTL_MS);
    } else snoozedRuns.set(o.run.id, Date.now() + 60000);

    if (reason === 'decline' && o.kind === 'assigned') api(`/api/runs/${o.run.id}/cancel`, 'POST');
    clearRideLayers();
    if (reason === 'expired') toast(t('i.offer.expired'));
    setMode('searching');
    scheduleSearch(reason === 'decline' ? 2500 : SEARCH_MS);
  }

  async function acceptOffer() {
    if (!offer) return;
    const o = offer;
    clearInterval(offerTimer);
    const btn = $('offerAccept');
    btn.disabled = true;
    try {
      let runId, v = offerView(o), shape = null;
      if (o.kind === 'recommended') {
        const best = o.json.best_option;
        const created = await api('/api/runs', 'POST', { trip_id: best.trip_id, stop_id: o.json.stop_feature?.properties?.stop_id ?? best.stop_id, potential_fines: best.potential_fines });
        if (created.ok) runId = created.data.id;
        else if (created.status === 409) { runId = (await api('/api/runs/current')).data?.run?.id ?? null; }
        else { toast(created.data.error || t('i.toast.runFail'), 'error'); offerEndsAt = Date.now() + 5000; offerTimer = setInterval(tickOffer, 250); return; }
        shape = o.json.shape_feature;
      } else {
        const acc = await api(`/api/runs/${o.run.id}/accept`, 'POST');
        if (!acc.ok) { toast(acc.data.error || t('i.toast.runFail'), 'error'); closeOffer('expired'); return; }
        runId = o.run.id;
        shape = o.details?.shape_feature;
      }
      offer = null;
      currentRunId = runId;
      const stopLL = v.stopLL || stopLLOf(v.stopFeature);
      const routeId = o.kind === 'recommended' ? o.json.best_option.route_id : o.details?.route_id;
      const stopId = o.kind === 'recommended' ? (o.json.stop_feature?.properties?.stop_id ?? o.json.best_option.stop_id) : o.run.stop_id;
      trip = { line: v.line, dest: v.dest, stopName: v.stopName, stopCode: v.stopCode, shape, routeId, stopId, stopLL };
      rideState = 'enroute';
      rideFines = 0;
      setMode('ride');
      fitRide();
    } finally {
      btn.disabled = false;
    }
  }

  // ---------------- ride flow ----------------
  const STEPS = ['enroute', 'waiting', 'onride'];
  const ARRIVE_M = 30;                 // within this distance of the stop you count as "at the stop"
  const WALK_M_PER_MIN = 80 / 1.3;     // ~80 m/min, +30% for the street layout
  const BUS_GONE_MS = 60000;           // no live sighting for this long -> tell the inspector

  const stopLLOf = (feature) => {
    const c = feature?.geometry?.coordinates;
    return Array.isArray(c) ? [c[1], c[0]] : null;
  };

  /** After accepting: frame me + the stop in the part of the map above the sheet. */
  function fitRide() {
    if (!trip?.stopLL || !map) return;
    const pts = [trip.stopLL];
    if (userLatLng) pts.push(userLatLng);
    requestAnimationFrame(() => {
      map.invalidateSize();
      map.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [48, 90], paddingBottomRight: [48, sheet.desktop() ? 48 : 300], maxZoom: 17 });
    });
  }

  function renderRide() {
    const tr = trip || {};
    const vars = { line: esc(tr.line), dest: bdi(tr.dest || ''), stop: bdi(tr.stopName || ''), code: esc(tr.stopCode || '') };
    const key = { enroute: 'enroute', waiting: 'waiting', onride: 'onride', resumed: 'resumed', completed: 'done' }[rideState];
    $('rideTitle').textContent = t(`i.ride.${key}.title`);
    $('rideDesc').innerHTML = t(`i.ride.${key}.desc`, vars);
    $('actionBtn').textContent = t(`i.ride.${key}.btn`);
    $('modeRide').classList.toggle('is-complete', rideState === 'completed');
    sheetEl.classList.toggle('is-complete', rideState === 'completed');

    const idx = STEPS.indexOf(rideState);
    $('stepper').classList.toggle('is-visible', idx >= 0);
    $('stepper').querySelectorAll('li').forEach((li, i) => {
      li.classList.toggle('is-done', i < idx);
      li.classList.toggle('is-current', i === idx);
      if (i === idx) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    });
    $('cancelBtn').hidden = !currentRunId || rideState === 'completed';
    disarmCancel();
    const counting = rideState === 'onride' || rideState === 'resumed';
    $('fineCounter').hidden = !counting;
    $('fineValue').textContent = rideFines;
    $('navLinks').hidden = rideState !== 'enroute' || !trip?.stopLL;
    if (!$('navLinks').hidden) {
      const [la, lo] = trip.stopLL;
      $('navGoogle').href = `https://www.google.com/maps/dir/?api=1&destination=${la},${lo}&travelmode=walking`;
      $('navWaze').href = `https://waze.com/ul?ll=${la},${lo}&navigate=yes`;
    }
    updateRideLive();
    sheet.refresh();
  }

  // ---------------- live guidance: walk to the stop, then track the bus ----------------
  function setLive({ label, value, progress = 0, note = '', tone = '' }) {
    const box = $('rideLive');
    box.hidden = false;
    box.classList.toggle('is-arrived', tone === 'ok');
    box.classList.toggle('is-warn', tone === 'warn');
    $('rideLiveLabel').textContent = label;
    $('rideLiveValue').textContent = value;
    $('rideLiveBar').style.width = `${Math.round(Math.max(0, Math.min(1, progress)) * 100)}%`;
    $('rideLiveNote').textContent = note;
  }

  function updateRideLive() {
    if (mode !== 'ride' || !trip || (rideState !== 'enroute' && rideState !== 'waiting')) { $('rideLive').hidden = true; return; }

    if (rideState === 'enroute') {
      if (!trip.stopLL || !userLatLng) { $('rideLive').hidden = true; return; }
      const dist = distanceM(userLatLng, trip.stopLL);
      trip.startDist = Math.max(trip.startDist || 0, dist);
      if (dist <= ARRIVE_M) {              // geofence: arrived without pressing anything
        toast(t('i.live.arrivedToast'), 'ok');
        if (settings.vibrate && navigator.vibrate) navigator.vibrate([120, 80, 120]);
        goWaiting();
        return;
      }
      const mins = Math.max(1, Math.round(dist / WALK_M_PER_MIN));
      setLive({
        label: t('i.live.walkLabel'),
        value: t('i.live.walkVal', { dist: t('i.unit.m', { n: Math.round(dist) }), min: minText(mins) }),
        progress: trip.startDist ? 1 - dist / trip.startDist : 0,
      });
      return;
    }

    // waiting: the bus tracker
    const a = matchArrival(trip.routeId, trip.stopId, trip.line, trip.stopName);
    if (a) {
      trip.lastSeen = Date.now();
      if (!trip.etaStart) trip.etaStart = Math.max(1, a.minutes_until_arrival || 1);
      const eta = etaParts(a), msLeft = Date.parse(a.arrival_at) - Date.now();
      const dist = a.vehicle_location && trip.stopLL ? distanceM([a.vehicle_location.lat, a.vehicle_location.lon], trip.stopLL) : null;
      let note = '';
      if (eta.soon && eta.unit === '') note = t('i.live.busNow');
      else if (dist != null) note = t('i.live.busFar', { dist: t('i.unit.m', { n: Math.round(dist) }) });
      if (!a.is_live) note = t('i.live.busSched');
      setLive({
        label: t('i.live.waitLabel', { line: trip.line }),
        value: eta.gone ? '\u2014' : `${eta.text}${eta.unit ? ` ${eta.unit}` : ''}`,
        progress: Number.isFinite(msLeft) ? 1 - msLeft / 60000 / trip.etaStart : 0,
        note, tone: eta.soon ? 'ok' : '',
      });
      if (Number.isFinite(msLeft) && msLeft <= 120000 && !trip.warned) {
        trip.warned = true;
        toast(t('i.live.soon'), 'ok');
        if (settings.vibrate && navigator.vibrate) navigator.vibrate([250, 100, 250, 100, 250]);
      }
      selectedKey = rowKey(a);
    } else {
      const gone = trip.lastSeen && Date.now() - trip.lastSeen > BUS_GONE_MS;
      setLive({ label: t('i.live.waitLabel', { line: trip.line }), value: '\u2014', note: gone ? t('i.live.busGone') : t('i.live.noEta'), tone: gone ? 'warn' : '' });
    }
  }

  // ---------------- fine counter (saved on the run) ----------------
  function changeFines(delta) {
    const next = Math.max(0, Math.min(500, rideFines + delta));
    if (next === rideFines) return;
    rideFines = next;
    const out = $('fineValue');
    out.textContent = rideFines;
    out.classList.remove('is-bump'); void out.offsetWidth; out.classList.add('is-bump');
    if (navigator.vibrate) navigator.vibrate(10);
    clearTimeout(fineSaveTimer);
    fineSaveTimer = setTimeout(saveFines, 400);
  }
  async function saveFines() {
    if (!currentRunId) return;
    const path = `/api/runs/${currentRunId}/progress`;
    const res = await api(path, 'PATCH', { fines: rideFines });
    if (res.status === 0) { enqueue(path, 'PATCH', { fines: rideFines }); return; }
    if (!res.ok) toast(t('i.toast.saveFail', { err: res.data.error || '' }), 'error');
  }

  function goWaiting() {
    rideState = 'waiting';
    if (layers.walk) { map.removeLayer(layers.walk); layers.walk = null; }
    if (layers.walkChip) { map.removeLayer(layers.walkChip); layers.walkChip = null; }
    if (layers.shape) { map.removeLayer(layers.shape); layers.shape = null; }
    if (trip?.shape) layers.shape = L.geoJSON(trip.shape, { style: { color: '#137a3b', weight: 5, opacity: 0.85 } }).addTo(map);
    renderRide();
    sheet.go('half');
  }

  function askFines(initial = 0) {
    return new Promise((resolve) => {
      const overlay = $('finesOverlay'), input = $('finesInput'), form = $('finesForm');
      input.value = String(initial);
      overlay.hidden = false;
      input.focus(); input.select();
      const value = () => Math.max(0, parseInt(input.value, 10) || 0);
      const clean = () => { overlay.hidden = true; form.removeEventListener('submit', onSubmit); $('finesCancel').removeEventListener('click', onCancel); $('finesMinus').removeEventListener('click', onMinus); $('finesPlus').removeEventListener('click', onPlus); document.removeEventListener('keydown', onKey); };
      const onSubmit = (e) => { e.preventDefault(); const v = value(); clean(); resolve(v); };
      const onCancel = () => { clean(); resolve(null); };
      const onMinus = () => { input.value = String(Math.max(0, value() - 1)); };
      const onPlus = () => { input.value = String(value() + 1); };
      const onKey = (e) => { if (e.key === 'Escape') onCancel(); };
      form.addEventListener('submit', onSubmit);
      $('finesCancel').addEventListener('click', onCancel);
      $('finesMinus').addEventListener('click', onMinus);
      $('finesPlus').addEventListener('click', onPlus);
      document.addEventListener('keydown', onKey);
    });
  }

  async function completeRide() {
    const fines = await askFines(rideFines);
    if (fines === null) return;
    rideFines = fines;                       // what was typed is kept: if saving fails, the next try starts from it
    $('fineValue').textContent = rideFines;
    if (currentRunId) {
      const path = `/api/runs/${currentRunId}/complete`;
      const done = await api(path, 'POST', { actual_fines: fines });
      if (done.status === 0 || done.status >= 500) { enqueue(path, 'POST', { actual_fines: fines }); toast(t('i.net.savedOffline'), 'ok'); }   // no signal or a server hiccup: keep it and sync later
      else if (!done.ok) { toast(t('i.toast.saveFail', { err: done.data.error || '' }), 'error'); return; }
      currentRunId = null;
    }
    clearTimeout(fineSaveTimer);
    rideFines = 0;
    clearRideLayers();
    rideState = 'completed';
    renderRide();
    toast(t('i.ride.saved', { n: fines }), 'ok');
    refreshMe();
  }

  function backToSearching() {
    trip = null;
    rideState = 'enroute';
    setMode('searching');
    scheduleSearch(1200);
  }

  let cancelTimer = null;
  function disarmCancel() {
    clearTimeout(cancelTimer);
    const b = $('cancelBtn');
    b.classList.remove('is-armed');
    b.textContent = t('i.ride.cancel');
  }
  async function onCancelClick() {
    const b = $('cancelBtn');
    if (!b.classList.contains('is-armed')) {
      b.classList.add('is-armed');
      b.textContent = t('i.ride.cancelAgain');
      cancelTimer = setTimeout(disarmCancel, 3500);
      return;
    }
    disarmCancel();
    const res = await api(`/api/runs/${currentRunId}/cancel`, 'POST');
    if (!res.ok) { toast(res.data.error || t('i.toast.runFail'), 'error'); return; }
    currentRunId = null;
    rideFines = 0;
    clearRideLayers();
    toast(t('i.ride.cancelled'));
    backToSearching();
  }

  async function onAction() {
    if (rideState === 'enroute') goWaiting();
    else if (rideState === 'waiting') { rideState = 'onride'; renderRide(); }
    else if (rideState === 'onride' || rideState === 'resumed') await completeRide();
    else if (rideState === 'completed') backToSearching();
  }

  async function resumeRun(run) {
    currentRunId = run.id;
    const d = await api(`/api/runs/${run.id}/details`);
    const det = d.data?.details || {};
    const props = det.stop_feature?.properties || {};
    trip = { line: det.route_num || '?', dest: det.destination || '', stopName: props.stop_name || '', stopCode: props.stop_code || run.stop_id || '', shape: det.shape_feature,
      routeId: det.route_id, stopId: run.stop_id, stopLL: stopLLOf(det.stop_feature) };
    rideFines = run.fines_in_progress || 0;
    clearRideLayers();
    if (det.stop_feature) layers.stop = L.geoJSON(det.stop_feature, { pointToLayer: (_f, latlng) => L.marker(latlng, { icon: stopIcon() }) }).addTo(map);
    if (det.shape_feature) layers.shape = L.geoJSON(det.shape_feature, { style: { color: '#137a3b', weight: 5, opacity: 0.85 } }).addTo(map);
    rideState = 'resumed';
    clearTimeout(searchTimer);
    setMode('ride');
  }

  // ---------------- break mode ----------------
  let breakEndsAt = 0, breakTimer = null, breakNotified = false, breakGrace = null;
  const breakPick = { minutes: 30, reason: 'lunch' };
  const breakCap = () => me.max_break_minutes || 90;
  const clockTime = (ms) => new Date(ms).toLocaleTimeString(`${window.I18n.lang}-u-nu-latn`, { hour: '2-digit', minute: '2-digit', hour12: false });

  const clock = (ms) => { const sec = Math.max(0, Math.ceil(ms / 1000)); return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`; };
  function renderBreakExtra() {
    $('breakUntil').textContent = t('i.break.until', { time: clockTime(breakEndsAt) });
    $('breakExtend').textContent = t('i.break.extend', { n: BREAK_EXTEND });
    $('breakExtend').disabled = (me.break_planned_minutes || 0) + BREAK_EXTEND > breakCap();
  }
  function tickBreak() {
    const left = breakEndsAt - Date.now(), el = $('breakLeft');
    if (left > 0) { el.classList.remove('is-over'); el.textContent = t('i.break.left', { time: clock(left) }); return; }
    el.classList.add('is-over');
    el.textContent = t('i.break.over');
    if (breakNotified) return;
    breakNotified = true;
    if (settings.vibrate && navigator.vibrate) navigator.vibrate([200, 100, 200]);
    if (settings.sound) beep();
    // A short moment to add time, then back to work on their own.
    breakGrace = setTimeout(backFromBreak, 20000);
  }
  async function backFromBreak() {
    clearTimeout(breakGrace); breakGrace = null;
    if (mode !== 'break') return;
    stopBreakTimer();
    await goOnline(true);
    refreshMe();
    toast(t('i.break.backOnline'), 'ok');
  }
  function stopBreakTimer() { clearInterval(breakTimer); breakTimer = null; clearTimeout(breakGrace); breakGrace = null; }
  function enterBreak(secondsLeft) {
    clearTimeout(searchTimer);
    breakEndsAt = Date.now() + secondsLeft * 1000;
    breakNotified = false;
    setMode('break');
    renderBreakExtra();
    tickBreak();
    stopBreakTimer();
    breakTimer = setInterval(tickBreak, 1000);
  }
  async function extendBreak() {
    const res = await api('/api/me/status', 'PUT', { break_extend: BREAK_EXTEND });
    if (!res.ok) { toast(res.data?.error ? window.I18n.tm(res.data.error) : t('i.toast.statusFail'), 'error'); return; }
    clearTimeout(breakGrace); breakGrace = null;
    breakEndsAt = Math.max(breakEndsAt, Date.now()) + BREAK_EXTEND * 60000;
    me.break_planned_minutes = (me.break_planned_minutes || 0) + BREAK_EXTEND;
    breakNotified = false;
    renderBreakExtra();
    tickBreak();
  }

  function renderBreakSheet() {
    const cap = breakCap();
    breakPick.minutes = Math.min(Math.max(BREAK_MIN, breakPick.minutes), cap);
    segment($('breakChoices'), BREAK_PRESETS.filter((m) => m <= cap).map((m) => ({ value: String(m), label: minText(m) })), String(breakPick.minutes), (v) => { breakPick.minutes = Number(v); renderBreakSheet(); });
    $('breakValue').textContent = minText(breakPick.minutes);
    $('breakLess').disabled = breakPick.minutes <= BREAK_MIN;
    $('breakMore').disabled = breakPick.minutes >= cap;
    $('breakCap').textContent = t('i.break.cap', { n: cap, time: clockTime(Date.now() + breakPick.minutes * 60000) });
    segment($('breakReasons'), BREAK_REASONS.map((r) => ({ value: r, label: t(`i.break.r.${r}`) })), breakPick.reason, (v) => { breakPick.reason = v; renderBreakSheet(); });
  }
  function openBreak() {
    lastFocus = document.activeElement;
    renderBreakSheet();
    $('breakOverlay').hidden = false;
    $('breakStart').focus();
  }
  function closeBreakSheet() { $('breakOverlay').hidden = true; lastFocus?.focus?.(); }
  async function startBreak() {
    const minutes = breakPick.minutes;
    $('breakOverlay').hidden = true;
    const res = await api('/api/me/status', 'PUT', { break_minutes: minutes, break_reason: breakPick.reason });
    if (!res.ok) { toast(res.data?.error ? window.I18n.tm(res.data.error) : t('i.toast.statusFail'), 'error'); return; }
    me.break_planned_minutes = minutes;
    releaseWakeLock();
    enterBreak(minutes * 60);
    toast(t('i.break.started'), 'ok');
  }

  // ---------------- menu ----------------
  function openMenu() { lastFocus = document.activeElement; $('menu').hidden = false; $('menuBtn').setAttribute('aria-expanded', 'true'); $('menu').querySelector('a,button')?.focus(); }
  function closeMenu() { $('menu').hidden = true; $('menuBtn').setAttribute('aria-expanded', 'false'); lastFocus?.focus?.(); }

  // ---------------- profile summary ----------------
  async function refreshMe() {
    const res = await api('/api/me');
    if (res.ok) { me = { ...me, ...res.data }; renderModeCopy(); }
    return res;
  }

  // ---------------- comfort options and installing the app ----------------
  let installPrompt = null;
  function applyComfort() {
    document.documentElement.dataset.size = settings.size;
    document.body.classList.toggle('hc', !!settings.contrast);
  }
  window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installPrompt = e; if ($('installRow')) $('installRow').hidden = false; });
  window.addEventListener('appinstalled', () => { installPrompt = null; $('installRow').hidden = true; });

  // ---------------- settings drawer ----------------
  let lastFocus = null;
  function openSettings() {
    lastFocus = document.activeElement;
    renderSettings();
    $('settings').hidden = false;
    $('settingsClose').focus();
  }
  function closeSettings() {
    $('settings').hidden = true;
    lastFocus?.focus?.();
  }

  function segment(el, items, current, onPick) {
    el.innerHTML = items.map((it) => `<button type="button" role="radio" aria-checked="${it.value === current}" data-v="${esc(it.value)}"${it.lang ? ` lang="${it.lang}"` : ''}>${esc(it.label)}</button>`).join('');
    el.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => onPick(b.dataset.v)));
  }

  function renderSettings() {
    segment($('langSeg'), window.I18n.LANGS.map((l) => ({ value: l.code, label: l.name, lang: l.code })), window.I18n.lang, (v) => window.I18n.setLang(v));
    segment($('radiusSeg'), RADIUS_OPTIONS.map((r) => ({ value: String(r), label: t('i.unit.m', { n: r }) })), String(settings.radius), (v) => {
      settings.radius = Number(v); saveSettings(); renderSettings(); arrivals = []; lastGoodPoll = null; renderBoard(); pollArrivals(true);
    });
    for (const [id, key] of [['setSound', 'sound'], ['setVibrate', 'vibrate'], ['setAwake', 'awake']]) {
      const input = $(id);
      input.checked = !!settings[key];
      input.onchange = () => {
        settings[key] = input.checked; saveSettings();
        if (key === 'awake') { if (input.checked && mode !== 'offline') requestWakeLock(); else releaseWakeLock(); }
        if (key === 'sound' && input.checked) beep();
      };
    }
    segment($('sizeSeg'), ['m', 'l', 'xl'].map((v) => ({ value: v, label: t(`i.settings.size.${v}`) })), settings.size, (v) => { settings.size = v; saveSettings(); applyComfort(); renderSettings(); sheet.refresh(); });
    segment($('goalSeg'), GOAL_OPTIONS.map((g) => ({ value: String(g), label: String(g) })), String(settings.goal), (v) => { settings.goal = Number(v); saveSettings(); renderSettings(); });
    const hc = $('setContrast');
    hc.checked = !!settings.contrast;
    hc.onchange = () => { settings.contrast = hc.checked; saveSettings(); applyComfort(); };
    $('installRow').hidden = !installPrompt;
    $('setVibrate').closest('.set-row').hidden = !navigator.vibrate;
    $('setAwake').closest('.set-row').hidden = !('wakeLock' in navigator);
  }

  // ---------------- push alerts (offers and break end while the app is closed) ----------------
  const b64ToBytes = (b64) => {
    const raw = atob((b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  };
  async function setupPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return;
    const info = await api('/api/push/key');
    if (!info.ok || !info.data.enabled) return;                       // the server has no push keys: the switch stays hidden
    const reg = await navigator.serviceWorker.ready;
    const input = $('setPush');
    $('pushRow').hidden = false;
    $('pushHint').hidden = false;
    input.checked = !!(await reg.pushManager.getSubscription()) && Notification.permission === 'granted';
    input.onchange = async () => {
      try {
        if (input.checked) {
          if ((await Notification.requestPermission()) !== 'granted') { input.checked = false; toast(t('i.settings.pushBlocked'), 'error'); return; }
          const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(info.data.public_key) });
          const res = await api('/api/push/subscribe', 'POST', { subscription: sub.toJSON(), lang: window.I18n.lang });
          if (!res.ok) throw new Error('subscribe');
        } else {
          const sub = await reg.pushManager.getSubscription();
          if (sub) { await api('/api/push/unsubscribe', 'POST', { endpoint: sub.endpoint }); await sub.unsubscribe(); }
        }
      } catch (err) {
        input.checked = !input.checked;
        toast(t('i.settings.pushFail'), 'error');
      }
    };
  }

  // ---------------- dialogs: the page behind an open one is inert ----------------
  function watchDialogs() {
    const dialogs = ['offer', 'settings', 'menu', 'breakOverlay', 'finesOverlay', 'sessionOverlay'].map($).filter(Boolean);
    const behind = ['map', 'sheet'].map($).concat([...document.querySelectorAll('.topbar, .map-tools')]).filter(Boolean);
    const sync = () => {
      const open = dialogs.some((d) => !d.hidden);
      behind.forEach((el) => { if (open) el.setAttribute('inert', ''); else el.removeAttribute('inert'); });
    };
    const observer = new MutationObserver(sync);
    dialogs.forEach((d) => observer.observe(d, { attributes: true, attributeFilter: ['hidden'] }));
    sync();
  }

  // ---------------- language changes ----------------
  function onLangChange() {
    renderModeCopy();
    renderBoard();
    updateChip();
    if (offer) renderOffer();
    if (mode === 'break') { renderBreakExtra(); tickBreak(); }
    if (!$('breakOverlay').hidden) renderBreakSheet();
    renderNet();
    if (!$('settings').hidden) renderSettings();
    sheet.refresh();
  }

  // ---------------- boot ----------------
  async function boot() {
    initMap();
    initSheet();
    initSwipe($('swipe'), goOnline);
    initSwipe($('swipeEnd'), goOffline);
    setMode('offline');

    $('actionBtn').addEventListener('click', onAction);
    $('cancelBtn').addEventListener('click', onCancelClick);
    $('fineLess').addEventListener('click', () => changeFines(-1));
    $('fineMore').addEventListener('click', () => changeFines(1));
    $('recenterBtn').addEventListener('click', recenter);
    $('zoomIn').addEventListener('click', () => map.zoomIn());
    $('zoomOut').addEventListener('click', () => map.zoomOut());
    $('offerAccept').addEventListener('click', acceptOffer);
    $('offerDecline').addEventListener('click', () => closeOffer('decline'));
    $('menuBtn').addEventListener('click', openMenu);
    $('menu').addEventListener('click', (e) => { if (e.target.id === 'menu') closeMenu(); });
    $('menuSettings').addEventListener('click', () => { closeMenu(); openSettings(); });
    $('breakBtn').addEventListener('click', openBreak);
    $('breakCancel').addEventListener('click', closeBreakSheet);
    $('breakStart').addEventListener('click', startBreak);
    $('breakExtend').addEventListener('click', extendBreak);
    $('breakLess').addEventListener('click', () => { breakPick.minutes -= 5; renderBreakSheet(); });
    $('breakMore').addEventListener('click', () => { breakPick.minutes += 5; renderBreakSheet(); });
    $('breakOverlay').addEventListener('click', (e) => { if (e.target.id === 'breakOverlay') $('breakOverlay').hidden = true; });
    $('breakBack').addEventListener('click', () => goOnline());
    $('installBtn').addEventListener('click', async () => { if (!installPrompt) return; installPrompt.prompt(); await installPrompt.userChoice.catch(() => {}); installPrompt = null; $('installRow').hidden = true; });
    window.addEventListener('online', () => { setNetDown(false); flushQueue(); });
    window.addEventListener('offline', () => setNetDown(true));
    setInterval(() => { if (readQueue().length && navigator.onLine) flushQueue(); }, 15000);
    document.querySelectorAll('a[href="/logout"]').forEach((a) => a.addEventListener('click', () => navigator.serviceWorker?.controller?.postMessage('logout')));
    applyComfort();
    renderNet();
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => { /* the app works without it */ });
    $('settingsClose').addEventListener('click', closeSettings);
    $('settings').addEventListener('click', (e) => { if (e.target.id === 'settings') closeSettings(); });
    document.addEventListener('keydown', (e) => { if (e.key !== 'Escape') return; if (!$('settings').hidden) closeSettings(); else if (!$('menu').hidden) closeMenu(); else if (!$('breakOverlay').hidden) closeBreakSheet(); });
    $('board').addEventListener('click', (e) => { const row = e.target.closest('.arrival'); if (row) selectArrival(row.dataset.key); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { pollArrivals(true); if (mode !== 'offline') requestWakeLock(); } });
    document.addEventListener('langchange', onLangChange);
    setInterval(tickCountdowns, 1000);

    startGeolocation();
    setupPush().catch(() => { /* push is optional */ });
    watchDialogs();

    // A stationary phone gets no new GPS fixes, so repeat the last one: the manager only sees inspectors who keep reporting.
    setInterval(() => {
      if (mode !== 'offline') rememberShift(true);   // keeps the "still on shift" memory fresh
      if (userLatLng && mode !== 'offline' && Date.now() - lastReport > REPORT_POSITION_MS) {
        lastReport = Date.now();
        api('/api/me/status', 'PUT', { latitude: userLatLng[0], longitude: userLatLng[1] });
      }
    }, 10000);

    // The server says when something changed (e.g. the manager sent an assignment), so an offer shows up at once. Polling stays as the fallback.
    if ('EventSource' in window) {
      let liveTimer = null;
      new EventSource('/api/events').addEventListener('change', () => {
        clearTimeout(liveTimer);
        liveTimer = setTimeout(() => { if (mode === 'searching' && !searching) scheduleSearch(50); }, 200);
      });
    }

    const started = Date.now();
    const hideSplash = () => {
      const splash = $('splash');
      if (!splash || splash.classList.contains('is-done')) return;
      splash.classList.add('is-done');
      setTimeout(() => splash.remove(), 700);
    };
    setTimeout(hideSplash, 6000);   // a dead connection can not keep the app behind the splash
    try {
    await flushQueue();        // rides finished without signal are delivered before anything else
    await refreshMe();
    // An unfinished run always wins; otherwise resume the shift if the app was closed only a moment ago.
    const current = await api('/api/runs/current');
    const run = current.data?.run;
    let wasOnline = false;
    wasOnline = shiftWasRecent();

    if (run && run.status === 'accepted') await resumeRun(run);
    else if (run && run.status === 'assigned') { await goOnline(true); }
    else if (me.on_break) enterBreak(me.break_seconds_left || 0);
    else if (wasOnline) await goOnline(true);
    else if (me.available) api('/api/me/status', 'PUT', { available: false }); // a long-closed app starts off shift
    } catch (err) {
      console.error('boot', err);
    } finally {
      setTimeout(hideSplash, Math.max(0, SPLASH_MIN_MS - (Date.now() - started)));
    }
  }

  boot();
})();
