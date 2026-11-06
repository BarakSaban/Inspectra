import unittest
from datetime import timedelta
from unittest.mock import patch

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun, User
from app.utils.clock import now_local
from tests.helpers import ApiTestCase, make_engine


class StaffStateTests(ApiTestCase):
    def state_of(self, inspector_id):
        staff = self.client.get("/api/staff").get_json()
        return next(s for s in staff if s["inspector_id"] == inspector_id)

    def test_each_inspector_gets_a_real_state(self):
        self.login()
        self.assertEqual(self.state_of("I001")["state"], "idle")

        Inspector.query.filter_by(inspector_id="I001").one().available = False
        db.session.commit()
        self.assertEqual(self.state_of("I001")["state"], "offline")

        Inspector.query.filter_by(inspector_id="I001").one().break_until = now_local() + timedelta(minutes=10)
        db.session.commit()
        self.assertEqual(self.state_of("I001")["state"], "break")

        db.session.add(InspectorRun(inspector_id="I001", trip_id="t1", stop_id="stop_1", status="assigned"))
        db.session.commit()
        self.assertEqual(self.state_of("I001")["state"], "offered")

        InspectorRun.query.one().status = "accepted"
        db.session.commit()
        entry = self.state_of("I001")
        self.assertEqual(entry["state"], "on_run")
        self.assertEqual(entry["current_assignment"]["run_id"], InspectorRun.query.one().id)

    def test_last_seen_comes_from_reported_positions(self):
        Inspector.query.filter_by(inspector_id="I002").one().location_updated_at = None
        db.session.commit()
        self.login("lior", role="inspector", inspector_id="I001")
        self.client.put("/api/me/status", json={"latitude": 32.1, "longitude": 34.8})
        self.login()
        self.assertLess(self.state_of("I001")["last_seen_seconds"], 5)
        self.assertIsNone(self.state_of("I002")["last_seen_seconds"])


class ReachabilityTests(ApiTestCase):
    def test_an_inspector_who_stopped_reporting_is_offline_and_not_assigned(self):
        from app.services.inspectors import STALE_POSITION_SECONDS
        Inspector.query.filter_by(inspector_id="I001").one().location_updated_at = now_local() - timedelta(seconds=STALE_POSITION_SECONDS + 30)
        db.session.commit()
        self.login()
        staff = {s["inspector_id"]: s for s in self.client.get("/api/staff").get_json()}
        self.assertEqual(staff["I001"]["state"], "offline")
        self.assertFalse(staff["I001"]["available"])
        self.assertEqual(staff["I002"]["state"], "idle")

    def test_new_accounts_start_offline_without_an_invented_position(self):
        code = User.query.filter_by(role="admin").first().manager_code
        client = self.app.test_client()
        self.assertEqual(client.post("/api/register", json={"name": "New One", "phone": "I777", "password": "pw12345", "role": "inspector", "manager_code": code}).status_code, 200)
        created = Inspector.query.filter_by(inspector_id="I777").one()
        self.assertIsNone(created.latitude)
        self.assertFalse(created.available)

    def test_manager_code_is_accepted_in_any_case(self):
        code = User.query.filter_by(role="admin").first().manager_code
        client = self.app.test_client()
        self.assertEqual(client.post("/api/register", json={"name": "Typed By Hand", "phone": "I778", "password": "pw12345", "role": "inspector", "manager_code": f" {code.lower()} "}).status_code, 200)
        self.assertEqual(User.query.filter_by(inspector_id="I778").one().manager_code, code)

    def test_demo_data_is_off_unless_asked_for(self):
        from app import config
        self.assertFalse(config.SEED_DEMO_DATA)


class ActivityTests(ApiTestCase):
    def test_feed_lists_offers_acceptances_and_results_newest_first(self):
        now = now_local()
        db.session.add_all([
            InspectorRun(inspector_id="I001", trip_id="t1", status="completed", actual_fines=3, potential_fines=5,
                         assigned_at=now - timedelta(minutes=30), accepted_at=now - timedelta(minutes=25), finished_at=now - timedelta(minutes=5)),
            InspectorRun(inspector_id="I002", trip_id="t2", status="accepted", assigned_at=now - timedelta(minutes=2), accepted_at=now - timedelta(minutes=2)),
            InspectorRun(inspector_id="X001", trip_id="t3", status="accepted", assigned_at=now, accepted_at=now),
        ])
        db.session.commit()
        self.login()

        events = self.client.get("/api/activity").get_json()["events"]

        kinds = [(e["name"], e["kind"]) for e in events]
        self.assertEqual(kinds, [("Dana", "accepted"), ("Lior", "completed"), ("Lior", "accepted"), ("Lior", "offered")])
        self.assertEqual(events[1]["fines"], 3)
        self.assertNotIn("Other", [e["name"] for e in events])   # another manager's team never shows up

    def test_activity_needs_an_admin_and_a_numeric_limit(self):
        self.assertEqual(self.client.get("/api/activity").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/activity?limit=x").status_code, 400)


class ManualAssignmentTests(ApiTestCase):
    def test_options_are_live_buses_near_the_inspector_with_expected_fines(self):
        self.login()
        live = [{"trip_id": "trip_101", "stop_id": "stop_1", "route_id": 101, "route_num": "101", "destination": "Terminal",
                 "minutes_until_arrival": 6.0, "stop_feature": {"properties": {"stop_name": "Stop One"}}}]
        with patch("app.api.admin_ops.get_engine", return_value=make_engine()), \
                patch("app.api.admin_ops.get_live_trip_options", return_value=live):
            body = self.client.get("/api/admin/options?inspector_id=I001").get_json()
        self.assertEqual(body["source"], "live")
        option = body["options"][0]
        self.assertEqual((option["route_num"], option["stop_name"], option["trip_id"]), ("101", "Stop One", "trip_101"))
        self.assertGreaterEqual(option["potential_fines"], 0)

    def test_options_are_limited_to_own_inspectors(self):
        self.login()
        self.assertEqual(self.client.get("/api/admin/options?inspector_id=X001").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/options?inspector_id=I001&radius=99999").status_code, 400)

    def test_assigning_creates_an_offer_the_inspector_can_accept(self):
        self.login()
        made = self.client.post("/api/admin/assign", json={"inspector_id": "I001", "trip_id": "trip_101", "stop_id": "stop_1", "potential_fines": 4})
        self.assertEqual((made.status_code, made.get_json()["status"]), (201, "assigned"))
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.client.get("/api/runs/current").get_json()["run"]["status"], "assigned")
        self.assertEqual(self.client.post(f"/api/runs/{made.get_json()['id']}/accept").get_json()["status"], "accepted")

    def test_assignment_guards(self):
        self.login()
        ok = {"inspector_id": "I001", "trip_id": "t", "stop_id": "s"}
        self.assertEqual(self.client.post("/api/admin/assign", json={**ok, "inspector_id": "X001"}).status_code, 404)
        self.assertEqual(self.client.post("/api/admin/assign", json={"inspector_id": "I001"}).status_code, 400)
        self.assertEqual(self.client.post("/api/admin/assign", json={**ok, "potential_fines": -2}).status_code, 400)
        self.assertEqual(self.client.post("/api/admin/assign", json=ok).status_code, 201)
        self.assertEqual(self.client.post("/api/admin/assign", json=ok).status_code, 409)   # already has an active run

        Inspector.query.filter_by(inspector_id="I002").one().break_until = now_local() + timedelta(minutes=5)
        db.session.commit()
        self.assertEqual(self.client.post("/api/admin/assign", json={**ok, "inspector_id": "I002"}).status_code, 409)

    def test_the_manager_can_cancel_an_offer_but_not_someone_elses(self):
        self.login()
        run_id = self.client.post("/api/admin/assign", json={"inspector_id": "I001", "trip_id": "t", "stop_id": "s"}).get_json()["id"]
        foreign = InspectorRun(inspector_id="X001", trip_id="t", status="assigned")
        db.session.add(foreign)
        db.session.commit()
        self.assertEqual(self.client.post(f"/api/admin/runs/{foreign.id}/cancel").status_code, 404)
        self.assertEqual(self.client.post(f"/api/admin/runs/{run_id}/cancel").get_json()["status"], "cancelled")
        self.assertEqual(self.client.post(f"/api/admin/runs/{run_id}/cancel").status_code, 409)


class InspectorDetailTests(ApiTestCase):
    def test_detail_shows_totals_per_day_fines_and_recent_runs(self):
        now = now_local()
        db.session.add(InspectorRun(inspector_id="I001", trip_id="trip_101", stop_id="stop_1", status="completed", potential_fines=10,
                                    actual_fines=4, assigned_at=now, accepted_at=now, finished_at=now))
        db.session.commit()
        self.login()
        with patch("app.services.recommendations.get_engine", return_value=make_engine()):
            body = self.client.get("/api/inspector/I001/detail").get_json()
        self.assertEqual((body["name"], body["completed_runs"], body["total_fines"], body["efficiency"]), ("Lior", 1, 4, 40))
        self.assertEqual(len(body["days"]), 14)
        self.assertEqual(body["days"][-1]["fines"], 4)
        self.assertEqual(body["runs"][0]["route_num"], "101")
        self.assertEqual(self.client.get("/api/inspector/X001/detail").status_code, 404)

    def test_the_detail_page_needs_an_admin(self):
        self.assertEqual(self.client.get("/staff/I001").status_code, 302)
        self.login()
        self.assertEqual(self.client.get("/staff/I001").status_code, 200)


class ReactivationTests(ApiTestCase):
    def test_a_removed_inspector_with_history_can_be_brought_back(self):
        db.session.add(Fine(inspector_id="I001", timestamp=now_local()))
        db.session.commit()
        self.login()
        removed = self.client.delete("/api/inspector/I001").get_json()
        self.assertTrue(removed["deactivated"])
        self.assertEqual([s["inspector_id"] for s in self.client.get("/api/staff").get_json()], ["I002"])

        gone = self.client.get("/api/staff/deactivated").get_json()
        self.assertEqual([g["inspector_id"] for g in gone], ["I001"])

        self.assertEqual(self.client.post("/api/inspector/I001/reactivate").status_code, 200)
        self.assertEqual(sorted(s["inspector_id"] for s in self.client.get("/api/staff").get_json()), ["I001", "I002"])
        self.assertTrue(Inspector.query.filter_by(inspector_id="I001").one().available)
        self.assertEqual(self.client.get("/api/staff/deactivated").get_json(), [])

    def test_only_the_removing_manager_can_reactivate(self):
        db.session.add(Fine(inspector_id="I001", timestamp=now_local()))
        db.session.commit()
        self.login()
        self.client.delete("/api/inspector/I001")
        self.login("admin2", admin_code="ADM002")
        self.assertEqual(self.client.post("/api/inspector/I001/reactivate").status_code, 404)
        self.assertEqual(self.client.get("/api/staff/deactivated").get_json(), [])
        self.assertIsNone(User.query.filter_by(inspector_id="I001").one().manager_code)


class TeamSettingsAndAuditTests(ApiTestCase):
    def test_settings_default_validate_and_stay_per_team(self):
        self.login()
        self.assertEqual(self.client.get("/api/team/settings").get_json(), {"buffer_minutes": 3, "radius_m": 666, "max_walk_minutes": 8, "max_break_minutes": 90})
        saved = self.client.put("/api/team/settings", json={"buffer_minutes": 5, "radius_m": 900})
        self.assertEqual((saved.status_code, saved.get_json()["buffer_minutes"], saved.get_json()["max_walk_minutes"]), (200, 5, 8))
        for bad in ({"radius_m": 50}, {"buffer_minutes": "x"}, {"max_walk_minutes": 99}):
            self.assertEqual(self.client.put("/api/team/settings", json=bad).status_code, 400, bad)
        self.assertEqual(self.client.get("/api/team/settings").get_json()["radius_m"], 900)
        self.login("admin2", admin_code="ADM002")
        self.assertEqual(self.client.get("/api/team/settings").get_json()["radius_m"], 666)

    def test_the_forced_assignment_uses_the_team_settings(self):
        self.login()
        self.client.put("/api/team/settings", json={"buffer_minutes": 7, "radius_m": 1200, "max_walk_minutes": 11})
        with patch("app.api.assignments.assign_and_persist_runs", return_value=[]) as assign:
            self.client.post("/api/assign_runs")
        assign.assert_called_once_with(buffer_minutes=7, radius_m=1200, max_walk_minutes=11, admin_code="ADM001")

    def test_sensitive_actions_are_written_to_the_audit_log(self):
        self.login()
        self.client.post("/api/inspector/I001/reset_password")
        self.client.post("/api/admin/assign", json={"inspector_id": "I002", "trip_id": "t", "stop_id": "s"})
        self.client.put("/api/team/settings", json={"radius_m": 700})
        entries = self.client.get("/api/audit").get_json()["entries"]
        self.assertEqual([e["action"] for e in entries], ["settings_changed", "run_assigned", "password_reset"])
        self.assertEqual((entries[2]["actor"], entries[2]["target"]), ("admin", "I001"))
        self.login("admin2", admin_code="ADM002")
        self.assertEqual(self.client.get("/api/audit").get_json()["entries"], [])   # another team never sees them

    def test_bulk_online_offline_only_touches_own_inspectors(self):
        self.login()
        done = self.client.post("/api/staff/bulk", json={"action": "offline", "inspector_ids": ["I001", "I002", "X001"]})
        self.assertEqual(done.get_json(), {"changed": 2})
        self.assertEqual([Inspector.query.filter_by(inspector_id=i).one().available for i in ("I001", "I002", "X001")], [False, False, True])
        self.assertEqual(self.client.post("/api/staff/bulk", json={"action": "online", "inspector_ids": ["I001"]}).get_json(), {"changed": 1})
        for bad in ({"action": "nuke", "inspector_ids": ["I001"]}, {"action": "online", "inspector_ids": []}, {"action": "online"}):
            self.assertEqual(self.client.post("/api/staff/bulk", json=bad).status_code, 400)


class InsightsTests(ApiTestCase):
    def test_insights_compare_periods_and_rank_stops_and_lines(self):
        now = now_local()
        db.session.add_all([
            Fine(inspector_id="I001", trip_id="trip_101", stop_id="stop_1", timestamp=now),
            Fine(inspector_id="I001", trip_id="trip_101", stop_id="stop_1", timestamp=now),
            Fine(inspector_id="I002", trip_id="trip_101", stop_id="stop_2", timestamp=now - timedelta(days=1)),
            Fine(inspector_id="I001", trip_id="trip_101", stop_id="stop_1", timestamp=now - timedelta(days=45)),
            Fine(inspector_id="X001", trip_id="trip_101", stop_id="stop_1", timestamp=now),
        ])
        db.session.commit()
        self.login()
        start = (now - timedelta(days=29)).date().isoformat()
        with patch("app.services.routing.get_engine", return_value=make_engine()):
            body = self.client.get(f"/api/analytics/insights?start={start}&end={now.date().isoformat()}").get_json()
        self.assertEqual((body["fines"], body["previous_fines"], body["change_percent"]), (3, 1, 200))
        self.assertEqual((body["stops"][0]["stop_id"], body["stops"][0]["fines"], body["stops"][0]["name"]), ("stop_1", 2, "Stop One"))
        self.assertEqual(body["lines"], [{"line": "101", "fines": 3}])

    def test_insights_validate_input(self):
        self.assertEqual(self.client.get("/api/analytics/insights").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/analytics/insights?start=2026-05-02&end=2026-05-01").status_code, 400)
        self.assertEqual(self.client.get("/api/analytics/insights?start=nope").status_code, 400)


if __name__ == "__main__":
    unittest.main()


class AttentionTests(ApiTestCase):
    def items(self):
        self.login()
        return self.client.get("/api/attention").get_json()["items"]

    def test_quiet_when_everything_is_fine(self):
        self.assertEqual(self.items(), [])

    def test_unanswered_offer_silent_phone_and_overrun_break(self):
        now = now_local()
        db.session.add(InspectorRun(inspector_id="I001", trip_id="t", stop_id="s", status="assigned", assigned_at=now - timedelta(seconds=200)))
        dana = Inspector.query.filter_by(inspector_id="I002").one()
        dana.location_updated_at = now - timedelta(minutes=10)
        db.session.commit()
        kinds = {i["kind"]: i for i in self.items()}
        self.assertEqual(kinds["offer_unanswered"]["inspector_id"], "I001")
        self.assertEqual(kinds["phone_silent"]["inspector_id"], "I002")
        dana.available = False
        dana.break_until = now - timedelta(minutes=10)
        db.session.commit()
        self.assertEqual({i["kind"] for i in self.items()}, {"offer_unanswered", "break_overrun"})

    def test_only_own_team(self):
        db.session.add(InspectorRun(inspector_id="X001", trip_id="t", stop_id="s", status="assigned", assigned_at=now_local() - timedelta(seconds=500)))
        db.session.commit()
        self.assertEqual(self.items(), [])

    def test_staff_list_reports_shift_hours_today(self):
        from app.models import ShiftLog
        db.session.add(ShiftLog(inspector_id="I001", started_at=now_local() - timedelta(minutes=90), ended_at=now_local() - timedelta(minutes=30)))
        db.session.commit()
        self.login()
        row = next(s for s in self.client.get("/api/staff").get_json() if s["inspector_id"] == "I001")
        self.assertGreater(row["shift_hours_today"], 0)          # (the part of the shift that falls on today)
