"""Web Push: subscription handling and what gets sent, with the network call replaced."""
import unittest
from unittest.mock import patch

from app import config
from app.models import PushSubscription
from app.services import push
from tests.helpers import ApiTestCase

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "key", "auth": "secret"}}


class PushTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.keys = patch.multiple(config, VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv")
        self.keys.start()
        self.login("lior", role="inspector", inspector_id="I001")

    def tearDown(self):
        self.keys.stop()
        super().tearDown()

    def test_key_endpoint_reports_whether_push_is_set_up(self):
        self.assertEqual(self.client.get("/api/push/key").get_json(), {"enabled": True, "public_key": "pub"})
        with patch.object(config, "VAPID_PRIVATE_KEY", ""):
            self.assertFalse(self.client.get("/api/push/key").get_json()["enabled"])

    def test_subscribe_stores_one_row_per_device_and_rejects_junk(self):
        self.assertEqual(self.client.post("/api/push/subscribe", json={"subscription": SUB, "lang": "ru"}).status_code, 200)
        self.client.post("/api/push/subscribe", json={"subscription": SUB, "lang": "en"})
        rows = PushSubscription.query.all()
        self.assertEqual((len(rows), rows[0].lang), (1, "en"))
        for bad in ({"subscription": {"endpoint": "http://insecure", "keys": SUB["keys"]}}, {"subscription": {"endpoint": SUB["endpoint"]}}, {}):
            self.assertEqual(self.client.post("/api/push/subscribe", json=bad).status_code, 400)

    def test_an_offer_is_pushed_in_the_devices_language(self):
        self.client.post("/api/push/subscribe", json={"subscription": SUB, "lang": "ar"})
        sent = []
        with patch.object(push, "_send", side_effect=lambda subs, payload_for: sent.append(payload_for(subs[0]["lang"])) or []), \
                patch.object(push.threading.Thread, "start", lambda self: self.run()):
            push.notify_inspector("I001", "offer")
        self.assertEqual(sent[0]["tag"], "offer")
        self.assertEqual(sent[0]["title"], push.MESSAGES["offer"]["ar"][0])

    def test_gone_devices_are_forgotten(self):
        self.client.post("/api/push/subscribe", json={"subscription": SUB})
        with patch.object(push, "_send", return_value=[SUB["endpoint"]]), patch.object(push.threading.Thread, "start", lambda self: self.run()):
            push.notify_inspector("I001", "break")
        self.assertEqual(PushSubscription.query.count(), 0)

    def test_nothing_happens_without_keys(self):
        self.client.post("/api/push/subscribe", json={"subscription": SUB})
        with patch.object(config, "VAPID_PUBLIC_KEY", ""), patch.object(push, "_send") as send:
            push.notify_inspector("I001", "offer")
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
