"""
test_delete_account_retry_mechanism.py
------------------------------------------
S1 Gate 5/6 -- proves the stale-JWT security fix (routes/routes_auth.py
::delete_account(), see test_delete_account_stale_jwt_security.py) does
NOT break the legitimate retry path for a genuine partial-failure
(D3 Firestore/Auth cleanup pending after D1's DB deletion already
committed).

Key architectural fact this test proves rather than assumes: D1's DB
deletion ALWAYS deletes the `users` row on a successful pass,
independent of whether D3's Firebase cleanup subsequently fails -- so
the JWT used for the ORIGINAL call is never valid for a bare retry
either way, security fix or not (`/api/auth/token`, the only way this
app's own Flutter client ever obtains a JWT for this route, already
requires a `users` row to exist and 404s otherwise -- confirmed by
reading routes/routes_auth.py::get_backend_token() and
lib/services/backend_auth_service.dart::getBackendToken() in the
Flutter repo, read-only, no Flutter file touched).

A genuine retry therefore always goes through re-authentication first --
exactly what /api/auth/register already does (re-creates a `users` row
for the same firebase_uid if none exists) -- producing a FRESH JWT for a
FRESH `users` row, which then completes the interrupted Firebase
cleanup through this SAME /api/auth/delete-account endpoint. This file
simulates exactly that sequence, using the same Firestore/Auth fakes as
test_firebase_cleanup_service.py, to prove it still works after the S1
fix.

LOCAL DB ONLY. NO REAL FIREBASE CALL ANYWHERE IN THIS FILE.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.models_premium_subscription import CurrentEntitlement  # noqa: E402

import routes.routes_auth as routes_auth_module  # noqa: E402
import modules.auth.firebase_cleanup_service as fcs_module  # noqa: E402

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


USER_IDS_ORIGINAL = [986001]
USER_IDS_RECREATED = [986002]  # simulates the NEW row /api/auth/register would create
PROFILE_IDS = [986101]

FB_RETRY = "s1-fb-retry-target"


def cleanup():
    CurrentEntitlement.query.filter(CurrentEntitlement.profile_id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS_ORIGINAL + USER_IDS_RECREATED)).delete(synchronize_session=False)
    db.session.commit()


class FakeFirebaseVerification:
    def __init__(self):
        self.calls = []

    def __call__(self, token):
        self.calls.append(token)
        if token == "retry-token":
            return {"uid": FB_RETRY}
        raise ValueError(f"simulated: unrecognized token {token!r}")


class FakeUserNotFoundError(Exception):
    pass


class FakeSnapshot:
    def __init__(self, exists):
        self.exists = exists


class FakeDocRef:
    def __init__(self, store, path, fail_at):
        self.store = store
        self.path = path
        self.fail_at = fail_at

    def collection(self, name):
        return FakeCollectionRef(self.store, f"{self.path}/{name}", self.fail_at)

    def get(self):
        return FakeSnapshot(self.path in self.store)

    def delete(self):
        self.store.pop(self.path, None)


class FakeStreamedDoc:
    def __init__(self, store, path, fail_at):
        self._store = store
        self._path = path
        self._fail_at = fail_at

    @property
    def reference(self):
        return FakeDocRef(self._store, self._path, self._fail_at)


class FakeCollectionRef:
    def __init__(self, store, path, fail_at):
        self.store = store
        self.path = path
        self.fail_at = fail_at

    def document(self, doc_id):
        return FakeDocRef(self.store, f"{self.path}/{doc_id}", self.fail_at)

    def stream(self):
        if self.fail_at == "profiles_stream":
            raise RuntimeError("simulated Firestore stream failure")
        prefix = self.path + "/"
        out = []
        for key in list(self.store.keys()):
            if key.startswith(prefix) and "/" not in key[len(prefix):]:
                out.append(FakeStreamedDoc(self.store, key, self.fail_at))
        return out


class FakeFirestoreClient:
    def __init__(self, store, fail_at=None):
        self.store = store
        self.fail_at = fail_at

    def collection(self, name):
        return FakeCollectionRef(self.store, name, self.fail_at)


class FakeFirestoreModule:
    def __init__(self, store):
        self.store = store
        self.fail_at = None

    def client(self):
        return FakeFirestoreClient(self.store, fail_at=self.fail_at)


class FakeAuthModule:
    def __init__(self, existing_uids=None):
        self.existing_uids = set(existing_uids or [])
        self.UserNotFoundError = FakeUserNotFoundError

    def delete_user(self, uid):
        if uid not in self.existing_uids:
            raise self.UserNotFoundError(f"no such user: {uid}")
        self.existing_uids.discard(uid)


def seed(store, uid, n_profiles):
    store[f"users/{uid}"] = True
    for i in range(n_profiles):
        store[f"users/{uid}/profiles/p{i}"] = True


def jwt_for(users_id: int) -> str:
    with app.app_context():
        return create_access_token(identity=str(users_id))


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        db.session.add(User(id=986001, email="s1-retry@example.com", firebase_uid=FB_RETRY))
        db.session.flush()
        db.session.add(AppUser(id=986101, firebase_uid=FB_RETRY, name="Retry Target"))
        db.session.flush()
        # Financial history -> Step 1's D1 pass ANONYMIZES this profile
        # rather than hard-deleting it, so it genuinely remains pending
        # (firebase_uid marker still set) going into Step 3 -- the
        # scenario that actually exercises the retry mechanism this test
        # is verifying, rather than having nothing left to retry at all.
        db.session.add(CurrentEntitlement(profile_id=986101, status="ACTIVE", plan="PRIME_MONTHLY"))
        db.session.commit()

        fake_verify = FakeFirebaseVerification()
        routes_auth_module.firebase_auth.verify_id_token = fake_verify

        store = {}
        seed(store, FB_RETRY, 2)
        fake_firestore_module = FakeFirestoreModule(store)
        fake_auth = FakeAuthModule(existing_uids={FB_RETRY})

        real_firestore_module = fcs_module._default_firestore_module
        real_auth_module = fcs_module._default_auth_module
        fcs_module._default_firestore_module = fake_firestore_module
        fcs_module._default_auth_module = fake_auth

        client = app.test_client()

        try:
            # ==========================================================
            print("=== Step 1: original call -- DB succeeds, Firestore FAILS -> pending ===")
            # ==========================================================
            original_jwt = jwt_for(986001)
            fake_firestore_module.fail_at = "profiles_stream"

            r1 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {original_jwt}", "X-Firebase-ID-Token": "retry-token"},
            )
            check("Step 1: 200, not 5xx", r1.status_code == 200)
            body1 = r1.get_json()
            check("Step 1: success True (DB side is the primary signal)", body1.get("success") is True)
            check("Step 1: firebase_cleanup_status pending", body1.get("firebase_cleanup_status") == "pending")
            check("Step 1: users row now gone (D1 always completes first)", User.query.get(986001) is None)
            profile_after_step1 = AppUser.query.get(986101)
            check("Step 1: AppUser row ANONYMIZED, not hard-deleted (financial history retained it)", profile_after_step1 is not None and profile_after_step1.name is None)
            check("Step 1: firebase_uid pending-cleanup marker still set (Firebase cleanup hasn't succeeded yet)", profile_after_step1 is not None and profile_after_step1.firebase_uid == FB_RETRY)
            check("Step 1: Firestore data NOT yet cleaned (the injected failure)", f"users/{FB_RETRY}" in store)
            check("Step 1: Firebase Auth user NOT yet deleted", FB_RETRY in fake_auth.existing_uids)

            # ==========================================================
            print("\n=== Step 2: bare retry with the SAME now-stale JWT -> correctly rejected (S1 fix) ===")
            # ==========================================================
            r2 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {original_jwt}", "X-Firebase-ID-Token": "retry-token"},
            )
            check("Step 2: bare retry with the stale JWT is rejected (401 stale_session), not silently accepted", r2.status_code == 401 and r2.get_json().get("error") == "stale_session")
            check("Step 2: Firestore STILL not cleaned (rejected before reaching D3)", f"users/{FB_RETRY}" in store)
            check("Step 2: Firebase Auth user STILL not deleted", FB_RETRY in fake_auth.existing_uids)

            # ==========================================================
            print("\n=== Step 3: genuine retry via re-authentication (simulates /api/auth/register recreating the users row + /api/auth/token minting a fresh JWT) ===")
            # ==========================================================
            # This is exactly what modules.auth routes_auth.py::register_user()
            # does in its own "STEP 1: LOOK UP BY firebase_uid" -> not found
            # -> "STEP 3: CREATE NEW USER" path when no `users` row exists
            # for this firebase_uid -- reproduced here directly against the
            # DB rather than re-invoking that route, since this file's own
            # scope is delete-account only.
            db.session.add(User(id=986002, email="s1-retry@example.com", firebase_uid=FB_RETRY))
            db.session.commit()
            fresh_jwt = jwt_for(986002)

            fake_firestore_module.fail_at = None  # the transient Firestore failure is now gone
            r3 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {fresh_jwt}", "X-Firebase-ID-Token": "retry-token"},
            )
            check("Step 3: fresh JWT (new users row, same firebase_uid) -> 200", r3.status_code == 200)
            body3 = r3.get_json()
            check("Step 3: firebase_cleanup_status now complete", body3.get("firebase_cleanup_status") == "complete")
            check("Step 3: Firestore data now genuinely cleaned", f"users/{FB_RETRY}" not in store)
            check("Step 3: Firebase Auth user now genuinely deleted", FB_RETRY not in fake_auth.existing_uids)
            check(
                "Step 3: the pending, still-anonymized AppUser row was re-resolved and re-processed by firebase_uid",
                body3.get("anonymized_profile_count", 0) == 1,
            )
            profile_after_step3 = AppUser.query.get(986101)
            check(
                "Step 3: that profile's pending-cleanup firebase_uid marker is now CLEARED "
                "(clear_pending_firebase_marker() ran after Firebase cleanup finally succeeded)",
                profile_after_step3 is not None and profile_after_step3.firebase_uid is None,
            )
            check(
                "Step 3: retained financial evidence (CurrentEntitlement) still intact throughout",
                CurrentEntitlement.query.filter_by(profile_id=986101).first() is not None,
            )

            print(f"\nStep 3 full response: {body3}")

        finally:
            fcs_module._default_firestore_module = real_firestore_module
            fcs_module._default_auth_module = real_auth_module
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
