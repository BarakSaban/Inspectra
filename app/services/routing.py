"""The routing engine: which bus should an inspector board to maximise expected fare-violation fines.

Candidates come from two sources, scored the same way:
  * scheduled trips from the static GTFS timetable (always available), and
  * live SIRI buses (see `live_trips`), which win whenever one of them can be scored.
A trip's score is min(fines that fit in the time on board, average non-paying passengers on that route now).
"""
import logging
import threading
from dataclasses import dataclass

import networkx as nx
import pandas as pd
from shapely.geometry import mapping

from app.services.gtfs import get_gtfs
from app.services.walking import WalkingNetwork
from app.utils.clock import minutes_since_midnight, now_israel

logger = logging.getLogger(__name__)

MINUTES_PER_FINE = 5
# Assignment mirrors find_best_fine_trip: a real bus that is on its way beats a timetable-only trip.
# The bonus dwarfs any fine count, so the matching only falls back to static trips when no live bus is left.
LIVE_ASSIGNMENT_BONUS = 1000


@dataclass(frozen=True)
class InspectorLocation:
    """What the engine needs to know about an inspector."""
    inspector_id: str
    lat: float
    lon: float
    available: bool = True


class RoutingEngine:
    def __init__(self, gtfs, walking=None):
        self.gtfs = gtfs
        self.walking = walking or WalkingNetwork(gtfs.stops)

    # --------------------------
    # Candidates
    # --------------------------
    def find_scheduled_trips(self, nearby_stops, buffer_minutes=3, weekday=None):
        """
        Timetable departures the inspector can still catch, as a DataFrame sorted by arrival. Only trips that run on
        `weekday` (default: today in Israel) are offered when the feed has a calendar.
        """
        now_minutes = minutes_since_midnight()
        running = self.gtfs.trips_running_on(now_israel().weekday() if weekday is None else weekday)
        reachable = []
        for stop_id, walk_minutes, route_geom in nearby_stops:
            stop_times = self.gtfs.stop_times_by_stop.get(stop_id)
            if stop_times is None or stop_times.empty:
                continue

            if running is not None:
                stop_times = stop_times[stop_times["trip_id"].isin(running)]
            waits = stop_times["arrival_min"] - now_minutes
            catchable = stop_times[waits >= walk_minutes + buffer_minutes]
            if catchable.empty:
                continue

            geometry = mapping(route_geom)
            for trip_id, arrival_time, wait in zip(catchable["trip_id"], catchable["arrival_time"], waits[catchable.index]):
                reachable.append({
                    'trip_id': trip_id,
                    'stop_id': stop_id,
                    'arrival_time': arrival_time,
                    'walk_time': round(walk_minutes, 2),
                    'route_geometry': geometry,
                    'minutes_until_arrival': round(float(wait), 1),
                })

        if not reachable:
            return pd.DataFrame()
        return pd.DataFrame(reachable).sort_values(by='minutes_until_arrival')

    @staticmethod
    def _dedupe_by_trip(rows):
        """One row per trip_id (a trip passes several nearby stops); the later arrival wins, ties keep the first."""
        deduped = {}
        for row in rows:
            current = deduped.get(row['trip_id'])
            if current is None or row['minutes_until_arrival'] > current['minutes_until_arrival']:
                deduped[row['trip_id']] = row
        return list(deduped.values())

    @staticmethod
    def _normalize_live_candidate(candidate):
        """A live option (see live_trips) as an engine row, or None when it lacks what scoring needs."""
        if not isinstance(candidate, dict):
            return None
        if candidate.get('trip_id') is None or candidate.get('stop_id') is None:
            return None

        arrival_time = candidate.get('arrival_time') or candidate.get('expected_arrival_time')
        minutes_until_arrival = candidate.get('minutes_until_arrival')
        if arrival_time is None and minutes_until_arrival is None:
            return None
        try:
            minutes_until_arrival = float(minutes_until_arrival)
        except (TypeError, ValueError):
            minutes_until_arrival = None

        return {
            'trip_id': str(candidate['trip_id']),
            'route_id': candidate.get('route_id'),
            'stop_id': str(candidate['stop_id']),
            'vehicle_ref': candidate.get('vehicle_ref'),
            'vehicle_location': candidate.get('vehicle_location'),
            'route_num': candidate.get('route_num'),
            'destination': candidate.get('destination'),
            'arrival_time': arrival_time,
            'walk_time': 0.0,
            'route_geometry': None,
            'minutes_until_arrival': minutes_until_arrival,
            'is_live': True,
            'data_source': 'live',
            'source_label': 'Live SIRI data',
            'live_status': 'live',
        }

    # --------------------------
    # Scoring
    # --------------------------
    def estimate_ride_minutes(self, route_id, stop_id):
        """
        Typical remaining ride time from a stop on a route, from the static timetable (median over the route's
        trips). Live visits have no trip_id that exists in this feed, but their route_id and stop_id do.
        """
        try:
            route_id = int(route_id)
        except (TypeError, ValueError):
            return None

        by_stop = self.gtfs.stop_times_by_stop
        stop_times = by_stop.get(stop_id)
        if stop_times is None:
            stop_times = by_stop.get(str(stop_id))
        if stop_times is None:
            try:
                stop_times = by_stop.get(int(stop_id))
            except (TypeError, ValueError):
                stop_times = None
        route_trips = self.gtfs.route_trips.get(route_id)
        if stop_times is None or stop_times.empty or not route_trips:
            return None

        rows = stop_times[stop_times["trip_id"].isin(route_trips)]
        ride = (rows["trip_id"].map(self.gtfs.trip_last_arrival) - rows["arrival_min"]).dropna()
        ride = ride[ride > 0]
        return round(float(ride.median()), 1) if not ride.empty else None

    def _score_option(self, row, time_on_board, route_id, walk_time, arrival_time):
        """A scored option, or None when nothing can be fined (no time on board, unknown or zero DontPay)."""
        if time_on_board <= 0:
            return None
        avg_dont_pay = self.gtfs.dontpay(route_id, now_israel().hour)
        if avg_dont_pay is None:
            return None

        potential_fines = min(int(time_on_board // MINUTES_PER_FINE), int(avg_dont_pay))
        if potential_fines <= 0:
            return None

        return {
            'trip_id': row['trip_id'],
            'route_id': route_id,
            'route_num': row.get('route_num') or self.gtfs.route_label(route_id),
            'destination': row.get('destination') or self.gtfs.headsign(row['trip_id'], route_id),
            'vehicle_location': row.get('vehicle_location'),
            'stop_id': row['stop_id'],
            'arrival_time': arrival_time,
            'walk_time': walk_time,
            'route_geometry': row.get('route_geometry'),
            'minutes_until_arrival': row.get('minutes_until_arrival', time_on_board),
            'time_on_board_min': round(time_on_board, 1),
            'AvgDontPay': avg_dont_pay,
            'potential_fines': potential_fines,
            'is_live': bool(row.get('is_live')),
            'data_source': row.get('data_source', 'static'),
            'source_label': row.get('source_label', 'Static GTFS fallback'),
            'live_status': row.get('live_status', 'fallback'),
        }

    def _score_scheduled(self, row, now_minutes):
        last_arrival = self.gtfs.trip_last_arrival.get(row['trip_id'])
        if last_arrival is None or pd.isna(last_arrival):
            return None
        return self._score_option(
            row,
            time_on_board=last_arrival - now_minutes,
            route_id=self.gtfs.route_id_of(row['trip_id']),
            walk_time=row['walk_time'],
            arrival_time=row['arrival_time'],
        )

    def _score_live(self, row, walk_by_stop, buffer_minutes):
        wait = row.get('minutes_until_arrival')
        if wait is None:
            return None
        walk_info = walk_by_stop.get(str(row['stop_id']))
        if walk_info is None:
            logger.debug("Live stop %s is outside walking range", row['stop_id'])
            return None
        walk_time, walk_geometry = walk_info
        if float(wait) < walk_time + buffer_minutes:
            logger.debug("Live bus at stop %s in %.1f min is too soon (walk %.1f min)", row['stop_id'], wait, walk_time)
            return None

        row = {**row, 'route_geometry': mapping(walk_geometry)}
        route_id = row.get('route_id')
        if route_id is None:
            route_id = self.gtfs.route_id_of(row['trip_id'])
        # Time on board is the ride after boarding; the wait is only a fallback when the route can't be estimated.
        ride_minutes = self.estimate_ride_minutes(route_id, row['stop_id'])
        return self._score_option(
            row,
            time_on_board=ride_minutes if ride_minutes is not None else float(wait),
            route_id=route_id,
            walk_time=walk_time,
            arrival_time=row.get('arrival_time'),
        )

    @staticmethod
    def _live_identity(row):
        """A live bus is identified by its vehicle, so two inspectors are never sent to the same bus."""
        return ('live', row.get('vehicle_ref') or row['trip_id'], row['stop_id'], row.get('minutes_until_arrival'))

    def _score_candidates(self, inspector, buffer_minutes, radius_m, max_walk_minutes, live_options):
        """Every fine-able option for an inspector as (identity, option) pairs: scheduled first, then live."""
        nearby = self.walking.nearby_stops(inspector.lat, inspector.lon, radius_m=radius_m, max_walk_minutes=max_walk_minutes)
        walk_by_stop = {str(stop_id): (walk, geometry) for stop_id, walk, geometry in nearby}

        scheduled = self.find_scheduled_trips(nearby, buffer_minutes)
        scheduled_rows = self._dedupe_by_trip(scheduled.to_dict(orient='records') if not scheduled.empty else [])
        live_rows = [row for row in map(self._normalize_live_candidate, live_options or []) if row is not None]

        now_minutes = minutes_since_midnight()
        scored = []
        for row in scheduled_rows:
            option = self._score_scheduled(row, now_minutes)
            if option is not None:
                scored.append((row['trip_id'], option))

        seen_live = set()
        for row in live_rows:
            identity = self._live_identity(row)
            if identity in seen_live:
                continue  # duplicate SIRI visit
            seen_live.add(identity)
            option = self._score_live(row, walk_by_stop, buffer_minutes)
            if option is not None:
                scored.append((identity, option))
        return scored

    # --------------------------
    # Public API
    # --------------------------
    def find_best_fine_trip(self, inspector, buffer_minutes=3, radius_m=666, max_walk_minutes=8, live_options=None):
        """Best trip for fines potential. A scored live bus beats any timetable-only trip; static is the fallback."""
        if not inspector.available:
            logger.info("Inspector %s unavailable", inspector.inspector_id)
            return None

        scored = self._score_candidates(inspector, buffer_minutes, radius_m, max_walk_minutes, live_options)
        if not scored:
            logger.info("No fine-able trips for inspector at (%s, %s)", inspector.lat, inspector.lon)
            return None

        # max() keeps the first of equal scores, so earlier (sooner) candidates win ties.
        options = [option for _, option in scored]
        best_live = max((o for o in options if o['is_live']), key=lambda o: o['potential_fines'], default=None)
        best_static = max((o for o in options if not o['is_live']), key=lambda o: o['potential_fines'], default=None)
        return best_live or best_static

    def assign_best_trips_global(self, inspectors, buffer_minutes=3, radius_m=666, max_walk_minutes=8, live_options_by_inspector=None):
        """
        Assign inspectors to trips/buses to maximise total fines (max-weight bipartite matching), never giving
        the same trip or live bus to two inspectors. Returns a DataFrame with one row per assignment.
        """
        graph = nx.Graph()
        details = {}
        live_options_by_inspector = live_options_by_inspector or {}

        for inspector in inspectors:
            if not inspector.available:
                continue

            inspector_node = f"inspector_{inspector.inspector_id}"
            scored = self._score_candidates(
                inspector, buffer_minutes, radius_m, max_walk_minutes,
                live_options_by_inspector.get(inspector.inspector_id, []),
            )
            for identity, option in scored:
                trip_node = f"trip_{identity}"
                weight = option['potential_fines'] + (LIVE_ASSIGNMENT_BONUS if option['is_live'] else 0)
                existing = graph.get_edge_data(inspector_node, trip_node)
                if existing and existing['weight'] >= weight:
                    continue
                graph.add_edge(inspector_node, trip_node, weight=weight)
                details[(inspector_node, trip_node)] = {
                    **option,
                    'inspector_id': inspector.inspector_id,
                    'inspector_lat': inspector.lat,
                    'inspector_lon': inspector.lon,
                }

        if not graph.edges:
            return pd.DataFrame()

        matching = nx.algorithms.matching.max_weight_matching(graph, maxcardinality=True, weight="weight")
        results = []
        for u, v in matching:
            inspector_node, trip_node = (u, v) if u.startswith("inspector_") else (v, u)
            if (inspector_node, trip_node) in details:
                results.append(details[(inspector_node, trip_node)])
        return pd.DataFrame(results)


_engine = None
_engine_lock = threading.Lock()


def get_engine():
    """The shared RoutingEngine, built on first use. None if the GTFS feed cannot be loaded."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            gtfs = get_gtfs()
            if gtfs is not None:
                _engine = RoutingEngine(gtfs)
    return _engine
