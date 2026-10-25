import logging

from Classes import Inspector
from app.services.actions_service import get_actions
from app.services.geo_service import get_stop_lookup, get_shape_lookup, get_stop_shape_map
from app.services.siri_service import get_live_best_trip_option

import pandas as pd

logger = logging.getLogger(__name__)


def _attach_result_metadata(result, source_name, live_status):
    if result is None:
        return None

    result["data_source"] = source_name
    result["source_label"] = (
        "Live SIRI data" if source_name == "live" else "Static GTFS fallback"
    )
    result["live_status"] = live_status
    result["is_live"] = source_name == "live"

    best_option = result.get("best_option")
    if isinstance(best_option, dict):
        best_option["data_source"] = source_name
        best_option["source_label"] = result["source_label"]
        best_option["live_status"] = live_status
        best_option["is_live"] = source_name == "live"

    return result


def _is_valid_live_match(live_option, static_best):
    if not isinstance(live_option, dict):
        return False
    if not isinstance(static_best, dict):
        return False

    live_stop_id = live_option.get("stop_id")
    static_stop_id = static_best.get("stop_id")
    if live_stop_id is not None and static_stop_id is not None:
        if str(live_stop_id) == str(static_stop_id):
            return True

    live_term = live_option.get("minutes_until_arrival")
    try:
        if live_term is not None and float(live_term) > 0:
            return True
    except (TypeError, ValueError):
        pass

    live_line = live_option.get("line_ref")
    static_route = static_best.get("route_num")
    if live_line and static_route and str(live_line) == str(static_route):
        return True

    return False


def find_best_trip(lat: float, lon: float, buffer_minutes: float = 3, radius_m: float = 666):
    actions = get_actions()
    if actions is None:
        return None

    stop_lookup = get_stop_lookup()
    shape_lookup = get_shape_lookup()
    stop_shape_map = get_stop_shape_map()

    live_option = get_live_best_trip_option(
        lat,
        lon,
        stop_lookup,
        shape_lookup,
        stop_shape_map,
        actions.trips_df,
        radius_m=radius_m,
    )
    if live_option is None:
        logger.warning(
            "No valid live SIRI candidate found for lat=%s lon=%s radius_m=%s; using static GTFS fallback.",
            lat,
            lon,
            radius_m,
        )
    inspector = Inspector(
        inspector_id="local",
        name="Local",
        lat=lat,
        lon=lon,
        available=True
    )

    best = actions.find_best_fine_trip(
        inspector,
        buffer_minutes=buffer_minutes,
        radius_m=radius_m,
        live_option=live_option,
    )

    if live_option and best and _is_valid_live_match(live_option, best):
        live_result = {
            "best_option": {
                **best,
                "route_geometry": None,
                "data_source": "live",
                "source_label": "Live SIRI data",
                "live_status": "live",
                "is_live": True,
            },
            "stop_feature": live_option.get("stop_feature"),
            "shape_feature": live_option.get("shape_feature"),
        }
        return _attach_result_metadata(live_result, "live", "live")

    if live_option and best and not _is_valid_live_match(live_option, best):
        logger.warning(
            "Live SIRI candidate rejected by validation for lat=%s lon=%s; falling back to static GTFS.",
            lat,
            lon,
        )

    if live_option and not best:
        return None

    if not best:
        return None

    stop_id = str(best["stop_id"])
    trip_id = str(best["trip_id"])

    stop_feature = stop_lookup.get(stop_id)
    shape_feature = None

    try:
        trips_df = actions.trips_df
        shape_id = (
            trips_df.loc[trips_df["trip_id"] == trip_id, "shape_id"]
            .values[0]
        )
        shape_id = str(shape_id).replace(".0", "")
        shape_feature = shape_lookup.get(shape_id)
    except Exception:
        shape_feature = None

    if shape_feature and stop_feature:
        shape_feature = actions.trim_shape_to_stop(
            shape_feature,
            stop_feature
        )

    fallback_result = {
        "best_option": best,
        "stop_feature": stop_feature,
        "shape_feature": shape_feature,
    }
    return _attach_result_metadata(fallback_result, "static", "fallback")

