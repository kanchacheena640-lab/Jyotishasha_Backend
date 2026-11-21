"""PR #8 security remediation regression tests.

A. /api/chat/reward: JWT always required; authenticated -> 403
   reward_unavailable; no balance, pack or quota is touched.
B. /api/auth/register never links a Google identity by email to an account
   that carries a password credential (409, row untouched); every other
   linking path is unchanged.
C. /requirements and /api/free-consult are gone; /api/smartchat is kept but
   rate-limited per client IP before any OpenAI call.
D. Warn-only JWT_SECRET_KEY / SECRET_KEY validation: logs names and reasons
   only, never values; never blocks; never runs for scripts that only import
   the app.
E. Ask Now observability: unauthenticated requests are logged (route, time,
   mode, outcome) without tokens, ids or payloads, and de-duplicated.

LOCAL ONLY: real app + real models against a local `jyotishasha_local`
Postgres (DATABASE_URL must point at localhost/127.0.0.1 and that database,
or the script refuses to run). Firebase, OpenAI and the chat engine are
mocked; no network, no production data.

Run: python test_pr8_security_remediation.py
"""
import logging
import os
import subprocess
import sys
import unittest
import uuid
from datetime import datetime
from unittest import mock
from urllib.parse import urlparse

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_u = urlparse(os.environ.get("DATABASE_URL", ""))
if _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/jyotishasha_local":
    raise SystemExit("REFUSING TO RUN: test_pr8_security_remediation.py needs DATABASE_URL = the local jyotishasha_local database.")
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")
os.environ.pop("REDIS_URL", None)  # limiter uses its in-process fallback

from flask_jwt_extended import create_access_token  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from modules.auth.models import User  # noqa: E402
from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.security import secret_validation  # noqa: E402
import routes.routes_chat as routes_chat  # noqa: E402
import routes.routes_smartchat as routes_smartchat  # noqa: E402

BIRTH = {"name": "A", "dob": "1990-01-01", "tob": "10:00", "pob": "Delhi", "lat": 28.6, "lng": 77.2, "tz": "+05:30"}


class _Base(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.client = app.test_client()
        self.assertEqual(db.session.execute(db.text("select current_database()")).scalar(), "jyotishasha_local")
        self.tag = uuid.uuid4().hex[:10]
        self.user_ids, self.profile_ids = [], []

    def tearDown(self):
        db.session.rollback()
        if self.user_ids:
            ChatPack.query.filter(ChatPack.user_id.in_(self.user_ids)).delete(synchronize_session=False)
            User.query.filter(User.id.in_(self.user_ids)).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.firebase_uid.like(f"%{self.tag}%")).delete(synchronize_session=False)
        User.query.filter(User.email.like(f"%{self.tag}%")).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def make_user(self, **kw):
        u = User(email=kw.pop("email", f"u-{uuid.uuid4().hex[:6]}-{self.tag}@example.test"), **kw)
        db.session.add(u)
        db.session.commit()
        self.user_ids.append(u.id)
        return u

    def auth(self, user_id):
        return {"Authorization": f"Bearer {create_access_token(identity=str(user_id))}"}


# --------------------------------------------------------------------------- A
class RewardOnHoldTests(_Base):
    def setUp(self):
        super().setUp()
        self.user = self.make_user(provider="firebase", firebase_uid=f"fb-r-{self.tag}")
        db.session.add(ChatPack(user_id=self.user.id, amount=51, questions_total=8, questions_used=2,
                                status="success", razorpay_order_id=f"order_{self.tag}",
                                razorpay_payment_id=f"pay_{self.tag}", verified_at=datetime.utcnow()))
        db.session.commit()

    def packs(self):
        db.session.expire_all()
        return [(p.questions_total, p.questions_used) for p in ChatPack.query.filter_by(user_id=self.user.id)]

    def test_missing_jwt_is_401_with_flag_on_and_off(self):
        for flag in ("1", ""):
            with self.subTest(flag=flag), mock.patch.dict(os.environ, {"ASKNOW_JWT_ENFORCEMENT": flag}):
                r = self.client.post("/api/chat/reward", json={"user_id": self.user.id})
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.get_json(), {"msg": "Missing Authorization Header"})
        self.assertEqual(self.packs(), [(8, 2)])

    def test_invalid_jwt_rejected(self):
        r = self.client.post("/api/chat/reward", json={}, headers={"Authorization": "Bearer not-a-jwt"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.packs(), [(8, 2)])

    def test_authenticated_gets_403_and_nothing_changes(self):
        for _ in range(3):
            r = self.client.post("/api/chat/reward", json={}, headers=self.auth(self.user.id))
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.get_json()["error"], "reward_unavailable")
            self.assertIs(r.get_json()["success"], False)
        self.assertEqual(self.packs(), [(8, 2)])  # no question granted, nothing consumed

    def test_user_without_pack_gets_no_mini_pack(self):
        other = self.make_user(provider="firebase", firebase_uid=f"fb-r2-{self.tag}")
        r = self.client.post("/api/chat/reward", json={}, headers=self.auth(other.id))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(ChatPack.query.filter_by(user_id=other.id).count(), 0)


# --------------------------------------------------------------------------- B
class AccountLinkGuardTests(_Base):
    def register(self, uid, email):
        decoded = {"uid": uid, "email": email, "email_verified": True, "name": "Owner"}
        with mock.patch("routes.routes_auth.firebase_auth.verify_id_token", return_value=decoded):
            return self.client.post("/api/auth/register", headers={"Authorization": "Bearer g"}, json={})

    def test_password_account_is_never_linked_by_email(self):
        email = f"victim-{self.tag}@example.test"
        squat = self.make_user(email=email, provider="password")
        squat.set_password("attacker-pass-123")
        db.session.commit()
        before = (squat.firebase_uid, squat.provider, squat.password_hash)
        r = self.register(f"fb-owner-{self.tag}", email)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error"], "account_link_conflict")
        db.session.expire_all()
        row = db.session.get(User, squat.id)
        self.assertEqual((row.firebase_uid, row.provider, row.password_hash), before)  # untouched
        self.assertEqual(User.query.filter_by(email=email).count(), 1)  # no duplicate created

    def test_attacker_tokens_never_reach_the_owner_profile(self):
        email = f"victim2-{self.tag}@example.test"
        squat = self.make_user(email=email, provider="password")
        squat.set_password("attacker-pass-123")
        db.session.commit()
        attacker_headers = self.auth(squat.id)
        self.assertEqual(self.register(f"fb-owner2-{self.tag}", email).status_code, 409)
        owner_profile = AppUser(firebase_uid=f"fb-owner2-{self.tag}", name="Owner", dob="1991-02-03")
        db.session.add(owner_profile)
        db.session.commit()
        r = self.client.get(f"/users/{owner_profile.id}", headers=attacker_headers)
        self.assertEqual(r.status_code, 403)

    def test_new_google_user_created(self):
        email = f"new-{self.tag}@example.test"
        r = self.register(f"fb-new-{self.tag}", email)
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.get_json()["new"], True)

    def test_returning_google_user_same_uid(self):
        u = self.make_user(provider="firebase", firebase_uid=f"fb-ret-{self.tag}")
        r = self.register(f"fb-ret-{self.tag}", u.email)
        self.assertEqual((r.status_code, r.get_json()["user_id"], r.get_json()["new"]), (200, u.id, False))

    def test_google_account_relinks_with_new_uid_as_before(self):
        u = self.make_user(provider="firebase", firebase_uid=f"fb-old-{self.tag}")
        db.session.add(AppUser(firebase_uid=f"fb-old-{self.tag}", name="Kept", dob="1980-01-01"))
        db.session.commit()
        r = self.register(f"fb-renewed-{self.tag}", u.email)
        self.assertEqual((r.status_code, r.get_json()["user_id"]), (200, u.id))
        db.session.expire_all()
        self.assertEqual(db.session.get(User, u.id).firebase_uid, f"fb-renewed-{self.tag}")
        self.assertEqual(AppUser.query.filter_by(firebase_uid=f"fb-renewed-{self.tag}").first().dob, "1980-01-01")

    def test_legacy_row_with_default_provider_but_no_password_still_links(self):
        # users.provider defaults to "password"; rows created by old code paths
        # carry it without any password. Those must keep linking.
        u = self.make_user(provider="password", firebase_uid=None)
        self.assertIsNone(u.password_hash)
        r = self.register(f"fb-legacy-{self.tag}", u.email)
        self.assertEqual((r.status_code, r.get_json()["user_id"]), (200, u.id))

    def test_missing_or_invalid_firebase_token_still_401(self):
        self.assertEqual(self.client.post("/api/auth/register", json={}).status_code, 401)


# --------------------------------------------------------------------------- C
class PublicOpenAIRoutesTests(_Base):
    def test_removed_routes_are_gone(self):
        rules = {r.rule for r in app.url_map.iter_rules()}
        for path in ("/requirements", "/api/free-consult"):
            self.assertNotIn(path, rules)
            for method in ("GET", "POST"):
                self.assertEqual(self.client.open(path, method=method, json={"question": "q", "birth": BIRTH}).status_code, 404)
        self.assertNotIn("routes_free_consult", app.blueprints)

    def test_smartchat_still_works_then_rate_limits_before_openai(self):
        ip = f"203.0.113.{int(self.tag[:2], 16) % 250}"
        headers = {"X-Forwarded-For": ip}
        with mock.patch.object(routes_smartchat, "run_smartchat", return_value={"answer": "ok"}) as run:
            codes = [self.client.post("/api/smartchat", json={"question": f"q{self.tag}", "birth": BIRTH}, headers=headers).status_code
                     for _ in range(12)]
            self.assertEqual(codes[:10], [200] * 10)
            self.assertEqual(codes[10:], [429, 429])
            self.assertEqual(run.call_count, 10)  # OpenAI path never reached once limited
            other = self.client.post("/api/smartchat", json={"question": "q", "birth": BIRTH},
                                     headers={"X-Forwarded-For": "198.51.100.77"})
            self.assertEqual(other.status_code, 200)  # a different client is unaffected
        self.assertEqual(self.client.post("/api/smartchat", json={}, headers={"X-Forwarded-For": "198.51.100.78"}).status_code, 400)

    def test_smartchat_daily_cap(self):
        bucket_limits = dict((b, (l, w)) for b, l, w in routes_smartchat.SMARTCHAT_LIMITS)
        self.assertEqual(bucket_limits["smartchat-hour"][0], 10)
        self.assertEqual(bucket_limits["smartchat-day"][0], 30)


# --------------------------------------------------------------------------- D
class SecretValidationTests(_Base):
    STRONG = "Z" * 20 + uuid.uuid4().hex  # 52 chars, test-only value

    def test_find_problems_rules(self):
        self.assertEqual({n for n, _ in secret_validation.find_problems({})}, {"JWT_SECRET_KEY", "SECRET_KEY"})
        self.assertEqual(secret_validation.find_problems({"JWT_SECRET_KEY": "change-this-in-prod", "SECRET_KEY": "fallback-secret"}),
                         [("JWT_SECRET_KEY", "set to a known placeholder value"), ("SECRET_KEY", "set to a known placeholder value")])
        self.assertEqual([n for n, _ in secret_validation.find_problems({"JWT_SECRET_KEY": "short", "SECRET_KEY": self.STRONG})], ["JWT_SECRET_KEY"])
        self.assertEqual(secret_validation.find_problems({"JWT_SECRET_KEY": self.STRONG, "SECRET_KEY": self.STRONG}), [])

    def test_warns_once_on_first_request_never_logs_values_never_blocks(self):
        secret_validation._checked = False
        with mock.patch.dict(os.environ, {"JWT_SECRET_KEY": self.STRONG}, clear=False):
            os.environ.pop("SECRET_KEY", None)
            with self.assertLogs("secret_validation", level="CRITICAL") as logs:
                r1 = self.client.get("/api/health")
                r2 = self.client.get("/api/health")
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        joined = "\n".join(logs.output)
        self.assertEqual(len(logs.output), 1)  # once per process, SECRET_KEY only
        self.assertIn("SECRET_KEY", joined)
        self.assertNotIn("JWT_SECRET_KEY", joined)
        self.assertNotIn(self.STRONG, joined)
        self.assertNotIn(self.STRONG[:8], joined)

    def test_check_never_raises(self):
        secret_validation._checked = False
        with mock.patch.object(secret_validation, "find_problems", side_effect=RuntimeError("boom")):
            self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_script_import_without_secrets_is_silent_and_succeeds(self):
        # Migration workflows / cron import `app` without JWT_SECRET_KEY or
        # SECRET_KEY and without serving HTTP: must boot, must not warn.
        env = {k: v for k, v in os.environ.items() if k not in ("JWT_SECRET_KEY", "SECRET_KEY")}
        env["PYTHONIOENCODING"] = "utf-8"
        code = ("import sys,types; m=types.ModuleType('weasyprint'); m.HTML=m.CSS=object; sys.modules['weasyprint']=m\n"
                "from app import app\nfrom modules.security import secret_validation as s\n"
                "with app.app_context(): pass\nprint('BOOT_OK', s._checked)")
        out = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(os.path.abspath(__file__)),
                             env=env, capture_output=True, text=True, timeout=180, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertIn("BOOT_OK False", out.stdout)
        self.assertNotIn("SECURITY secret_validation", out.stdout + out.stderr)


# --------------------------------------------------------------------------- E
class AskNowObservabilityTests(_Base):
    def setUp(self):
        super().setUp()
        routes_chat._unauth_log_state.clear()

    def test_unauthenticated_requests_logged_once_without_ids_or_payload(self):
        secret_marker = f"question-{self.tag}"
        with mock.patch.dict(os.environ, {"ASKNOW_JWT_ENFORCEMENT": "1"}):
            with self.assertLogs("asknow_auth", level="WARNING") as logs:
                for _ in range(6):
                    r = self.client.post("/api/chat/free", json={"user_id": 987654321, "question": secret_marker, "birth": BIRTH})
                    self.assertEqual(r.status_code, 401)
        self.assertEqual(len(logs.output), 1)  # de-duplicated
        line = logs.output[0]
        for expected in ("route=/api/chat/free", "auth=missing_jwt", "enforcement=on", "outcome=rejected_401", "at=20"):
            self.assertIn(expected, line)
        for forbidden in ("987654321", secret_marker, "Bearer"):
            self.assertNotIn(forbidden, line)

    def test_each_route_logged_separately_and_reward_included(self):
        with mock.patch.dict(os.environ, {"ASKNOW_JWT_ENFORCEMENT": "1"}):
            with self.assertLogs("asknow_auth", level="WARNING") as logs:
                self.client.post("/api/chat/pack", json={})
                self.client.get("/api/chat/status")
                self.client.post("/api/chat/reward", json={})
        routes = sorted(l.split("route=")[1].split()[0] for l in logs.output)
        self.assertEqual(routes, ["/api/chat/pack", "/api/chat/reward", "/api/chat/status"])

    def test_suppressed_count_reported_after_interval(self):
        with mock.patch.dict(os.environ, {"ASKNOW_JWT_ENFORCEMENT": "1"}):
            with mock.patch.object(routes_chat, "_UNAUTH_LOG_INTERVAL_SECONDS", 0):
                with self.assertLogs("asknow_auth", level="WARNING") as logs:
                    self.client.post("/api/chat/free", json={})
                    self.client.post("/api/chat/free", json={})
        self.assertEqual(len(logs.output), 2)

    def test_authenticated_requests_not_logged_and_still_work(self):
        u = self.make_user(provider="firebase", firebase_uid=f"fb-o-{self.tag}")
        with mock.patch.dict(os.environ, {"ASKNOW_JWT_ENFORCEMENT": "1"}):
            logger = logging.getLogger("asknow_auth")
            with mock.patch.object(logger, "warning") as warn:
                r = self.client.get("/api/chat/status", headers=self.auth(u.id))
            self.assertEqual(r.status_code, 200)
            warn.assert_not_called()

    def test_legacy_mode_logged_with_its_outcome(self):
        with mock.patch.dict(os.environ, {"ASKNOW_JWT_ENFORCEMENT": ""}):
            with self.assertLogs("asknow_auth", level="WARNING") as logs:
                self.client.post("/api/chat/free", json={})
        self.assertIn("outcome=legacy_body_user_id", logs.output[0])
        self.assertIn("enforcement=off", logs.output[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
