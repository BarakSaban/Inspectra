from Classes import Inspector
from app.services.actions_service import get_actions
from app.services.geo_service import get_stop_lookup, get_shape_lookup

import pandas as pd

def find_best_trip(lat: float, lon: float, buffer_minutes: float = 3, radius_m: float = 666):
    actions = get_actions()
    if actions is None:
        return None
    
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
        radius_m=radius_m
    )

    if not best:
        return None

    stop_lookup = get_stop_lookup()
    shape_lookup = get_shape_lookup()

    stop_id = str(best["stop_id"])
    trip_id = str(best["trip_id"])

    stop_feature = stop_lookup.get(stop_id)
    shape_feature = None

    try:
        trips_df = actions.trips_df  # comes from Actions
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

    return {
        "best_option": best,
        "stop_feature": stop_feature,
        "shape_feature": shape_feature
    }

