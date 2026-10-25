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
| `POST /api/find_best_trip` | logged in | best next bus for `{lat, lon, buffer, radius}` |
| `GET/POST /api/profile` | logged in | own profile |
| `GET /api/staff`, `GET /api/analytics` | admin | the admin's inspectors and summary numbers |
| `POST /api/inspector`, `GET/PUT/DELETE /api/inspector/<id>` | admin | manage the admin's own inspectors |
| `POST /api/assign_runs` | admin | assign the best trips (live first) to free inspectors |
| `GET /api/runs/current`, `POST /api/runs` | inspector | the active run; take a recommended trip (creates an accepted run) |
| `POST /api/runs/<id>/accept`, `/cancel`, `/complete` | inspector | move own run along; `complete` takes `{actual_fines}`, records the fines and updates totals |
| `PUT /api/me/status` | inspector | go available/unavailable, optionally report `{latitude, longitude}` |
| `GET /api/health` | public | liveness and SIRI cache state |
