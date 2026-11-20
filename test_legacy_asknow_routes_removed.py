"""P1 regression: the deprecated, unauthenticated /asknow/* routes
(order, verify, use-token, tokens/<id>) are gone. Nobody -- anonymous,
invalid token, ordinary user, admin -- can create Razorpay orders, fake a
"paid" asknow_orders row, change anyone's token balance, or read another
user's balance through them. The live, JWT-guarded chat-pack purchase
routes stay registered and guarded.

LOCAL ONLY: real app + real models against a local `jyotishasha_local`
Postgres (DATABASE_URL must point at localhost/127.0.0.1 and that database,
or the script refuses to run). Razorpay is mocked and all outbound HTTP is
blocked, so no real order or payment can ever be created. No Firebase,
network or production data.

Run: python test_legacy_asknow_routes_removed.py
"""
import os
import sys
import unittest
import uuid
from unittest import mock
from urllib.parse import urlparse

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_u = urlparse(os.environ.get("DATABASE_URL", ""))
if _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/jyotishasha_local":
    raise SystemExit("REFUSING TO RUN: test_legacy_asknow_routes_removed.py needs DATABASE_URL = the local jyotishasha_local database.")
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_local_unused"
os.environ["RAZORPAY_KEY_SECRET"] = "local-test-unused"
ADMIN_ID, ORDINARY_ID = "990201", "990202"
os.environ["ADMIN_USER_IDS"] = ADMIN_ID
os.environ.pop("ADMIN_BRIDGE_KEY", None)

from flask_jwt_extended import create_access_token  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from modules.models_asknow import AskNowOrder  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
import modules.services.asknow_service as asknow_service  # noqa: E402

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _no_network(*args, **kwargs):
    raise AssertionError("outbound HTTP attempted during a local-only test")


class RemovedLegacyAskNowRoutesTests(unittest.TestCase):
    def setUp(self):
        # Never reach Razorpay: mock the client the legacy service uses, and
        # fail loudly on any outbound HTTP at all.
        self.rzp = mock.MagicMock()
        self.rzp.order.create.side_effect = lambda payload: {"id": f"order_fake_{uuid.uuid4().hex[:12]}"}
        self.patches = [
            mock.patch.object(asknow_service, "razorpay_client", self.rzp),
            mock.patch("requests.adapters.HTTPAdapter.send", _no_network),
        ]
        for p in self.patches:
            p.start()
        self.ctx = app.app_context()
        self.ctx.push()
        self.client = app.test_client()
        self.assertEqual(db.session.execute(db.text("select current_database()")).scalar(), "jyotishasha_local")
        marker = uuid.uuid4().hex[:10]
        self.victim = AppUser(firebase_uid=f"p6-victim-{marker}", name="Victim", asknow_tokens=3)
        self.attacker = AppUser(firebase_uid=f"p6-attacker-{marker}", name="Attacker", asknow_tokens=0)
        db.session.add_all([self.victim, self.attacker])
        db.session.commit()
        self.ids = (self.victim.id, self.attacker.id)
        self.paths = (
            "/asknow/order", "/asknow/verify", "/asknow/use-token",
            f"/asknow/tokens/{self.victim.id}", f"/asknow/tokens/{self.attacker.id}",
        )

    def tearDown(self):
        db.session.rollback()
        AskNowOrder.query.filter(AskNowOrder.user_id.in_(self.ids)).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.in_(self.ids)).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()
        for p in reversed(self.patches):
            p.stop()

    def auth(self, identity):
        return {"Authorization": f"Bearer {create_access_token(identity=str(identity))}"}

    def callers(self):
        return {
            "anonymous": {},
            "invalid token": {"Authorization": "Bearer not-a-real-firebase-or-jwt-token"},
            "ordinary user": self.auth(ORDINARY_ID),
            "attacker (own JWT)": self.auth(self.attacker.id),
            "admin": self.auth(ADMIN_ID),
        }

    def balances(self):
        db.session.expire_all()
        return tuple(db.session.get(AppUser, i).asknow_tokens for i in self.ids)

    def orders(self):
        db.session.expire_all()
        return AskNowOrder.query.filter(AskNowOrder.user_id.in_(self.ids)).count()

    def test_routes_absent_from_url_map(self):
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertFalse([r for r in rules if r.startswith("/asknow")], rules)
        self.assertNotIn("routes_asknow", app.blueprints)
        self.assertFalse(any(ep.startswith("routes_asknow.") for ep in app.view_functions))

    def test_no_caller_can_reach_them(self):
        for who, headers in self.callers().items():
            for path in self.paths + tuple(p + "/" for p in self.paths):
                for method in METHODS:
                    with self.subTest(who=who, path=path, method=method):
                        r = self.client.open(path, method=method, headers=headers,
                                             json={"user_id": self.victim.id, "order_id": "order_x", "payment_id": "pay_x"})
                        self.assertEqual(r.status_code, 404)
        self.rzp.order.create.assert_not_called()

    def test_no_fake_paid_order_and_no_token_change(self):
        before = self.balances()
        for who, headers in self.callers().items():
            for target in self.ids:  # cross-user (victim) and self (attacker)
                with self.subTest(who=who, target=target):
                    r = self.client.post("/asknow/order", headers=headers, json={"user_id": target})
                    order_id = ((r.get_json(silent=True) or {}).get("order") or {}).get("razorpay_order_id", "order_guess")
                    self.client.post("/asknow/verify", headers=headers,
                                     json={"user_id": target, "order_id": order_id, "payment_id": "pay_FAKE_no_signature"})
                    self.client.post("/asknow/use-token", headers=headers, json={"user_id": target})
        self.assertEqual(self.orders(), 0)  # no pending or "success" legacy orders
        self.assertEqual(self.balances(), before)
        self.rzp.order.create.assert_not_called()  # no Razorpay order attempted

    def test_balance_not_disclosed(self):
        for who, headers in self.callers().items():
            for target in self.ids:
                with self.subTest(who=who, target=target):
                    r = self.client.get(f"/asknow/tokens/{target}", headers=headers)
                    self.assertEqual(r.status_code, 404)
                    self.assertNotIn("asknow_tokens", r.get_data(as_text=True))

    def test_live_chat_pack_purchase_routes_still_registered_and_guarded(self):
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        for path in ("/api/chat/pack/order", "/api/chat/pack/verify", "/api/chatpack/verify",
                     "/api/chat/pack/google/verify", "/api/chat/pack/status", "/api/chat/free"):
            self.assertIn(path, rules)
        for path in ("/api/chat/pack/order", "/api/chat/pack/verify", "/api/chatpack/verify", "/api/chat/pack/google/verify"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json={}).status_code, 401)
        self.rzp.order.create.assert_not_called()

    def test_admin_guard_and_registration_unchanged(self):
        self.assertEqual(self.client.get("/admin/api/users").status_code, 401)
        self.assertEqual(self.client.get("/admin/api/users", headers=self.auth(ORDINARY_ID)).status_code, 403)
        self.assertEqual(self.client.get("/admin/api/users", headers=self.auth(ADMIN_ID)).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/register", json={}).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
