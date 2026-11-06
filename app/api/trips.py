import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.services.live_trips import list_live_arrivals
from app.services.recommendations import find_best_trip
from app.services.routing import get_engine
from app.services.siri import get_siri_status
from app.utils.auth import login_required_api
from app.utils.serialization import to_serializable

logger = logging.getLogger(__name__)

trips_api = Blueprint("trips_api", __name__)

# A request triggers street-network downloads and SIRI calls, so inputs are bounded.
MAX_RADIUS_M = 2000
MAX_BUFFER_MINUTES = 30


def _parse_query(data):
    """Validated (lat, lon, buffer, radius) from a request body; raises ValueError on bad input."""
    lat = float(data.get("lat", 32.0880))
    lon = float(data.get("lon", 34.7898))
    buffer_minutes = float(data.get("buffer", 3))
    radius_m = float(data.get("radius", 666))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("lat/lon out of range")
    if not (0 <= buffer_minutes <= MAX_BUFFER_MINUTES):
        raise ValueError("buffer out of range")
    if not (0 < radius_m <= MAX_RADIUS_M):
        raise ValueError("radius out of range")
    return lat, lon, buffer_minutes, radius_m


MAX_EXCLUDED_OFFERS = 50


def _parse_exclude(raw):
    """Declined offers as a set of (route_id, stop_id) strings; empty/None means nothing is excluded."""
    if raw in (None, []):
        return set()
    if not isinstance(raw, list) or len(raw) > MAX_EXCLUDED_OFFERS:
        raise ValueError("exclude must be a short list")
    pairs = set()
    for item in raw:
        if not isinstance(item, dict) or item.get("route_id") is None or item.get("stop_id") is None:
            raise ValueError("exclude items need route_id and stop_id")
        pairs.add((str(item["route_id"]), str(item["stop_id"])))
    return pairs


@trips_api.route("/find_best_trip", methods=["POST"])
@login_required_api
def api_find_best_trip():
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}

    try:
        lat, lon, buffer_minutes, radius_m = _parse_query(data)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"invalid parameters: {exc}"}), 400

    try:
        exclude = _parse_exclude(data.get("exclude"))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"invalid parameters: {exc}"}), 400

    kwargs = {"exclude": exclude} if exclude else {}
    try:
        result = find_best_trip(lat=lat, lon=lon, buffer_minutes=buffer_minutes, radius_m=radius_m, **kwargs)
    except Exception:
        logger.exception("find_best_trip failed for lat=%s lon=%s", lat, lon)
        return jsonify({"error": "routing failed"}), 500

    if result is None:
        return jsonify({"fallback": "No suitable trip found"})

    return jsonify(to_serializable(result))


@trips_api.route("/arrivals", methods=["GET"])
@login_required_api
def api_arrivals():
    """Live arrivals board near a point: every upcoming bus at nearby stops, soonest first. Cheap to poll."""
    try:
        lat, lon, _buffer, radius_m = _parse_query(request.args)
        limit = int(request.args.get("limit", 30))
        if not 1 <= limit <= 100:
            raise ValueError("limit out of range")
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"invalid parameters: {exc}"}), 400

    fetched_at = datetime.now(timezone.utc).isoformat()
    engine = get_engine()
    if engine is None:
        return jsonify({"arrivals": [], "source": "unavailable", "fetched_at": fetched_at})

    try:
        arrivals = list_live_arrivals(lat, lon, engine.gtfs, radius_m=radius_m, limit=limit)
    except Exception:
        logger.exception("arrivals lookup failed for lat=%s lon=%s", lat, lon)
        return jsonify({"arrivals": [], "source": "error", "fetched_at": fetched_at})

    return jsonify(to_serializable({"arrivals": arrivals, "source": "live", "fetched_at": fetched_at}))


@trips_api.route("/health", methods=["GET"])
def api_health():
    """Liveness plus a quick view of live-data health (no secrets, no outbound calls)."""
    return jsonify({"status": "ok", "siri": get_siri_status()})
