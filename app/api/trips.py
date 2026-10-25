import logging

from flask import Blueprint, jsonify, request

from app.services.recommendations import find_best_trip
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
        result = find_best_trip(lat=lat, lon=lon, buffer_minutes=buffer_minutes, radius_m=radius_m)
    except Exception:
        logger.exception("find_best_trip failed for lat=%s lon=%s", lat, lon)
        return jsonify({"error": "routing failed"}), 500

    if result is None:
        return jsonify({"fallback": "No suitable trip found"})

    return jsonify(to_serializable(result))


@trips_api.route("/health", methods=["GET"])
def api_health():
    """Liveness plus a quick view of live-data health (no secrets, no outbound calls)."""
    return jsonify({"status": "ok", "siri": get_siri_status()})
