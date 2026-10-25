import unittest
from unittest.mock import patch

import pandas as pd
from shapely.geometry import LineString

from app.services.gtfs import WEEKDAY_COLUMNS
from app.services.routing import InspectorLocation, RoutingEngine
from app.services.walking import WalkingNetwork
from app.utils.clock import now_israel
from tests.helpers import make_engine, make_gtfs, offline_walking

INSPECTOR = InspectorLocation("I001", 32.088, 34.7898)


class StaticScoringTests(unittest.TestCase):
    def test_best_scheduled_trip_carries_route_label_destination_and_score(self):
        with offline_walking():
            best = make_engine().find_best_fine_trip(INSPECTOR)
        self.assertFalse(best["is_live"])
        self.assertEqual((best["route_id"], best["route_num"], best["destination"]), (101, "101", "Terminal"))
        self.assertEqual((best["data_source"], best["source_label"]), ("static", "Static GTFS fallback"))
        # time_on_board_min is rounded to 0.1, so its floor can sit one fine above the unrounded value the score used.
        self.assertIn(best["potential_fines"], range(1, int(best["time_on_board_min"] // 5) + 1))
        self.assertTrue(best["route_geometry"])

    def test_unavailable_inspector_gets_nothing(self):
        away = InspectorLocation("I001", 32.088, 34.7898, available=False)
        self.assertIsNone(make_engine().find_best_fine_trip(away))

    def test_no_fares_to_catch_means_no_recommendation(self):
        with offline_walking():
            self.assertIsNone(make_engine(dont_pay=0).find_best_fine_trip(INSPECTOR))

    def test_nowhere_near_any_stop(self):
        self.assertIsNone(make_engine().find_best_fine_trip(InspectorLocation("I001", 10.0, 10.0)))

    def test_scheduled_trips_skip_departures_too_soon_to_walk_to(self):
        engine = make_engine()
        nearby = [("stop_1", 40.0, None)]  # a 40 minute walk: the bus in 30 minutes cannot be caught
        self.assertTrue(engine.find_scheduled_trips(nearby).empty)

    def test_one_trip_passing_two_stops_is_scored_once(self):
        engine = make_engine()
        engine.gtfs.stop_times_by_stop["stop_2"] = engine.gtfs.stop_times_by_stop["stop_1"].assign(stop_id="stop_2")
        deduped = engine._dedupe_by_trip([
            {"trip_id": "t", "stop_id": "stop_1", "minutes_until_arrival": 10.0},
            {"trip_id": "t", "stop_id": "stop_2", "minutes_until_arrival": 14.0},
            {"trip_id": "u", "stop_id": "stop_1", "minutes_until_arrival": 5.0},
        ])
        self.assertEqual([(r["trip_id"], r["stop_id"]) for r in deduped], [("t", "stop_2"), ("u", "stop_1")])


class ServiceDayTests(unittest.TestCase):
    def engine(self, flags):
        calendar = pd.DataFrame([{"service_id": "S1", "monday": 0, "tuesday": 0, "wednesday": 0, "thursday": 0,
                                  "friday": 0, "saturday": 0, "sunday": 0, **flags}])
        return make_engine(calendar=calendar)

    def scheduled(self, engine, weekday):
        walking = [("stop_1", 1.0, LineString([(34.7898, 32.088), (34.79, 32.09)]))]
        return engine.find_scheduled_trips(walking, buffer_minutes=3, weekday=weekday)

    def test_trips_that_do_not_run_today_are_not_offered(self):
        engine = self.engine({"saturday": 1})
        self.assertEqual(len(self.scheduled(engine, weekday=5)), 1)
        self.assertTrue(self.scheduled(engine, weekday=2).empty)

    def test_today_defaults_to_the_current_israeli_weekday(self):
        engine = self.engine({day: 1 for day in WEEKDAY_COLUMNS})
        with patch("app.services.routing.now_israel", return_value=now_israel()):
            self.assertEqual(len(engine.find_scheduled_trips([("stop_1", 1.0, LineString([(0, 0), (1, 1)]))])), 1)

    def test_a_day_with_no_service_means_no_static_fallback(self):
        with offline_walking():
            self.assertIsNotNone(self.engine({day: 1 for day in WEEKDAY_COLUMNS}).find_best_fine_trip(INSPECTOR))
            self.assertIsNone(self.engine({}).find_best_fine_trip(INSPECTOR))


class LiveScoringTests(unittest.TestCase):
    def live(self, **overrides):
        return {"trip_id": "old_release_trip", "route_id": "101", "stop_id": "stop_1", "minutes_until_arrival": 15.0, **overrides}

    def best(self, *live, engine=None):
        with offline_walking():
            return (engine or make_engine()).find_best_fine_trip(INSPECTOR, live_options=list(live))

    def test_live_bus_is_scored_by_ride_time_and_beats_a_better_static_trip(self):
        best = self.best(self.live())
        self.assertTrue(best["is_live"])
        self.assertEqual(best["route_id"], "101")
        self.assertEqual(best["time_on_board_min"], 20.0)  # the ride, not the 15 minute wait
        self.assertEqual((best["potential_fines"], best["AvgDontPay"]), (4, 12))  # the static trip alone would give 10

    def test_bus_too_soon_to_walk_to_is_skipped(self):
        best = self.best(self.live(minutes_until_arrival=1.0))
        self.assertFalse(best["is_live"])

    def test_bus_at_a_stop_out_of_walking_range_is_skipped(self):
        best = self.best(self.live(stop_id="stop_2"))
        self.assertFalse(best["is_live"])

    def test_route_without_fare_data_cannot_be_scored_live(self):
        self.assertFalse(self.best(self.live(route_id="999"))["is_live"])  # no fare data -> cannot be scored

    def test_live_option_keeps_its_own_label_destination_and_vehicle(self):
        best = self.best(self.live(route_num="66", destination="Ramat Gan", vehicle_location={"lat": 1, "lon": 2}))
        self.assertEqual((best["route_num"], best["destination"], best["vehicle_location"]), ("66", "Ramat Gan", {"lat": 1, "lon": 2}))

    def test_live_option_without_destination_uses_the_routes_headsign(self):
        self.assertEqual(self.best(self.live(destination=None))["destination"], "Terminal")

    def test_duplicate_visits_do_not_inflate_the_result(self):
        self.assertEqual(self.best(self.live(), self.live())["potential_fines"], self.best(self.live())["potential_fines"])

    def test_unusable_live_candidates_fall_back_to_static(self):
        for broken in ({"trip_id": "t", "stop_id": "stop_1"}, {"stop_id": "stop_1", "minutes_until_arrival": 9}, "nonsense", None):
            best = self.best(broken)
            self.assertFalse(best["is_live"], broken)

    def test_ride_estimate_comes_from_the_routes_timetable(self):
        engine = make_engine()
        self.assertEqual(engine.estimate_ride_minutes("101", "stop_1"), 20.0)
        self.assertIsNone(engine.estimate_ride_minutes("101", "stop_2"))  # last stop: nothing left to ride
        self.assertIsNone(engine.estimate_ride_minutes("999", "stop_1"))
        self.assertIsNone(engine.estimate_ride_minutes(None, "stop_1"))
        self.assertIsNone(engine.estimate_ride_minutes("101", "no-such-stop"))


class AssignmentTests(unittest.TestCase):
    people = [InspectorLocation("I001", 32.088, 34.7898), InspectorLocation("I002", 32.0881, 34.7899)]

    def assign(self, engine, people=None, live=None):
        with offline_walking():
            return engine.assign_best_trips_global(self.people if people is None else people, live_options_by_inspector=live)

    def test_one_trip_goes_to_only_one_inspector(self):
        result = self.assign(make_engine(route_ids=(101,)))
        self.assertEqual(len(result), 1)
        self.assertIn(result.iloc[0]["inspector_id"], {"I001", "I002"})

    def test_two_trips_serve_two_inspectors_without_overlap(self):
        result = self.assign(make_engine(route_ids=(101, 102)))
        self.assertEqual(sorted(result["inspector_id"]), ["I001", "I002"])
        self.assertEqual(len(set(result["trip_id"])), 2)

    def test_a_live_bus_is_preferred_and_never_double_booked(self):
        bus = {"trip_id": "old", "route_id": "101", "stop_id": "stop_1", "vehicle_ref": "bus-7", "minutes_until_arrival": 15.0}
        result = self.assign(make_engine(route_ids=(101,)), live={"I001": [bus], "I002": [bus]})
        by_trip = result.set_index("trip_id")
        self.assertEqual(len(result), 2)  # one inspector gets the bus, the other the scheduled trip
        self.assertTrue(by_trip.loc["old", "is_live"])

    def test_live_bus_beats_a_better_scoring_static_trip_for_a_lone_inspector(self):
        bus = {"trip_id": "old", "route_id": "101", "stop_id": "stop_1", "vehicle_ref": "bus-7", "minutes_until_arrival": 15.0}
        result = self.assign(make_engine(route_ids=(101,)), people=self.people[:1], live={"I001": [bus]})
        self.assertEqual((result.iloc[0]["trip_id"], result.iloc[0]["potential_fines"]), ("old", 4))

    def test_unavailable_inspectors_and_empty_input(self):
        away = [InspectorLocation("I001", 32.088, 34.7898, available=False)]
        self.assertTrue(self.assign(make_engine(), people=away).empty)
        self.assertTrue(self.assign(make_engine(), people=[]).empty)


class WalkingTests(unittest.TestCase):
    def test_falls_back_to_straight_line_when_osm_is_unavailable(self):
        walking = WalkingNetwork(make_gtfs().stops)
        with patch("app.services.walking.ox.graph_from_point", side_effect=ConnectionError("no network")):
            stops = walking.nearby_stops(32.0880, 34.7898)
        self.assertEqual([stop_id for stop_id, _, _ in stops], ["stop_1"])
        self.assertLessEqual(stops[0][1], 8)
        self.assertEqual(stops[0][2].geom_type, "LineString")

    def test_stops_too_far_to_walk_are_excluded(self):
        walking = WalkingNetwork(make_gtfs().stops)
        with offline_walking():
            self.assertEqual(walking.nearby_stops(32.0880, 34.7898, radius_m=5000, max_walk_minutes=2)[0][0], "stop_1")
            self.assertEqual([s for s, _, _ in walking.nearby_stops(32.0950, 34.7950, radius_m=5000, max_walk_minutes=1)], [])

    def test_street_graphs_are_cached_per_area_and_evicted_least_recently_used_first(self):
        import networkx as nx
        walking = WalkingNetwork(make_gtfs().stops)
        build = lambda *args, **kwargs: nx.MultiDiGraph([(1, 2)])  # noqa: E731
        with patch("app.services.walking.ox.graph_from_point", side_effect=build) as download,              patch("app.services.walking.ox.add_edge_travel_times", side_effect=lambda graph: graph):
            walking._graph(32.0880, 34.7898, 666)
            walking._graph(32.0872, 34.7910, 666)          # ~130 m away: reuses the first graph
            self.assertEqual(download.call_count, 1)
            walking._graph(32.0500, 34.7500, 666)          # another part of town: a second graph
            walking._graph(32.0880, 34.7898, 666)          # back again: still cached
            self.assertEqual(download.call_count, 2)
            for lat in (32.20, 32.30, 32.40):              # three more areas push the oldest out
                walking._graph(lat, 34.8, 666)
            self.assertEqual(len(walking._graphs), 4)
            walking._graph(32.0500, 34.7500, 666)          # was evicted: downloaded again
            self.assertEqual(download.call_count, 6)

    def test_nothing_in_range(self):
        self.assertEqual(WalkingNetwork(make_gtfs().stops).nearby_stops(10.0, 10.0), [])


class EngineConstructionTests(unittest.TestCase):
    def test_engine_builds_its_own_walking_network(self):
        engine = RoutingEngine(make_gtfs())
        self.assertIsInstance(engine.walking, WalkingNetwork)

    def test_missing_arrival_times_never_crash_scoring(self):
        gtfs = make_gtfs()
        gtfs.trip_last_arrival["trip_101"] = float("nan")
        with offline_walking():
            self.assertIsNone(RoutingEngine(gtfs, WalkingNetwork(gtfs.stops)).find_best_fine_trip(INSPECTOR))


if __name__ == "__main__":
    unittest.main()
