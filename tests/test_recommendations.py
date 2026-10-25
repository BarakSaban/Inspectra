import unittest
from unittest.mock import patch

from app.services import recommendations
from app.services.recommendations import find_best_trip, is_winning_live_option
from app.services.routing import RoutingEngine
from app.services.walking import WalkingNetwork
from tests.helpers import make_gtfs, offline_walking


def engine_with_shapes(route_ids=(101,)):
    gtfs = make_gtfs(route_ids)
    gtfs.__dict__["shape_lookup"] = {"7": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[34.78, 32.08], [34.79, 32.088], [34.80, 32.09]]}}}
    return RoutingEngine(gtfs, WalkingNetwork(gtfs.stops))


def live_option(**overrides):
    return {"trip_id": "old_release_trip", "route_id": "101", "stop_id": "stop_1", "minutes_until_arrival": 41.0,
            "stop_feature": {"geometry": {"coordinates": [34.7898, 32.088]}},
            "shape_feature": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[34.7898, 32.088], [34.80, 32.09]]}},
            **overrides}


class FindBestTripTests(unittest.TestCase):
    def run_find(self, engine, live_options):
        with patch.object(recommendations, "get_engine", return_value=engine), \
             patch.object(recommendations, "fetch_live_options", return_value=live_options), offline_walking():
            return find_best_trip(32.0880, 34.7898)

    def test_scored_live_bus_is_reported_as_live(self):
        result = self.run_find(engine_with_shapes(), [live_option()])
        self.assertEqual((result["data_source"], result["source_label"], result["live_status"]), ("live", "Live SIRI data", "live"))
        self.assertTrue(result["is_live"] and result["best_option"]["is_live"])
        self.assertEqual((result["best_option"]["stop_id"], result["best_option"]["route_id"], result["best_option"]["AvgDontPay"]), ("stop_1", "101", 12))
        self.assertEqual(result["shape_feature"]["geometry"]["coordinates"][0], [34.7898, 32.088])

    def test_without_live_data_the_schedule_is_the_fallback(self):
        result = self.run_find(engine_with_shapes(), [])
        self.assertEqual((result["data_source"], result["source_label"], result["live_status"]), ("static", "Static GTFS fallback", "fallback"))
        self.assertFalse(result["is_live"] or result["best_option"]["is_live"])
        self.assertEqual(result["best_option"]["trip_id"], "trip_101")
        self.assertEqual(result["stop_feature"]["properties"]["stop_id"], "stop_1")
        self.assertTrue(result["shape_feature"])

    def test_live_option_that_cannot_be_scored_falls_back_to_static(self):
        result = self.run_find(engine_with_shapes(), [live_option(route_id="999", stop_id="stop_999")])
        self.assertEqual(result["source_label"], "Static GTFS fallback")
        self.assertEqual(result["best_option"]["trip_id"], "trip_101")

    def test_static_shape_is_trimmed_without_touching_the_shared_shape(self):
        engine = engine_with_shapes()
        original = list(engine.gtfs.shape_lookup["7"]["geometry"]["coordinates"])
        result = self.run_find(engine, [])
        self.assertLess(len(result["shape_feature"]["geometry"]["coordinates"]), len(original))
        self.assertEqual(engine.gtfs.shape_lookup["7"]["geometry"]["coordinates"], original)

    def test_nothing_worth_taking_returns_none(self):
        self.assertIsNone(self.run_find(RoutingEngine(make_gtfs(dont_pay=0)), []))

    def test_no_engine_returns_none(self):
        with patch.object(recommendations, "get_engine", return_value=None):
            self.assertIsNone(find_best_trip(32.0, 34.0))

    def test_siri_outage_never_breaks_the_recommendation(self):
        engine = engine_with_shapes()
        with patch.object(recommendations, "get_engine", return_value=engine), \
             patch.object(recommendations, "get_live_trip_options", side_effect=RuntimeError("siri down")), offline_walking():
            result = find_best_trip(32.0880, 34.7898)
        self.assertEqual(result["data_source"], "static")


class WinningLiveOptionTests(unittest.TestCase):
    live = {"stop_id": "stop_1", "route_id": "101", "minutes_until_arrival": 5.0}
    best = {"is_live": True, "stop_id": "stop_1", "route_id": 101, "minutes_until_arrival": 5.0}

    def test_match(self):
        self.assertTrue(is_winning_live_option(self.live, self.best))

    def test_each_mismatch_rejects(self):
        for change in ({"route_id": 200}, {"stop_id": "stop_2"}, {"is_live": False}, {"minutes_until_arrival": 6.0}, {"route_id": None}):
            self.assertFalse(is_winning_live_option(self.live, {**self.best, **change}), change)
        self.assertFalse(is_winning_live_option({**self.live, "route_id": None}, self.best))


if __name__ == "__main__":
    unittest.main()
