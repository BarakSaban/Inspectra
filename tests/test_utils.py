import unittest
from datetime import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.models import User
from app.utils.clock import ISRAEL_TZ, minutes_since_midnight, now_israel, now_local
from app.utils.geo import haversine_meters, trim_shape_to_stop
from app.utils.ids import normalize_id, normalize_line_ref, normalize_route_name
from app.utils.serialization import to_serializable
from tests.helpers import ApiTestCase


class IdTests(unittest.TestCase):
    def test_normalize_id(self):
        self.assertEqual(normalize_id(" 123 "), "123")
        self.assertEqual(normalize_id(136835.0), "136835")
        self.assertEqual(normalize_id("12.0"), "12")
        for empty in (None, "", "  ", "null", "None", "NaN", float("nan")):
            self.assertIsNone(normalize_id(empty), empty)

    def test_line_ref_keeps_the_last_namespace_segment(self):
        self.assertEqual(normalize_line_ref("ISR:44290"), "44290")
        self.assertEqual(normalize_line_ref(27081), "27081")
        self.assertIsNone(normalize_line_ref(None))

    def test_route_names_lose_their_spaces(self):
        self.assertEqual(normalize_route_name("2 A"), "2A")
        self.assertEqual(normalize_route_name(66), "66")
        self.assertIsNone(normalize_route_name("null"))


class GeoTests(unittest.TestCase):
    def test_haversine(self):
        self.assertEqual(haversine_meters(32.0, 34.0, 32.0, 34.0), 0)
        self.assertAlmostEqual(haversine_meters(32.0, 34.0, 33.0, 34.0), 111195, delta=100)  # one degree of latitude

    def shape(self):
        return {"type": "Feature", "properties": {"id": 1},
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1], [2, 2], [3, 3]]}}

    def test_trim_starts_at_the_closest_point_and_never_mutates(self):
        shape = self.shape()
        trimmed = trim_shape_to_stop(shape, {"geometry": {"coordinates": [2.1, 1.9]}})
        self.assertEqual(trimmed["geometry"]["coordinates"], [[2, 2], [3, 3]])
        self.assertEqual(trimmed["properties"], {"id": 1})
        self.assertEqual(len(shape["geometry"]["coordinates"]), 4)

    def test_trim_returns_the_input_when_it_cannot_help(self):
        shape = self.shape()
        self.assertIs(trim_shape_to_stop(shape, None), shape)
        self.assertIsNone(trim_shape_to_stop(None, {"geometry": {"coordinates": [0, 0]}}))
        self.assertIs(trim_shape_to_stop(shape, {"geometry": {"coordinates": [1]}}), shape)
        short = {"geometry": {"coordinates": [[0, 0]]}}
        self.assertIs(trim_shape_to_stop(short, {"geometry": {"coordinates": [0, 0]}}), short)
        broken = {"geometry": {"coordinates": [["a", "b"], ["c", "d"]]}}
        self.assertIs(trim_shape_to_stop(broken, {"geometry": {"coordinates": [0, 0]}}), broken)


class SerializationTests(unittest.TestCase):
    def test_numpy_and_pandas_values_become_plain_json_types(self):
        data = {"i": np.int64(3), "f": np.float64(1.5), "a": np.array([1, 2]), "t": (1, np.int32(2)),
                "frame": pd.DataFrame([{"x": 1}]), "series": pd.Series([1, 2]), "nested": [{"n": np.int8(4)}], "s": "text"}
        result = to_serializable(data)
        self.assertEqual(result, {"i": 3, "f": 1.5, "a": [1, 2], "t": [1, 2], "frame": [{"x": 1}],
                                  "series": [1, 2], "nested": [{"n": 4}], "s": "text"})
        self.assertIs(type(result["i"]), int)
        self.assertIs(type(result["f"]), float)
        self.assertIs(type(result["nested"][0]["n"]), int)


class ClockTests(unittest.TestCase):
    def test_israel_time_is_timezone_aware_and_local_is_naive(self):
        self.assertEqual(now_israel().tzinfo, ISRAEL_TZ)
        self.assertIsNone(now_local().tzinfo)

    def test_minutes_since_midnight(self):
        self.assertEqual(minutes_since_midnight(datetime(2026, 1, 1, 13, 30, 30)), 13 * 60 + 30 + 0.5)

    def test_server_timezone_does_not_matter(self):
        utc_evening = datetime(2026, 6, 1, 20, 0, tzinfo=ISRAEL_TZ).astimezone(ISRAEL_TZ)
        with patch("app.utils.clock.datetime") as fake:
            fake.now.return_value = utc_evening
            self.assertEqual(now_israel().hour, 20)
            fake.now.assert_called_once_with(ISRAEL_TZ)


class ProfileEdgeCaseTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login("lior", role="inspector", inspector_id="I001")

    def test_empty_updates_and_blank_usernames_are_rejected(self):
        self.assertEqual(self.client.post("/api/profile", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/profile", json={"username": "   "}).status_code, 400)

    def test_changing_username_and_password(self):
        response = self.client.post("/api/profile", json={"username": "lior2", "password": "new-pass-1"})
        self.assertEqual(response.status_code, 200)
        user = User.query.filter_by(username="lior2").one()
        self.assertTrue(user.check_password("new-pass-1"))
        self.assertEqual(self.client.get("/api/profile").get_json()["username"], "lior2")  # the session followed the rename

    def test_a_deleted_user_gets_404(self):
        with self.client.session_transaction() as sess:
            sess["user"] = "ghost"
        self.assertEqual(self.client.get("/api/profile").status_code, 404)


if __name__ == "__main__":
    unittest.main()
