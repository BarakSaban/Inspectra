# Inspectra

Inspectra helps public-transport fare inspectors work far more efficiently. For an inspector standing somewhere in
Tel Aviv it recommends **the next bus to board to maximise expected fare violations**, using the static GTFS
timetable plus live bus positions from the Ministry of Transport's SIRI stop-monitoring feed. Admins manage
inspectors, assign runs and review analytics.

Made by Ofek and Barak.

## How a recommendation is made

1. **Walk:** stops within walking range of the inspector are found, with real street routing from OpenStreetMap
   (straight-line estimates if OSM is unreachable).
2. **Live buses:** the nearby stops are queried in parallel on the SIRI proxy by their public `stop_code`. A visit's
   `line_ref` is the GTFS `route_id`, so it is matched to the feed by route and direction.
3. **Score:** `fines = min(minutes on board / 5, average non-paying passengers on that route in the current 3-hour slot)`.
   Live buses are scored on the remaining ride, and only if the inspector can reach the stop before the bus arrives.
4. **Pick:** a scored live bus wins; if none qualifies (or SIRI is down) the best scheduled trip from the static
   GTFS timetable is used. The response says which one it was (`data_source`: `live` or `static`).

## Project layout

```
app/                      the Flask application (a self-contained package)
  __init__.py             create_app() application factory
  config.py               .env loading and every environment-driven setting (single source of configuration)
  extensions.py           shared Flask extensions (SQLAlchemy)
  seeds.py                database bootstrap: default admin and demo data for an empty database
  models/                 SQLAlchemy models: User, Inspector, InspectorRun, Fine
  api/                    JSON endpoints, one blueprint per resource
                          auth, profile, staff, inspectors, analytics, assignments, runs, trips (+ /api/health)
  views/pages.py          HTML pages (data is loaded client-side from the API)
  services/               business logic, independent of Flask
    gtfs.py                 the GTFS feed and everything derived from it (map GeoJSON, stop->route index, lookups)
    walking.py              which stops can be walked to, and how long it takes
    routing.py              scoring and assignment: RoutingEngine
    siri.py                 SIRI client: fetch, parse, cache, retry/back-off
    live_trips.py           matches live visits to GTFS routes and builds scoreable options
    recommendations.py      the find_best_trip workflow (live first, static fallback)
    runs.py                 the life of a run: assigned -> accepted -> completed/cancelled, fines, totals
    inspectors.py           admin-scoped inspector lookups
  utils/                  small helpers: auth/session, login rate limit, Israel clock, ids, geo, JSON
  templates/ static/      Jinja templates (partials/sidebar.html is shared) and web assets (static/img)
data/
  gtfs/                   filtered GTFS feed (routes, trips, stops, stop_times, shapes)
  routes_with_avgs.csv    per-route passenger / fare-evasion averages by 3-hour slot
tools/                    offline data tools (not used at runtime)
tests/                    unittest suite, one module per area
run.py                    development entry point (`python run.py`); WSGI servers can use `run:app`
```

Design rules: `api/` and `views/` only translate HTTP; all logic lives in `services/`; `services/gtfs.py` is the
only place that reads the GTFS files; `config.py` is the only place that reads the environment.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit it (at least INSPECTRA_SECRET and INSPECTRA_ADMIN_PW)
python run.py                      # http://localhost:5000  (log in as `admin`)
```

The first start creates `inspectra.db`, an `admin` account and (for an empty database) demo inspectors.
Configuration is documented in [`.env.example`](.env.example). The first live recommendation downloads the street
network for the area from OpenStreetMap and caches it in `cache/`.

## Tests

```bash
python -m unittest discover -s tests -t .
```

The suite needs no network: SIRI and OpenStreetMap are simulated. `tests/helpers.py` has the shared fixtures
(a tiny GTFS feed, an in-memory database per test). Lint with `ruff check app tools tests run.py` (settings in
`pyproject.toml`). The same two commands run in CI (`.github/workflows/ci.yml`).

For production use a real WSGI server instead of `python run.py`, for example `gunicorn run:app` (Linux) or
`waitress-serve run:app` (Windows), set `INSPECTRA_SECRET` and `INSPECTRA_ADMIN_PW`, and keep the default
`INSPECTRA_DEBUG=0`. Login rate limiting is per process (see `app/utils/ratelimit.py`).

## Inviting inspectors

The overview and staff pages have an invite dialog: it copies the manager code, a sign-up link (`/signup?code=ABC123`,
which pre-fills the code) or a ready message in the current language, and shares it through the system share sheet or
WhatsApp. Inspectors added by hand get a temporary password, and a manager can reset it from the staff table.

## Languages

Every page is available in Hebrew (the default), English, Arabic and Russian, with right-to-left layout for Hebrew and
Arabic. Strings are rows `[key, he, en, ar, ru]` in `app/static/js/i18n-strings*.js`; markup uses `data-i18n`,
`data-i18n-html` and `data-i18n-attr`, scripts use `I18n.t(key, vars)`. The choice is kept in a `lang` cookie and
`localStorage`; the server reads the cookie to set `lang` and `dir` on first paint. Messages returned by the API stay in
English and are translated in the browser through `srv.<message>` rows. `tests/test_i18n.py` fails when a key is used
but missing, or when a row lacks a language or has mismatched `{placeholders}`.

## Data tools

| Tool | Purpose |
| --- | --- |
| `python tools/build_gtfs_subset.py <israel-public-transportation.zip>` | Rebuild `data/gtfs/` from the national GTFS feed for the tracked routes (`TRACKED_ROUTE_IDS`). |
| `python tools/refresh_fare_evasion.py [--write]` | Compare (dry run) or refresh the API-backed passenger averages in `data/routes_with_avgs.csv` from data.gov.il. |
| `PYTHONPATH=. python tools/probe_siri.py [lat lon]` | Diagnostic: print the raw SIRI answer for the stops nearest a point. |

Map GeoJSON and the stop→route index are derived from `data/gtfs/` when the app starts, so updating the feed is a
single step. The GTFS feed is a snapshot (July 2025); route ids can change between releases, in which case live
visits fall back to matching by public bus number.

## API overview

| Endpoint | Who | Purpose |
| --- | --- | --- |
| `POST /api/login`, `/api/register`, `/api/logout` | public | accounts and sessions |
| `POST /api/find_best_trip` | logged in | best next bus for `{lat, lon, buffer, radius}`; `exclude` (trip ids) skips offers the inspector declined |
| `GET/POST /api/profile` | logged in | own profile |
| `GET /api/staff`, `GET /api/analytics` | admin | the admin's inspectors and summary numbers |
| `GET /api/analytics/report` | admin | fines between `start` and `end` (YYYY-MM-DD) by hour, weekday and `granularity` (day, month, quarter, year) |
| `POST /api/inspector`, `GET/PUT/DELETE /api/inspector/<id>` | admin | manage the admin's own inspectors |
| `POST /api/inspector/<id>/reset_password` | admin | new temporary password for an own inspector (returned once) |
| `POST /api/assign_runs` | admin | assign the best trips (live first) to free inspectors |
| `GET /api/runs/current`, `POST /api/runs` | inspector | the active run; take a recommended trip (creates an accepted run) |
| `POST /api/runs/<id>/accept`, `/cancel`, `/complete` | inspector | move own run along; `complete` takes `{actual_fines}`, records the fines and updates totals |
| `GET /api/arrivals` | logged in | live buses arriving near `lat`, `lon` (`radius`, `limit`): countdown, vehicle position, `source` (live, error, unavailable) |
| `PATCH /api/runs/<id>/progress` | inspector | saves the running fine count `{fines}` of an accepted run, so the +/- counter survives a reload |
| `GET /api/activity?limit=30` | admin | the team's latest events: offers, started and finished rides (with fines), declines and cancellations |
| `GET /api/admin/options?inspector_id=` | admin | live buses near an inspector with expected fines, for manual assignment |
| `POST /api/admin/assign` | admin | `{inspector_id, trip_id, stop_id, potential_fines}` sends the inspector an offer (409 if they have a run or are on a break) |
| `POST /api/admin/runs/<id>/cancel` | admin | takes back an offer or stops a ride of an own inspector |
| `GET /api/inspector/<id>/detail` | admin | state, totals, efficiency, fines per day and recent rides of one inspector (page: `/staff/<id>`) |
| `GET /api/staff/deactivated`, `POST /api/inspector/<id>/reactivate` | admin | removed inspectors who have history, and bringing one back |
| `GET/PUT /api/team/settings` | admin | safety buffer (0-30 min), search radius (100-2000 m), max walk (1-20 min), longest break (15-180 min, default 90); used by assignment. Edited on the *Manage team* page (`/staff`), `/settings` redirects there |
| `GET /api/audit?limit=` | admin | log of sensitive manager actions (password resets, removals, assignments, settings, bulk changes) |
| `POST /api/staff/bulk` | admin | `{action: online\|offline, inspector_ids: [...]}`; only the manager's own inspectors are touched |
| `GET /api/analytics/insights?start&end` | admin | fines vs the previous period of equal length, top stops (with coordinates for the hotspot map) and top lines |
| `GET /api/events` | any signed-in user | Server-Sent Events: sends `change` when the user's data changes so pages refresh at once; polling remains as the fallback |
| `GET /api/me/stats?period=today\|week\|month\|year&offset=` | inspector | totals, change vs the previous period, bucketed series, best hour, streak, shift and break hours, rides (page: `/inspect/stats`) |
| `GET /api/inspector/<id>/stats?period&offset` | admin | the same payload for one of the manager's inspectors plus the shift and break logs (other managers get 404) |
| `GET /api/attention` | admin | what needs the manager now: unanswered offers, phones gone dark while online, breaks over their end time, nobody online |
| `GET /api/analytics/people?start&end` | admin | per inspector: fines, rides, hours on shift, hours on break, breaks, fines per hour |
| `PUT /api/me/status` | inspector | `{available}` and/or a position; `{break_minutes: 5..cap, break_reason: lunch\|rest\|other}` starts a timed break, `{break_extend: 1..60}` lengthens it (never past the cap), `0` ends it (`GET /api/me` shows `on_break`, `break_seconds_left`, `max_break_minutes`) |
| `GET /api/me`, `GET /api/runs/<id>/details` | inspector | own summary (today's fines and trips, availability); stop, route and shape of a run, to resume it after a reload |
| `PUT /api/me/status` | inspector | go available/unavailable, optionally report `{latitude, longitude}` |
| `GET /api/health` | public | liveness and SIRI cache state |

## Installing the field app

The inspector page is a PWA: open `/inspect` on a phone and use *Install* in Settings (or the browser's "Add to Home screen"). `/manifest.webmanifest` and a root-scoped `/sw.js` make it open full screen and load fast; map tiles and static files are cached, `/api/*` is never cached. Rides finished without signal are kept on the phone and delivered when the connection returns. Service workers need HTTPS (localhost is exempt).

## Manager conveniences

The manager pages have a light/dark toggle (remembered in the browser), a QR code in the invite dialog (loaded from a CDN on demand; the code and link work without it), bulk online/offline on the staff table, editable team settings, an audit log, and a printable analytics report (Print button). `/api/events` holds a connection open for up to 55 s per request, so run the app with a threaded server (for example gunicorn `--worker-class gthread`); with a single sync worker the pages simply fall back to polling.

## Real data only

A fresh database contains just the `admin` account: no demo inspectors, runs or fines (`INSPECTRA_SEED_DEMO=1` brings the old demo data back for screenshots). New inspectors start offline with no position; the phone reports a real one (every 30 s, also while standing still). An inspector counts as reachable only while available and reporting within the last 3 minutes, so the manager sees who is really there and "Run assignment" skips phones that went dark. Manager codes are accepted in any case. Removing an inspector detaches them from the team but does not delete their login.

## Breaks, shifts and stats

An inspector picks any break length from 5 minutes up to the cap the manager sets under *Manage team* (default 90), with a reason (lunch, rest, other). When the time is up the phone alerts and the inspector is available again; +10 minutes extends it within the cap. Every shift (from going available until offline or the phone going dark) and every break is logged, so hours are measured and never inflated: an unfinished shift is closed at the last time the phone was heard. The inspector sees only the map, the swipe and the lines on the main page; numbers over time live on `/inspect/stats`. The manager's dashboard opens with an attention strip, four key numbers and the live map; on phones it has a bottom tab bar. The manager's view of one inspector reuses the same stats and adds the shift and break logs, and Analytics adds date presets and an hours-and-breaks table per inspector.

## Demo accounts

`python -m tools.demo_data create` adds two managers (`demo.manager1` with 6 inspectors, `demo.manager2` with 3) and about six weeks of shifts, breaks, rides and fines to the real database, all with the password `demo1234`; inspectors are `demo.i01` to `demo.i09`. Rides use real trips and stops from the timetable. `status` lists them, `live` keeps four demo inspectors online (fresh position every 30 s, Ctrl-C to stop) so the manager's live map has people on it, and `delete` removes exactly what `create` made (usernames starting `demo.`, inspector ids starting `DM`) after showing the counts; real accounts are never touched.
