import unittest
from datetime import date, timedelta

from app.extensions import db
from app.models import BreakLog, Inspector, InspectorRun, ShiftLog
from app.services.stats import period_range
from app.utils.clock import now_local
from tests.helpers import ApiTestCase


def finished(inspector_id, fines, when):
    return InspectorRun(inspector_id=inspector_id, trip_id="t", stop_id="s", status="completed", actual_fines=fines,
                        potential_fines=fines, assigned_at=when, finished_at=when)


class PeriodTests(unittest.TestCase):
    def test_ranges(self):
        today = date(2026, 11, 5)
        self.assertEqual(period_range("today", 0, today), (today, today, "hour"))
        self.assertEqual(period_range("week", 0, today), (date(2026, 10, 30), today, "day"))
        self.assertEqual(period_range("week", 1, today)[1], date(2026, 10, 29))
        self.assertEqual(period_range("month", 0, today), (date(2026, 11, 1), date(2026, 11, 30), "day"))
        self.assertEqual(period_range("month", 1, today)[:2], (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(period_range("month", 11, today)[:2], (date(2025, 12, 1), date(2025, 12, 31)))
        self.assertEqual(period_range("year", 1, today), (date(2025, 1, 1), date(2025, 12, 31), "month"))
        with self.assertRaises(ValueError):
            period_range("decade", 0, today)


class StatsApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        now = now_local()
        db.session.add_all([
            finished("I001", 4, now.replace(hour=9, minute=0)),
            finished("I001", 2, now.replace(hour=14, minute=0)),
            finished("I001", 5, now - timedelta(days=1)),
            finished("I001", 9, now - timedelta(days=9)),
            finished("I002", 7, now),
        ])
        db.session.commit()

    def stats(self, query=""):
        self.login("lior", role="inspector", inspector_id="I001")
        return self.client.get(f"/api/me/stats{query}")

    def test_today_counts_only_own_finished_rides_by_hour(self):
        data = self.stats("?period=today").get_json()
        self.assertEqual((data["totals"]["fines"], data["totals"]["rides"]), (6, 2))
        self.assertEqual(len(data["series"]), 24)
        self.assertEqual(data["series"][9]["fines"], 4)
        self.assertEqual(data["best"]["hour"], 9)
        self.assertEqual(data["totals"]["fines_per_ride"], 3.0)

    def test_week_compares_with_the_week_before(self):
        data = self.stats("?period=week").get_json()
        self.assertEqual(data["totals"]["fines"], 11)       # today 6 + yesterday 5
        self.assertEqual(data["previous"]["fines"], 9)      # the ride 9 days ago
        self.assertEqual(data["change_percent"], 22)
        self.assertEqual(len(data["series"]), 7)
        self.assertEqual(data["streak_days"], 2)

    def test_going_back_in_time(self):
        data = self.stats("?period=week&offset=1").get_json()
        self.assertEqual(data["totals"]["fines"], 9)

    def test_bad_input_is_rejected(self):
        self.assertEqual(self.stats("?period=decade").status_code, 400)
        self.assertEqual(self.stats("?offset=abc").status_code, 400)

    def test_shift_and_break_hours_are_summed_and_clipped(self):
        now = now_local()
        db.session.add_all([
            ShiftLog(inspector_id="I001", started_at=now - timedelta(hours=5), ended_at=now - timedelta(hours=3)),
            BreakLog(inspector_id="I001", started_at=now - timedelta(hours=3), planned_minutes=30, ended_at=now - timedelta(hours=2, minutes=30)),
        ])
        db.session.commit()
        data = self.stats("?period=week").get_json()
        self.assertEqual(data["totals"]["shift_hours"], 2.0)
        self.assertEqual(data["totals"]["break_hours"], 0.5)

    def test_a_shift_nobody_closed_ends_when_the_phone_went_quiet(self):
        now = now_local()
        inspector = Inspector.query.filter_by(inspector_id="I001").one()
        inspector.location_updated_at = now - timedelta(hours=1)
        db.session.add(ShiftLog(inspector_id="I001", started_at=now - timedelta(hours=3)))
        db.session.commit()
        data = self.stats("?period=week").get_json()
        self.assertEqual(data["totals"]["shift_hours"], 2.0)
        self.assertIsNotNone(ShiftLog.query.filter_by(inspector_id="I001").one().ended_at)

    def test_manager_sees_own_inspector_but_not_another_teams(self):
        self.login()
        self.assertEqual(self.client.get("/api/inspector/I001/stats?period=today").get_json()["totals"]["fines"], 6)
        self.assertEqual(self.client.get("/api/inspector/X001/stats").status_code, 404)

    def test_inspectors_cannot_use_the_manager_endpoint(self):
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertIn(self.client.get("/api/inspector/I001/stats").status_code, (401, 403))


class PagesTests(ApiTestCase):
    def test_stats_page_is_for_signed_in_inspectors(self):
        self.assertEqual(self.client.get("/inspect/stats").status_code, 302)
        self.login()
        self.assertEqual(self.client.get("/inspect/stats").status_code, 302)           # a manager has no field stats
        self.login("lior", role="inspector", inspector_id="I001")
        page = self.client.get("/inspect/stats")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"inspector-stats.js", page.data)

    def test_main_field_page_no_longer_carries_the_stats(self):
        self.login("lior", role="inspector", inspector_id="I001")
        html = self.client.get("/inspect").get_data(as_text=True)
        for gone in ('id="dayBtn"', 'id="todayRuns"', 'id="day"'):
            self.assertNotIn(gone, html)
        self.assertIn('href="/inspect/stats"', html)


class BreakTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login("lior", role="inspector", inspector_id="I001")

    def status(self, **body):
        return self.client.put("/api/me/status", json=body)

    def test_any_length_up_to_the_manager_cap(self):
        self.assertEqual(self.client.get("/api/me").get_json()["max_break_minutes"], 90)
        self.assertEqual(self.status(break_minutes=45, break_reason="lunch").status_code, 200)
        me = self.client.get("/api/me").get_json()
        self.assertEqual((me["on_break"], me["break_planned_minutes"], me["break_reason"]), (True, 45, "lunch"))
        self.assertLessEqual(abs(me["break_seconds_left"] - 45 * 60), 5)
        self.assertEqual(BreakLog.query.one().reason, "lunch")

    def test_limits(self):
        self.assertEqual(self.status(break_minutes=4).status_code, 400)
        self.assertEqual(self.status(break_minutes=91).status_code, 400)
        self.login()
        self.assertEqual(self.client.put("/api/team/settings", json={"max_break_minutes": 120}).status_code, 200)
        self.assertEqual(self.client.put("/api/team/settings", json={"max_break_minutes": 5}).status_code, 400)
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.status(break_minutes=110).status_code, 200)

    def test_extend_stays_within_the_cap(self):
        self.status(break_minutes=60)
        before = self.client.get("/api/me").get_json()["break_seconds_left"]
        self.assertEqual(self.status(break_extend=10).status_code, 200)
        self.assertGreater(self.client.get("/api/me").get_json()["break_seconds_left"], before + 500)
        self.assertEqual(self.status(break_extend=30).status_code, 400)      # 60 + 10 + 30 would pass the 90 minute cap
        self.assertEqual(self.status(break_extend=20).status_code, 200)      # exactly the cap
        self.assertEqual(self.status(break_extend=1).status_code, 400)

    def test_extend_needs_a_running_break(self):
        self.assertEqual(self.status(break_extend=10).status_code, 409)

    def test_a_break_closes_the_shift_and_coming_back_reopens_it(self):
        self.status(available=True)
        self.assertEqual(ShiftLog.query.filter_by(ended_at=None).count(), 1)
        self.status(break_minutes=15)
        self.assertEqual(ShiftLog.query.filter_by(ended_at=None).count(), 0)
        self.status(break_minutes=0)
        self.assertEqual(ShiftLog.query.filter_by(ended_at=None).count(), 1)
        self.assertIsNotNone(BreakLog.query.one().ended_at)

    def test_ending_the_shift_closes_it(self):
        self.status(available=True)
        self.status(available=False)
        self.assertEqual(ShiftLog.query.filter_by(ended_at=None).count(), 0)
        self.assertEqual(ShiftLog.query.count(), 1)


if __name__ == "__main__":
    unittest.main()


class ManagerViewTests(ApiTestCase):
    def test_admin_stats_carry_the_shift_and_break_logs(self):
        now = now_local()
        db.session.add_all([
            ShiftLog(inspector_id="I001", started_at=now - timedelta(hours=4), ended_at=now - timedelta(hours=2)),
            BreakLog(inspector_id="I001", started_at=now - timedelta(hours=2), planned_minutes=30, reason="lunch", ended_at=now - timedelta(hours=1, minutes=30)),
        ])
        db.session.commit()
        self.login()
        data = self.client.get("/api/inspector/I001/stats?period=week").get_json()
        self.assertEqual(len(data["shifts"]), 1)
        self.assertEqual(data["breaks"][0]["reason"], "lunch")
        # the inspector's own view does not carry the raw logs
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertNotIn("shifts", self.client.get("/api/me/stats").get_json())

    def test_people_table_sums_hours_per_inspector_for_own_team_only(self):
        now = now_local()
        db.session.add_all([
            finished("I001", 6, now),
            finished("X001", 50, now),
            ShiftLog(inspector_id="I001", started_at=now - timedelta(hours=3), ended_at=now - timedelta(hours=1)),
            BreakLog(inspector_id="I001", started_at=now - timedelta(hours=1), planned_minutes=30, ended_at=now - timedelta(minutes=30)),
        ])
        db.session.commit()
        self.login()
        yesterday = (now_local().date() - timedelta(days=1)).isoformat()
        data = self.client.get(f"/api/analytics/people?start={yesterday}").get_json()["people"]
        self.assertEqual({p["inspector_id"] for p in data}, {"I001", "I002"})
        lior = next(p for p in data if p["inspector_id"] == "I001")
        self.assertEqual((lior["fines"], lior["shift_hours"], lior["break_hours"], lior["fines_per_hour"]), (6, 2.0, 0.5, 3.0))
        self.assertEqual(self.client.get("/api/analytics/people?start=2026-02-01&end=2025-01-01").status_code, 400)
