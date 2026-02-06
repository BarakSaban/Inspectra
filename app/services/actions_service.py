import os
import pandas as pd
from Actions import Actions

_actions = None

def get_actions():
    global _actions
    if _actions is not None:
        return _actions

    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    GTFS_PATH = os.path.join(BASE_DIR, "gtfs", "gtfs_filtered")

    try:
        stops_df = pd.read_csv(os.path.join(GTFS_PATH, "stops.txt"))
        stop_times_df = pd.read_csv(os.path.join(GTFS_PATH, "stop_times.txt"))
        trips_df = pd.read_csv(os.path.join(GTFS_PATH, "trips.txt"))
        routes_df = pd.read_csv(os.path.join(BASE_DIR, "static", "routes_with_avgs.csv"))

        _actions = Actions(stops_df, stop_times_df, trips_df, routes_df)
        print("✓ Actions initialized")
    except Exception as e:
        print("⚠️ Actions init failed:", e)
        _actions = None

    return _actions
