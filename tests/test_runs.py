import unittest

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun
from app.services import runs
from tests.helpers import ApiTestCase


class RunServiceTests(ApiTestCase):
    def test_a_started_run_is_accepted_and_blocks_a_second_one(self):
        run = runs.start_run("I001", trip_id="t1", stop_id=77, potential_fines=4)
        self.assertEqual((run.status, run.stop_id, run.potential_fines), ("accepted", "77", 4))
        self.assertIsNotNone(run.accepted_at)
        with self.assertRaises(runs.RunError) as raised:
            runs.start_run("I001", trip_id="t2")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(runs.get_active_run("I001").id, run.id)
        self.assertIsNone(runs.get_active_run("I002"))

    def test_start_validates_input(self):
        for bad in ({"trip_id": None}, {"trip_id": "t", "potential_fines": "many"}, {"trip_id": "t", "potential_fines": -1}):
            with self.assertRaises(runs.RunError):
                runs.start_run("I001", **bad)
        self.assertEqual(InspectorRun.query.count(), 0)

    def test_complete_records_fines_and_updates_the_inspector(self):
        run = runs.start_run("I001", trip_id="t1", stop_id="s1", potential_fines=5)
        runs.complete_run(run, 3)

        inspector = Inspector.query.filter_by(inspector_id="I001").one()
        self.assertEqual((run.status, run.actual_fines), ("completed", 3))
        self.assertIsNotNone(run.finished_at)
        self.assertEqual((inspector.completed_trips, inspector.total_fines), (1, 3))
        self.assertIsNotNone(inspector.last_assignment_completed_at)
        fines = Fine.query.filter_by(run_id=run.id).all()
        self.assertEqual((len(fines), {f.inspector_id for f in fines}, {f.trip_id for f in fines}), (3, {"I001"}, {"t1"}))
        self.assertIsNone(runs.get_active_run("I001"))

    def test_zero_fines_is_a_valid_outcome(self):
        run = runs.start_run("I001", trip_id="t1")
        runs.complete_run(run, 0)
        self.assertEqual((run.actual_fines, Fine.query.count()), (0, 0))

    def test_complete_rejects_bad_counts_and_wrong_states(self):
        run = runs.start_run("I001", trip_id="t1")
        for bad in (-1, "x", runs.MAX_FINES_PER_RUN + 1):
            with self.assertRaises(runs.RunError):
                runs.complete_run(run, bad)
        self.assertEqual(run.status, "accepted")
        runs.complete_run(run, 1)
        with self.assertRaises(runs.RunError):
            runs.complete_run(run, 1)  # already completed
        self.assertEqual(Fine.query.count(), 1)

    def test_an_assigned_run_must_be_accepted_before_completion(self):
        run = InspectorRun(inspector_id="I002", trip_id="t1", status="assigned")
        db.session.add(run)
        db.session.commit()
        with self.assertRaises(runs.RunError) as raised:
            runs.complete_run(run, 1)
        self.assertEqual(raised.exception.status, 409)
        runs.accept_run(run)
        self.assertEqual(run.status, "accepted")
        with self.assertRaises(runs.RunError):
            runs.accept_run(run)

    def test_cancel_frees_the_inspector(self):
        run = runs.start_run("I001", trip_id="t1")
        runs.cancel_run(run)
        self.assertEqual(run.status, "cancelled")
        self.assertIsNone(runs.get_active_run("I001"))
        with self.assertRaises(runs.RunError):
            runs.cancel_run(run)
        runs.start_run("I001", trip_id="t2")  # free to take another


class RunApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login("lior", role="inspector", inspector_id="I001")

    def test_runs_require_an_inspector_session(self):
        anonymous = self.app.test_client()
        admin = self.app.test_client()
        with admin.session_transaction() as sess:
            sess.update(user="admin", role="admin", admin_code="ADM001")
        for client in (anonymous, admin):
            for method, url in (("get", "/api/runs/current"), ("post", "/api/runs"), ("put", "/api/me/status"),
                                ("post", "/api/runs/1/complete")):
                self.assertEqual(getattr(client, method)(url).status_code, 401, url)

    def test_full_lifecycle_over_http(self):
        self.assertEqual(self.client.get("/api/runs/current").get_json(), {"run": None})

        created = self.client.post("/api/runs", json={"trip_id": "t9", "stop_id": "s9", "potential_fines": 6})
        self.assertEqual(created.status_code, 201)
        run_id = created.get_json()["id"]
        self.assertEqual(self.client.get("/api/runs/current").get_json()["run"]["id"], run_id)
        self.assertEqual(self.client.post("/api/runs", json={"trip_id": "other"}).status_code, 409)

        done = self.client.post(f"/api/runs/{run_id}/complete", json={"actual_fines": 4})
        self.assertEqual((done.status_code, done.get_json()["status"], done.get_json()["actual_fines"]), (200, "completed", 4))
        self.assertEqual(self.client.get("/api/runs/current").get_json(), {"run": None})
        self.assertEqual(Inspector.query.filter_by(inspector_id="I001").one().total_fines, 4)

    def test_errors_map_to_clear_statuses(self):
        self.assertEqual(self.client.post("/api/runs", json={}).status_code, 400)
        run_id = self.client.post("/api/runs", json={"trip_id": "t"}).get_json()["id"]
        self.assertEqual(self.client.post(f"/api/runs/{run_id}/complete", json={"actual_fines": "lots"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/runs/{run_id}/accept").status_code, 409)
        self.assertEqual(self.client.post("/api/runs/99999/complete", json={}).status_code, 404)
        self.assertEqual(self.client.post(f"/api/runs/{run_id}/cancel").get_json()["status"], "cancelled")

    def test_an_inspector_cannot_touch_someone_elses_run(self):
        foreign = InspectorRun(inspector_id="I002", trip_id="t1", status="accepted")
        db.session.add(foreign)
        db.session.commit()
        for action in ("accept", "cancel", "complete"):
            self.assertEqual(self.client.post(f"/api/runs/{foreign.id}/{action}", json={}).status_code, 404, action)
        self.assertEqual(db.session.get(InspectorRun, foreign.id).status, "accepted")

    def test_availability_and_position_can_be_updated(self):
        response = self.client.put("/api/me/status", json={"available": False, "latitude": 32.1, "longitude": 34.8})
        self.assertEqual(response.get_json(), {"available": False, "latitude": 32.1, "longitude": 34.8})
        inspector = Inspector.query.filter_by(inspector_id="I001").one()
        self.assertEqual((inspector.available, inspector.latitude), (False, 32.1))
        self.assertTrue(self.client.put("/api/me/status", json={"available": True}).get_json()["available"])

    def test_me_summarises_the_inspector_and_todays_work(self):
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["inspector_id"], me["name"], me["today_runs"], me["today_fines"]), ("I001", "Lior", 0, 0))
        run_id = self.client.post("/api/runs", json={"trip_id": "t1"}).get_json()["id"]
        self.assertEqual(self.client.get("/api/me").get_json()["today_runs"], 0)  # not finished yet
        self.client.post(f"/api/runs/{run_id}/complete", json={"actual_fines": 3})
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["today_runs"], me["today_fines"], me["total_fines"], me["total_runs"]), (1, 3, 3, 1))

    def test_run_details_describe_the_stored_trip_or_degrade_to_none(self):
        from unittest.mock import patch

        from tests.helpers import make_engine
        run_id = self.client.post("/api/runs", json={"trip_id": "trip_101", "stop_id": "stop_1"}).get_json()["id"]
        with patch("app.services.recommendations.get_engine", return_value=make_engine()):
            body = self.client.get(f"/api/runs/{run_id}/details").get_json()
        self.assertEqual(body["run"]["id"], run_id)
        self.assertEqual((body["details"]["route_num"], body["details"]["destination"]), ("101", "Terminal"))
        self.assertEqual(body["details"]["stop_feature"]["properties"]["stop_id"], "stop_1")

        with patch("app.services.recommendations.get_engine", return_value=None):
            self.assertIsNone(self.client.get(f"/api/runs/{run_id}/details").get_json()["details"])
        self.assertEqual(self.client.get("/api/runs/99999/details").status_code, 404)

    def test_the_fine_counter_is_saved_while_the_ride_is_running(self):
        run_id = self.client.post("/api/runs", json={"trip_id": "t1"}).get_json()["id"]
        self.assertEqual(self.client.get("/api/runs/current").get_json()["run"]["fines_in_progress"], 0)
        saved = self.client.patch(f"/api/runs/{run_id}/progress", json={"fines": 4})
        self.assertEqual((saved.status_code, saved.get_json()["fines_in_progress"]), (200, 4))
        self.assertEqual(self.client.get("/api/runs/current").get_json()["run"]["fines_in_progress"], 4)
        for bad in (-1, "x", runs.MAX_FINES_PER_RUN + 1):
            self.assertEqual(self.client.patch(f"/api/runs/{run_id}/progress", json={"fines": bad}).status_code, 400)
        self.assertEqual(db.session.get(InspectorRun, run_id).fines_in_progress, 4)
        self.client.post(f"/api/runs/{run_id}/complete", json={"actual_fines": 4})
        self.assertEqual(self.client.patch(f"/api/runs/{run_id}/progress", json={"fines": 1}).status_code, 409)
        self.assertEqual(self.client.patch("/api/runs/99999/progress", json={"fines": 1}).status_code, 404)

    def test_a_timed_break_makes_the_inspector_unavailable_until_it_ends(self):
        started = self.client.put("/api/me/status", json={"break_minutes": 15})
        self.assertEqual((started.status_code, started.get_json()["available"]), (200, False))
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["on_break"], me["available"]), (True, False))
        self.assertIsNotNone(me["break_until"])

        self.client.put("/api/me/status", json={"break_minutes": 0})  # back from the break
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["on_break"], me["available"], me["break_until"]), (False, True, None))

        for bad in (3, 500, "x", -5):
            self.assertEqual(self.client.put("/api/me/status", json={"break_minutes": bad}).status_code, 400)

    def test_an_expired_break_closes_itself(self):
        from datetime import timedelta

        from app.utils.clock import now_local
        inspector = Inspector.query.filter_by(inspector_id="I001").one()
        inspector.available, inspector.break_until = False, now_local() - timedelta(minutes=1)
        db.session.commit()
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["on_break"], me["available"]), (False, True))

    def test_no_break_during_a_run_and_going_online_ends_a_break(self):
        self.client.put("/api/me/status", json={"break_minutes": 30})
        self.client.put("/api/me/status", json={"available": True})
        self.assertFalse(self.client.get("/api/me").get_json()["on_break"])
        self.client.post("/api/runs", json={"trip_id": "t1"})
        self.assertEqual(self.client.put("/api/me/status", json={"break_minutes": 15}).status_code, 409)

    def test_history_groups_finished_rides_by_day(self):
        for fines in (2, 3):
            run_id = self.client.post("/api/runs", json={"trip_id": "t1", "stop_id": "s1"}).get_json()["id"]
            self.client.post(f"/api/runs/{run_id}/complete", json={"actual_fines": fines})
        body = self.client.get("/api/me/history?days=3").get_json()
        self.assertEqual(len(body["days"]), 3)
        self.assertEqual((body["days"][-1]["rides"], body["days"][-1]["fines"]), (2, 5))
        self.assertEqual(sorted(r["fines"] for r in body["rides"]), [2, 3])
        self.assertEqual(self.client.get("/api/me/history?days=x").status_code, 400)
        self.assertEqual(self.app.test_client().get("/api/me/history").status_code, 401)

    def test_me_requires_an_inspector(self):
        self.assertEqual(self.app.test_client().get("/api/me").status_code, 401)

    def test_bad_status_updates_change_nothing(self):
        for body in ({"latitude": 999, "longitude": 34.8}, {"latitude": "x", "longitude": 1}, {"latitude": 32.0}):
            self.assertEqual(self.client.put("/api/me/status", json=body).status_code, 400, body)
        inspector = Inspector.query.filter_by(inspector_id="I001").one()
        self.assertEqual((inspector.latitude, inspector.longitude), (32.088, 34.7898))

    def test_admin_assigned_runs_are_visible_and_acceptable(self):
        assigned = InspectorRun(inspector_id="I001", trip_id="t5", status="assigned", potential_fines=7)
        db.session.add(assigned)
        db.session.commit()
        self.assertEqual(self.client.get("/api/runs/current").get_json()["run"]["status"], "assigned")
        self.assertEqual(self.client.post(f"/api/runs/{assigned.id}/accept").get_json()["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
