import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

from utils.geo_utils import haversine_meters

logger = logging.getLogger(__name__)


def _load_env_file():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))


_load_env_file()

_INSPECTRA_SIRI_BASE_URL = os.environ.get("INSPECTRA_SIRI_BASE_URL")
_SIRI_BASE_URL = os.environ.get("SIRI_BASE_URL")

if _INSPECTRA_SIRI_BASE_URL and _SIRI_BASE_URL and _INSPECTRA_SIRI_BASE_URL.rstrip("/") != _SIRI_BASE_URL.rstrip("/"):
    logger.warning(
        "INSPECTRA_SIRI_BASE_URL overrides SIRI_BASE_URL. Effective SIRI_BASE_URL=%s",
        _INSPECTRA_SIRI_BASE_URL,
    )

SIRI_BASE_URL = (_INSPECTRA_SIRI_BASE_URL or _SIRI_BASE_URL or "https://raspberry-phy.taila18e05.ts.net").rstrip("/")
SIRI_TIMEOUT_SECONDS = float(
    os.environ.get("SIRI_TIMEOUT_SECONDS")
    or os.environ.get("INSPECTRA_SIRI_TIMEOUT_SECONDS")
    or "1000"
)
SIRI_RETRY_DELAY_SECONDS = float(os.environ.get("SIRI_RETRY_DELAY_SECONDS", "0.5"))
SIRI_CACHE_TTL_SECONDS = int(os.environ.get("INSPECTRA_SIRI_CACHE_TTL_SECONDS", "60"))
SIRI_STALE_SECONDS = int(os.environ.get("INSPECTRA_SIRI_STALE_SECONDS", "180"))

logger.info("SIRI base URL configured: %s", SIRI_BASE_URL)
logger.info("SIRI timeout configured: %.1fs", SIRI_TIMEOUT_SECONDS)

_LIVE_CACHE = {}


def _utc_now():
    return datetime.now(timezone.utc)


def _normalize_stop_id(stop_id):
    if stop_id is None:
        return None
    value = str(stop_id).strip()
    return value if value and value.lower() not in {"none", "null"} else None


def _normalize_line_ref(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    text = text.split(":")[-1]
    return text


def _normalize_route_name(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text.replace(" ", "")


def _parse_iso_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _is_response_fresh(cached_entry):
    if not isinstance(cached_entry, dict):
        return False
    timestamp = cached_entry.get("timestamp")
    if not isinstance(timestamp, datetime):
        return False
    age_seconds = (_utc_now() - timestamp).total_seconds()
    return age_seconds <= SIRI_STALE_SECONDS


def _build_request_url(monitoring_ref, line_ref=None, preview_interval=None):
    ref = _normalize_stop_id(monitoring_ref)
    if not ref:
        return None

    url = f"{SIRI_BASE_URL}/stops/{ref}"
    params = []
    if line_ref is not None:
        params.append(f"line_ref={parse.quote(str(line_ref))}")
    if preview_interval is not None:
        params.append(f"preview_interval={int(preview_interval)}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    return url


def parse_stop_visits_response(payload):
    if not isinstance(payload, dict):
        return []

    visits = payload.get("visits") or []
    if not isinstance(visits, list):
        return []

    monitoring_ref = payload.get("monitoring_ref") or payload.get("monitoringRef")
    unique = []
    seen = set()

    for visit in visits:
        if not isinstance(visit, dict):
            continue

        line_ref = _normalize_line_ref(visit.get("line_ref") or visit.get("lineId") or visit.get("line") or visit.get("route_ref"))
        line_name = visit.get("line_name") or visit.get("lineName") or visit.get("route_short_name") or visit.get("routeShortName")
        line_name = _normalize_route_name(line_name)
        direction_ref = visit.get("direction_ref") or visit.get("directionRef")
        destination_ref = visit.get("destination_ref") or visit.get("destinationRef")
        vehicle_ref = visit.get("vehicle_ref") or visit.get("vehicleId") or visit.get("vehicle")
        destination_name = (
            visit.get("destination_name")
            or visit.get("destinationName")
            or visit.get("destination")
            or "Destination unknown"
        )
        arrival_raw = (
            visit.get("expected_arrival_time")
            or visit.get("expectedArrivalTime")
            or visit.get("arrival_time")
            or visit.get("predictedArrivalTime")
            or visit.get("estimatedArrivalTime")
        )
        if arrival_raw is None:
            continue

        arrival_dt = _parse_iso_datetime(arrival_raw)
        if arrival_dt is not None:
            arrival_key = arrival_dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        else:
            arrival_key = str(arrival_raw)

        latitude = visit.get("latitude")
        longitude = visit.get("longitude")
        try:
            if latitude is not None:
                latitude = float(latitude)
            if longitude is not None:
                longitude = float(longitude)
        except (TypeError, ValueError):
            latitude = None
            longitude = None

        key = (
            str(vehicle_ref or ""),
            str(line_ref or ""),
            str(line_name or ""),
            str(destination_name or ""),
            arrival_key,
        )
        if key in seen:
            continue
        seen.add(key)

        normalized_visit = {
            "monitoring_ref": monitoring_ref,
            "line_ref": line_ref,
            "line_name": line_name,
            "direction_ref": direction_ref,
            "destination_ref": destination_ref,
            "vehicle_ref": vehicle_ref,
            "destination_name": destination_name,
            "expected_arrival_time": arrival_raw,
            "arrival_dt": arrival_dt,
            "latitude": latitude,
            "longitude": longitude,
            "bearing": visit.get("bearing"),
            "velocity": visit.get("velocity"),
            "raw": visit,
        }
        unique.append(normalized_visit)

    return unique


def _fetch_siri_url_with_retry(url):
    last_error = None
    last_status = None

    for attempt in range(1, 3):
        started = time.perf_counter()
        logger.info(
            "SIRI request attempt %s/%s to %s with timeout=%.1fs",
            attempt,
            2,
            url,
            SIRI_TIMEOUT_SECONDS,
        )
        try:
            with request.urlopen(url, timeout=SIRI_TIMEOUT_SECONDS) as response:
                elapsed = time.perf_counter() - started
                status = getattr(response, "status", None) or getattr(response, "code", None)
                logger.info(
                    "SIRI request to %s completed in %.2fs (status=%s, timeout=%.1fs)",
                    url,
                    elapsed,
                    status if status is not None else "unknown",
                    SIRI_TIMEOUT_SECONDS,
                )
                raw = response.read().decode("utf-8")
                return raw, status
        except error.HTTPError as exc:
            elapsed = time.perf_counter() - started
            status = getattr(exc, "code", None)
            last_error = exc
            last_status = status
            headers = getattr(exc, "headers", None)
            content_type = headers.get("Content-Type") if headers else None
            logger.warning(
                "SIRI request to %s failed after %.2fs (configured_timeout=%.1fs, status=%s, reason=%r, content_type=%s, exception=%r)",
                url,
                elapsed,
                SIRI_TIMEOUT_SECONDS,
                status,
                getattr(exc, "reason", None),
                content_type,
                exc,
            )
            if attempt == 1 and (status == 429 or (status is not None and 500 <= int(status) < 600)):
                logger.warning(
                    "Retrying transient SIRI HTTP status %s for %s after %.2fs",
                    status,
                    url,
                    SIRI_RETRY_DELAY_SECONDS,
                )
                time.sleep(SIRI_RETRY_DELAY_SECONDS)
                continue
            if attempt == 2 and (status == 429 or (status is not None and 500 <= int(status) < 600)):
                break
            return None, status
        except (error.URLError, TimeoutError, OSError, ValueError) as exc:
            elapsed = time.perf_counter() - started
            last_error = exc
            last_status = None
            logger.warning(
                "SIRI request to %s failed after %.2fs (configured_timeout=%.1fs, exception=%r)",
                url,
                elapsed,
                SIRI_TIMEOUT_SECONDS,
                exc,
            )
            if attempt == 1 and isinstance(exc, (TimeoutError, error.URLError, OSError, ValueError)):
                logger.warning(
                    "Retrying transient SIRI connection failure for %s after %.2fs",
                    url,
                    SIRI_RETRY_DELAY_SECONDS,
                )
                time.sleep(SIRI_RETRY_DELAY_SECONDS)
                continue
            return None, None
        except Exception as exc:
            elapsed = time.perf_counter() - started
            last_error = exc
            last_status = None
            logger.warning(
                "SIRI request to %s failed after %.2fs (configured_timeout=%.1fs, exception=%r)",
                url,
                elapsed,
                SIRI_TIMEOUT_SECONDS,
                exc,
            )
            return None, None

    logger.warning(
        "SIRI request to %s exhausted retry budget after %s attempts and will fall back to static GTFS. last_exception=%r status=%s",
        url,
        2,
        last_error,
        last_status,
    )
    return None, last_status


def fetch_live_stop_visits(monitoring_ref, line_ref=None, preview_interval=None):
    ref = _normalize_stop_id(monitoring_ref)
    if not ref:
        return []

    cached = _LIVE_CACHE.get(ref)
    if cached is not None and _is_response_fresh(cached):
        return cached.get("visits", [])

    url = _build_request_url(ref, line_ref=line_ref, preview_interval=preview_interval)
    if not url:
        return []

    logger.info("Fetching SIRI live visits for stop %s from %s", ref, url)
    raw, status = _fetch_siri_url_with_retry(url)
    if raw is None:
        logger.warning(
            "Falling back to static GTFS for stop %s because live SIRI request failed or timed out. url=%s status=%s",
            ref,
            url,
            status,
        )
        return []

    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        logger.warning(
            "Malformed JSON in SIRI response from %s for stop %s; falling back to static GTFS. exception=%r",
            url,
            ref,
            exc,
        )
        return []

    visits = parse_stop_visits_response(payload)
    _LIVE_CACHE[ref] = {"timestamp": _utc_now(), "visits": visits}
    return visits


def _find_matching_shape_entry(stop_id, line_ref, stop_shape_map, trips_df=None, line_name=None, direction_ref=None, destination_ref=None):
    stop_id_str = _normalize_stop_id(stop_id)
    if stop_id_str is None:
        return None

    candidates = [
        entry for entry in (stop_shape_map or [])
        if str(entry.get("stop_id")) == stop_id_str
    ]
    if not candidates:
        logger.warning("SIRI stop %s has no GTFS stop_shape_map candidates", stop_id_str)
        return None

    normalized_name = _normalize_route_name(line_name)
    route_candidates = [
        entry for entry in candidates
        if normalized_name is not None
        and _normalize_route_name(entry.get("route_short_name")) == normalized_name
    ]
    if not route_candidates:
        logger.warning(
            "SIRI stop %s line_ref %s public_line_name %s matched 0 GTFS route_short_name candidates; rejecting live option. Candidate routes=%s",
            stop_id_str,
            _normalize_line_ref(line_ref),
            normalized_name,
            sorted({str(e.get("route_short_name")) for e in candidates}),
        )
        return None

    def normalized_gtfs_id(value):
        if value is None:
            return None
        value = str(value).strip()
        if value.endswith(".0"):
            value = value[:-2]
        return value if value and value.lower() not in {"none", "null", "nan"} else None

    verified_candidates = []
    for entry in route_candidates:
        trip_id = normalized_gtfs_id(entry.get("trip_id"))
        route_id = normalized_gtfs_id(entry.get("route_id"))
        if not trip_id or not route_id:
            continue

        if trips_df is not None:
            if hasattr(trips_df, "columns"):
                trip_rows = trips_df[trips_df["trip_id"].astype(str) == trip_id]
                trip_rows = trip_rows.to_dict(orient="records")
            else:
                trip_rows = [
                    row for row in trips_df
                    if normalized_gtfs_id(row.get("trip_id")) == trip_id
                ]
            if not any(normalized_gtfs_id(row.get("route_id")) == route_id for row in trip_rows):
                continue
        verified_candidates.append(entry)

    if not verified_candidates:
        logger.warning(
            "SIRI stop %s public_line_name %s had %s route-name candidates but none had a trip_id verified against trips.txt; rejecting live option.",
            stop_id_str,
            normalized_name,
            len(route_candidates),
        )
        return None

    route_shapes = {
        (normalized_gtfs_id(entry.get("route_id")), normalized_gtfs_id(entry.get("shape_id")))
        for entry in verified_candidates
    }
    if len(route_shapes) > 1:
        logger.warning(
            "SIRI stop %s public_line_name %s matched multiple GTFS route/shape pairs; rejecting ambiguous live option. Candidates=%s",
            stop_id_str,
            normalized_name,
            sorted(route_shapes),
        )
        return None

    return min(verified_candidates, key=lambda entry: str(entry.get("trip_id", "")))


def build_live_trip_option(visit, stop_id, stop_lookup, shape_lookup, stop_shape_map, trips_df=None):
    if not isinstance(visit, dict):
        return None

    stop_id_str = _normalize_stop_id(stop_id)
    if not stop_id_str:
        return None

    line_ref = _normalize_line_ref(visit.get("line_ref"))
    line_name = _normalize_route_name(visit.get("line_name") or visit.get("lineName") or visit.get("route_short_name") or visit.get("routeShortName"))
    direction_ref = visit.get("direction_ref") or visit.get("directionRef")
    destination = visit.get("destination_name") or "Destination unknown"
    arrival_dt = visit.get("arrival_dt")
    if arrival_dt is None:
        arrival_dt = _parse_iso_datetime(visit.get("expected_arrival_time"))
    minutes_until_arrival = None
    if arrival_dt is not None:
        minutes_until_arrival = round((arrival_dt - _utc_now()).total_seconds() / 60.0, 1)

    stop_feature = stop_lookup.get(stop_id_str) if isinstance(stop_lookup, dict) else None
    matching_entry = _find_matching_shape_entry(
        stop_id_str,
        line_ref,
        stop_shape_map,
        trips_df,
        line_name=line_name,
        direction_ref=direction_ref,
        destination_ref=visit.get("destination_ref") or visit.get("destinationRef"),
    )
    if matching_entry is None:
        logger.warning(
            "Rejecting live SIRI visit for stop %s line_ref %s line_name %s destination=%s because no GTFS mapping matched.",
            stop_id_str,
            line_ref,
            line_name,
            destination,
        )
        return None

    shape_feature = None
    shape_id = None
    if isinstance(matching_entry, dict):
        shape_id = matching_entry.get("shape_id")
        if shape_id is not None:
            shape_feature = shape_lookup.get(str(shape_id).replace(".0", "")) if isinstance(shape_lookup, dict) else None

    if shape_feature is None and isinstance(trips_df, list):
        for row in trips_df:
            if str(row.get("trip_id")) == str(matching_entry.get("trip_id")) if matching_entry else False:
                shape_id = row.get("shape_id")
                shape_feature = shape_lookup.get(str(shape_id).replace(".0", "")) if isinstance(shape_lookup, dict) else None
                if shape_feature is not None:
                    break

    latitude = visit.get("latitude")
    longitude = visit.get("longitude")
    vehicle_location = None
    if latitude is not None and longitude is not None:
        vehicle_location = {"lat": float(latitude), "lon": float(longitude)}

    route_num = line_name or line_ref or "Unknown"
    if isinstance(matching_entry, dict):
        route_num = _normalize_route_name(matching_entry.get("route_short_name")) or _normalize_line_ref(matching_entry.get("route_id")) or route_num

    return {
        "trip_id": matching_entry.get("trip_id") if isinstance(matching_entry, dict) else None,
        "stop_id": stop_id_str,
        "arrival_time": visit.get("expected_arrival_time"),
        "minutes_until_arrival": minutes_until_arrival,
        "route_num": route_num,
        "destination": destination,
        "vehicle_ref": visit.get("vehicle_ref"),
        "vehicle_location": vehicle_location,
        "latitude": latitude,
        "longitude": longitude,
        "line_ref": line_ref,
        "line_name": line_name,
        "direction_ref": direction_ref,
        "shape_feature": shape_feature,
        "stop_feature": stop_feature,
        "data_source": "live",
        "source_label": "Live SIRI data",
        "is_live": True,
        "live_status": "live",
        "shape_id": shape_id,
    }


def choose_best_live_option(stop_id, stop_lookup, shape_lookup, stop_shape_map, trips_df, visit):
    if not isinstance(visit, dict):
        return None
    option = build_live_trip_option(
        visit,
        stop_id,
        stop_lookup,
        shape_lookup,
        stop_shape_map,
        trips_df,
    )
    if option is None:
        return None
    if option.get("minutes_until_arrival") is None:
        return None
    return option


def get_live_best_trip_option(lat, lon, stop_lookup, shape_lookup, stop_shape_map, trips_df, radius_m=666):
    if not stop_lookup:
        return None

    candidate_stops = []
    for stop_id, feature in stop_lookup.items():
        props = feature.get("properties", {})
        if not props:
            continue
        stop_lat = props.get("stop_lat")
        stop_lon = props.get("stop_lon")
        if stop_lat is None or stop_lon is None:
            coords = feature.get("geometry", {}).get("coordinates")
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                continue
            stop_lat = coords[1]
            stop_lon = coords[0]
        if stop_lat is None or stop_lon is None:
            continue
        distance = haversine_meters(float(lat), float(lon), float(stop_lat), float(stop_lon))
        if distance <= float(radius_m):
            candidate_stops.append((str(stop_id), feature, float(distance)))

    if not candidate_stops:
        logger.info("No GTFS stops within SIRI search radius %.1fm", float(radius_m))
        return None

    best_option = None
    visits_received = 0
    valid_candidates = 0
    seen_stop_ids = set()
    logger.info("Checking %s unique nearby GTFS stops for live SIRI visits", len(candidate_stops))
    for stop_id, _, _ in sorted(candidate_stops, key=lambda item: item[2]):
        if stop_id in seen_stop_ids:
            continue
        seen_stop_ids.add(stop_id)

        visits = fetch_live_stop_visits(stop_id)
        visits_received += len(visits)
        logger.info("SIRI stop %s returned %s parsed live visits", stop_id, len(visits))
        if not visits:
            continue

        for visit in visits:
            option = choose_best_live_option(
                stop_id,
                stop_lookup,
                shape_lookup,
                stop_shape_map,
                trips_df,
                visit,
            )
            if option is None:
                continue
            valid_candidates += 1
            if best_option is None or option["minutes_until_arrival"] < best_option["minutes_until_arrival"]:
                best_option = option

    logger.info(
        "SIRI selection processed %s nearby stops and %s visits; %s valid candidates reached scoring; selected_live=%s",
        len(seen_stop_ids),
        visits_received,
        valid_candidates,
        best_option is not None,
    )
    return best_option
