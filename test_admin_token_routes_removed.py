"""P1/P2 regression: the unauthenticated POST /admin/add-tokens and
GET /_admin/init-daily-counter routes are gone. Nobody (anonymous, invalid
token, ordinary user, admin) can change an AskNow token balance -- their own
or another user's -- or create the daily_counter row through them, and the
legitimate neighbours (self-initialising daily horoscope rotation,
admin-guarded APIs, Firebase-guarded registration) still work.

LOCAL ONLY: real app + real models against a local `jyotishasha_local`
Postgres (DATABASE_URL must point at localhost/127.0.0.1 and that database,
or the script refuses to run). No Firebase, network or production data.

Run: python test_admin_token_routes_removed.py
"""
import os
import sys
import unittest
import uuid
from urllib.parse import urlparse

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_u = urlparse(os.environ.get("DATABASE_URL", ""))
if _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/jyotishasha_local":
    raise SystemExit("REFUSING TO RUN: test_admin_token_routes_removed.py needs DATABASE_URL = the local jyotishasha_local database.")
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")
ADMIN_ID, ORDINARY_ID = "990101", "990102"
os.environ["ADMIN_USER_IDS"] = ADMIN_ID
os.environ.pop("ADMIN_BRIDGE_KEY", None)

from flask_jwt_extended import create_access_token  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from modules.daily_counter.model import DailyCounter  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
import routes.daily_horoscope as daily_horoscope  # noqa: E402

REMOVED = ("/admin/add-tokens", "/_admin/init-daily-counter")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class RemovedAdminTokenRoutesTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.client = app.test_client()
        self.assertEqual(db.session.execute(db.text("select current_database()")).scalar(), "jyotishasha_local")
        marker = uuid.uuid4().hex[:10]
        self.victim = AppUser(firebase_uid=f"p5-victim-{marker}", name="Victim", asknow_tokens=3)
        self.attacker = AppUser(firebase_uid=f"p5-attacker-{marker}", name="Attacker", asknow_tokens=0)
        db.session.add_all([self.victim, self.attacker])
        db.session.commit()
        self.ids = (self.victim.id, self.attacker.id)

    def tearDown(self):
        db.session.rollback()
        AppUser.query.filter(AppUser.id.in_(self.ids)).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

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

    def counter_rows(self):
        db.session.expire_all()
        return DailyCounter.query.count()

    def test_routes_absent_from_url_map(self):
        rules = {rule.rule.rstrip("/") for rule in app.url_map.iter_rules()}
        for path in REMOVED:
            self.assertNotIn(path, rules)
        self.assertNotIn("routes_admin_tokens", app.blueprints)
        self.assertFalse(any(ep.startswith("routes_admin_tokens.") for ep in app.view_functions))

    def test_no_caller_can_reach_them(self):
        for who, headers in self.callers().items():
            for path in REMOVED + tuple(p + "/" for p in REMOVED):
                for method in METHODS:
                    with self.subTest(who=who, path=path, method=method):
                        r = self.client.open(path, method=method, headers=headers,
                                             json={"user_id": self.victim.id, "tokens": 1000})
                        self.assertEqual(r.status_code, 404)

    def test_no_one_can_change_any_token_balance(self):
        before = self.balances()
        for who, headers in self.callers().items():
            for target in self.ids:  # cross-user (victim) and self (attacker)
                for tokens in (1000, -3, "50"):
                    with self.subTest(who=who, target=target, tokens=tokens):
                        self.client.post("/admin/add-tokens", headers=headers,
                                         json={"user_id": target, "tokens": tokens})
        self.assertEqual(self.balances(), before)

    def test_init_daily_counter_cannot_create_state(self):
        DailyCounter.query.delete()
        db.session.commit()
        for who, headers in self.callers().items():
            self.client.get("/_admin/init-daily-counter", headers=headers)
        self.assertEqual(self.counter_rows(), 0)

    def test_daily_horoscope_initialises_and_rotates_itself(self):
        DailyCounter.query.delete()
        db.session.commit()
        daily_horoscope.ROTATION_CACHE = None
        daily_horoscope.ROTATION_DATE = None
        first = self.client.get("/api/daily-horoscope?sign=aries&lang=en")
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True)[:300])
        self.assertEqual(self.counter_rows(), 1)  # created on demand, no init route needed
        db.session.expire_all()
        after_first = DailyCounter.query.first().counter
        self.assertNotEqual(after_first, 0)  # advanced once
        second = self.client.get("/api/daily-horoscope?sign=leo&lang=hi")
        summary = self.client.get("/api/daily-horoscope-summary?lang=en")
        self.assertEqual((second.status_code, summary.status_code), (200, 200))
        db.session.expire_all()
        self.assertEqual(DailyCounter.query.first().counter, after_first)  # cached for the day

    def test_admin_guard_still_enforced_on_admin_api(self):
        self.assertEqual(self.client.get("/admin/api/users").status_code, 401)
        self.assertIn(self.client.get("/admin/api/users", headers={"Authorization": "Bearer not-a-real-token"}).status_code, (401, 422))
        self.assertEqual(self.client.get("/admin/api/users", headers=self.auth(ORDINARY_ID)).status_code, 403)
        self.assertEqual(self.client.get("/admin/api/users", headers=self.auth(ADMIN_ID)).status_code, 200)

    def test_firebase_registration_route_still_present_and_guarded(self):
        self.assertEqual(self.client.post("/api/auth/register", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/register", json={}, headers={"Authorization": "Bearer x"}).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
