"""Runs stay consistent when two requests race: one winner, no double fines, never two active runs."""
import unittest
import unittest.mock

from sqlalchemy import text
from sqlalchemy.orm.attributes import set_committed_value

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun
from app.services import runs
from tests.helpers import ApiTestCase


class RunRaceTests(ApiTestCase):
    def test_a_double_tap_on_complete_records_the_fines_once(self):
        run = runs.start_run("I001", trip_id="T1", stop_id="S1", potential_fines=5)
        stale_copy = db.session.get(InspectorRun, run.id)
        db.session.expire_all()
        runs.complete_run(run, 3)
        set_committed_value(stale_copy, "status", "accepted")   # what a second request that read the row earlier still believes
        with self.assertRaises(runs.RunError) as caught:
            runs.complete_run(stale_copy, 3)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(Fine.query.filter_by(inspector_id="I001").count(), 3)
        self.assertEqual(Inspector.query.filter_by(inspector_id="I001").one().total_fines, 3)

    def test_the_database_refuses_a_second_active_run(self):
        runs.create_run(inspector_id="I001", trip_id="T1", status="assigned")
        db.session.commit()
        with self.assertRaises(runs.RunError) as caught:
            runs.create_run(inspector_id="I001", trip_id="T2", status="accepted")
        self.assertEqual(caught.exception.status, 409)
        runs.create_run(inspector_id="I002", trip_id="T3", status="assigned")   # other inspectors are unaffected
        db.session.commit()
        self.assertEqual(InspectorRun.query.filter_by(inspector_id="I001").count(), 1)

    def test_a_finished_run_does_not_block_the_next_one(self):
        first = runs.start_run("I001", trip_id="T1", stop_id="S1")
        runs.complete_run(first, 0)
        self.assertEqual(runs.start_run("I001", trip_id="T2", stop_id="S2").status, "accepted")

    def test_cancelling_twice_is_a_conflict_not_a_second_write(self):
        run = runs.start_run("I001", trip_id="T1", stop_id="S1")
        runs.cancel_run(run)
        with self.assertRaises(runs.RunError):
            runs.cancel_run(run)


class DatabaseSettingsTests(ApiTestCase):
    def test_links_between_tables_are_enforced_and_hot_columns_indexed(self):
        self.assertEqual(db.session.execute(text("PRAGMA foreign_keys")).scalar(), 1)
        names = {row[1] for row in db.session.execute(text("PRAGMA index_list('inspector_runs')"))}
        self.assertIn("uq_runs_one_active_per_inspector", names)
        fines = {row[1] for row in db.session.execute(text("PRAGMA index_list('fines')"))}
        self.assertIn("ix_fines_inspector_time", fines)


if __name__ == "__main__":
    unittest.main()


class StreamAndCacheTests(ApiTestCase):
    def test_a_person_can_only_hold_a_few_event_streams(self):
        from app.api import events
        self.login()
        with unittest.mock.patch.dict(events._open_streams, {"admin": events.MAX_STREAMS_PER_USER}):
            self.assertEqual(self.client.get("/api/events?max_seconds=0.1").status_code, 429)

    def test_the_live_cache_stays_bounded(self):
        from app.services import siri
        with unittest.mock.patch.object(siri, "MAX_CACHE_ENTRIES", 5):
            for n in range(20):
                siri._remember(f"u{n}", {"timestamp": siri._utc_now(), "visits": []})
            self.assertLessEqual(len(siri._LIVE_CACHE), 5)
