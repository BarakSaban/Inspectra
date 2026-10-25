import json
import unittest

import pandas as pd

from app.services.gtfs import get_gtfs, gtfs_time_to_minutes
from tests.helpers import make_gtfs


class GtfsDerivationTests(unittest.TestCase):
    def test_time_conversion_handles_after_midnight_and_garbage(self):
        minutes = gtfs_time_to_minutes(pd.Series(["06:30:00", "25:10:30", "not a time", None]))
        self.assertEqual(minutes.iloc[0], 390.0)
        self.assertAlmostEqual(minutes.iloc[1], 25 * 60 + 10.5)
        self.assertTrue(pd.isna(minutes.iloc[2]) and pd.isna(minutes.iloc[3]))

    def test_scalar_lookups(self):
        gtfs = make_gtfs(route_ids=(101,), dont_pay=12)
        self.assertEqual(gtfs.route_id_of("trip_101"), 101)
        self.assertIsNone(gtfs.route_id_of("nope"))
        self.assertEqual(gtfs.shape_key("trip_101"), "7")  # 7.0 in trips.txt -> '7'
        self.assertEqual(gtfs.route_label(101), "101")
        self.assertIsNone(gtfs.route_label(999))
        self.assertEqual(gtfs.headsign("trip_101"), "Terminal")
        self.assertEqual(gtfs.headsign("unknown-trip", route_id="101"), "Terminal")
        self.assertIsNone(gtfs.headsign("unknown-trip"))

    def test_dontpay_uses_the_three_hour_slot_and_tolerates_bad_input(self):
        gtfs = make_gtfs(dont_pay=12)
        for hour in (0, 5, 14, 23):
            self.assertEqual(gtfs.dontpay("101", hour), 12)
        self.assertIsInstance(gtfs.dontpay(101, 14), int)
        self.assertIsNone(gtfs.dontpay(999, 14))
        self.assertIsNone(gtfs.dontpay(None, 14))
        broken = make_gtfs()
        broken._routes_by_id = broken._routes_by_id[["route_short_name"]]  # no DontPay columns at all
        self.assertIsNone(broken.dontpay(101, 14))

    def test_stop_routes_index_and_names(self):
        gtfs = make_gtfs(route_ids=(101, 102))
        entries = gtfs.stop_routes["stop_1"]
        self.assertEqual({e["route_id"] for e in entries}, {"101", "102"})
        self.assertEqual(entries[0]["direction_id"], "0")
        self.assertEqual(gtfs.stop_names_by_code["1002"], "Stop Two")


class CalendarTests(unittest.TestCase):
    def feed(self, **days):
        calendar = pd.DataFrame([{"service_id": "S1", "monday": 1, "tuesday": 1, "wednesday": 1, "thursday": 1,
                                  "friday": 0, "saturday": 0, "sunday": 1, **days}])
        gtfs = make_gtfs(route_ids=(101, 102), calendar=calendar)
        gtfs.trips.loc[gtfs.trips["trip_id"] == "trip_102", "service_id"] = "S_unlisted"  # not in the calendar
        return gtfs

    def test_without_a_calendar_every_trip_is_assumed_to_run(self):
        self.assertIsNone(make_gtfs().trips_running_on(5))

    def test_trips_follow_their_services_weekday_flags(self):
        gtfs = self.feed()
        self.assertIn("trip_101", gtfs.trips_running_on(0))       # Monday
        self.assertNotIn("trip_101", gtfs.trips_running_on(5))    # Saturday
        self.assertIn("trip_101", gtfs.trips_running_on(6))       # Sunday

    def test_services_missing_from_the_calendar_are_kept_not_dropped(self):
        self.assertIn("trip_102", self.feed().trips_running_on(5))


class RealFeedTests(unittest.TestCase):
    """The committed feed in data/gtfs must load and yield consistent, JSON-safe map data."""

    @classmethod
    def setUpClass(cls):
        cls.gtfs = get_gtfs()

    def test_feed_loads_with_expected_shape(self):
        self.assertIsNotNone(self.gtfs)
        self.assertEqual(len(self.gtfs.stop_lookup), len(self.gtfs.stops))
        self.assertGreater(len(self.gtfs.shape_lookup), 0)

    def test_map_data_is_valid_json(self):
        json.dumps(self.gtfs.stop_lookup)
        json.dumps(self.gtfs.shape_lookup)

    def test_every_stop_route_points_at_a_known_shape_and_trip(self):
        for entries in self.gtfs.stop_routes.values():
            for entry in entries:
                self.assertIn(entry["shape_id"], self.gtfs.shape_lookup)
                self.assertIn(entry["trip_id"], self.gtfs.trip_last_arrival)

    def test_one_shape_per_stop_and_route_so_live_matches_are_unambiguous(self):
        for entries in self.gtfs.stop_routes.values():
            routes = [e["route_id"] for e in entries]
            self.assertEqual(len(routes), len(set(routes)))

    def test_every_route_has_fare_evasion_data_for_every_slot(self):
        for route_id in self.gtfs.route_trips:
            for hour in range(0, 24, 3):
                self.assertIsNotNone(self.gtfs.dontpay(route_id, hour), (route_id, hour))


if __name__ == "__main__":
    unittest.main()
