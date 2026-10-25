import json
import logging
import os

from utils.geo_utils import haversine_meters, to_serializable

logger = logging.getLogger(__name__)

_stops_gj = None
_shapes_gj = None
_stop_shape_map = None
_stop_lookup = None
_shape_lookup = None


def load_geo_data():
    global _stops_gj, _shapes_gj, _stop_shape_map, _stop_lookup, _shape_lookup

    if _stops_gj is not None:
        return

    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    STATIC_DIR = os.path.join(BASE_DIR, "static")

    try:
        with open(os.path.join(STATIC_DIR, "stops.geojson"), encoding="utf-8") as stops_file:
            _stops_gj = json.load(stops_file)
        with open(os.path.join(STATIC_DIR, "shapes.geojson"), encoding="utf-8") as shapes_file:
            _shapes_gj = json.load(shapes_file)
        with open(os.path.join(STATIC_DIR, "stop_shape_map.json"), encoding="utf-8") as stop_map_file:
            _stop_shape_map = json.load(stop_map_file)

        _stop_lookup = {
            str(f["properties"]["stop_id"]): f
            for f in _stops_gj.get("features", [])
        }

        _shape_lookup = {
            str(f["properties"].get("shape_id")): f
            for f in _shapes_gj.get("features", [])
        }

        logger.info("Geo data loaded")

    except Exception as exc:
        logger.warning("Geo data load failed: %s", exc)

        _stops_gj = {"features": []}
        _shapes_gj = {"features": []}
        _stop_shape_map = []
        _stop_lookup = {}
        _shape_lookup = {}

def get_stops_geojson():
    load_geo_data()
    return _stops_gj


def get_shapes_geojson():
    load_geo_data()
    return _shapes_gj


def get_stop_shape_map():
    load_geo_data()
    return _stop_shape_map


def get_stop_lookup():
    load_geo_data()
    return _stop_lookup


def get_shape_lookup():
    load_geo_data()
    return _shape_lookup

def find_nearest_stop(lat: float, lon: float):
    """Legacy nearest-stop helper kept for fallback/offline scenarios.

    Prefer the cached stop lookup services when available; this helper is retained
    for compatibility and offline fallback use only.
    """
    logger.warning("find_nearest_stop is legacy and should only be used for offline fallback paths.")
    stops_gj = get_stops_geojson()

    best = None
    best_distance = float("inf")

    for feature in stops_gj.get("features", []):
        coords = feature["geometry"]["coordinates"]
        stop_lat = coords[1]
        stop_lon = coords[0]

        distance = haversine_meters(lat, lon, stop_lat, stop_lon)

        if distance < best_distance:
            best_distance = distance
            best = feature

    if best is None:
        return None

    stop_id = str(best["properties"]["stop_id"])
    mappings = [
        m for m in get_stop_shape_map()
        if str(m.get("stop_id")) == stop_id
    ]

    return {
        "stop": to_serializable(best),
        "distance_m": to_serializable(best_distance),
        "mappings": to_serializable(mappings)
    }
