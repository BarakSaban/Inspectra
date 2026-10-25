"""The recommendation workflow behind `POST /api/find_best_trip`: live SIRI data first, static GTFS as fallback."""
import logging

from app.services.live_trips import get_live_trip_options
from app.services.routing import InspectorLocation, get_engine
from app.utils.geo import trim_shape_to_stop

logger = logging.getLogger(__name__)


def fetch_live_options(lat, lon, gtfs, radius_m):
    """Live SIRI options near the point. SIRI trouble must never break a recommendation, so errors -> []."""
    try:
        return get_live_trip_options(lat, lon, gtfs, radius_m=radius_m)
    except Exception:
        logger.exception("Live SIRI lookup failed; using static GTFS only")
        return []


def _attach_result_metadata(result, source_name, live_status):
    is_live = source_name == "live"
    label = "Live SIRI data" if is_live else "Static GTFS fallback"
    for target in (result, result["best_option"]):
        target["data_source"] = source_name
        target["source_label"] = label
        target["live_status"] = live_status
        target["is_live"] = is_live
    return result


def is_winning_live_option(live_option, best):
    """The scored winner must be this live candidate itself: same stop, same route, same arrival."""
    if not best.get("is_live"):
        return False
    for key in ("stop_id", "route_id"):
        if live_option.get(key) is None or best.get(key) is None or str(live_option[key]) != str(best[key]):
            return False
    return live_option.get("minutes_until_arrival") == best.get("minutes_until_arrival")


def find_best_trip(lat: float, lon: float, buffer_minutes: float = 3, radius_m: float = 666):
    """
    The best next bus for an inspector at (lat, lon) as {best_option, stop_feature, shape_feature, data_source, ...},
    or None when there is no engine (GTFS unavailable) or no trip is worth taking.
    """
    engine = get_engine()
    if engine is None:
        return None
    gtfs = engine.gtfs

    live_options = fetch_live_options(lat, lon, gtfs, radius_m)
    if not live_options:
        logger.info("No valid live SIRI candidate for lat=%s lon=%s radius_m=%s; static GTFS only.", lat, lon, radius_m)

    best = engine.find_best_fine_trip(
        InspectorLocation("local", lat, lon),
        buffer_minutes=buffer_minutes,
        radius_m=radius_m,
        live_options=live_options,
    )
    if not best:
        return None

    live_option = next((option for option in live_options if is_winning_live_option(option, best)), None)
    if live_option:
        stop_feature, shape_feature = live_option["stop_feature"], live_option["shape_feature"]
        source_name, live_status = "live", "live"
    else:
        if live_options:
            logger.info("Live SIRI candidates did not win scoring for lat=%s lon=%s; using static GTFS.", lat, lon)
        stop_feature = gtfs.stop_lookup.get(str(best["stop_id"]))
        shape_feature = gtfs.shape_lookup.get(gtfs.shape_key(best["trip_id"]))
        source_name, live_status = "static", "fallback"

    result = {
        "best_option": best,
        "stop_feature": stop_feature,
        "shape_feature": trim_shape_to_stop(shape_feature, stop_feature),
    }
    return _attach_result_metadata(result, source_name, live_status)
