"""P0 regression: /api/auth/register must never let a caller take over another
account by sending someone else's email.

LOCAL ONLY: runs the real app + real models against a local
`jyotishasha_local` Postgres (DATABASE_URL must point at localhost /
127.0.0.1 and that database name, or the script refuses to run). Firebase
token verification is mocked -- each fake token maps to chosen claims -- so
no Firebase project, network or production data is involved. Every row this
creates uses a unique marker and is deleted in tearDown.

Run: python test_auth_register_takeover.py
"""
import os
import sys
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlparse

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_url = os.environ.get("DATABASE_URL", "")
_u = urlparse(_url)
if _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/jyotishasha_local":
    raise SystemExit("REFUSING TO RUN: test_auth_register_takeover.py needs DATABASE_URL = the local jyotishasha_local database.")
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", _FAKE_FCM_JSON)
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.subscription.models import Subscription  # noqa: E402
try:  # absent before the fix -- lets the same file demonstrate the bug on main
    from routes.routes_auth import verified_token_email  # noqa: E402
except ImportError:  # pragma: no cover
    verified_token_email = None

RUN = uuid.uuid4().hex[:10]


def mark(label):
    return f"p0auth-{RUN}-{label}"


def mail(label):
    return f"{mark(label)}@example.test"


class RegisterTakeoverTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        self.client = app.test_client()
        self.tokens = {}
        patcher = patch("routes.routes_auth.firebase_auth.verify_id_token", side_effect=self._verify)
        patcher.start()
        self.addCleanup(patcher.stop)
        current = db.session.execute(db.text("select current_database()")).scalar()
        self.assertEqual(current, "jyotishasha_local")

    def tearDown(self):
        db.session.rollback()
        users = User.query.filter(User.email.like(f"p0auth-{RUN}-%")).all()
        uids = [u.firebase_uid for u in users] + [mark(x) for x in ("victim-uid", "attacker-uid", "new-uid", "other-uid", "fresh-uid")]
        for u in users:
            Subscription.query.filter_by(user_id=u.id).delete()
        AppUser.query.filter(AppUser.firebase_uid.in_([x for x in uids if x])).delete(synchronize_session=False)
        User.query.filter(User.email.like(f"p0auth-{RUN}-%")).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    # ---- helpers -------------------------------------------------------
    def _verify(self, token):
        if token not in self.tokens:
            raise ValueError("invalid token")
        return dict(self.tokens[token])

    def token(self, uid, email=None, email_verified=None):
        name = f"tok-{uuid.uuid4().hex}"
        claims = {"uid": uid}
        if email is not None:
            claims["email"] = email
        if email_verified is not None:
            claims["email_verified"] = email_verified
        self.tokens[name] = claims
        return name

    def register(self, token, **body):
        return self.client.post("/api/auth/register", json=body, headers={"Authorization": f"Bearer {token}"})

    def backend_token(self, token):
        return self.client.post("/api/auth/token", headers={"Authorization": f"Bearer {token}"})

    def make_victim(self):
        victim = User(email=mail("victim"), firebase_uid=mark("victim-uid"), provider="firebase", name="Victim")
        db.session.add(victim)
        db.session.flush()
        profile = AppUser(firebase_uid=mark("victim-uid"), name="Victim", email=mail("victim"),
                          dob="1985-03-31", tob="19:45", pob="Lucknow", lat=26.85, lng=80.95)
        db.session.add(profile)
        db.session.add(Subscription(user_id=victim.id, plan="premium", status="active"))
        db.session.commit()
        return victim.id, profile.id

    def snapshot(self, user_id, profile_id):
        db.session.expire_all()
        user = db.session.get(User, user_id)
        profile = db.session.get(AppUser, profile_id)
        subs = [(s.user_id, s.plan, s.status) for s in Subscription.query.filter_by(user_id=user_id).all()]
        return {
            "user": (user.firebase_uid, user.email, user.name, user.provider),
            "profile": (profile.firebase_uid, profile.dob, profile.tob, profile.pob, profile.lat, profile.lng),
            "subscriptions": subs,
        }

    # ---- the helper itself ---------------------------------------------
    def test_verified_token_email_requires_boolean_true(self):
        if verified_token_email is None:
            self.skipTest("verified_token_email() not present (pre-fix code)")
        self.assertEqual(verified_token_email({"email": "a@b.c", "email_verified": True}), "a@b.c")
        for claims in ({"email": "a@b.c"}, {"email": "a@b.c", "email_verified": False},
                       {"email": "a@b.c", "email_verified": "true"}, {"email": "a@b.c", "email_verified": 1},
                       {"email_verified": True}, {"email": "", "email_verified": True},
                       {"email": ["a@b.c"], "email_verified": True}):
            with self.subTest(claims=claims):
                self.assertIsNone(verified_token_email(claims))

    # ---- attacker / victim -----------------------------------------------
    def test_attacker_with_own_verified_email_cannot_claim_victim_by_body_email(self):
        victim_id, profile_id = self.make_victim()
        before = self.snapshot(victim_id, profile_id)
        attacker = self.token(mark("attacker-uid"), mail("attacker"), True)
        r = self.register(attacker, email=mail("victim"), name="Attacker")
        self.assertEqual(r.status_code, 200, r.json)
        self.assertNotEqual(r.json["user_id"], victim_id)
        self.assertTrue(r.json["new"])
        self.assertEqual(self.snapshot(victim_id, profile_id), before)
        attacker_row = db.session.get(User, r.json["user_id"])
        self.assertEqual(attacker_row.email, mail("attacker"))  # the token's email, not the body's
        # the attacker's backend JWT is for the attacker's own row only
        jwt = self.backend_token(attacker)
        self.assertEqual(jwt.status_code, 200)
        self.assertEqual(jwt.json["user_id"], r.json["user_id"])
        self.assertNotEqual(jwt.json["user_id"], victim_id)

    def test_attacker_without_token_email_cannot_claim_victim(self):
        victim_id, profile_id = self.make_victim()
        before = self.snapshot(victim_id, profile_id)
        attacker = self.token(mark("attacker-uid"))  # e.g. phone sign-in: no email claim
        r = self.register(attacker, email=mail("victim"))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json["error"], "verified_email_required")
        self.assertEqual(self.snapshot(victim_id, profile_id), before)
        self.assertIsNone(User.query.filter_by(firebase_uid=mark("attacker-uid")).first())

    def test_unverified_token_email_matching_victim_does_not_relink(self):
        victim_id, profile_id = self.make_victim()
        before = self.snapshot(victim_id, profile_id)
        for verified in (False, None, "true"):
            with self.subTest(email_verified=verified):
                attacker = self.token(mark("attacker-uid"), mail("victim"), verified)
                r = self.register(attacker, email=mail("victim"))
                self.assertEqual(r.status_code, 403)
                self.assertEqual(self.snapshot(victim_id, profile_id), before)
        self.assertEqual(self.backend_token(self.token(mark("attacker-uid"), mail("victim"), False)).status_code, 404)

    def test_existing_attacker_row_cannot_overwrite_its_email_to_victims(self):
        victim_id, profile_id = self.make_victim()
        attacker = self.token(mark("attacker-uid"), mail("attacker"), True)
        first = self.register(attacker, name="Attacker")
        self.assertEqual(first.status_code, 200)
        before = self.snapshot(victim_id, profile_id)
        r = self.register(attacker, email=mail("victim"), name="Attacker")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["user_id"], first.json["user_id"])
        self.assertEqual(db.session.get(User, first.json["user_id"]).email, mail("attacker"))
        self.assertEqual(self.snapshot(victim_id, profile_id), before)

    def test_victim_still_signs_in_normally_after_attempts(self):
        victim_id, profile_id = self.make_victim()
        self.register(self.token(mark("attacker-uid"), mail("attacker"), True), email=mail("victim"))
        victim = self.token(mark("victim-uid"), mail("victim"), True)
        r = self.register(victim, email=mail("victim"), name="Victim")
        self.assertEqual((r.status_code, r.json["user_id"], r.json["new"]), (200, victim_id, False))
        jwt = self.backend_token(victim)
        self.assertEqual((jwt.status_code, jwt.json["user_id"]), (200, victim_id))

    # ---- legitimate users --------------------------------------------------
    def test_new_google_user_is_created_with_token_email(self):
        fresh = self.token(mark("fresh-uid"), mail("fresh"), True)
        r = self.register(fresh, email="ignored-body@example.test", name="Fresh User")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json["new"])
        row = db.session.get(User, r.json["user_id"])
        self.assertEqual((row.email, row.firebase_uid, row.name, row.provider),
                         (mail("fresh"), mark("fresh-uid"), "Fresh User", "firebase"))
        self.assertEqual(self.backend_token(fresh).status_code, 200)

    def test_returning_user_same_uid_keeps_account_and_syncs_name(self):
        victim_id, profile_id = self.make_victim()
        before = self.snapshot(victim_id, profile_id)
        r = self.register(self.token(mark("victim-uid"), mail("victim"), True), email=mail("victim"), name="Victim Renamed")
        self.assertEqual((r.status_code, r.json["user_id"], r.json["new"]), (200, victim_id, False))
        after = self.snapshot(victim_id, profile_id)
        self.assertEqual(after["user"][2], "Victim Renamed")
        self.assertEqual(after["profile"], before["profile"])
        self.assertEqual(after["subscriptions"], before["subscriptions"])

    def test_returning_user_with_unverified_or_missing_email_keeps_account(self):
        victim_id, profile_id = self.make_victim()
        before = self.snapshot(victim_id, profile_id)
        for token in (self.token(mark("victim-uid")), self.token(mark("victim-uid"), "other@example.test", False)):
            r = self.register(token, email="other@example.test")
            self.assertEqual((r.status_code, r.json["user_id"]), (200, victim_id))
        self.assertEqual(self.snapshot(victim_id, profile_id), before)

    def test_verified_email_change_onto_another_accounts_email_is_skipped(self):
        victim_id, profile_id = self.make_victim()
        other = User(email=mail("other"), firebase_uid=mark("other-uid"), provider="firebase")
        db.session.add(other)
        db.session.commit()
        r = self.register(self.token(mark("victim-uid"), mail("other"), True))
        self.assertEqual((r.status_code, r.json["user_id"]), (200, victim_id))
        db.session.expire_all()
        self.assertEqual(db.session.get(User, victim_id).email, mail("victim"))
        self.assertEqual(db.session.get(User, other.id).firebase_uid, mark("other-uid"))

    def test_legitimate_relink_new_uid_same_verified_email_keeps_profile_and_subscription(self):
        victim_id, profile_id = self.make_victim()
        before = self.snapshot(victim_id, profile_id)
        r = self.register(self.token(mark("new-uid"), mail("victim"), True), email=mail("victim"))
        self.assertEqual((r.status_code, r.json["user_id"], r.json["new"]), (200, victim_id, False))
        after = self.snapshot(victim_id, profile_id)
        self.assertEqual(after["user"][0], mark("new-uid"))
        self.assertEqual(after["profile"][0], mark("new-uid"))
        self.assertEqual(after["profile"][1:], before["profile"][1:])  # birth details intact
        self.assertEqual(after["subscriptions"], before["subscriptions"])
        self.assertEqual(User.query.filter_by(email=mail("victim")).count(), 1)

    # ---- authentication unchanged ----------------------------------------
    def test_missing_or_invalid_token_rejected(self):
        self.assertEqual(self.client.post("/api/auth/register", json={"email": mail("x")}).status_code, 401)
        self.assertEqual(self.register("not-a-real-token", email=mail("x")).status_code, 401)
        self.assertEqual(self.register(self.token(""), email=mail("x")).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
