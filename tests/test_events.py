import unittest
from unittest.mock import patch

from app.api import events
from app.extensions import db
from app.models import Inspector, InspectorRun
from tests.helpers import ApiTestCase


class SignatureTests(ApiTestCase):
    def test_the_fingerprint_changes_when_the_teams_picture_changes(self):
        before = events.signature("admin", admin_code="ADM001")
        db.session.add(InspectorRun(inspector_id="I001", trip_id="t", status="assigned"))
        db.session.commit()
        offered = events.signature("admin", admin_code="ADM001")
        InspectorRun.query.one().status = "accepted"
        db.session.commit()
        accepted = events.signature("admin", admin_code="ADM001")
        Inspector.query.filter_by(inspector_id="I002").one().available = False
        db.session.commit()
        away = events.signature("admin", admin_code="ADM001")
        self.assertEqual(len({before, offered, accepted, away}), 4)

    def test_teams_and_inspectors_only_see_their_own_changes(self):
        other_before = events.signature("admin", admin_code="ADM002")
        mine_before = events.signature("inspector", inspector_id="I002")
        db.session.add(InspectorRun(inspector_id="I001", trip_id="t", status="assigned"))
        db.session.commit()
        self.assertEqual(events.signature("admin", admin_code="ADM002"), other_before)
        self.assertEqual(events.signature("inspector", inspector_id="I002"), mine_before)
        self.assertEqual(events.signature("admin", admin_code="NOBODY"), "empty")


class StreamTests(ApiTestCase):
    def test_the_stream_needs_a_login_and_speaks_event_stream(self):
        self.assertEqual(self.client.get("/api/events").status_code, 401)
        self.login()
        response = self.client.get("/api/events?max_seconds=0.05")
        self.assertEqual(response.mimetype, "text/event-stream")
        self.assertIn(b"retry: 3000", response.data)
        self.assertEqual(self.client.get("/api/events?max_seconds=x").status_code, 400)

    def test_a_change_during_the_stream_is_announced(self):
        self.login()
        calls = iter(["a", "b", "b", "b"])
        with patch("app.api.events.signature", side_effect=lambda *a, **k: next(calls, "b")), patch("app.api.events.POLL_SECONDS", 0.01):
            data = self.client.get("/api/events?max_seconds=0.2").data
        self.assertIn(b"event: change", data)


if __name__ == "__main__":
    unittest.main()
