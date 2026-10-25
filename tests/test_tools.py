import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tools import build_gtfs_subset, refresh_fare_evasion


def write_feed(path, with_calendar=True):
    tables = {
        "routes.txt": pd.DataFrame({"route_id": ["1", "2", "3"], "route_short_name": ["10", "20", "30"],
                                    "route_desc": ["5010-1-0", "5020-1-0", "5030-1-0"]}),
        "trips.txt": pd.DataFrame({"route_id": ["1", "2", "3"], "trip_id": ["a", "b", "c"], "service_id": ["S1", "S2", "S3"],
                                   "shape_id": [11, 12, 13]}),
        "stop_times.txt": pd.DataFrame({"trip_id": ["a", "a", "b", "c"], "stop_id": [100, 101, 100, 102],
                                        "arrival_time": ["10:00:00"] * 4}),
        "stops.txt": pd.DataFrame({"stop_id": [100, 101, 102, 103], "stop_code": [1, 2, 3, 4]}),
        "shapes.txt": pd.DataFrame({"shape_id": [11, 12, 13], "shape_pt_lat": [1.0] * 3, "shape_pt_lon": [2.0] * 3,
                                    "shape_pt_sequence": [1] * 3}),
    }
    if with_calendar:
        tables["calendar.txt"] = pd.DataFrame({"service_id": ["S1", "S2", "S3"], "monday": [1, 1, 1], "saturday": [0, 1, 1]})
    with zipfile.ZipFile(path, "w") as archive:
        for name, table in tables.items():
            archive.writestr(name, table.to_csv(index=False))


class BuildGtfsSubsetTests(unittest.TestCase):
    def build(self, **feed_options):
        directory = Path(tempfile.mkdtemp())
        write_feed(directory / "feed.zip", **feed_options)
        with patch("builtins.print"):
            build_gtfs_subset.build(directory / "feed.zip", directory / "out", route_ids=["1", "2"])
        return directory / "out"

    def test_only_tracked_routes_and_everything_that_belongs_to_them_are_kept(self):
        out = self.build()
        read = lambda name: pd.read_csv(out / f"{name}.txt")  # noqa: E731
        self.assertEqual(sorted(read("routes")["route_id"]), [1, 2])
        self.assertEqual(sorted(read("trips")["trip_id"]), ["a", "b"])
        self.assertEqual(len(read("stop_times")), 3)
        self.assertEqual(sorted(read("stops")["stop_id"]), [100, 101])      # 102/103 belong to untracked trips
        self.assertEqual(sorted(read("shapes")["shape_id"]), [11, 12])
        self.assertEqual(sorted(read("calendar")["service_id"]), ["S1", "S2"])

    def test_a_feed_without_a_calendar_still_builds(self):
        out = self.build(with_calendar=False)
        self.assertTrue((out / "trips.txt").exists())
        self.assertFalse((out / "calendar.txt").exists())

    def test_the_committed_feed_round_trips_unchanged(self):
        from app import config
        directory = Path(tempfile.mkdtemp())
        with zipfile.ZipFile(directory / "feed.zip", "w") as archive:
            for table in config.GTFS_DIR.glob("*.txt"):
                archive.write(table, table.name)
        with patch("builtins.print"):
            build_gtfs_subset.build(directory / "feed.zip", directory / "out")
        for table in config.GTFS_DIR.glob("*.txt"):
            original = table.read_bytes().replace(b"\r\n", b"\n")
            rebuilt = (directory / "out" / table.name).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(original, rebuilt, table.name)


class RefreshFareEvasionTests(unittest.TestCase):
    routes = pd.DataFrame({"route_id": [1, 2], "route_desc": ["5010-1-0", "5020-2-0"]})
    existing = pd.DataFrame({
        "route_id": [1, 2],
        "WorkDay - 06:00-08:59": [1.0, 2.0], "DontPay - 06:00-08:59": [0, 0],
        "WorkDay - 21:00-23:59": [30.0, 40.0], "DontPay - 21:00-23:59": [6, 8],   # a slot the API does not publish
    })

    def refresh(self, answers):
        with patch.object(refresh_fare_evasion, "fetch_workday_averages", side_effect=lambda nesoa_id: answers[nesoa_id]), \
             patch("builtins.print"):
            return refresh_fare_evasion.refresh(self.routes, self.existing)

    def test_api_backed_slots_are_updated_and_dont_pay_is_twenty_percent(self):
        result = self.refresh({"5010": {"06:00-08:59": 50, "09:00-11:59": 10, "12:00-14:59": 0},
                               "5020": {"06:00-08:59": 24.9, "09:00-11:59": 0, "12:00-14:59": 5}})
        first = result[result["route_id"] == 1].iloc[0]
        self.assertEqual((first["WorkDay - 06:00-08:59"], first["DontPay - 06:00-08:59"]), (50, 10))
        self.assertEqual(first["DontPay - 09:00-11:59"], 2)
        self.assertEqual(result[result["route_id"] == 2].iloc[0]["DontPay - 06:00-08:59"], 5)

    def test_slots_the_api_does_not_publish_are_left_untouched(self):
        result = self.refresh({"5010": {"06:00-08:59": 50, "09:00-11:59": 0, "12:00-14:59": 0}, "5020": None})
        self.assertEqual(list(result["WorkDay - 21:00-23:59"]), [30.0, 40.0])
        self.assertEqual(list(result["DontPay - 21:00-23:59"]), [6, 8])

    def test_routes_without_api_data_or_with_api_errors_keep_their_values(self):
        def answers(nesoa_id):
            if nesoa_id == "5010":
                raise OSError("network down")
            return None

        with patch.object(refresh_fare_evasion, "fetch_workday_averages", side_effect=answers), patch("builtins.print"):
            result = refresh_fare_evasion.refresh(self.routes, self.existing)
        self.assertEqual(list(result["WorkDay - 06:00-08:59"]), [1.0, 2.0])

    def test_nesoa_route_id_is_the_number_before_the_first_dash(self):
        result = self.refresh({"5010": None, "5020": None})
        self.assertEqual(list(result["NesoaRouteID"]), ["5010", "5020"])

    def test_differences_report_only_changed_columns(self):
        before = pd.DataFrame({"a": [1, 2], "b": [1, 2]})
        after = pd.DataFrame({"a": [1, 3], "b": [1, 2]})
        self.assertEqual(refresh_fare_evasion._differences(before, after), {"a": 1})


if __name__ == "__main__":
    unittest.main()
