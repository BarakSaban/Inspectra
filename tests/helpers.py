"""Shared fixtures: a tiny GTFS feed, a routing engine over it, stub lookups and an app/DB test case."""
import unittest
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from werkzeug.security import generate_password_hash

import app.services.siri as siri
from app import create_app
from app.extensions import db
from app.models import Inspector, User
from app.services.gtfs import DONTPAY_SLOTS, GtfsData
from app.services.routing import RoutingEngine
from app.services.walking import WalkingNetwork
from app.utils.clock import now_israel
from app.utils.ratelimit import login_limiter

# Password hashing is deliberately slow; every fixture user shares one hash of "pw" computed once.
PASSWORD_HASH = generate_password_hash("pw")
ADMIN_CODE = "ADM001"
OTHER_ADMIN_CODE = "ADM002"


def make_gtfs(route_ids=(101,), dont_pay=12, calendar=None):
    """Two-stop timetable for each route: stop_1 (30 min from now) -> stop_2 (50 min from now)."""
    now = now_israel()
    at = lambda minutes: (now + timedelta(minutes=minutes)).strftime("%H:%M:%S")  # noqa: E731
    stops = pd.DataFrame([
        {"stop_id": "stop_1", "stop_code": "1001", "stop_name": "Stop One", "stop_lat": 32.088, "stop_lon": 34.7898},
        {"stop_id": "stop_2", "stop_code": "1002", "stop_name": "Stop Two", "stop_lat": 32.100, "stop_lon": 34.7999},
    ])
    stop_times, trips, routes = [], [], []
    for route_id in route_ids:
        trip_id = f"trip_{route_id}"
        stop_times += [
            {"trip_id": trip_id, "stop_id": "stop_1", "arrival_time": at(30), "stop_sequence": 1},
            {"trip_id": trip_id, "stop_id": "stop_2", "arrival_time": at(50), "stop_sequence": 2},
        ]
        trips.append({"trip_id": trip_id, "route_id": route_id, "shape_id": 7.0, "direction_id": 0, "trip_headsign": "Terminal", "service_id": "S1"})
        routes.append({"route_id": route_id, "route_short_name": str(route_id),
                       **{f"DontPay - {slot}": dont_pay for slot in DONTPAY_SLOTS}})
    return GtfsData(stops, pd.DataFrame(stop_times), pd.DataFrame(trips), pd.DataFrame(routes), calendar=calendar)


def make_engine(route_ids=(101,), dont_pay=12, calendar=None):
    gtfs = make_gtfs(route_ids, dont_pay, calendar)
    return RoutingEngine(gtfs, WalkingNetwork(gtfs.stops))


@contextmanager
def offline_walking():
    """Pretend the OSM street network is unreachable so walking falls back to straight-line estimates."""
    with patch.object(WalkingNetwork, "_walk_via_osm", side_effect=RuntimeError("offline")):
        yield


def route_entry(stop_id, route_id, short_name, direction_id="0", shape_id=None, trip_id=None):
    return {
        "stop_id": str(stop_id), "route_id": str(route_id), "route_short_name": short_name,
        "direction_id": direction_id, "shape_id": shape_id or f"shape_{route_id}", "trip_id": trip_id or f"trip_{route_id}",
    }


def stub_gtfs(stop_routes=None, stops=None, shapes=None, names_by_code=None):
    """The slice of GtfsData that the live-trip code reads, built from plain dicts."""
    stops = stops if stops is not None else {}
    return SimpleNamespace(
        stop_routes=stop_routes or {},
        stop_lookup={
            str(stop_id): {"properties": {"stop_id": stop_id, "stop_code": code, "stop_lat": lat, "stop_lon": lon}}
            for stop_id, (code, lat, lon) in stops.items()
        },
        shape_lookup=shapes or {},
        stop_names_by_code=names_by_code or {},
    )


def route_index(*entries):
    index = {}
    for entry in entries:
        index.setdefault(entry["stop_id"], []).append(entry)
    return index


class ApiTestCase(unittest.TestCase):
    """A fresh in-memory database with two admins and three inspectors per test, plus a test client."""

    def setUp(self):
        siri._LIVE_CACHE.clear()
        login_limiter.clear()
        self.app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                               "BOOTSTRAP_DB": False, "WARM_UP": False, "SECRET_KEY": "test"})
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add_all([
            Inspector(inspector_id="I001", name="Lior", latitude=32.088, longitude=34.7898, available=True),
            Inspector(inspector_id="I002", name="Dana", latitude=32.089, longitude=34.7900, available=True),
            Inspector(inspector_id="X001", name="Other", latitude=32.0, longitude=34.7, available=True),
        ])
        for username, role, inspector_id, code in (
            ("admin", "admin", None, ADMIN_CODE),
            ("admin2", "admin", None, OTHER_ADMIN_CODE),
            ("lior", "inspector", "I001", ADMIN_CODE),
            ("dana", "inspector", "I002", ADMIN_CODE),
            ("other", "inspector", "X001", OTHER_ADMIN_CODE),
        ):
            db.session.add(User(username=username, role=role, inspector_id=inspector_id, manager_code=code,
                                full_name=username, password_hash=PASSWORD_HASH))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()

    def login(self, username="admin", role="admin", admin_code=ADMIN_CODE, inspector_id=None):
        with self.client.session_transaction() as sess:
            sess.update(user=username, role=role, admin_code=admin_code, inspector_id=inspector_id)
