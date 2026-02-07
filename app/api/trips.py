from flask import Blueprint, request, jsonify
from app.services.trip_service import find_best_trip
from utils.geo_utils import to_serializable

trips_api = Blueprint("trips_api", __name__)

@trips_api.route("/find_best_trip", methods=["POST"])
def api_find_best_trip():
    data = request.get_json(force=True)

    result = find_best_trip(
        lat=float(data.get("lat", 32.0880)),
        lon=float(data.get("lon", 34.7898)),
        buffer_minutes=float(data.get("buffer", 3)),
        radius_m=float(data.get("radius", 666))
    )

    if result is None:
        return jsonify({"fallback": "No suitable trip found"})

    return jsonify(to_serializable(result))
