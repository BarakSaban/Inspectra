import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from urllib import error

import app.services.siri as siri
from app import config


def in_minutes(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def visit(**overrides):
    return {
        "line_ref": "44290", "line_name": "48", "direction_ref": "1", "destination_name": "Downtown",
        "expected_arrival_time": in_minutes(5), "latitude": 32.090652, "longitude": 34.869121,
        "vehicle_ref": "52497803", **overrides,
    }


def http_response(payload, status=200):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.status = response.code = status
    return response


class SiriTestCase(unittest.TestCase):
    def setUp(self):
        siri._LIVE_CACHE.clear()


class ParsingTests(SiriTestCase):
    def test_request_url_uses_the_configured_proxy_and_stop_code(self):
        self.assertEqual(siri.build_request_url("32902"), f"{config.SIRI_BASE_URL}/stops/32902")
        self.assertEqual(siri.build_request_url("32902", line_ref="5", preview_interval=30),
                         f"{config.SIRI_BASE_URL}/stops/32902?line_ref=5&preview_interval=30")
        self.assertIsNone(siri.build_request_url(None))
        self.assertIsNone(siri.build_request_url("null"))

    def test_duplicates_and_null_coordinates(self):
        same = visit(line_ref="2", latitude=None, longitude=None, expected_arrival_time=in_minutes(4))
        visits = siri.parse_stop_visits_response({"visits": [same, dict(same)]})
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["line_ref"], "2")
        self.assertIsNone(visits[0]["latitude"])

    def test_real_proxy_payload(self):
        payload = {"monitoring_ref": "32902", "visits": [{
            "line_ref": "44290", "line_name": "48", "direction_ref": "1", "destination_ref": "32742",
            "vehicle_ref": "52497803", "expected_arrival_time": "2026-10-19T20:11:00+03:00",
            "latitude": "32.090652", "longitude": "34.869121",
        }]}
        parsed = siri.parse_stop_visits_response(payload)[0]
        self.assertEqual(parsed["monitoring_ref"], "32902")
        self.assertEqual((parsed["line_ref"], parsed["line_name"], parsed["direction_ref"]), ("44290", "48", "1"))
        self.assertEqual(parsed["destination_ref"], "32742")
        self.assertEqual(parsed["destination_name"], siri.DESTINATION_UNKNOWN)
        self.assertEqual(parsed["latitude"], 32.090652)

    def test_unusable_payloads_yield_no_visits(self):
        for payload in (None, [], {"visits": "x"}, {"visits": [None, "x", {"line_ref": "1"}]}):
            self.assertEqual(siri.parse_stop_visits_response(payload), [])

    def test_naive_timestamps_are_israel_local_time(self):
        self.assertEqual(siri.parse_iso_datetime("2026-10-25T14:08:00"), datetime(2026, 10, 25, 12, 8, tzinfo=timezone.utc))  # +02:00
        self.assertEqual(siri.parse_iso_datetime("2026-07-01T14:08:00"), datetime(2026, 7, 1, 11, 8, tzinfo=timezone.utc))  # +03:00
        self.assertEqual(siri.parse_iso_datetime("2026-10-25T14:08:00+02:00"), datetime(2026, 10, 25, 12, 8, tzinfo=timezone.utc))
        self.assertEqual(siri.parse_iso_datetime("2026-10-25T12:08:00Z"), datetime(2026, 10, 25, 12, 8, tzinfo=timezone.utc))
        self.assertIsNone(siri.parse_iso_datetime("garbage"))
        self.assertIsNone(siri.parse_iso_datetime(None))


@patch("app.services.siri.time.sleep")
@patch("app.services.siri.request.urlopen")
class FetchTests(SiriTestCase):
    payload = {"monitoring_ref": "32902", "visits": [visit()]}

    def test_success_is_parsed(self, urlopen, sleep):
        urlopen.return_value = http_response(self.payload)
        visits = siri.fetch_live_stop_visits("32902")
        self.assertEqual((len(visits), visits[0]["monitoring_ref"], visits[0]["line_name"]), (1, "32902", "48"))

    def test_timeout_is_retried_once_then_succeeds(self, urlopen, sleep):
        urlopen.side_effect = [TimeoutError("timed out"), http_response(self.payload)]
        self.assertEqual(len(siri.fetch_live_stop_visits("32902")), 1)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(config.SIRI_RETRY_DELAY_SECONDS)

    def test_http_429_is_retried_once_then_succeeds(self, urlopen, sleep):
        urlopen.side_effect = [error.HTTPError("u", 429, "Too Many Requests", hdrs=None, fp=None), http_response(self.payload)]
        self.assertEqual(len(siri.fetch_live_stop_visits("32902")), 1)
        self.assertEqual(urlopen.call_count, 2)

    def test_http_502_twice_gives_up(self, urlopen, sleep):
        bad_gateway = error.HTTPError("u", 502, "Bad Gateway", hdrs={"Content-Type": "text/plain"}, fp=None)
        urlopen.side_effect = [bad_gateway, bad_gateway]
        self.assertEqual(siri.fetch_live_stop_visits("32902"), [])
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_http_404_is_not_retried(self, urlopen, sleep):
        urlopen.side_effect = error.HTTPError("u", 404, "Not Found", hdrs=None, fp=None)
        self.assertEqual(siri.fetch_live_stop_visits("32902"), [])
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_unexpected_error_returns_empty(self, urlopen, sleep):
        urlopen.side_effect = Exception("offline")
        self.assertEqual(siri.fetch_live_stop_visits("14533"), [])

    def test_malformed_json_returns_empty(self, urlopen, sleep):
        response = http_response({})
        response.read.return_value = b"<html>not json"
        urlopen.return_value = response
        self.assertEqual(siri.fetch_live_stop_visits("32902"), [])
        self.assertEqual(siri.get_siri_status()["failing_stops"], 1)

    def test_fresh_success_is_served_from_cache(self, urlopen, sleep):
        urlopen.return_value = http_response(self.payload)
        siri.fetch_live_stop_visits("222")
        siri.fetch_live_stop_visits("222")
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(siri.get_siri_status()["cached_stops"], 1)

    def test_expired_cache_entry_is_refetched(self, urlopen, sleep):
        stale = datetime.now(timezone.utc) - timedelta(seconds=config.SIRI_CACHE_TTL_SECONDS + 5)
        siri._LIVE_CACHE["222"] = {"timestamp": stale, "visits": [{"old": True}]}
        urlopen.return_value = http_response(self.payload)
        self.assertEqual(siri.fetch_live_stop_visits("222")[0]["line_name"], "48")

    def test_failed_fetch_backs_off_instead_of_hammering_the_proxy(self, urlopen, sleep):
        urlopen.side_effect = Exception("down")
        self.assertEqual(siri.fetch_live_stop_visits("111"), [])
        self.assertEqual(siri.fetch_live_stop_visits("111"), [])
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(siri.get_siri_status()["failing_stops"], 1)

    def test_blank_stop_code_does_no_request(self, urlopen, sleep):
        self.assertEqual(siri.fetch_live_stop_visits(None), [])
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
