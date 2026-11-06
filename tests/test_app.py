import time
import unittest
from unittest.mock import patch

from app import config, create_app
from app.extensions import db
from app.models import Fine, Inspector, InspectorRun, User
from app.seeds import bootstrap_database
from tests.helpers import ApiTestCase


def make_app(**overrides):
    return create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "BOOTSTRAP_DB": False,
                       "WARM_UP": False, "SECRET_KEY": "test", **overrides})


class FactoryTests(unittest.TestCase):
    def test_every_expected_route_is_registered(self):
        rules = {rule.rule for rule in make_app().url_map.iter_rules()}
        expected = {"/", "/login", "/signup", "/logout", "/admin", "/analytics", "/staff", "/profile", "/inspect",
                    "/api/login", "/api/register", "/api/logout", "/api/profile", "/api/staff", "/api/analytics",
                    "/api/assign_runs", "/api/inspector", "/api/inspector/<inspector_id>", "/api/find_best_trip",
                    "/api/health"}
        self.assertLessEqual(expected, rules)

    def test_overrides_win_and_cors_is_off_by_default(self):
        app = make_app(SECRET_KEY="custom")
        self.assertEqual(app.config["SECRET_KEY"], "custom")
        response = app.test_client().get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_cors_can_be_enabled_for_listed_origins_only(self):
        client = make_app(CORS_ORIGINS=["https://ok.example"]).test_client()
        allowed = client.get("/api/health", headers={"Origin": "https://ok.example"})
        denied = client.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertEqual(allowed.headers.get("Access-Control-Allow-Origin"), "https://ok.example")
        self.assertIsNone(denied.headers.get("Access-Control-Allow-Origin"))

    def test_session_cookie_settings(self):
        app = make_app()
        self.assertTrue(app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(app.config["SESSION_COOKIE_SAMESITE"], "Lax")

    def test_warm_up_builds_the_engine_in_the_background_only_when_enabled(self):
        with patch("app.services.routing.get_engine") as get_engine:
            make_app(WARM_UP=False)
            get_engine.assert_not_called()
            make_app(WARM_UP=True)
            for _ in range(100):
                if get_engine.called:
                    break
                time.sleep(0.02)
            get_engine.assert_called_once()

    def test_configuration_points_at_existing_data(self):
        self.assertTrue(config.GTFS_DIR.is_dir())
        self.assertTrue(config.FARE_EVASION_CSV.is_file())
        self.assertTrue(config.Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite:///"))


class PwaTests(ApiTestCase):
    def test_the_manifest_makes_the_field_app_installable(self):
        body = self.app.test_client().get("/manifest.webmanifest")
        self.assertEqual(body.mimetype, "application/manifest+json")
        data = body.get_json()
        self.assertEqual((data["start_url"], data["display"]), ("/inspect", "standalone"))
        sizes = {icon["sizes"] for icon in data["icons"]}
        self.assertLessEqual({"192x192", "512x512"}, sizes)
        for icon in data["icons"]:
            self.assertEqual(self.app.test_client().get(icon["src"]).status_code, 200, icon["src"])

    def test_the_service_worker_is_served_from_the_root_and_never_cached(self):
        response = self.app.test_client().get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", response.headers["Cache-Control"])
        self.assertIn(b"/api/", response.data)   # it must know to leave the API alone
        response.close()

    def test_the_inspector_page_links_the_manifest(self):
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertIn(b'rel="manifest"', self.client.get("/inspect").data)


class PageTests(ApiTestCase):
    def test_public_pages_render(self):
        for url in ("/login", "/signup"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_protected_pages_redirect_to_login(self):
        for url in ("/admin", "/analytics", "/staff", "/profile", "/inspect"):
            response = self.client.get(url)
            self.assertEqual((response.status_code, response.headers["Location"]), (302, "/login"), url)
        self.assertEqual(self.client.get("/").headers["Location"], "/login")

    def test_admin_pages_render_for_admins(self):
        self.login()
        for url in ("/admin", "/analytics", "/staff", "/profile"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/").headers["Location"], "/admin")

    def test_nav_is_rendered_on_the_server_with_greeting_and_active_link(self):
        self.login()
        staff = self.client.get("/staff").get_data(as_text=True)
        self.assertIn("<bdi>admin</bdi>", staff)
        self.assertRegex(staff, r'<a href="/staff" aria-current="page">')
        self.assertNotRegex(staff, r'<a href="/admin" aria-current="page">')

    def test_log_out_link_logs_out(self):
        self.login()
        html = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('<a href="/logout">', html)
        self.assertNotIn('href="/signup"', html)

    def test_nav_links_depend_on_role(self):
        self.login()
        admin_nav = self.client.get("/profile").get_data(as_text=True)
        for href in ("/analytics", "/admin", "/staff", "/profile", "/logout"):
            self.assertIn(f'<a href="{href}"', admin_nav)
        self.assertNotIn('<a href="/inspect"', admin_nav)

        inspector = self.app.test_client()
        with inspector.session_transaction() as sess:
            sess.update(user="lior", role="inspector", inspector_id="I001")
        inspector_nav = inspector.get("/profile").get_data(as_text=True)
        for href in ("/inspect", "/profile", "/logout"):
            self.assertIn(f'<a href="{href}"', inspector_nav)
        for href in ("/analytics", "/admin", "/staff"):
            self.assertNotIn(f'<a href="{href}"', inspector_nav)

    def test_unknown_pages_get_a_friendly_page_and_unknown_api_paths_json(self):
        page = self.client.get("/no-such-page")
        self.assertEqual(page.status_code, 404)
        self.assertIn('data-i18n="e.404.title"', page.get_data(as_text=True))
        api = self.client.get("/api/no-such-endpoint")
        self.assertEqual((api.status_code, api.get_json()), (404, {"error": "not found"}))

    def test_inspector_page_renders_for_inspectors_only(self):
        self.login("lior", role="inspector", inspector_id="I001")
        self.assertEqual(self.client.get("/inspect").status_code, 200)
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_inspector_page_no_longer_downloads_map_data(self):
        self.login("lior", role="inspector", inspector_id="I001")
        html = self.client.get("/inspect").get_data(as_text=True)
        for needle in ("stop_shape_map.json", "shapes.geojson", "stops.geojson"):
            self.assertNotIn(needle, html)

    def test_logout_page_redirects(self):
        self.login()
        self.assertEqual(self.client.get("/logout").headers["Location"], "/login")
        self.assertEqual(self.client.get("/staff").status_code, 302)

    def test_static_assets_are_served_and_data_files_are_not(self):
        for url in ("/static/img/INSPECTRA_NEW.png", "/static/img/bus-stop.png"):
            with self.client.get(url) as response:
                self.assertEqual(response.status_code, 200, url)
        self.assertEqual(self.client.get("/static/stop_shape_map.json").status_code, 404)
        self.assertEqual(self.client.get("/static/routes_with_avgs.csv").status_code, 404)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.ctx = make_app().app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()

    def test_creates_tables_and_a_single_admin(self):
        bootstrap_database({"ADMIN_PASSWORD": "s3cret", "SEED_DEMO_DATA": False})
        bootstrap_database({"ADMIN_PASSWORD": "other", "SEED_DEMO_DATA": False})
        admins = User.query.filter_by(username="admin").all()
        self.assertEqual(len(admins), 1)
        self.assertTrue(admins[0].check_password("s3cret"))
        self.assertTrue(admins[0].manager_code)

    def test_demo_data_is_seeded_once_and_can_be_disabled(self):
        bootstrap_database({"ADMIN_PASSWORD": "x", "SEED_DEMO_DATA": False})
        self.assertEqual(Inspector.query.count(), 0)
        bootstrap_database({"ADMIN_PASSWORD": "x", "SEED_DEMO_DATA": True})
        counts = (Inspector.query.count(), InspectorRun.query.count(), Fine.query.count())
        self.assertGreater(counts[0], 0)
        bootstrap_database({"ADMIN_PASSWORD": "x", "SEED_DEMO_DATA": True})
        self.assertEqual((Inspector.query.count(), InspectorRun.query.count(), Fine.query.count()), counts)

    def test_a_failing_database_does_not_stop_startup(self):
        with patch("app.seeds.db.create_all", side_effect=RuntimeError("disk full")):
            bootstrap_database({"ADMIN_PASSWORD": "x", "SEED_DEMO_DATA": True})  # must not raise


if __name__ == "__main__":
    unittest.main()
