"""Client for the SIRI stop-monitoring proxy: fetch, parse and cache live bus visits per stop.

Nothing here knows about GTFS; see `live_trips` for matching visits to the schedule. Every public function is
safe to call when the proxy is down: failures are logged, remembered briefly (back-off) and reported as "no visits".
"""
import json
import logging
import time
from datetime import datetime, timezone
from urllib import error, parse, request

from app import config
from app.utils.clock import ISRAEL_TZ
from app.utils.ids import normalize_id, normalize_line_ref, normalize_route_name

logger = logging.getLogger(__name__)

DESTINATION_UNKNOWN = "Destination unknown"

# request URL -> {"timestamp": datetime, "visits": [...], "failed": bool}
_LIVE_CACHE = {}


def _utc_now():
    return datetime.now(timezone.utc)


def parse_iso_datetime(value):
    """Parse an ISO timestamp to UTC. Naive timestamps are Israel local time (what SIRI emits)."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ISRAEL_TZ)
    return moment.astimezone(timezone.utc)


def _is_fresh(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get("timestamp"), datetime):
        return False
    limit = config.SIRI_FAILURE_BACKOFF_SECONDS if entry.get("failed") else config.SIRI_CACHE_TTL_SECONDS
    return (_utc_now() - entry["timestamp"]).total_seconds() <= limit


def build_request_url(stop_code, line_ref=None, preview_interval=None):
    ref = normalize_id(stop_code)
    if not ref:
        return None

    url = f"{config.SIRI_BASE_URL}/stops/{ref}"
    params = []
    if line_ref is not None:
        params.append(f"line_ref={parse.quote(str(line_ref))}")
    if preview_interval is not None:
        params.append(f"preview_interval={int(preview_interval)}")
    return f"{url}?{'&'.join(params)}" if params else url


def parse_stop_visits_response(payload):
    """Normalise a proxy response into a list of unique visit dicts (visits without an arrival time are dropped)."""
    visits = payload.get("visits") if isinstance(payload, dict) else None
    if not isinstance(visits, list):
        return []

    monitoring_ref = payload.get("monitoring_ref") or payload.get("monitoringRef")
    unique, seen = [], set()

    for visit in visits:
        if not isinstance(visit, dict):
            continue

        arrival_raw = (
            visit.get("expected_arrival_time")
            or visit.get("expectedArrivalTime")
            or visit.get("arrival_time")
            or visit.get("predictedArrivalTime")
            or visit.get("estimatedArrivalTime")
        )
        if arrival_raw is None:
            continue

        line_ref = normalize_line_ref(visit.get("line_ref") or visit.get("lineId") or visit.get("line") or visit.get("route_ref"))
        line_name = normalize_route_name(
            visit.get("line_name") or visit.get("lineName") or visit.get("route_short_name") or visit.get("routeShortName")
        )
        vehicle_ref = visit.get("vehicle_ref") or visit.get("vehicleId") or visit.get("vehicle")
        destination_name = (
            visit.get("destination_name") or visit.get("destinationName") or visit.get("destination") or DESTINATION_UNKNOWN
        )
        arrival_dt = parse_iso_datetime(arrival_raw)

        key = (
            str(vehicle_ref or ""), str(line_ref or ""), str(line_name or ""), str(destination_name),
            arrival_dt.strftime("%Y-%m-%dT%H:%M:%S%z") if arrival_dt is not None else str(arrival_raw),
        )
        if key in seen:
            continue
        seen.add(key)

        try:
            latitude = float(visit["latitude"]) if visit.get("latitude") is not None else None
            longitude = float(visit["longitude"]) if visit.get("longitude") is not None else None
        except (TypeError, ValueError):
            latitude = longitude = None

        unique.append({
            "monitoring_ref": monitoring_ref,
            "line_ref": line_ref,
            "line_name": line_name,
            "direction_ref": visit.get("direction_ref") or visit.get("directionRef"),
            "destination_ref": visit.get("destination_ref") or visit.get("destinationRef"),
            "vehicle_ref": vehicle_ref,
            "destination_name": destination_name,
            "expected_arrival_time": arrival_raw,
            "arrival_dt": arrival_dt,
            "latitude": latitude,
            "longitude": longitude,
            "bearing": visit.get("bearing"),
            "velocity": visit.get("velocity"),
            "raw": visit,
        })

    return unique


def _fetch_with_retry(url):
    """GET a URL, retrying once on transient failures (429, 5xx, connection errors). Returns (body, status)."""
    last_error = last_status = None

    for attempt in (1, 2):
        started = time.perf_counter()
        try:
            with request.urlopen(url, timeout=config.SIRI_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", None) or getattr(response, "code", None)
                logger.debug("SIRI %s -> %s in %.2fs", url, status, time.perf_counter() - started)
                return response.read().decode("utf-8"), status
        except error.HTTPError as exc:
            last_error, last_status = exc, exc.code
            transient = last_status == 429 or 500 <= int(last_status) < 600
            if not transient:
                logger.warning("SIRI request to %s failed with HTTP %s", url, last_status)
                return None, last_status
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error, last_status = exc, None
        except Exception as exc:
            logger.warning("SIRI request to %s failed unexpectedly: %r", url, exc)
            return None, None

        logger.warning(
            "SIRI request to %s failed after %.2fs (attempt %s/2, status=%s, error=%r)",
            url, time.perf_counter() - started, attempt, last_status, last_error,
        )
        if attempt == 1:
            time.sleep(config.SIRI_RETRY_DELAY_SECONDS)

    logger.warning("SIRI request to %s exhausted retries; falling back to static GTFS. status=%s", url, last_status)
    return None, last_status


def fetch_live_stop_visits(stop_code, line_ref=None, preview_interval=None):
    """Live visits for a stop, keyed by the public stop_code (SIRI MonitoringRef). Never raises; [] on failure."""
    ref = normalize_id(stop_code)
    if not ref:
        return []

    url = build_request_url(ref, line_ref=line_ref, preview_interval=preview_interval)
    cached = _LIVE_CACHE.get(url)
    if cached is not None and _is_fresh(cached):
        return cached.get("visits", [])

    raw, _status = _fetch_with_retry(url)

    visits = None
    if raw is not None:
        try:
            visits = parse_stop_visits_response(json.loads(raw or "{}"))
        except json.JSONDecodeError as exc:
            logger.warning("Malformed JSON in SIRI response for stop %s: %r", ref, exc)

    if visits is None:
        _LIVE_CACHE[url] = {"timestamp": _utc_now(), "visits": [], "failed": True}
        return []
    _LIVE_CACHE[url] = {"timestamp": _utc_now(), "visits": visits}
    return visits


def get_siri_status():
    """Health snapshot from the in-memory cache: stops with fresh data vs. stops currently backing off."""
    fresh = [entry for entry in list(_LIVE_CACHE.values()) if _is_fresh(entry)]
    return {
        "cached_stops": sum(1 for e in fresh if not e.get("failed")),
        "failing_stops": sum(1 for e in fresh if e.get("failed")),
        "cache_ttl_seconds": config.SIRI_CACHE_TTL_SECONDS,
        "timeout_seconds": config.SIRI_TIMEOUT_SECONDS,
    }
