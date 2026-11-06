import time
import unittest
from datetime import timedelta
from unittest.mock import patch

from app import config
from app.api.assignments import assign_and_persist_runs
from app.extensions import db
from app.models import Fine, Inspector, InspectorRun, User
from app.utils.clock import now_local
from tests.helpers import ADMIN_CODE, ApiTestCase, make_engine, offline_walking


class AuthorizationTests(ApiTestCase):
    def test_protected_endpoints_require_login(self):
        for method, url in (("get", "/api/staff"), ("get", "/api/analytics"), ("post", "/api/assign_runs"),
                            ("get", "/api/profile"), ("post", "/api/find_best_trip"), ("get", "/api/inspector/I001"),
                            ("post", "/api/inspector"), ("put", "/api/inspector/I001"), ("delete", "/api/inspector/I001")):
            self.assertEqual(getattr(self.client, method)(url).status_code, 401, url)

    def test_inspector_role_cannot_use_admin_endpoints(self):
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.client.get("/api/staff").status_code, 401)
        self.assertEqual(self.client.post("/api/assign_runs").status_code, 401)

    def test_health_is_public_and_reports_siri_state(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        self.assertIn("failing_stops", response.get_json()["siri"])


class AccountFlowTests(ApiTestCase):
    def test_register_admin_then_inspector_with_manager_code_then_login(self):
        admin = self.client.post("/api/register", json={"name": "Boss", "email": "boss@x.io", "password": "pw123456", "role": "admin"})
        self.assertTrue(admin.get_json()["pending"])
        boss = User.query.filter_by(username="boss@x.io").one()
        self.assertFalse(boss.approved)
        code = boss.manager_code

        inspector = self.app.test_client()
        registered = inspector.post("/api/register", json={"name": "Insp", "phone": "I777", "password": "pw123456",
                                                           "role": "inspector", "manager_code": code})
        self.assertEqual(registered.get_json(), {"success": True, "redirect": "/inspect"})
        self.assertEqual(Inspector.query.filter_by(inspector_id="I777").one().name, "Insp")

        fresh = self.app.test_client()
        self.assertEqual(fresh.post("/api/login", json={"username": "I777", "password": "pw123456"}).get_json()["redirect"], "/inspect")

    def test_invalid_manager_code_is_rejected(self):
        response = self.client.post("/api/register", json={"name": "X", "email": "x@x.io", "password": "pw123456",
                                                          "role": "inspector", "manager_code": "NOPE00"})
        self.assertEqual(response.status_code, 400)

    def test_unknown_roles_are_rejected(self):
        response = self.client.post("/api/register", json={"name": "X", "email": "x@x.io", "password": "pw123456", "role": "superuser"})
        self.assertEqual((response.status_code, response.get_json()["message"]), (400, "Invalid role"))
        self.assertIsNone(User.query.filter_by(username="x@x.io").first())

    def test_taken_usernames_get_a_numeric_suffix(self):
        self.client.post("/api/register", json={"name": "A", "email": "dup@x.io", "password": "pw123456", "role": "admin"})
        self.app.test_client().post("/api/register", json={"name": "B", "email": "dup@x.io", "password": "pw123456", "role": "admin"})
        self.assertEqual(sorted(u.username for u in User.query.filter(User.username.like("dup@x.io%"))), ["dup@x.io", "dup@x.io_1"])

    def test_inspector_without_manager_code_still_gets_an_inspector_record(self):
        self.app.test_client().post("/api/register", json={"name": "Solo", "phone": "0501234567", "password": "pw123456", "role": "inspector"})
        user = User.query.filter_by(username="0501234567").one()
        self.assertTrue(user.inspector_id.startswith("I"))
        self.assertEqual(Inspector.query.filter_by(inspector_id=user.inspector_id).one().name, "Solo")

    def test_unknown_user_and_wrong_password_look_identical(self):
        wrong = self.client.post("/api/login", json={"username": "lior", "password": "nope"})
        unknown = self.client.post("/api/login", json={"username": "ghost", "password": "nope"})
        self.assertEqual((wrong.status_code, wrong.get_json()), (unknown.status_code, unknown.get_json()))
        self.assertEqual(wrong.status_code, 401)

    def test_repeated_failed_logins_are_locked_out_even_for_the_right_password(self):
        for _ in range(config.LOGIN_MAX_FAILURES):
            self.assertEqual(self.client.post("/api/login", json={"username": "lior", "password": "bad"}).status_code, 401)
        locked = self.client.post("/api/login", json={"username": "lior", "password": "pw123456"})
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(self.client.get("/api/profile").status_code, 401)  # not logged in

    def test_lockout_is_per_username_and_cleared_by_a_successful_login(self):
        for _ in range(config.LOGIN_MAX_FAILURES - 1):
            self.client.post("/api/login", json={"username": "lior", "password": "bad"})
        self.assertEqual(self.client.post("/api/login", json={"username": "dana", "password": "bad"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"username": "lior", "password": "pw123456"}).status_code, 200)
        for _ in range(config.LOGIN_MAX_FAILURES - 1):  # the earlier failures no longer count
            self.client.post("/api/login", json={"username": "lior", "password": "bad"})
        self.assertEqual(self.client.post("/api/login", json={"username": "lior", "password": "pw123456"}).status_code, 200)

    def test_lockout_expires(self):
        for _ in range(config.LOGIN_MAX_FAILURES):
            self.client.post("/api/login", json={"username": "lior", "password": "bad"})
        with patch.object(config, "LOGIN_LOCKOUT_SECONDS", 0):
            time.sleep(0.01)
            self.assertEqual(self.client.post("/api/login", json={"username": "lior", "password": "pw123456"}).status_code, 200)

    def test_credentials_in_the_query_string_are_ignored(self):
        response = self.client.post("/api/login?username=lior&password=pw")
        self.assertEqual(response.status_code, 400)

    def test_logout_clears_the_session(self):
        self.login()
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/staff").status_code, 401)


class StaffAndAnalyticsTests(ApiTestCase):
    def test_staff_lists_only_own_inspectors_with_stats(self):
        db.session.add_all([
            InspectorRun(inspector_id="I001", trip_id="t1", stop_id="s1", potential_fines=5, status="assigned"),
            Fine(inspector_id="I001", timestamp=now_local()),
            Fine(inspector_id="I001", timestamp=now_local() - timedelta(days=30)),
        ])
        db.session.commit()
        self.login()

        staff = self.client.get("/api/staff").get_json()

        self.assertEqual(sorted(s["inspector_id"] for s in staff), ["I001", "I002"])
        lior = next(s for s in staff if s["inspector_id"] == "I001")
        self.assertEqual((lior["name"], lior["weekly_fines"], lior["today_trips"]), ("Lior", 1, 1))
        self.assertEqual(lior["current_assignment"]["status"], "assigned")
        self.assertIsNone(next(s for s in staff if s["inspector_id"] == "I002")["current_assignment"])

    def test_analytics_aggregates_own_inspectors_only(self):
        db.session.add_all([
            InspectorRun(inspector_id="I001", trip_id="t1", potential_fines=10, actual_fines=5, status="completed"),
            InspectorRun(inspector_id="X001", trip_id="t2", potential_fines=100, actual_fines=0, status="completed"),
            Fine(inspector_id="I001", timestamp=now_local()),
            Fine(inspector_id="X001", timestamp=now_local()),
        ])
        db.session.commit()
        self.login()

        data = self.client.get("/api/analytics").get_json()

        self.assertEqual((data["totalFines"], data["weeklyTotal"], data["activeInspectors"], data["avgEfficiency"]), (1, 1, 2, 50))
        self.assertEqual(len(data["inspectors"]), 2)

    def test_analytics_counts_assigned_inspectors_and_average_completion_time(self):
        started = now_local().replace(hour=9, minute=0, second=0, microsecond=0)
        db.session.add_all([
            InspectorRun(inspector_id="I001", trip_id="t1", status="accepted", accepted_at=started),
            InspectorRun(inspector_id="I002", trip_id="t2", status="completed", accepted_at=started,
                         finished_at=started + timedelta(minutes=12)),
            InspectorRun(inspector_id="I002", trip_id="t3", status="completed", accepted_at=started,
                         finished_at=started + timedelta(minutes=20)),
            InspectorRun(inspector_id="X001", trip_id="t4", status="accepted"),  # another admin's inspector
        ])
        db.session.commit()
        self.login()

        data = self.client.get("/api/analytics").get_json()

        self.assertEqual((data["assignedInspectors"], data["unassignedInspectors"]), (1, 1))
        self.assertEqual(data["avgCompletionMin"], 16.0)

    def test_analytics_without_activity_has_no_completion_time(self):
        self.login()
        data = self.client.get("/api/analytics").get_json()
        self.assertEqual((data["assignedInspectors"], data["unassignedInspectors"], data["avgCompletionMin"]), (0, 2, None))

    def test_analytics_report_groups_own_fines_by_hour_weekday_and_period(self):
        from datetime import datetime
        sunday_9 = datetime(2025, 3, 2, 9, 15)  # a Sunday
        db.session.add_all([
            Fine(inspector_id="I001", timestamp=sunday_9),
            Fine(inspector_id="I002", timestamp=sunday_9.replace(hour=9, minute=40)),
            Fine(inspector_id="I001", timestamp=datetime(2025, 5, 7, 14, 0)),  # Wednesday, a later month
            Fine(inspector_id="X001", timestamp=sunday_9),  # another admin's inspector
            Fine(inspector_id="I001", timestamp=datetime(2024, 12, 1, 8, 0)),  # outside the range
        ])
        db.session.commit()
        self.login()

        data = self.client.get("/api/analytics/report?start=2025-03-01&end=2025-05-31&granularity=month").get_json()

        self.assertEqual(data["totals"]["fines"], 3)
        self.assertEqual((data["hourly"][9], data["hourly"][14]), (2, 1))
        self.assertEqual((data["weekday"][0], data["weekday"][3]), (2, 1))  # Sunday first
        self.assertEqual(data["timeline"], [{"period": "2025-03", "fines": 2}, {"period": "2025-04", "fines": 0},
                                            {"period": "2025-05", "fines": 1}])

    def test_analytics_report_ranks_inspectors_by_fines(self):
        from datetime import datetime
        db.session.add_all([Fine(inspector_id="I002", timestamp=datetime(2025, 3, 2, 9)),
                            Fine(inspector_id="I002", timestamp=datetime(2025, 3, 3, 9)),
                            Fine(inspector_id="I001", timestamp=datetime(2025, 3, 4, 9)),
                            Fine(inspector_id="X001", timestamp=datetime(2025, 3, 4, 9))])
        db.session.commit()
        self.login()
        board = self.client.get("/api/analytics/report?start=2025-03-01&end=2025-03-31").get_json()["leaderboard"]
        self.assertEqual([(row["inspector_id"], row["fines"]) for row in board], [("I002", 2), ("I001", 1)])

    def test_analytics_report_quarters_and_validation(self):
        self.login()
        quarters = self.client.get("/api/analytics/report?start=2025-02-01&end=2025-08-01&granularity=quarter").get_json()
        self.assertEqual([row["period"] for row in quarters["timeline"]], ["2025-Q1", "2025-Q2", "2025-Q3"])
        for query in ("start=nope", "start=2025-05-01&end=2025-01-01", "granularity=hour", "start=1990-01-01&end=2025-01-01"):
            self.assertEqual(self.client.get(f"/api/analytics/report?{query}").status_code, 400, query)

    def test_analytics_report_requires_admin(self):
        self.assertEqual(self.client.get("/api/analytics/report").status_code, 401)
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.client.get("/api/analytics/report").status_code, 401)

    def test_profile_update_syncs_inspector_name(self):
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.client.post("/api/profile", json={"full_name": "Lior Cohen"}).status_code, 200)
        self.assertEqual(Inspector.query.filter_by(inspector_id="I001").one().name, "Lior Cohen")
        self.assertEqual(self.client.get("/api/profile").get_json()["full_name"], "Lior Cohen")

    def test_profile_rejects_taken_usernames(self):
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.client.post("/api/profile", json={"username": "dana"}).status_code, 400)


class InspectorCrudTests(ApiTestCase):
    def test_create_get_update_delete_roundtrip(self):
        self.login()
        created = self.client.post("/api/inspector", json={"inspector_id": "I900", "name": "New Person", "email": "n@x.io",
                                                          "latitude": 32.1, "longitude": 34.8})
        self.assertEqual(created.status_code, 201)
        user = User.query.filter_by(inspector_id="I900").one()
        self.assertEqual(user.manager_code, ADMIN_CODE)
        self.assertTrue(user.check_password(created.get_json()["temporary_password"]))

        self.assertEqual(self.client.get("/api/inspector/I900").get_json()["email"], "n@x.io")
        updated = self.client.put("/api/inspector/I900", json={"name": "Renamed", "latitude": 32.2, "available": False}).get_json()
        self.assertEqual((updated["name"], updated["available"], updated["latitude"]), ("Renamed", False, 32.2))
        self.assertEqual(User.query.filter_by(inspector_id="I900").one().full_name, "Renamed")

        self.assertEqual(self.client.delete("/api/inspector/I900").get_json(), {"success": True, "deactivated": False})
        self.assertIsNone(Inspector.query.filter_by(inspector_id="I900").first())
        self.assertIsNone(User.query.filter_by(inspector_id="I900").first())

    def test_create_rejects_duplicates_and_bad_input(self):
        self.login()
        self.assertEqual(self.client.post("/api/inspector", json={"inspector_id": "I001", "name": "Dup"}).status_code, 409)
        self.assertEqual(self.client.post("/api/inspector", json={"name": "No id"}).status_code, 400)
        self.assertEqual(self.client.post("/api/inspector", json={"inspector_id": "I901", "name": "Far", "latitude": 400}).status_code, 400)
        self.assertIsNone(Inspector.query.filter_by(inspector_id="I901").first())

    def test_admin_cannot_touch_another_admins_inspector(self):
        self.login()
        self.assertEqual(self.client.get("/api/inspector/X001").status_code, 404)
        self.assertEqual(self.client.put("/api/inspector/X001", json={"name": "Hacked"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/inspector/X001").status_code, 404)
        self.assertEqual(Inspector.query.filter_by(inspector_id="X001").one().name, "Other")

    def test_delete_with_history_deactivates_instead_of_deleting(self):
        db.session.add(InspectorRun(inspector_id="I002", trip_id="t1", status="completed"))
        db.session.commit()
        self.login()

        self.assertEqual(self.client.delete("/api/inspector/I002").get_json(), {"success": True, "deactivated": True})
        self.assertFalse(Inspector.query.filter_by(inspector_id="I002").one().available)
        self.assertIsNone(User.query.filter_by(inspector_id="I002").one().manager_code)
        self.assertEqual(InspectorRun.query.filter_by(inspector_id="I002").count(), 1)
        self.assertEqual([s["inspector_id"] for s in self.client.get("/api/staff").get_json()], ["I001"])


class ResetPasswordTests(ApiTestCase):
    def test_reset_gives_a_new_working_password_and_blocks_the_old_one(self):
        user = User.query.filter_by(inspector_id="I001").one()
        user.set_password("old-pass-1")
        db.session.commit()
        self.login()

        response = self.client.post("/api/inspector/I001/reset_password")

        self.assertEqual(response.status_code, 200)
        fresh = response.get_json()["temporary_password"]
        user = User.query.filter_by(inspector_id="I001").one()
        self.assertTrue(user.check_password(fresh))
        self.assertFalse(user.check_password("old-pass-1"))

    def test_reset_is_limited_to_own_inspectors_and_admins(self):
        self.assertEqual(self.client.post("/api/inspector/I001/reset_password").status_code, 401)
        self.login()
        self.assertEqual(self.client.post("/api/inspector/X001/reset_password").status_code, 404)
        self.assertEqual(self.client.post("/api/inspector/NOPE/reset_password").status_code, 404)
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.client.post("/api/inspector/I001/reset_password").status_code, 401)


class TripEndpointTests(ApiTestCase):
    def test_invalid_parameters_are_rejected(self):
        self.login()
        for body in ({"lat": "abc"}, {"lat": 123}, {"radius": 999999}, {"buffer": -1}):
            self.assertEqual(self.client.post("/api/find_best_trip", json=body).status_code, 400, body)

    def test_engine_failure_returns_json_500(self):
        self.login()
        with patch("app.api.trips.find_best_trip", side_effect=RuntimeError("boom")):
            response = self.client.post("/api/find_best_trip", json={})
        self.assertEqual((response.status_code, response.get_json()), (500, {"error": "routing failed"}))

    def test_no_trip_returns_fallback_message(self):
        self.login()
        with patch("app.api.trips.find_best_trip", return_value=None):
            self.assertEqual(self.client.post("/api/find_best_trip", json={}).get_json(), {"fallback": "No suitable trip found"})

    def test_result_is_returned_as_json(self):
        self.login()
        result = {"best_option": {"route_id": 5}, "data_source": "live"}
        with patch("app.api.trips.find_best_trip", return_value=result) as find:
            response = self.client.post("/api/find_best_trip", json={"lat": 32.1, "lon": 34.8, "radius": 500, "buffer": 2})
        self.assertEqual(response.get_json(), result)
        find.assert_called_once_with(lat=32.1, lon=34.8, buffer_minutes=2.0, radius_m=500.0)


class DeclinedOfferTests(ApiTestCase):
    def test_declined_offers_are_passed_to_the_search_as_pairs(self):
        self.login()
        with patch("app.api.trips.find_best_trip", return_value=None) as find:
            self.client.post("/api/find_best_trip", json={"exclude": [{"route_id": 5, "stop_id": "A"}]})
        self.assertEqual(find.call_args.kwargs["exclude"], {("5", "A")})

    def test_malformed_exclude_lists_are_rejected(self):
        self.login()
        for exclude in ("x", [1], [{"route_id": 1}], [{"route_id": 1, "stop_id": 2}] * 51):
            self.assertEqual(self.client.post("/api/find_best_trip", json={"exclude": exclude}).status_code, 400, exclude)


class ArrivalsEndpointTests(ApiTestCase):
    def test_requires_login(self):
        self.assertEqual(self.client.get("/api/arrivals").status_code, 401)

    def test_invalid_parameters_are_rejected(self):
        self.login()
        for query in ("lat=abc", "lat=123", "radius=999999", "limit=0", "limit=500"):
            self.assertEqual(self.client.get(f"/api/arrivals?{query}").status_code, 400, query)

    def test_returns_arrivals_with_freshness_metadata(self):
        self.login()
        arrivals = [{"route_num": "66", "minutes_until_arrival": 3.5, "is_live": True}]
        with patch("app.api.trips.get_engine", return_value=make_engine()), \
             patch("app.api.trips.list_live_arrivals", return_value=arrivals) as listing:
            body = self.client.get("/api/arrivals?lat=32.1&lon=34.8&radius=500&limit=5").get_json()
        self.assertEqual((body["arrivals"], body["source"]), (arrivals, "live"))
        self.assertIn("fetched_at", body)
        self.assertEqual((listing.call_args.kwargs["radius_m"], listing.call_args.kwargs["limit"]), (500.0, 5))

    def test_missing_engine_or_siri_failure_degrades_to_empty_board(self):
        self.login()
        with patch("app.api.trips.get_engine", return_value=None):
            self.assertEqual(self.client.get("/api/arrivals").get_json()["source"], "unavailable")
        with patch("app.api.trips.get_engine", return_value=make_engine()), \
             patch("app.api.trips.list_live_arrivals", side_effect=RuntimeError("boom")):
            response = self.client.get("/api/arrivals")
        self.assertEqual((response.status_code, response.get_json()["arrivals"], response.get_json()["source"]), (200, [], "error"))


class AssignmentTests(ApiTestCase):
    def assign(self, engine, live=None):
        with patch("app.api.assignments.get_engine", return_value=engine), \
             patch("app.api.assignments.fetch_live_options", side_effect=lambda lat, lon, gtfs, radius: live or []), \
             offline_walking():
            return assign_and_persist_runs(admin_code=ADMIN_CODE)

    def test_runs_are_persisted_for_own_available_inspectors_only(self):
        results = self.assign(make_engine(route_ids=(101, 102)))

        self.assertEqual({r["inspector_id"] for r in results}, {"I001", "I002"})
        self.assertEqual(len({r["trip_id"] for r in results}), 2)
        self.assertEqual(InspectorRun.query.filter_by(status="assigned").count(), 2)
        self.assertEqual(InspectorRun.query.filter_by(inspector_id="X001").count(), 0)

    def test_repeating_the_assignment_skips_busy_inspectors(self):
        engine = make_engine(route_ids=(101, 102))
        self.assign(engine)
        self.assertEqual(self.assign(engine), [])
        self.assertEqual(InspectorRun.query.count(), 2)

    def test_offline_inspectors_are_not_assigned(self):
        Inspector.query.filter_by(inspector_id="I002").one().available = False
        db.session.commit()
        self.assertEqual([r["inspector_id"] for r in self.assign(make_engine(route_ids=(101, 102)))], ["I001"])

    def test_live_bus_is_assigned_to_at_most_one_inspector(self):
        bus = {"trip_id": "old_trip", "route_id": "101", "stop_id": "stop_1", "vehicle_ref": "bus-7", "minutes_until_arrival": 15.0}
        results = self.assign(make_engine(route_ids=(101,)), live=[bus])
        self.assertEqual(sorted(r["trip_id"] for r in results), ["old_trip", "trip_101"])

    def test_endpoint_reports_assignments(self):
        self.login()
        with patch("app.api.assignments.get_engine", return_value=make_engine(route_ids=(101, 102))), \
             patch("app.api.assignments.fetch_live_options", return_value=[]), offline_walking():
            body = self.client.post("/api/assign_runs").get_json()
        self.assertEqual(body["assigned_count"], 2)

    def test_without_an_engine_nothing_is_assigned(self):
        with patch("app.api.assignments.get_engine", return_value=None):
            self.assertEqual(assign_and_persist_runs(admin_code=ADMIN_CODE), [])


if __name__ == "__main__":
    unittest.main()
