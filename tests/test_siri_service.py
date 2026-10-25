import importlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib import error

import app.services.siri_service as siri_service

import pandas as pd

from Actions import Actions
from Classes import Inspector
from app.services.siri_service import (
    _find_matching_shape_entry,
    build_live_trip_option,
    choose_best_live_option,
    fetch_live_stop_visits,
    get_live_best_trip_option,
    parse_stop_visits_response,
)
from app.services.trip_service import find_best_trip


class SiriServiceTests(unittest.TestCase):
    def setUp(self):
        self.stop_lookup = {
            "14533": {"properties": {"stop_id": "14533", "stop_name": "Test Stop"}},
            "14009": {"properties": {"stop_id": "14009", "stop_name": "Another Stop"}},
        }
        self.shape_lookup = {
            "145685": {"properties": {"shape_id": "145685"}},
        }
        self.stop_shape_map = [
            {"stop_id": "14533", "trip_id": "44236234_080725", "route_id": "27081", "shape_id": "145685", "route_short_name": 2,
             "route_long_name": "Line 2"},
            {"stop_id": "14009", "trip_id": "44236234_080725", "route_id": "27081", "shape_id": "145685", "route_short_name": 2,
             "route_long_name": "Line 2"},
        ]
        self.trips_df = [
            {"trip_id": "44236234_080725", "route_id": "27081", "shape_id": "145685"},
        ]

    def test_build_request_url_uses_raspberry_service_root_with_single_stop_suffix(self):
        importlib.reload(siri_service)

        self.assertEqual(siri_service.SIRI_BASE_URL, "https://raspberry-phy.taila18e05.ts.net")
        self.assertEqual(
            siri_service._build_request_url("32902"),
            "https://raspberry-phy.taila18e05.ts.net/stops/32902",
        )

    def test_parse_stop_visits_response_handles_duplicates_and_null_coordinates(self):
        payload = {
            "visits": [
                {
                    "line_ref": "2",
                    "vehicle_ref": "v-1",
                    "destination_name": "Downtown",
                    "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
                    "latitude": None,
                    "longitude": None,
                },
                {
                    "line_ref": "2",
                    "vehicle_ref": "v-1",
                    "destination_name": "Downtown",
                    "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
                    "latitude": None,
                    "longitude": None,
                },
            ]
        }

        visits = parse_stop_visits_response(payload)
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["line_ref"], "2")
        self.assertIsNone(visits[0]["latitude"])

    def test_parse_stop_visits_response_supports_real_siri_payload(self):
        payload = {
            "monitoring_ref": "32902",
            "visits": [
                {
                    "line_ref": "44290",
                    "line_name": "48",
                    "direction_ref": "1",
                    "destination_ref": "32742",
                    "vehicle_ref": "52497803",
                    "expected_arrival_time": "2026-10-19T20:11:00+03:00",
                    "latitude": "32.090652",
                    "longitude": "34.869121",
                }
            ]
        }

        visits = parse_stop_visits_response(payload)
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["monitoring_ref"], "32902")
        self.assertEqual(visits[0]["line_ref"], "44290")
        self.assertEqual(visits[0]["line_name"], "48")
        self.assertEqual(visits[0]["direction_ref"], "1")
        self.assertEqual(visits[0]["destination_ref"], "32742")
        self.assertEqual(visits[0]["expected_arrival_time"], "2026-10-19T20:11:00+03:00")

    def test_build_live_trip_option_matches_route_id_and_line_name(self):
        visit = {
            "line_ref": "44290",
            "line_name": "48",
            "direction_ref": "1",
            "destination_ref": "32742",
            "vehicle_ref": "52497803",
            "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
            "latitude": 32.090652,
            "longitude": 34.869121,
        }

        stop_shape_map = [
            {
                "stop_id": "32902",
                "trip_id": "trip_48_a",
                "route_id": "44290",
                "shape_id": "shape_48",
                "route_short_name": "48",
                "line_ref": "44290",
            },
            {
                "stop_id": "32742",
                "trip_id": "trip_48_a",
                "route_id": "44290",
                "shape_id": "shape_48",
                "route_short_name": "48",
                "line_ref": "44290",
            }
        ]

        option = build_live_trip_option(
            visit,
            stop_id="32902",
            stop_lookup={"32902": {"properties": {"stop_id": "32902"}}},
            shape_lookup={"shape_48": {"properties": {"shape_id": "shape_48"}}},
            stop_shape_map=stop_shape_map,
            trips_df=[{"trip_id": "trip_48_a", "route_id": "44290", "shape_id": "shape_48"}],
        )

        self.assertIsNotNone(option)
        self.assertEqual(option["trip_id"], "trip_48_a")
        self.assertEqual(option["route_num"], "48")
        self.assertTrue(option["is_live"])

    def test_find_matching_shape_entry_requires_unique_verified_line_match(self):
        match = _find_matching_shape_entry(
            "14533",
            "unrelated-internal-ref",
            self.stop_shape_map,
            trips_df=self.trips_df,
            line_name="2",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["shape_id"], "145685")

    def test_find_matching_shape_entry_rejects_ambiguous_candidates(self):
        ambiguous_map = [
            {"stop_id": "14533", "trip_id": "trip_a", "route_id": "27081", "shape_id": "145685", "route_short_name": "2", "line_ref": "2"},
            {"stop_id": "14533", "trip_id": "trip_b", "route_id": "27082", "shape_id": "145686", "route_short_name": "2", "line_ref": "2"},
        ]
        self.assertIsNone(_find_matching_shape_entry("14533", "internal", ambiguous_map, line_name="2"))

    def test_find_matching_shape_entry_rejects_unknown_line(self):
        self.assertIsNone(_find_matching_shape_entry("14533", "27081", self.stop_shape_map, line_name="7"))

    def test_find_matching_shape_entry_rejects_internal_route_id_without_public_route_match(self):
        self.assertIsNone(
            _find_matching_shape_entry(
                "14533",
                "27081",
                self.stop_shape_map,
                trips_df=self.trips_df,
                line_name="301",
            )
        )

    def test_find_matching_shape_entry_rejects_stop_without_map_entry(self):
        self.assertIsNone(
            _find_matching_shape_entry(
                "13113",
                "internal-ref",
                self.stop_shape_map,
                trips_df=self.trips_df,
                line_name="46",
            )
        )

    def test_build_live_trip_option_rejects_unmatched_route(self):
        visit = {
            "line_ref": "9",
            "vehicle_ref": "v-9",
            "destination_name": "Unknown Terminal",
            "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
            "latitude": 32.088,
            "longitude": 34.7898,
        }

        option = build_live_trip_option(
            visit,
            stop_id="14533",
            stop_lookup=self.stop_lookup,
            shape_lookup=self.shape_lookup,
            stop_shape_map=self.stop_shape_map,
            trips_df=self.trips_df,
        )

        self.assertIsNone(option)

    def test_choose_best_live_option_returns_live_candidate(self):
        visit = {
            "line_ref": "2",
            "line_name": "2",
            "vehicle_ref": "v-10",
            "destination_name": "Downtown",
            "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
            "latitude": 32.088,
            "longitude": 34.7898,
        }

        live_option = choose_best_live_option(
            "14533",
            stop_lookup=self.stop_lookup,
            shape_lookup=self.shape_lookup,
            stop_shape_map=self.stop_shape_map,
            trips_df=self.trips_df,
            visit=visit,
        )

        self.assertIsNotNone(live_option)
        self.assertEqual(live_option["data_source"], "live")
        self.assertEqual(live_option["route_num"], "2")
        self.assertEqual(live_option["destination"], "Downtown")

    def test_build_live_trip_option_handles_missing_coordinates(self):
        visit = {
            "line_ref": "2",
            "line_name": "2",
            "vehicle_ref": "v-7",
            "destination_name": "Old City",
            "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "latitude": None,
            "longitude": None,
        }

        option = build_live_trip_option(
            visit,
            stop_id="14533",
            stop_lookup=self.stop_lookup,
            shape_lookup=self.shape_lookup,
            stop_shape_map=self.stop_shape_map,
            trips_df=self.trips_df,
        )

        self.assertIsNotNone(option)
        self.assertEqual(option["data_source"], "live")
        self.assertIsNone(option.get("vehicle_location"))

    def _mock_http_response(self, payload, status=200):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.status = status
        response.code = status
        return response

    def test_fetch_live_stop_visits_successfully_parses_response(self):
        payload = {
            "monitoring_ref": "32902",
            "visits": [{
                "line_ref": "44290",
                "line_name": "48",
                "direction_ref": "1",
                "destination_name": "Downtown",
                "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                "latitude": 32.090652,
                "longitude": 34.869121,
                "vehicle_ref": "52497803",
            }],
        }

        with patch("app.services.siri_service.request.urlopen", return_value=self._mock_http_response(payload)):
            visits = fetch_live_stop_visits("32902")
            self.assertEqual(len(visits), 1)
            self.assertEqual(visits[0]["monitoring_ref"], "32902")
            self.assertEqual(visits[0]["line_name"], "48")

    @patch("app.services.siri_service.time.sleep")
    @patch("app.services.siri_service.request.urlopen")
    def test_fetch_live_stop_visits_retries_timeout_once_then_succeeds(self, mock_urlopen, mock_sleep):
        payload = {
            "monitoring_ref": "32902",
            "visits": [{
                "line_ref": "44290",
                "line_name": "48",
                "direction_ref": "1",
                "destination_name": "Downtown",
                "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                "latitude": 32.090652,
                "longitude": 34.869121,
                "vehicle_ref": "52497803",
            }],
        }
        mock_urlopen.side_effect = [TimeoutError("timed out"), self._mock_http_response(payload)]

        visits = fetch_live_stop_visits("32902")

        self.assertEqual(len(visits), 1)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("app.services.siri_service.time.sleep")
    @patch("app.services.siri_service.request.urlopen")
    def test_fetch_live_stop_visits_retries_http_429_once_then_succeeds(self, mock_urlopen, mock_sleep):
        payload = {
            "monitoring_ref": "32902",
            "visits": [{
                "line_ref": "44290",
                "line_name": "48",
                "direction_ref": "1",
                "destination_name": "Downtown",
                "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                "latitude": 32.090652,
                "longitude": 34.869121,
                "vehicle_ref": "52497803",
            }],
        }
        mock_urlopen.side_effect = [
            error.HTTPError("https://raspberry-phy.taila18e05.ts.net/stops/32902", 429, "Too Many Requests", hdrs=None, fp=None),
            self._mock_http_response(payload),
        ]

        visits = fetch_live_stop_visits("32902")

        self.assertEqual(len(visits), 1)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("app.services.siri_service.time.sleep")
    @patch("app.services.siri_service.request.urlopen")
    def test_fetch_live_stop_visits_retries_http_502_once_then_falls_back(self, mock_urlopen, mock_sleep):
        http_error = error.HTTPError(
            "https://raspberry-phy.taila18e05.ts.net/stops/32902",
            502,
            "Bad Gateway",
            hdrs={"Content-Type": "text/plain"},
            fp=None,
        )
        mock_urlopen.side_effect = [http_error, http_error]

        visits = fetch_live_stop_visits("32902")

        self.assertEqual(visits, [])
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("app.services.siri_service.time.sleep")
    @patch("app.services.siri_service.request.urlopen")
    def test_fetch_live_stop_visits_falls_back_after_exhausted_retries(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [TimeoutError("timed out"), TimeoutError("timed out")]

        visits = fetch_live_stop_visits("32902")

        self.assertEqual(visits, [])
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    def test_fetch_live_stop_visits_handles_api_failure(self):
        with patch("app.services.siri_service.request.urlopen", side_effect=Exception("offline")):
            visits = fetch_live_stop_visits("14533")
            self.assertEqual(visits, [])

    def test_fetch_live_stop_visits_uses_stale_cache(self):
        cached = {
            "timestamp": datetime.now(timezone.utc) - timedelta(minutes=10),
            "visits": [{
                "line_ref": "2",
                "vehicle_ref": "v-3",
                "destination_name": "City Center",
                "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=7)).isoformat(),
                "latitude": 32.088,
                "longitude": 34.7898,
            }],
        }

        with patch("app.services.siri_service._LIVE_CACHE", {"14533": cached}), \
             patch("app.services.siri_service._is_response_fresh", return_value=False), \
             patch("app.services.siri_service.request.urlopen", side_effect=Exception("offline")):
            visits = fetch_live_stop_visits("14533")
            self.assertEqual(visits, [])

    def test_get_live_best_trip_option_checks_nearby_live_stops(self):
        stop_lookup = {
            "14533": {"properties": {"stop_id": "14533", "stop_lat": 32.1080, "stop_lon": 34.8301}},
            "32902": {"properties": {"stop_id": "32902", "stop_lat": 32.0907, "stop_lon": 34.8691}},
        }
        shape_lookup = {"shape_48": {"properties": {"shape_id": "shape_48"}}}
        stop_shape_map = [{
            "stop_id": "32902",
            "trip_id": "trip_48_a",
            "route_id": "44290",
            "shape_id": "shape_48",
            "route_short_name": "48",
            "line_ref": "44290",
        }]
        visit = {
            "line_ref": "44290",
            "line_name": "48",
            "direction_ref": "1",
            "destination_name": "Downtown",
            "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
            "latitude": 32.090652,
            "longitude": 34.869121,
            "vehicle_ref": "52497803",
        }

        with patch("app.services.siri_service.fetch_live_stop_visits", side_effect=lambda stop_id: [visit] if stop_id == "32902" else []):
            option = get_live_best_trip_option(
            32.0907,
            34.8691,
                stop_lookup,
                shape_lookup,
                stop_shape_map,
                [{"trip_id": "trip_48_a", "route_id": "44290", "shape_id": "shape_48"}],
            )

        self.assertIsNotNone(option)
        self.assertEqual(option["stop_id"], "32902")
        self.assertEqual(option["route_num"], "48")
        self.assertTrue(option["is_live"])

    def test_get_live_best_trip_option_queries_only_stops_inside_meter_radius(self):
        stop_lookup = {
            "near": {"properties": {"stop_id": "near", "stop_lat": 32.088, "stop_lon": 34.7898}},
            "far": {"properties": {"stop_id": "far", "stop_lat": 32.2, "stop_lon": 34.9}},
        }
        with patch("app.services.siri_service.fetch_live_stop_visits", return_value=[]) as fetch_visits:
            result = get_live_best_trip_option(
                32.088,
                34.7898,
                stop_lookup,
                {},
                [],
                [],
                radius_m=666,
            )

        self.assertIsNone(result)
        fetch_visits.assert_called_once_with("near")

    def test_multiple_visits_do_not_match_unrelated_public_route(self):
        stop_lookup = {"14533": {"properties": {"stop_id": "14533"}}}
        visits = [
            {
                "line_ref": "27081",
                "line_name": "8",
                "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
            },
            {
                "line_ref": "different-internal-id",
                "line_name": "2",
                "expected_arrival_time": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
            },
        ]

        with patch("app.services.siri_service.fetch_live_stop_visits", return_value=visits):
            option = get_live_best_trip_option(
                32.088,
                34.7898,
                stop_lookup,
                self.shape_lookup,
                self.stop_shape_map,
                self.trips_df,
                radius_m=666,
            )

        self.assertIsNotNone(option)
        self.assertEqual(option["line_name"], "2")
        self.assertEqual(option["route_num"], "2")

    def _make_action_fixture(self):
        now = datetime.now()
        static_arrival = (now + timedelta(minutes=30)).strftime("%H:%M:%S")
        live_arrival = (now + timedelta(minutes=7)).strftime("%H:%M:%S")

        stops_df = pd.DataFrame([
            {"stop_id": "stop_1", "stop_lat": 32.088, "stop_lon": 34.7898},
            {"stop_id": "stop_2", "stop_lat": 32.100, "stop_lon": 34.7999},
        ])
        stop_times_df = pd.DataFrame([
            {"trip_id": "trip_1", "stop_id": "stop_1", "arrival_time": static_arrival, "stop_sequence": 1},
            {"trip_id": "trip_2", "stop_id": "stop_2", "arrival_time": static_arrival, "stop_sequence": 1},
        ])
        trips_df = pd.DataFrame([
            {"trip_id": "trip_1", "route_id": 101, "shape_id": "shape_1"},
            {"trip_id": "trip_2", "route_id": 200, "shape_id": "shape_2"},
        ])
        routes_df = pd.DataFrame([
            {
                "route_id": 101,
                "DontPay - 06:00-08:59": 12,
                "DontPay - 09:00-11:59": 12,
                "DontPay - 12:00-14:59": 12,
                "DontPay - 15:00-17:59": 12,
                "DontPay - 18:00-20:59": 12,
                "DontPay - 21:00-23:59": 12,
                "DontPay - 00:00-02:59": 12,
                "DontPay - 03:00-05:59": 12,
            },
            {
                "route_id": 200,
                "DontPay - 06:00-08:59": 2,
                "DontPay - 09:00-11:59": 2,
                "DontPay - 12:00-14:59": 2,
                "DontPay - 15:00-17:59": 2,
                "DontPay - 18:00-20:59": 2,
                "DontPay - 21:00-23:59": 2,
                "DontPay - 00:00-02:59": 2,
                "DontPay - 03:00-05:59": 2,
            },
        ])
        actions = Actions(stops_df, stop_times_df, trips_df, routes_df)
        return actions, live_arrival

    def test_live_arrival_changes_recommendation_score(self):
        actions, live_arrival = self._make_action_fixture()
        inspector = Inspector("inspector_1", "Inspector 1", 32.0880, 34.7898, available=True)

        static_best = actions.find_best_fine_trip(inspector)
        self.assertIsNotNone(static_best)

        live_option = {
            "trip_id": "trip_1",
            "stop_id": "stop_1",
            "arrival_time": (datetime.now() + timedelta(minutes=7)).isoformat(),
            "expected_arrival_time": (datetime.now() + timedelta(minutes=7)).isoformat(),
            "minutes_until_arrival": 7.0,
        }

        live_best = actions.find_best_fine_trip(inspector, live_option=live_option)
        self.assertIsNotNone(live_best)
        self.assertNotEqual(static_best["potential_fines"], live_best["potential_fines"])

    def test_invalid_live_data_falls_back_to_static_gtfs(self):
        actions, _ = self._make_action_fixture()
        inspector = Inspector("inspector_1", "Inspector 1", 32.0880, 34.7898, available=True)

        invalid_live = {
            "trip_id": "trip_999",
            "stop_id": "stop_999",
            "arrival_time": None,
            "expected_arrival_time": None,
            "minutes_until_arrival": None,
        }

        static_best = actions.find_best_fine_trip(inspector)
        live_best = actions.find_best_fine_trip(inspector, live_option=invalid_live)
        self.assertEqual(static_best["trip_id"], live_best["trip_id"])

    def test_trip_service_falls_back_to_static_gtfs_when_live_trip_is_invalid(self):
        actions, _ = self._make_action_fixture()
        stop_lookup = {
            "stop_1": {"properties": {"stop_id": "stop_1", "stop_lat": 32.088, "stop_lon": 34.7898}},
            "stop_2": {"properties": {"stop_id": "stop_2", "stop_lat": 32.100, "stop_lon": 34.7999}},
        }
        shape_lookup = {"shape_1": {"properties": {"shape_id": "shape_1"}}}
        stop_shape_map = [{"stop_id": "stop_1", "trip_id": "trip_1", "shape_id": "shape_1"}]

        with patch("app.services.trip_service.get_actions", return_value=actions), \
             patch("app.services.trip_service.get_stop_lookup", return_value=stop_lookup), \
             patch("app.services.trip_service.get_shape_lookup", return_value=shape_lookup), \
             patch("app.services.trip_service.get_stop_shape_map", return_value=stop_shape_map), \
             patch("app.services.trip_service.get_live_best_trip_option", return_value={
                 "trip_id": "trip_999",
                 "stop_id": "stop_999",
                 "minutes_until_arrival": 7.0,
                 "stop_feature": stop_lookup["stop_1"],
                 "shape_feature": shape_lookup["shape_1"],
             }):
            result = find_best_trip(32.0880, 34.7898, buffer_minutes=3, radius_m=666)

        self.assertIsNotNone(result)
        self.assertEqual(result["best_option"]["trip_id"], "trip_1")
        self.assertEqual(result["source_label"], "Static GTFS fallback")
        self.assertFalse(result["best_option"].get("is_live", False))

    def test_trip_service_prefers_valid_live_option_even_when_trip_id_differs(self):
        actions, _ = self._make_action_fixture()
        stop_lookup = {
            "stop_1": {"properties": {"stop_id": "stop_1", "stop_lat": 32.088, "stop_lon": 34.7898}},
            "stop_2": {"properties": {"stop_id": "stop_2", "stop_lat": 32.100, "stop_lon": 34.7999}},
        }
        shape_lookup = {"shape_1": {"properties": {"shape_id": "shape_1"}}}
        stop_shape_map = [{"stop_id": "stop_1", "trip_id": "trip_1", "shape_id": "shape_1"}]

        with patch("app.services.trip_service.get_actions", return_value=actions), \
             patch("app.services.trip_service.get_stop_lookup", return_value=stop_lookup), \
             patch("app.services.trip_service.get_shape_lookup", return_value=shape_lookup), \
             patch("app.services.trip_service.get_stop_shape_map", return_value=stop_shape_map), \
             patch("app.services.trip_service.get_live_best_trip_option", return_value={
                 "trip_id": "trip_999",
                 "stop_id": "stop_1",
                 "minutes_until_arrival": 7.0,
                 "stop_feature": stop_lookup["stop_1"],
                 "shape_feature": shape_lookup["shape_1"],
             }):
            result = find_best_trip(32.0880, 34.7898, buffer_minutes=3, radius_m=666)

        self.assertIsNotNone(result)
        self.assertEqual(result["source_label"], "Live SIRI data")
        self.assertTrue(result["best_option"].get("is_live", False))
        self.assertEqual(result["best_option"]["stop_id"], "stop_1")

    def test_duplicate_live_visits_do_not_inflate_score(self):
        actions, _ = self._make_action_fixture()
        inspector = Inspector("inspector_1", "Inspector 1", 32.0880, 34.7898, available=True)

        live_option = {
            "trip_id": "trip_1",
            "stop_id": "stop_1",
            "arrival_time": (datetime.now() + timedelta(minutes=7)).isoformat(),
            "expected_arrival_time": (datetime.now() + timedelta(minutes=7)).isoformat(),
            "minutes_until_arrival": 7.0,
        }

        best_single = actions.find_best_fine_trip(inspector, live_option=live_option)
        best_duplicate = actions.find_best_fine_trip(inspector, live_options=[live_option, live_option])
        self.assertEqual(best_single["potential_fines"], best_duplicate["potential_fines"])

    def test_assign_best_trips_global_keeps_conflicting_assignments_out(self):
        now = datetime.now()
        stops_df = pd.DataFrame([
            {"stop_id": "stop_1", "stop_lat": 32.088, "stop_lon": 34.7898},
            {"stop_id": "stop_2", "stop_lat": 32.090, "stop_lon": 34.7910},
        ])
        stop_times_df = pd.DataFrame([
            {"trip_id": "trip_1", "stop_id": "stop_1", "arrival_time": (now + timedelta(minutes=20)).strftime("%H:%M:%S"), "stop_sequence": 1},
            {"trip_id": "trip_1", "stop_id": "stop_2", "arrival_time": (now + timedelta(minutes=26)).strftime("%H:%M:%S"), "stop_sequence": 2},
        ])
        trips_df = pd.DataFrame([
            {"trip_id": "trip_1", "route_id": 101, "shape_id": "shape_1"},
        ])
        routes_df = pd.DataFrame([
            {
                "route_id": 101,
                "DontPay - 06:00-08:59": 10,
                "DontPay - 09:00-11:59": 10,
                "DontPay - 12:00-14:59": 10,
                "DontPay - 15:00-17:59": 10,
                "DontPay - 18:00-20:59": 10,
                "DontPay - 21:00-23:59": 10,
                "DontPay - 00:00-02:59": 10,
                "DontPay - 03:00-05:59": 10,
            }
        ])
        actions = Actions(stops_df, stop_times_df, trips_df, routes_df)
        inspectors = [
            Inspector("inspector_1", "A", 32.0880, 34.7898, available=True),
            Inspector("inspector_2", "B", 32.0900, 34.7910, available=True),
        ]

        result = actions.assign_best_trips_global(inspectors)
        trip_ids = result["trip_id"].tolist() if not result.empty else []
        self.assertLessEqual(len(trip_ids), 1)


if __name__ == "__main__":
    unittest.main()
