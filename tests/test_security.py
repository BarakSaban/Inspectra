"""Account and request security: session revocation, same-origin writes, approvals, password rules, headers."""
import unittest

from app.extensions import db
from app.models import Inspector, User
from tests.helpers import ADMIN_CODE, ApiTestCase

GOOD = "pw123456"


class SessionRevocationTests(ApiTestCase):
    def _login(self, username):
        client = self.app.test_client()
        self.assertEqual(client.post("/api/login", json={"username": username, "password": GOOD}).status_code, 200)
        return client

    def test_resetting_a_password_ends_the_open_session(self):
        phone = self._login("lior")
        self.assertEqual(phone.get("/api/me").status_code, 200)
        admin = self._login("admin")
        self.assertEqual(admin.post("/api/inspector/I001/reset_password").status_code, 200)
        self.assertEqual(phone.get("/api/me").status_code, 401)

    def test_a_temporary_password_must_be_replaced_before_anything_else(self):
        admin = self._login("admin")
        temp = admin.post("/api/inspector/I001/reset_password").get_json()["temporary_password"]
        phone = self.app.test_client()
        login = phone.post("/api/login", json={"username": "lior", "password": temp})
        self.assertEqual(login.get_json()["redirect"], "/profile")
        self.assertEqual(phone.get("/api/me").status_code, 403)
        self.assertEqual(phone.get("/inspect").headers["Location"], "/profile")
        self.assertEqual(phone.post("/api/profile", json={"password": "short"}).status_code, 400)
        self.assertEqual(phone.post("/api/profile", json={"password": "a-new-secret-1"}).status_code, 200)
        self.assertEqual(phone.get("/api/me").status_code, 200)

    def test_a_deactivated_inspector_is_logged_out_and_cannot_log_back_in(self):
        phone = self._login("lior")
        db.session.add(Inspector(inspector_id="I001-h", name="x"))   # history so that deleting deactivates
        from app.models import Fine
        db.session.add(Fine(inspector_id="I001", trip_id="t", stop_id="s", amount=100))
        db.session.commit()
        admin = self._login("admin")
        self.assertTrue(admin.delete("/api/inspector/I001").get_json()["deactivated"])
        self.assertEqual(phone.get("/api/me").status_code, 401)
        again = self.app.test_client().post("/api/login", json={"username": "lior", "password": GOOD})
        self.assertEqual(again.status_code, 403)

    def test_changing_a_password_needs_the_current_one(self):
        phone = self._login("lior")
        self.assertEqual(phone.post("/api/profile", json={"password": "another-pass-1"}).status_code, 400)
        self.assertEqual(phone.post("/api/profile", json={"password": "another-pass-1", "current_password": "nope"}).status_code, 400)
        self.assertEqual(phone.post("/api/profile", json={"password": "another-pass-1", "current_password": GOOD}).status_code, 200)
        self.assertEqual(phone.get("/api/me").status_code, 200)   # this session stays signed in


class ManagerApprovalTests(ApiTestCase):
    def test_a_new_manager_cannot_log_in_until_approved(self):
        client = self.app.test_client()
        registered = client.post("/api/register", json={"name": "New Boss", "email": "nb@x.io", "password": GOOD, "role": "admin"}).get_json()
        self.assertTrue(registered["pending"])
        self.assertEqual(client.get("/api/staff").status_code, 401)
        self.assertEqual(client.post("/api/login", json={"username": "nb@x.io", "password": GOOD}).status_code, 403)
        User.query.filter_by(username="nb@x.io").one().approved = True
        db.session.commit()
        self.assertEqual(client.post("/api/login", json={"username": "nb@x.io", "password": GOOD}).status_code, 200)


class RequestGuardTests(ApiTestCase):
    def test_writes_from_another_site_are_refused(self):
        self.login()
        refused = self.client.post("/api/logout", headers={"Origin": "https://evil.example"})
        self.assertEqual(refused.status_code, 403)
        ok = self.client.post("/api/logout", headers={"Origin": "http://localhost"})
        self.assertEqual(ok.status_code, 200)

    def test_logout_is_post_only(self):
        self.assertEqual(self.client.get("/api/logout").status_code, 405)
        self.assertEqual(self.client.get("/api/logout").get_json()["error"], "method not allowed")

    def test_short_passwords_and_bad_input_are_rejected(self):
        for body in ({"name": "A", "email": "a@x.io", "password": "short", "role": "inspector"},
                     {"name": "A", "email": "a@x.io", "password": "x" * 200, "role": "inspector"},
                     {"name": ["list"], "password": GOOD, "role": "inspector"}):
            self.assertEqual(self.client.post("/api/register", json=body).status_code, 400, body)

    def test_pages_carry_security_headers_and_api_is_not_cached(self):
        page = self.client.get("/login")
        self.assertEqual(page.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", page.headers["Content-Security-Policy"])
        self.login()
        self.assertEqual(self.client.get("/api/staff").headers["Cache-Control"], "no-store")

    def test_inspectors_do_not_receive_the_manager_code(self):
        self.login("lior", role="inspector", admin_code=ADMIN_CODE, inspector_id="I001")
        self.assertIsNone(self.client.get("/api/profile").get_json()["manager_code"])


if __name__ == "__main__":
    unittest.main()


class OwnerToolsTests(ApiTestCase):
    def test_only_the_owner_decides_on_pending_managers(self):
        db.session.add(User(username="nb@x.io", role="admin", manager_code="NEWBOS", full_name="NB", approved=False, password_hash=User.query.first().password_hash))
        db.session.commit()
        self.login("admin2", admin_code="OTHER2")
        self.assertEqual(self.client.get("/api/approvals").get_json(), {"owner": False, "pending": []})
        self.assertEqual(self.client.post("/api/approvals/nb@x.io/approve").status_code, 403)
        self.login("admin")
        self.assertEqual([p["username"] for p in self.client.get("/api/approvals").get_json()["pending"]], ["nb@x.io"])
        self.assertEqual(self.client.post("/api/approvals/nb@x.io/approve").status_code, 200)
        self.assertTrue(User.query.filter_by(username="nb@x.io").one().approved)

    def test_rotating_the_code_moves_the_whole_team(self):
        self.login("admin")
        new = self.client.post("/api/admin/code/rotate").get_json()["manager_code"]
        self.assertNotEqual(new, ADMIN_CODE)
        self.assertEqual(User.query.filter_by(username="lior").one().manager_code, new)
        self.assertEqual(self.client.get("/api/staff").status_code, 200)
        old = self.app.test_client().post("/api/register", json={"name": "Late", "phone": "I999", "password": "pw123456", "role": "inspector", "manager_code": ADMIN_CODE})
        self.assertEqual(old.status_code, 400)


class InputValidationTests(ApiTestCase):
    def test_bad_values_become_400_not_500(self):
        self.login()
        self.assertEqual(self.client.put("/api/inspector/I001", json={"available": "false"}).status_code, 400)
        self.assertEqual(self.client.get("/api/audit?limit=abc").status_code, 200)
        long_name = self.client.put("/api/inspector/I001", json={"name": "n" * 500}).get_json()["name"]
        self.assertEqual(len(long_name), 120)
