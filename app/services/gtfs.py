"""The static GTFS feed and everything derived from it.

`GtfsData` is the single source of truth for schedule data: the routing engine, the live-data matcher and the
recommendation service all read from it. Map GeoJSON, the stop->route index and the lookups are derived from the
GTFS tables on demand, so there is no separate generated artifact that can drift out of sync with the feed.
"""
import logging
import threading
from functools import cached_property

import numpy as np
import pandas as pd

from app import config
from app.utils.ids import normalize_id

logger = logging.getLogger(__name__)

# DontPay columns are 3-hour slots named by their time range; the slot index is hour // 3.
DONTPAY_SLOTS = (
    "00:00-02:59", "03:00-05:59", "06:00-08:59", "09:00-11:59",
    "12:00-14:59", "15:00-17:59", "18:00-20:59", "21:00-23:59",
)


# calendar.txt column per weekday, indexed like datetime.weekday() (Monday = 0)
WEEKDAY_COLUMNS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def gtfs_time_to_minutes(series):
    """Vectorised 'HH:MM:SS' -> minutes since midnight (GTFS hours may exceed 23). Invalid -> NaN."""
    parts = series.astype(str).str.split(":", expand=True)
    if parts.shape[1] < 3:
        return pd.Series(np.nan, index=series.index)
    return (
        pd.to_numeric(parts[0], errors="coerce") * 60
        + pd.to_numeric(parts[1], errors="coerce")
        + pd.to_numeric(parts[2], errors="coerce") / 60.0
    )


def _records(frame):
    """DataFrame -> list of dicts with NaN replaced by None (valid JSON)."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


class GtfsData:
    """
    Parameters are the GTFS tables as DataFrames. `routes` is the routes table enriched with fare-evasion
    columns (`DontPay - HH:MM-HH:MM`); `shapes` (map geometry) and `calendar` (which weekdays each service runs)
    are optional.
    """

    def __init__(self, stops, stop_times, trips, routes, shapes=None, calendar=None):
        self.stops = stops.reset_index(drop=True)
        self.stop_times = stop_times
        self.trips = trips
        self.routes = routes
        self.shapes = shapes
        self.calendar = calendar
        self._running_trips = {}  # weekday -> trip_ids that run that day

        arrival_minutes = gtfs_time_to_minutes(stop_times["arrival_time"])
        # Per stop: that stop's stop_times with a numeric `arrival_min` column.
        self.stop_times_by_stop = {
            stop_id: frame for stop_id, frame in stop_times.assign(arrival_min=arrival_minutes.values).groupby("stop_id")
        }
        # Per trip: arrival minute at its final stop (when the ride ends).
        self.trip_last_arrival = (
            pd.Series(arrival_minutes.values).groupby(stop_times["trip_id"].values).max().to_dict()
        )
        self._trip_route = dict(zip(trips["trip_id"], trips["route_id"]))
        self._trip_shape = dict(zip(trips["trip_id"], trips["shape_id"])) if "shape_id" in trips.columns else {}
        self._trip_headsign = dict(zip(trips["trip_id"], trips["trip_headsign"])) if "trip_headsign" in trips.columns else {}
        self._route_headsign = (
            trips.groupby("route_id")["trip_headsign"].first().to_dict() if "trip_headsign" in trips.columns else {}
        )
        self.route_trips = trips.groupby("route_id")["trip_id"].agg(set).to_dict()
        self._routes_by_id = routes.drop_duplicates("route_id").set_index("route_id")
        self._warned_columns = set()

    # ---------- scalar lookups ----------
    def route_id_of(self, trip_id):
        route_id = self._trip_route.get(trip_id)
        return None if route_id is None or pd.isna(route_id) else int(route_id)

    def shape_key(self, trip_id):
        """shape_id of a trip as the string key of `shape_lookup` ('136835.0' -> '136835')."""
        shape_id = self._trip_shape.get(trip_id)
        return None if shape_id is None or pd.isna(shape_id) else normalize_id(shape_id)

    def route_label(self, route_id):
        """Public bus number (route_short_name) of a route, or None."""
        if "route_short_name" not in self._routes_by_id.columns:
            return None
        try:
            value = self._routes_by_id.at[int(route_id), "route_short_name"]
        except (KeyError, TypeError, ValueError):
            return None
        return None if pd.isna(value) else str(value)

    def headsign(self, trip_id=None, route_id=None):
        """Destination of a trip, falling back to the route's typical headsign."""
        headsign = self._trip_headsign.get(trip_id)
        if headsign is None and route_id is not None:
            try:
                headsign = self._route_headsign.get(int(route_id))
            except (TypeError, ValueError):
                headsign = None
        return headsign

    def dontpay(self, route_id, hour):
        """Average non-paying passengers for a route in the 3-hour slot containing `hour` (None if unknown)."""
        try:
            route_id = int(route_id)  # live route_ids arrive as strings
        except (TypeError, ValueError):
            return None

        column = f"DontPay - {DONTPAY_SLOTS[hour // 3]}"
        if column not in self._routes_by_id.columns:
            if column not in self._warned_columns:
                self._warned_columns.add(column)
                logger.warning("routes table has no column %r; fare-evasion scores unavailable for this slot", column)
            return None
        try:
            value = self._routes_by_id.at[route_id, column]
        except KeyError:
            return None
        if pd.isna(value):
            return None
        return value.item() if hasattr(value, "item") else value

    def trips_running_on(self, weekday):
        """
        trip_ids that run on a weekday (Monday = 0), or None when the feed has no calendar and every trip must be
        assumed to run. Only weekday flags are used (not date ranges): feeds are snapshots, so a date window would
        wrongly empty the schedule once the snapshot ages. Trips of a service missing from the calendar are kept.
        """
        if self.calendar is None or "service_id" not in self.trips.columns:
            return None
        if weekday not in self._running_trips:
            runs_today = set(self.calendar.loc[self.calendar[WEEKDAY_COLUMNS[weekday]] == 1, "service_id"])
            known = set(self.calendar["service_id"])
            services = self.trips["service_id"]
            self._running_trips[weekday] = set(self.trips.loc[services.isin(runs_today) | ~services.isin(known), "trip_id"])
        return self._running_trips[weekday]

    # ---------- derived map data ----------
    @cached_property
    def stop_lookup(self):
        """stop_id (str) -> GeoJSON Point feature carrying every stops.txt column as properties."""
        records = _records(self.stops)
        return {
            str(row["stop_id"]): {
                "type": "Feature",
                "properties": row,
                "geometry": {"type": "Point", "coordinates": [row["stop_lon"], row["stop_lat"]]},
            }
            for row in records
        }

    @cached_property
    def shape_lookup(self):
        """shape_id (str) -> GeoJSON LineString feature, points ordered by shape_pt_sequence."""
        if self.shapes is None or self.shapes.empty:
            return {}
        lookup = {}
        ordered = self.shapes.sort_values(["shape_id", "shape_pt_sequence"])
        for shape_id, points in ordered.groupby("shape_id"):
            coordinates = [[lon, lat] for lon, lat in zip(points["shape_pt_lon"], points["shape_pt_lat"])]
            if len(coordinates) < 2:
                continue  # skip broken shapes
            lookup[normalize_id(shape_id)] = {
                "type": "Feature",
                "properties": {"shape_id": int(shape_id) if float(shape_id).is_integer() else shape_id},
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        return lookup

    @cached_property
    def stop_routes(self):
        """
        stop_id (str) -> the routes serving that stop, one entry per (route, shape, direction):
        {stop_id, route_id, shape_id, direction_id, trip_id (a representative trip), route_short_name}.
        This is what a live SIRI visit is matched against.
        """
        trips = self.trips[["trip_id", "route_id", "shape_id"] + (["direction_id"] if "direction_id" in self.trips.columns else [])]
        merged = self.stop_times[["stop_id", "trip_id"]].merge(trips, on="trip_id", how="inner")
        keys = ["stop_id", "route_id", "shape_id"] + (["direction_id"] if "direction_id" in merged.columns else [])
        grouped = merged.groupby(keys, dropna=False)["trip_id"].min().reset_index()

        names = (
            self._routes_by_id["route_short_name"].to_dict() if "route_short_name" in self._routes_by_id.columns else {}
        )
        index = {}
        for row in grouped.to_dict(orient="records"):
            entry = {
                "stop_id": normalize_id(row["stop_id"]),
                "route_id": normalize_id(row["route_id"]),
                "shape_id": normalize_id(row["shape_id"]),
                "direction_id": normalize_id(row.get("direction_id")),
                "trip_id": row["trip_id"],
                "route_short_name": names.get(row["route_id"]),
            }
            index.setdefault(entry["stop_id"], []).append(entry)
        return index

    @cached_property
    def stop_names_by_code(self):
        """Public stop_code (str) -> stop name; resolves SIRI destination references."""
        if "stop_code" not in self.stops.columns:
            return {}
        return {
            normalize_id(code): name
            for code, name in zip(self.stops["stop_code"], self.stops["stop_name"])
            if normalize_id(code)
        }


def load_gtfs():
    """Read the committed feed (`data/gtfs`) and the fare-evasion table into a GtfsData."""
    read = lambda name: pd.read_csv(config.GTFS_DIR / name)  # noqa: E731
    calendar_file = config.GTFS_DIR / "calendar.txt"
    return GtfsData(
        stops=read("stops.txt"),
        stop_times=read("stop_times.txt"),
        trips=read("trips.txt"),
        routes=pd.read_csv(config.FARE_EVASION_CSV),
        shapes=read("shapes.txt"),
        calendar=read("calendar.txt") if calendar_file.exists() else None,
    )


_gtfs = None
_gtfs_lock = threading.Lock()


def get_gtfs():
    """The shared GtfsData, loaded on first use. None if the feed cannot be read (callers fall back gracefully)."""
    global _gtfs
    if _gtfs is not None:
        return _gtfs
    with _gtfs_lock:
        if _gtfs is None:
            try:
                _gtfs = load_gtfs()
                logger.info("GTFS loaded: %s stops, %s trips", len(_gtfs.stops), len(_gtfs.trips))
            except Exception:
                logger.exception("GTFS load failed")
    return _gtfs
