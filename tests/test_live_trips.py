import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import config
from app.services.live_trips import (
    build_live_trip_option,
    get_live_trip_options,
    match_route_entry,
    stops_within_radius,
)
from tests.helpers import route_entry, route_index, stub_gtfs


def in_minutes(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def visit(**overrides):
    return {"line_ref": "27081", "line_name": "2", "direction_ref": "1", "vehicle_ref": "v1",
            "destination_name": "Downtown", "expected_arrival_time": in_minutes(4), **overrides}


class MatchRouteEntryTests(unittest.TestCase):
    def setUp(self):
        self.index = route_index(
            route_entry("5", 100, "7", direction_id="0"),
            route_entry("5", 200, "7", direction_id="1"),
            route_entry("5", 300, "9", direction_id="0"),
        )

    def match(self, line_ref, line_name=None, direction_ref=None, stop="5"):
        return match_route_entry(self.index, stop, line_ref, line_name, direction_ref)

    def test_line_ref_is_the_route_id(self):
        self.assertEqual(self.match("200", "7", "2")["route_id"], "200")
        self.assertEqual(self.match("ISR:300")["route_id"], "300")  # namespaced refs keep their last segment

    def test_line_ref_contradicting_the_bus_number_is_a_stale_id(self):
        self.assertIsNone(self.match("100", "8"))  # route 100 is bus 7 and no bus 8 exists here
        self.assertEqual(self.match("100", "9")["route_id"], "300")  # falls back to the bus number instead

    def test_unknown_line_ref_falls_back_to_bus_number_and_direction(self):
        self.assertEqual(self.match("stale", "7", "1")["route_id"], "100")
        self.assertEqual(self.match("stale", "7", "2")["route_id"], "200")

    def test_same_bus_number_without_direction_is_ambiguous(self):
        self.assertIsNone(self.match("stale", "7"))

    def test_wrong_direction_is_rejected(self):
        self.assertIsNone(self.match("100", "7", "2"))

    def test_unknown_line_or_stop_is_rejected(self):
        self.assertIsNone(self.match("999", "46"))
        self.assertIsNone(self.match("100", "7", "1", stop="404"))
        self.assertIsNone(self.match(None, None))

    def test_entry_without_direction_matches_any_direction(self):
        index = route_index(route_entry("5", 100, "7", direction_id=None))
        self.assertIsNotNone(match_route_entry(index, "5", "100", "7", "2"))

    def test_representative_trip_is_the_lowest_trip_id(self):
        index = route_index(route_entry("5", 100, "7", shape_id="s", trip_id="b"), route_entry("5", 100, "7", shape_id="s", trip_id="a"))
        self.assertEqual(match_route_entry(index, "5", "100")["trip_id"], "a")

    def test_two_shapes_for_one_route_are_ambiguous(self):
        index = route_index(route_entry("5", 100, "7", shape_id="s1"), route_entry("5", 100, "7", shape_id="s2"))
        self.assertIsNone(match_route_entry(index, "5", "100", "7"))


class BuildOptionTests(unittest.TestCase):
    def setUp(self):
        self.gtfs = stub_gtfs(
            stop_routes=route_index(route_entry("14533", 27081, "2", shape_id="145685", trip_id="t1")),
            stops={"14533": ("20001", 32.088, 34.7898), "99": ("30003", 32.09, 34.79)},
            shapes={"145685": {"properties": {"shape_id": 145685}}},
            names_by_code={"30003": "Terminal X"},
        )

    def test_option_carries_route_shape_stop_and_vehicle(self):
        option = build_live_trip_option(visit(latitude=32.1, longitude=34.8), "14533", self.gtfs)
        self.assertEqual((option["trip_id"], option["route_id"], option["route_num"]), ("t1", "27081", "2"))
        self.assertEqual(option["stop_id"], "14533")
        self.assertEqual(option["shape_feature"], {"properties": {"shape_id": 145685}})
        self.assertEqual(option["stop_feature"]["properties"]["stop_code"], "20001")
        self.assertEqual(option["vehicle_location"], {"lat": 32.1, "lon": 34.8})
        self.assertEqual((option["destination"], option["data_source"], option["is_live"]), ("Downtown", "live", True))
        self.assertAlmostEqual(option["minutes_until_arrival"], 4, delta=0.2)

    def test_missing_coordinates_give_no_vehicle_location(self):
        self.assertIsNone(build_live_trip_option(visit(), "14533", self.gtfs)["vehicle_location"])

    def test_unmatched_or_timeless_visits_are_dropped(self):
        self.assertIsNone(build_live_trip_option(visit(line_ref="9", line_name="9"), "14533", self.gtfs))
        self.assertIsNone(build_live_trip_option(visit(expected_arrival_time=None), "14533", self.gtfs))
        self.assertIsNone(build_live_trip_option(None, "14533", self.gtfs))
        self.assertIsNone(build_live_trip_option(visit(), None, self.gtfs))

    def test_destination_ref_resolves_to_a_stop_name(self):
        unnamed = visit(destination_name="Destination unknown", destination_ref="30003")
        self.assertEqual(build_live_trip_option(unnamed, "14533", self.gtfs)["destination"], "Terminal X")
        self.assertIsNone(build_live_trip_option({**unnamed, "destination_ref": "9999"}, "14533", self.gtfs)["destination"])

    def test_arrival_given_as_aware_datetime_object(self):
        option = build_live_trip_option(visit(arrival_dt=datetime.now(timezone.utc) + timedelta(minutes=9)), "14533", self.gtfs)
        self.assertAlmostEqual(option["minutes_until_arrival"], 9, delta=0.2)


class NearbyOptionsTests(unittest.TestCase):
    def setUp(self):
        self.gtfs = stub_gtfs(
            stop_routes=route_index(route_entry("A", 2532, "66", trip_id="t1")),
            stops={"A": ("1001", 32.088, 34.7898), "B": ("1002", 32.0881, 34.7899), "far": ("1003", 32.2, 34.9)},
        )

    def test_stops_within_radius_are_queried_by_stop_code_nearest_first(self):
        nearby = stops_within_radius(32.088, 34.7898, self.gtfs.stop_lookup, 666)
        self.assertEqual([(stop_id, code) for stop_id, code, _ in nearby], [("A", "1001"), ("B", "1002")])

    def test_stops_without_a_stop_code_are_skipped(self):
        gtfs = stub_gtfs(stops={"A": (None, 32.088, 34.7898)})
        self.assertEqual(stops_within_radius(32.088, 34.7898, gtfs.stop_lookup, 666), [])

    def test_siri_is_queried_with_stop_code_and_gtfs_uses_stop_id(self):
        with patch("app.services.live_trips.fetch_live_stop_visits",
                   side_effect=lambda code: [visit(line_ref="2532", line_name="66")] if code == "1001" else []) as fetch:
            options = get_live_trip_options(32.088, 34.7898, self.gtfs, radius_m=666)
        self.assertEqual(sorted(call.args[0] for call in fetch.call_args_list), ["1001", "1002"])
        self.assertEqual([(o["stop_id"], o["route_id"]) for o in options], [("A", "2532")])

    def test_options_are_sorted_soonest_first_and_past_visits_dropped(self):
        visits = [visit(line_ref="2532", line_name="66", vehicle_ref=name, expected_arrival_time=in_minutes(minutes))
                  for name, minutes in (("late", 20), ("soon", 8), ("gone", -3))]
        with patch("app.services.live_trips.fetch_live_stop_visits", return_value=visits):
            options = get_live_trip_options(32.088, 34.7898, stub_gtfs(self.gtfs.stop_routes, {"A": ("1001", 32.088, 34.7898)}))
        self.assertEqual([o["vehicle_ref"] for o in options], ["soon", "late"])

    def test_no_stops_nearby_means_no_siri_calls(self):
        with patch("app.services.live_trips.fetch_live_stop_visits") as fetch:
            self.assertEqual(get_live_trip_options(10.0, 10.0, self.gtfs), [])
        fetch.assert_not_called()

    def test_stops_are_fetched_in_parallel(self):
        gtfs = stub_gtfs(stops={str(i): (str(1000 + i), 32.088, 34.7898) for i in range(6)})

        def slow(code):
            time.sleep(0.3)
            return []

        started = time.perf_counter()
        with patch("app.services.live_trips.fetch_live_stop_visits", side_effect=slow):
            get_live_trip_options(32.088, 34.7898, gtfs)
        self.assertLess(time.perf_counter() - started, 1.2)  # sequential would take >= 1.8 s

    def test_a_slow_stop_does_not_block_the_response(self):
        def fetch(code):
            if code == "1001":
                return [visit(line_ref="2532", line_name="66")]
            time.sleep(2)  # the sluggish stop
            return []

        started = time.perf_counter()
        with patch("app.services.live_trips.fetch_live_stop_visits", side_effect=fetch), \
             patch.object(config, "SIRI_REQUEST_BUDGET_SECONDS", 0.3):
            options = get_live_trip_options(32.088, 34.7898, self.gtfs)
        self.assertLess(time.perf_counter() - started, 1.5)
        self.assertEqual(len(options), 1)

    def test_a_failing_stop_is_skipped_not_fatal(self):
        def fetch(code):
            if code == "1002":
                raise RuntimeError("boom")
            return [visit(line_ref="2532", line_name="66")]

        with patch("app.services.live_trips.fetch_live_stop_visits", side_effect=fetch):
            self.assertEqual(len(get_live_trip_options(32.088, 34.7898, self.gtfs)), 1)


if __name__ == "__main__":
    unittest.main()
