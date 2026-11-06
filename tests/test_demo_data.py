"""The demo-data tool builds recognisable accounts and removes exactly those, never real ones."""
from unittest.mock import patch

from app.models import AuditLog, BreakLog, Fine, Inspector, InspectorRun, ShiftLog, TeamSettings, User
from tests.helpers import ApiTestCase
from tools import demo_data

POOL = [{"stop_id": "stop_1", "lat": 32.088, "lon": 34.7898, "trips": ["trip_101"]},
        {"stop_id": "stop_2", "lat": 32.100, "lon": 34.7999, "trips": ["trip_101"]}]


class DemoDataTests(ApiTestCase):
    def build(self):
        with patch.object(demo_data, "get_gtfs", return_value=object()), patch.object(demo_data, "_stop_pool", return_value=POOL):
            return demo_data.create(10)

    def test_create_builds_accounts_that_can_log_in_and_a_second_create_is_refused(self):
        self.assertEqual(self.build(), 0)
        self.assertEqual(User.query.filter(User.username.like("demo.%")).count(), 11)
        self.assertEqual(Inspector.query.filter(Inspector.inspector_id.like("DM%")).count(), 9)
        self.assertGreater(InspectorRun.query.filter(InspectorRun.inspector_id.like("DM%")).count(), 0)
        self.assertGreater(ShiftLog.query.filter(ShiftLog.inspector_id.like("DM%")).count(), 0)
        for username, redirect in (("demo.manager1", "/admin"), ("demo.i01", "/inspect")):
            reply = self.client.post("/api/login", json={"username": username, "password": demo_data.PASSWORD})
            self.assertEqual(reply.get_json().get("redirect"), redirect)
            self.client.post("/api/logout")
        self.assertEqual(self.build(), 1)

    def test_managers_see_only_their_own_demo_team(self):
        self.build()
        self.client.post("/api/login", json={"username": "demo.manager2", "password": demo_data.PASSWORD})
        people = self.client.get("/api/analytics/people").get_json()["people"]
        self.assertEqual({p["inspector_id"] for p in people}, {"DM07", "DM08", "DM09"})

    def test_delete_removes_only_demo_records(self):
        real_users, real_inspectors = User.query.count(), Inspector.query.count()
        self.build()
        self.assertEqual(demo_data.delete(True), 0)
        self.assertEqual(User.query.count(), real_users)
        self.assertEqual(Inspector.query.count(), real_inspectors)
        for model in (InspectorRun, Fine, ShiftLog, BreakLog, TeamSettings, AuditLog):
            self.assertEqual(model.query.count(), 0, model.__name__)

    def test_delete_refuses_when_a_real_inspector_belongs_to_a_demo_manager(self):
        self.build()
        code = User.query.filter_by(username="demo.manager1").first().manager_code
        User.query.filter_by(username="lior").update({"manager_code": code})
        self.assertEqual(demo_data.delete(True), 1)
        self.assertEqual(User.query.filter(User.username.like("demo.%")).count(), 11)
