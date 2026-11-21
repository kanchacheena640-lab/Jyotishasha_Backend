"""PR #8 security remediation regression tests.

A. /api/chat/reward: JWT always required; authenticated -> 403
   reward_unavailable; no balance, pack or quota is touched.
B. /api/auth/signup is gone (no new email squats). A pre-existing,
   never-verified password account on an email is quarantined when the
   email's Firebase-verified owner signs in: the owner gets their own
   account, the squatter's credentials never reach it, and nothing blocks the
   owner. Every other linking path is unchanged.
C. /requirements and /api/free-consult are gone; /api/smartchat is kept
   behind a GLOBAL Redis-backed budget (not client-IP based, since the proxy
   chain is unverified) checked before any OpenAI call: spoofed headers,
   concurrency and Redis failure cannot bypass it.
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
import threading
import time
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
from modules.reviews import rate_limit  # noqa: E402
_PRODUCTION_SMARTCHAT_LIMITS = routes_smartchat.SMARTCHAT_GLOBAL_LIMITS  # captured before any test patches it

# Unpredictable quarantine address: users.id hint + 128-bit CSPRNG hex.
QUARANTINE_RE = r"^quarantined\+{id}\.[0-9a-f]{{32}}@quarantined\.invalid$"
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
class AccountLinkingTests(_Base):
    """Email squatting and account takeover via unverified password accounts."""

    def register(self, uid, email):
        decoded = {"uid": uid, "email": email, "email_verified": True, "name": "Owner"}
        with mock.patch("routes.routes_auth.firebase_auth.verify_id_token", return_value=decoded):
            return self.client.post("/api/auth/register", headers={"Authorization": "Bearer g"}, json={})

    def squat(self, email):
        # The state an attacker could have left behind via the (now removed)
        # /api/auth/signup: a password row on someone else's email.
        row = self.make_user(email=email, provider="password", name="Attacker", phone="9000000001")
        row.set_password("attacker-pass-123")
        db.session.commit()
        return row

    def test_signup_route_is_gone_login_and_refresh_remain(self):
        rules = {r.rule for r in app.url_map.iter_rules()}
        self.assertNotIn("/api/auth/signup", rules)
        self.assertIn("/api/auth/login", rules)
        self.assertIn("/api/auth/refresh", rules)
        email = f"new-squat-{self.tag}@example.test"
        r = self.client.post("/api/auth/signup", json={"email": email, "password": "x" * 12})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(User.query.filter_by(email=email).count(), 0)  # squatting cannot be reproduced

    def test_preexisting_squat_does_not_block_the_verified_owner(self):
        email = f"victim-{self.tag}@example.test"
        squat = self.squat(email)
        r = self.register(f"fb-owner-{self.tag}", email)
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        self.assertIs(body["new"], True)
        self.assertNotEqual(body["user_id"], squat.id)
        db.session.expire_all()
        owner = db.session.get(User, body["user_id"])
        self.user_ids.append(owner.id)
        self.assertEqual((owner.email, owner.firebase_uid, owner.provider, owner.password_hash),
                         (email, f"fb-owner-{self.tag}", "firebase", None))
        q = db.session.get(User, squat.id)
        self.assertRegex(q.email, QUARANTINE_RE.format(id=squat.id))
        self.assertIsNone(q.password_hash)
        self.assertEqual(q.provider, "quarantined")
        self.assertIsNone(q.firebase_uid)
        self.assertEqual((q.name, q.phone), ("Attacker", "9000000001"))  # data kept for review
        self.assertEqual(User.query.filter_by(email=email).count(), 1)
        # the owner's next sign-in is an ordinary returning-user sign-in
        again = self.register(f"fb-owner-{self.tag}", email)
        self.assertEqual((again.status_code, again.get_json()["user_id"], again.get_json()["new"]), (200, owner.id, False))

    def test_attacker_credentials_never_reach_the_owner(self):
        from flask_jwt_extended import create_refresh_token
        email = f"victim2-{self.tag}@example.test"
        squat = self.squat(email)
        attacker_access = self.auth(squat.id)
        attacker_refresh = {"Authorization": f"Bearer {create_refresh_token(identity=str(squat.id))}"}
        owner_id = self.register(f"fb-owner2-{self.tag}", email).get_json()["user_id"]
        self.user_ids.append(owner_id)
        owner_profile = AppUser(firebase_uid=f"fb-owner2-{self.tag}", name="Owner", dob="1991-02-03")
        db.session.add(owner_profile)
        db.session.commit()
        # the password no longer works on the email (or on the row at all)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": email, "password": "attacker-pass-123"}).status_code, 401)
        # an old access token, and a refreshed one, stay bound to the quarantined row
        refreshed = self.client.post("/api/auth/refresh", headers=attacker_refresh)
        self.assertEqual(refreshed.status_code, 200)
        refreshed_headers = {"Authorization": f"Bearer {refreshed.get_json()['access_token']}"}
        for headers in (attacker_access, refreshed_headers):
            self.assertEqual(self.client.get(f"/users/{owner_profile.id}", headers=headers).status_code, 403)
            me = self.client.get("/api/profile", headers=headers).get_json()["user"]
            self.assertEqual(me["id"], squat.id)
            self.assertNotEqual(me["email"], email)
            self.assertNotEqual(me.get("dob"), "1991-02-03")

    def test_genuine_preexisting_password_account_can_still_log_in(self):
        email = f"pw-user-{self.tag}@example.test"
        self.squat(email)
        r = self.client.post("/api/auth/login", json={"email": email, "password": "attacker-pass-123"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access_token", r.get_json())

    def test_row_already_bound_to_firebase_relinks_not_quarantined(self):
        # A password row linked to a verified Firebase identity before PR #8
        # is a real account; a UID change must re-link it, never quarantine it.
        u = self.make_user(provider="firebase", firebase_uid=f"fb-bound-{self.tag}")
        u.set_password("legacy-pass-123")
        db.session.commit()
        r = self.register(f"fb-bound-new-{self.tag}", u.email)
        self.assertEqual((r.status_code, r.get_json()["user_id"], r.get_json()["new"]), (200, u.id, False))
        db.session.expire_all()
        self.assertEqual(db.session.get(User, u.id).firebase_uid, f"fb-bound-new-{self.tag}")

    def test_new_google_user_created(self):
        r = self.register(f"fb-new-{self.tag}", f"new-{self.tag}@example.test")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.get_json()["new"], True)
        self.user_ids.append(r.get_json()["user_id"])

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

    def test_unverified_or_missing_token_still_refused(self):
        self.assertEqual(self.client.post("/api/auth/register", json={}).status_code, 401)
        email = f"unverified-{self.tag}@example.test"
        squat = self.squat(email)
        decoded = {"uid": f"fb-unv-{self.tag}", "email": email, "email_verified": False}
        with mock.patch("routes.routes_auth.firebase_auth.verify_id_token", return_value=decoded):
            r = self.client.post("/api/auth/register", headers={"Authorization": "Bearer g"}, json={})
        self.assertEqual(r.status_code, 403)  # an unproven email never quarantines anything
        db.session.expire_all()
        self.assertEqual(db.session.get(User, squat.id).email, email)

    # ---- quarantine address: unpredictable, collision-safe, atomic ---------
    def plant(self, address):
        row = self.make_user(email=address, provider="password", name="Planted")
        row.set_password("planted-pass-123")
        db.session.commit()
        return row

    def assert_quarantined(self, row_id):
        db.session.expire_all()
        q = db.session.get(User, row_id)
        self.assertRegex(q.email, QUARANTINE_RE.format(id=row_id))
        self.assertEqual((q.provider, q.password_hash, q.firebase_uid), ("quarantined", None, None))
        return q

    def test_preplanted_predictable_address_cannot_block_the_owner(self):
        # The old deterministic format, planted in advance by an attacker.
        email = f"victim3-{self.tag}@example.test"
        squat = self.squat(email)
        self.plant(f"quarantined+{squat.id}@quarantined.invalid")
        r = self.register(f"fb-owner3-{self.tag}", email)
        self.assertEqual((r.status_code, r.get_json()["new"]), (200, True))
        self.user_ids.append(r.get_json()["user_id"])
        self.assert_quarantined(squat.id)

    def test_addresses_are_random_and_distinct(self):
        import routes.routes_auth as ra
        addresses = {ra._quarantine_address(42) for _ in range(200)}
        self.assertEqual(len(addresses), 200)
        for a in addresses:
            self.assertRegex(a, QUARANTINE_RE.format(id=42))
        with mock.patch("routes.routes_auth.secrets.token_hex", return_value="f" * 32) as tok:
            self.assertEqual(ra._quarantine_address(7), "quarantined+7." + "f" * 32 + "@quarantined.invalid")
            tok.assert_called_once_with(16)  # 128 bits from the secrets CSPRNG

    def test_colliding_random_address_is_retried(self):
        email = f"victim4-{self.tag}@example.test"
        squat = self.squat(email)
        taken = "a" * 32
        self.plant(f"quarantined+{squat.id}.{taken}@quarantined.invalid")
        with mock.patch("routes.routes_auth.secrets.token_hex", side_effect=[taken, "b" * 32]):
            r = self.register(f"fb-owner4-{self.tag}", email)
        self.assertEqual((r.status_code, r.get_json()["new"]), (200, True))
        self.user_ids.append(r.get_json()["user_id"])
        self.assertEqual(self.assert_quarantined(squat.id).email, f"quarantined+{squat.id}.{'b' * 32}@quarantined.invalid")

    def test_conflict_at_flush_is_retried_inside_a_savepoint(self):
        # The pre-check misses (race between check and flush): the savepoint
        # absorbs the IntegrityError, the next attempt succeeds, and the outer
        # transaction (owner account) is unaffected.
        email = f"victim5-{self.tag}@example.test"
        squat = self.squat(email)
        taken = "c" * 32
        self.plant(f"quarantined+{squat.id}.{taken}@quarantined.invalid")
        with mock.patch("routes.routes_auth._quarantine_address_taken", return_value=False), \
             mock.patch("routes.routes_auth.secrets.token_hex", side_effect=[taken, "d" * 32]):
            r = self.register(f"fb-owner5-{self.tag}", email)
        self.assertEqual((r.status_code, r.get_json()["new"]), (200, True))
        owner_id = r.get_json()["user_id"]
        self.user_ids.append(owner_id)
        self.assertEqual(self.assert_quarantined(squat.id).email, f"quarantined+{squat.id}.{'d' * 32}@quarantined.invalid")
        self.assertEqual(db.session.get(User, owner_id).email, email)

    def test_exhausted_retries_roll_back_everything(self):
        import routes.routes_auth as ra
        email = f"victim6-{self.tag}@example.test"
        squat = self.squat(email)
        before = (squat.email, squat.provider, squat.password_hash)
        with mock.patch("routes.routes_auth._quarantine_address_taken", return_value=True) as taken:
            try:
                outcome = self.register(f"fb-owner6-{self.tag}", email).status_code
            except ra.QuarantineAllocationError:
                outcome = "raised"
        self.assertIn(outcome, (500, "raised"))  # depends only on PROPAGATE_EXCEPTIONS
        self.assertEqual(taken.call_count, ra.QUARANTINE_MAX_ATTEMPTS)  # bounded
        db.session.rollback()
        db.session.expire_all()
        row = db.session.get(User, squat.id)
        self.assertEqual((row.email, row.provider, row.password_hash), before)  # untouched
        self.assertIsNone(User.query.filter_by(firebase_uid=f"fb-owner6-{self.tag}").first())  # no owner row
        r = self.register(f"fb-owner6-{self.tag}", email)  # normal retry then succeeds
        self.assertEqual((r.status_code, r.get_json()["new"]), (200, True))
        self.user_ids.append(r.get_json()["user_id"])

    def test_concurrent_owner_signins_yield_one_account_and_no_errors(self):
        email = f"victim7-{self.tag}@example.test"
        squat = self.squat(email)
        uid = f"fb-owner7-{self.tag}"
        decoded = {"uid": uid, "email": email, "email_verified": True, "name": "Owner"}
        results, lock, barrier = [], threading.Lock(), threading.Barrier(6)

        def worker():
            with app.app_context():
                barrier.wait()
                try:
                    with mock.patch("routes.routes_auth.firebase_auth.verify_id_token", return_value=decoded):
                        r = app.test_client().post("/api/auth/register", headers={"Authorization": "Bearer g"}, json={})
                    out = (r.status_code, (r.get_json() or {}).get("user_id"))
                except Exception as exc:  # surfaced below
                    out = (type(exc).__name__, None)
                finally:
                    db.session.remove()
                with lock:
                    results.append(out)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        db.session.expire_all()
        owners = User.query.filter_by(email=email).all()
        self.assertEqual(len(owners), 1)
        self.user_ids.append(owners[0].id)
        self.assertEqual(owners[0].firebase_uid, uid)
        self.assertEqual(sorted(code for code, _ in results), [200] * 6, results)  # every caller succeeds
        self.assertEqual({user_id for _, user_id in results}, {owners[0].id})  # all see the same account
        self.assert_quarantined(squat.id)


# --------------------------------------------------------------------------- C
class _FakeRedis:
    """Minimal atomic INCR store shared by 'workers' (threads) in-process."""

    def __init__(self, fail=False):
        self.fail, self.data, self.lock = fail, {}, threading.Lock()

    def incr(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        with self.lock:
            self.data[key] = self.data.get(key, 0) + 1
            return self.data[key]

    def expire(self, key, seconds):
        return True


class PublicOpenAIRoutesTests(_Base):
    TIGHT = (("t-hour", 3, 3600), ("t-day", 5, 86400))

    def setUp(self):
        super().setUp()
        rate_limit._memory.clear()
        self.patches = [
            mock.patch.object(routes_smartchat, "SMARTCHAT_GLOBAL_LIMITS",
                              tuple((f"{b}-{self.tag}", l, w) for b, l, w in self.TIGHT)),
            mock.patch.object(routes_smartchat, "run_smartchat", return_value={"answer": "ok"}),
        ]
        self.run = [p.start() for p in self.patches][1]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def ask(self, headers=None):
        return self.client.post("/api/smartchat", json={"question": "q", "birth": BIRTH}, headers=headers or {})

    def test_removed_routes_are_gone(self):
        rules = {r.rule for r in app.url_map.iter_rules()}
        for path in ("/requirements", "/api/free-consult"):
            self.assertNotIn(path, rules)
            for method in ("GET", "POST"):
                self.assertEqual(self.client.open(path, method=method, json={"question": "q", "birth": BIRTH}).status_code, 404)
        self.assertNotIn("routes_free_consult", app.blueprints)

    def test_legitimate_requests_succeed_then_cap_applies_before_openai(self):
        codes = [self.ask().status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])
        self.assertEqual(self.run.call_count, 3)

    def test_spoofed_and_malformed_headers_cannot_bypass(self):
        spoofs = [{"X-Forwarded-For": f"203.0.113.{i}"} for i in range(5)] + [
            {"X-Forwarded-For": "not-an-ip"}, {"X-Forwarded-For": ""}, {"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3"},
            {"X-Forwarded-For": "2001:db8::111"}, {"X-Forwarded-For": "," * 50},
            {"X-Real-IP": "9.9.9.9", "True-Client-IP": "8.8.8.8", "CF-Connecting-IP": "7.7.7.7"},
        ]
        codes = [self.ask(h).status_code for h in spoofs]
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(set(codes[3:]), {429})
        self.assertEqual(self.run.call_count, 3)

    def test_users_sharing_one_ip_are_not_singled_out(self):
        same_ip = {"X-Forwarded-For": "100.64.0.1"}  # CGNAT-style shared address
        self.assertEqual([self.ask(same_ip).status_code for _ in range(3)], [200, 200, 200])

    def test_hourly_rejections_do_not_consume_the_daily_budget(self):
        for _ in range(10):
            self.ask()
        self.assertEqual(self.run.call_count, 3)
        next_hour = time.time() + 3600
        with mock.patch.object(rate_limit.time, "time", return_value=next_hour):
            codes = [self.ask().status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 429, 429])  # day cap 5 = 3 + 2; the 7 hourly rejects cost nothing
        self.assertEqual(self.run.call_count, 5)

    def test_redis_counter_is_shared_by_concurrent_workers(self):
        shared = _FakeRedis()
        results, lock = [], threading.Lock()

        def worker():
            code = app.test_client().post("/api/smartchat", json={"question": "q", "birth": BIRTH}).status_code
            with lock:
                results.append(code)

        with mock.patch.object(rate_limit, "_redis", return_value=shared):
            threads = [threading.Thread(target=worker) for _ in range(24)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(results.count(200), 3)
        self.assertEqual(results.count(429), 21)
        self.assertEqual(self.run.call_count, 3)
        self.assertEqual(rate_limit._memory, {})  # nothing fell back to per-process counting

    def test_redis_failure_degrades_safely(self):
        with mock.patch.object(rate_limit, "_redis", return_value=_FakeRedis(fail=True)):
            codes = [self.ask().status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])  # in-process fallback still enforces; never 500
        self.assertEqual(self.run.call_count, 3)

    def test_validation_still_applies(self):
        self.assertEqual(self.client.post("/api/smartchat", json={}).status_code, 400)

    def test_production_budget_values(self):
        self.assertEqual(_PRODUCTION_SMARTCHAT_LIMITS,
                         (("smartchat-global-hour", 120, 3600), ("smartchat-global-day", 1000, 86400)))


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
