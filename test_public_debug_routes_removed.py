"""P1 regression: the unauthenticated /add_user and /_debug/run-daily routes
are gone, nobody (anonymous, bad token, ordinary user, admin) can reach them,
and the legitimate neighbours -- the self-rotating daily horoscope and
admin-guarded APIs -- still work.

LOCAL ONLY: real app + real models against a local `jyotishasha_local`
Postgres (DATABASE_URL must point at localhost/127.0.0.1 and that database,
or the script refuses to run). No Firebase, network or production data.

Run: python test_public_debug_routes_removed.py
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
    raise SystemExit("REFUSING TO RUN: test_public_debug_routes_removed.py needs DATABASE_URL = the local jyotishasha_local database.")
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")
ADMIN_ID, ORDINARY_ID = "990001", "990002"
os.environ["ADMIN_USER_IDS"] = ADMIN_ID
os.environ.pop("ADMIN_BRIDGE_KEY", None)

from flask_jwt_extended import create_access_token  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from modules.auth.models import User  # noqa: E402
from modules.daily_counter.model import DailyCounter  # noqa: E402
import routes.daily_horoscope as daily_horoscope  # noqa: E402

REMOVED = ("/add_user", "/_debug/run-daily")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class RemovedPublicRoutesTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.client = app.test_client()
        self.assertEqual(db.session.execute(db.text("select current_database()")).scalar(), "jyotishasha_local")
        self.marker = f"p1routes-{uuid.uuid4().hex[:10]}"

    def tearDown(self):
        db.session.rollback()
        User.query.filter(User.email.like(f"{self.marker}%")).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def auth(self, identity):
        return {"Authorization": f"Bearer {create_access_token(identity=identity)}"}

    def callers(self):
        return {
            "anonymous": {},
            "invalid token": {"Authorization": "Bearer not-a-real-token"},
            "ordinary user": self.auth(ORDINARY_ID),
            "admin": self.auth(ADMIN_ID),
        }

    def counter(self):
        db.session.expire_all()
        row = DailyCounter.query.first()
        return None if row is None else row.counter

    def test_routes_absent_from_url_map(self):
        rules = {rule.rule.rstrip("/") for rule in app.url_map.iter_rules()}
        for path in REMOVED:
            self.assertNotIn(path, rules)
        self.assertNotIn("add_user", app.view_functions)
        self.assertNotIn("debug_run_daily", app.view_functions)

    def test_no_caller_can_reach_them(self):
        for who, headers in self.callers().items():
            for path in REMOVED + tuple(p + "/" for p in REMOVED):
                for method in METHODS:
                    with self.subTest(who=who, path=path, method=method):
                        r = self.client.open(path, method=method, headers=headers,
                                             json={"name": "Spam", "email": f"{self.marker}@example.test"})
                        self.assertEqual(r.status_code, 404)

    def test_add_user_no_longer_creates_rows(self):
        before = User.query.count()
        for who, headers in self.callers().items():
            self.client.post("/add_user", headers=headers, json={"name": who, "email": f"{self.marker}-{who.replace(' ', '')}@example.test"})
        self.assertEqual(User.query.count(), before)
        self.assertEqual(User.query.filter(User.email.like(f"{self.marker}%")).count(), 0)

    def test_run_daily_cannot_advance_the_rotation(self):
        before = self.counter()
        for who, headers in self.callers().items():
            self.client.get("/_debug/run-daily", headers=headers)
        self.assertEqual(self.counter(), before)

    def test_daily_horoscope_still_rotates_itself_once_per_day(self):
        daily_horoscope.ROTATION_CACHE = None
        daily_horoscope.ROTATION_DATE = None
        first = self.client.get("/api/daily-horoscope?sign=aries&lang=en")
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True)[:300])
        after_first = self.counter()
        self.assertIsNotNone(after_first)
        second = self.client.get("/api/daily-horoscope?sign=leo&lang=hi")
        summary = self.client.get("/api/daily-horoscope-summary?lang=en")
        self.assertEqual((second.status_code, summary.status_code), (200, 200))
        self.assertEqual(self.counter(), after_first)  # cached: one advance per day, not per request

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
