"""
test_firebase_cleanup_service.py
----------------------------------
Local-only entry point for D3 (Firebase Auth + Firestore Cleanup).

Two sections:
  SECTION 1 -- unit tests of cleanup_firebase_account() in isolation,
    called directly with injected fake Firestore/Auth dependencies.
    No database involved at all.
  SECTION 2 -- route-level orchestration tests against the real
    POST /api/auth/delete-account (D2's route, extended by D3), using
    the LOCAL scratch Postgres DB and Flask's real test client, with
    the module-level Firebase Admin defaults inside
    modules/auth/firebase_cleanup_service.py monkeypatched to the same
    fakes -- so the route's own, real, unmodified orchestration code
    runs end-to-end, and only the actual Firebase/Firestore boundary is
    faked.

NO REAL FIREBASE OR FIRESTORE CALL IS EVER MADE ANYWHERE IN THIS FILE.

Re-runs test_account_deletion_service.py (D1, 59 checks) and
test_delete_account_route.py (D2, 35 checks) unchanged at the end, via
subprocess, to confirm zero regression.
"""

import os
import subprocess
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
from modules.auth.firebase_cleanup_service import (  # noqa: E402
    FirebaseCleanupError,
    cleanup_firebase_account,
)

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


# =============================================================================
# Fakes -- an in-memory Firestore ("store" is a flat dict of path -> True)
# and a minimal Firebase Auth stand-in. Neither talks to any network.
# =============================================================================

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
        if self.fail_at == "user_doc_get":
            raise RuntimeError("simulated Firestore get failure")
        return FakeSnapshot(self.path in self.store)

    def delete(self):
        if self.fail_at == "user_doc_delete":
            raise RuntimeError("simulated Firestore delete failure")
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
    """Stands in for `firebase_admin.firestore` -- only `.client()` is
    ever called on it by the service under test."""

    def __init__(self, store):
        self.store = store
        self.fail_at = None

    def client(self):
        return FakeFirestoreClient(self.store, fail_at=self.fail_at)


class FakeAuthModule:
    """Stands in for `firebase_admin.auth` -- only `.delete_user()` and
    `.UserNotFoundError` are ever used by the service under test."""

    def __init__(self, existing_uids=None):
        self.existing_uids = set(existing_uids or [])
        self.fail_uids = set()
        self.deleted_uids = []
        self.delete_calls = []
        self.UserNotFoundError = FakeUserNotFoundError

    def delete_user(self, uid):
        self.delete_calls.append(uid)
        if uid in self.fail_uids:
            raise RuntimeError("simulated Firebase Auth deletion failure")
        if uid not in self.existing_uids:
            raise self.UserNotFoundError(f"no such user: {uid}")
        self.existing_uids.discard(uid)
        self.deleted_uids.append(uid)


def seed(store, uid, n_profiles):
    store[f"users/{uid}"] = True
    for i in range(n_profiles):
        store[f"users/{uid}/profiles/p{i}"] = True


# =============================================================================
# SECTION 1 -- unit tests of cleanup_firebase_account() directly
# =============================================================================

def run_unit_tests():
    print("=" * 70)
    print("SECTION 1: cleanup_firebase_account() unit tests (no DB, no Flask)")
    print("=" * 70)

    # -- Test U1/U2/U3: complete successful deletion; user tree removed;
    #    all profile subcollection docs removed. --------------------------
    print("\n=== U1: complete successful deletion ===")
    store = {}
    seed(store, "uid-u1", 3)
    auth = FakeAuthModule(existing_uids={"uid-u1"})
    client = FakeFirestoreClient(store)
    result = cleanup_firebase_account("uid-u1", firestore_client=client, auth_module=auth)
    check("U1: firestore_profiles_deleted == 3", result.firestore_profiles_deleted == 3)
    check("U1: firestore_user_doc_deleted True", result.firestore_user_doc_deleted is True)
    check("U1: auth_user_deleted True", result.auth_user_deleted is True)
    check("U2: user doc actually gone from store", "users/uid-u1" not in store)
    check("U3: all profile docs actually gone from store", not any(k.startswith("users/uid-u1/profiles/") for k in store))
    check("U1: auth uid actually removed", "uid-u1" not in auth.existing_uids)

    # -- Test U4/U7: Auth deleted only after Firestore; Firestore
    #    failure -> Auth deletion must NOT occur. -------------------------
    print("\n=== U4/U7: Firestore failure -> Auth deletion never attempted ===")
    store2 = {}
    seed(store2, "uid-u4", 2)
    auth2 = FakeAuthModule(existing_uids={"uid-u4"})
    client2 = FakeFirestoreClient(store2, fail_at="profiles_stream")
    threw = False
    try:
        cleanup_firebase_account("uid-u4", firestore_client=client2, auth_module=auth2)
    except FirebaseCleanupError:
        threw = True
    check("U4/U7: FirebaseCleanupError raised on Firestore failure", threw)
    check("U4/U7: Auth.delete_user was NEVER called", auth2.delete_calls == [])
    check("U4/U7: Auth uid still present (untouched)", "uid-u4" in auth2.existing_uids)

    # -- Test U5: already-missing Firestore data -> success, not error. --
    print("\n=== U5: already-missing Firestore data ===")
    store3 = {}
    auth3 = FakeAuthModule(existing_uids={"uid-u5"})
    client3 = FakeFirestoreClient(store3)
    result5 = cleanup_firebase_account("uid-u5", firestore_client=client3, auth_module=auth3)
    check("U5: firestore_already_absent True", result5.firestore_already_absent is True)
    check("U5: auth_user_deleted True (still cleaned up)", result5.auth_user_deleted is True)

    # -- Test U6: already-missing Firebase Auth user -> success. ---------
    print("\n=== U6: already-missing Firebase Auth user ===")
    store4 = {}
    seed(store4, "uid-u6", 1)
    auth4 = FakeAuthModule(existing_uids=set())  # nothing here
    client4 = FakeFirestoreClient(store4)
    result6 = cleanup_firebase_account("uid-u6", firestore_client=client4, auth_module=auth4)
    check("U6: auth_already_absent True", result6.auth_already_absent is True)
    check("U6: auth_user_deleted False", result6.auth_user_deleted is False)
    check("U6: Firestore data still genuinely removed", "users/uid-u6" not in store4)

    # -- Test U8: Auth deletion failure after Firestore cleanup. ---------
    print("\n=== U8: Auth deletion failure AFTER Firestore cleanup already committed ===")
    store5 = {}
    seed(store5, "uid-u8", 2)
    auth5 = FakeAuthModule(existing_uids={"uid-u8"})
    auth5.fail_uids.add("uid-u8")
    client5 = FakeFirestoreClient(store5)
    threw8 = False
    try:
        cleanup_firebase_account("uid-u8", firestore_client=client5, auth_module=auth5)
    except FirebaseCleanupError:
        threw8 = True
    check("U8: FirebaseCleanupError raised", threw8)
    check("U8: Firestore data WAS already removed despite the later Auth failure", "users/uid-u8" not in store5 and not any(k.startswith("users/uid-u8/profiles/") for k in store5))
    check("U8: Auth uid still present (delete_user raised, never discarded)", "uid-u8" in auth5.existing_uids)

    # -- Test U9: retry after partial failure -- succeeds the second time,
    #    without re-erroring on already-cleaned Firestore data. ----------
    print("\n=== U9: retry after partial failure completes cleanly ===")
    auth5.fail_uids.discard("uid-u8")
    result9 = cleanup_firebase_account("uid-u8", firestore_client=FakeFirestoreClient(store5), auth_module=auth5)
    check("U9: retry -> firestore_already_absent True (nothing left to redo)", result9.firestore_already_absent is True)
    check("U9: retry -> auth_user_deleted True this time", result9.auth_user_deleted is True)
    check("U9: retry -> uid now actually gone from Auth", "uid-u8" not in auth5.existing_uids)

    # -- Test U13: unrelated Firebase UID never touched. ------------------
    print("\n=== U13: unrelated Firebase UID never touched ===")
    store6 = {}
    seed(store6, "uid-target", 2)
    seed(store6, "uid-bystander", 3)
    auth6 = FakeAuthModule(existing_uids={"uid-target", "uid-bystander"})
    client6 = FakeFirestoreClient(store6)
    cleanup_firebase_account("uid-target", firestore_client=client6, auth_module=auth6)
    check("U13: bystander user doc still present", "users/uid-bystander" in store6)
    check("U13: all 3 bystander profile docs still present", sum(1 for k in store6 if k.startswith("users/uid-bystander/profiles/")) == 3)
    check("U13: bystander Auth uid untouched", "uid-bystander" in auth6.existing_uids)
    check("U13: bystander never appeared in any delete_user call", "uid-bystander" not in auth6.delete_calls)


# =============================================================================
# SECTION 2 -- route-level orchestration tests
# =============================================================================

USER_IDS = [983001, 983002, 983003, 983004, 983005, 983006, 983007]
PROFILE_IDS = [983101, 983102, 983103, 983104, 983105]

FB_X = "d3-fb-user-x"     # no financial history -> hard delete path
FB_Y = "d3-fb-user-y"     # financial history -> anonymize path
FB_Z = "d3-fb-user-z"     # two profiles, one of each kind
FB_W = "d3-fb-user-w"     # partial-failure / retry target
FB_BYSTANDER = "d3-fb-bystander"


def cleanup_db():
    CurrentEntitlement.query.filter(CurrentEntitlement.profile_id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


class FakeFirebaseVerification:
    def __init__(self):
        self.calls = []
        self.token_to_uid = {
            "token-x": FB_X,
            "token-y": FB_Y,
            "token-z": FB_Z,
            "token-w": FB_W,
        }

    def __call__(self, token):
        self.calls.append(token)
        if token in self.token_to_uid:
            return {"uid": self.token_to_uid[token]}
        raise ValueError(f"simulated: unrecognized token {token!r}")


def jwt_for(users_id: int) -> str:
    with app.app_context():
        return create_access_token(identity=str(users_id))


def run_route_tests():
    print("\n" + "=" * 70)
    print("SECTION 2: /api/auth/delete-account route-level D3 orchestration")
    print("=" * 70)

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup_db()

        db.session.add(User(id=983001, email="d3-x@example.com", firebase_uid=FB_X))
        db.session.add(User(id=983002, email="d3-y@example.com", firebase_uid=FB_Y))
        db.session.add(User(id=983003, email="d3-z@example.com", firebase_uid=FB_Z))
        db.session.add(User(id=983004, email="d3-w@example.com", firebase_uid=FB_W))
        db.session.flush()

        db.session.add(AppUser(id=983101, firebase_uid=FB_X, name="User X"))
        db.session.add(AppUser(id=983102, firebase_uid=FB_Y, name="User Y"))
        db.session.add(AppUser(id=983103, firebase_uid=FB_Z, name="User Z-1"))  # will be anonymized
        db.session.add(AppUser(id=983104, firebase_uid=FB_Z, name="User Z-2"))  # will be hard-deleted
        db.session.flush()
        db.session.add(CurrentEntitlement(profile_id=983102))  # gives Y financial history
        db.session.add(CurrentEntitlement(profile_id=983103))  # gives Z-1 financial history
        db.session.commit()

        fake_verify = FakeFirebaseVerification()
        routes_auth_module.firebase_auth.verify_id_token = fake_verify

        store = {}
        seed(store, FB_X, 2)
        seed(store, FB_Y, 1)
        seed(store, FB_Z, 3)
        seed(store, FB_W, 1)
        seed(store, FB_BYSTANDER, 2)

        fake_firestore_module = FakeFirestoreModule(store)
        fake_auth = FakeAuthModule(existing_uids={FB_X, FB_Y, FB_Z, FB_W, FB_BYSTANDER})

        real_firestore_module = fcs_module._default_firestore_module
        real_auth_module = fcs_module._default_auth_module
        fcs_module._default_firestore_module = fake_firestore_module
        fcs_module._default_auth_module = fake_auth

        client = app.test_client()

        try:
            # ==========================================================
            print("\n=== R1: full success, hard-delete path (DB + Firestore + Auth) ===")
            # ==========================================================
            jwt_x = jwt_for(983001)
            resp1 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_x}", "X-Firebase-ID-Token": "token-x"},
            )
            check("R1: 200", resp1.status_code == 200)
            body1 = resp1.get_json()
            check("R1: success True", body1.get("success") is True)
            check("R1: firebase_cleanup_status complete", body1.get("firebase_cleanup_status") == "complete")
            check("R1: hard_deleted_profile_count == 1", body1.get("hard_deleted_profile_count") == 1)
            check("R1: DB user row gone", User.query.get(983001) is None)
            check("R1: DB profile row gone", AppUser.query.get(983101) is None)
            check("R1: Firestore user doc gone", f"users/{FB_X}" not in store)
            check("R1: Firestore profile docs gone", not any(k.startswith(f"users/{FB_X}/profiles/") for k in store))
            check("R1: Firebase Auth user gone", FB_X not in fake_auth.existing_uids)

            # ==========================================================
            print("\n=== R2: full success, anonymize path -- financial retained, marker cleared ===")
            # ==========================================================
            jwt_y = jwt_for(983002)
            resp2 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_y}", "X-Firebase-ID-Token": "token-y"},
            )
            check("R2: 200", resp2.status_code == 200)
            body2 = resp2.get_json()
            check("R2: firebase_cleanup_status complete", body2.get("firebase_cleanup_status") == "complete")
            check("R2: anonymized_profile_count == 1", body2.get("anonymized_profile_count") == 1)
            profile_y = AppUser.query.get(983102)
            check("R2: profile Y row still exists (anonymized, not hard-deleted)", profile_y is not None)
            check("R2: profile Y personal fields nulled", profile_y is not None and profile_y.name is None)
            check("R2: profile Y firebase_uid marker CLEARED after successful Firebase cleanup", profile_y is not None and profile_y.firebase_uid is None)
            check("R2: financial CurrentEntitlement row still present (retained evidence)", CurrentEntitlement.query.filter_by(profile_id=983102).first() is not None)
            check("R2: Firestore/Auth actually cleaned for Y too", f"users/{FB_Y}" not in store and FB_Y not in fake_auth.existing_uids)

            # ==========================================================
            print("\n=== R3 (Gate6 #10/#11): multiple app_users under one firebase_uid, mixed outcomes ===")
            # ==========================================================
            jwt_z = jwt_for(983003)
            resp3 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_z}", "X-Firebase-ID-Token": "token-z"},
            )
            check("R3: 200", resp3.status_code == 200)
            body3 = resp3.get_json()
            check("R3: one hard-deleted, one anonymized", body3.get("hard_deleted_profile_count") == 1 and body3.get("anonymized_profile_count") == 1)
            check("R3: firebase_cleanup_status complete (single shared-uid cleanup)", body3.get("firebase_cleanup_status") == "complete")
            check("R3: Z-1 (anonymized) still exists, marker cleared", AppUser.query.get(983103) is not None and AppUser.query.get(983103).firebase_uid is None)
            check("R3: Z-2 (hard-deleted) is gone", AppUser.query.get(983104) is None)
            check("R3: shared Firestore uid tree fully removed exactly once", f"users/{FB_Z}" not in store and not any(k.startswith(f"users/{FB_Z}/profiles/") for k in store))
            check("R3: shared Firebase Auth uid removed exactly once", FB_Z not in fake_auth.existing_uids)

            # ==========================================================
            print("\n=== R4: Firestore failure -> DB success but firebase_cleanup_status pending, NOT a 5xx ===")
            # ==========================================================
            jwt_w = jwt_for(983004)
            fake_firestore_module.fail_at = "profiles_stream"
            resp4 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_w}", "X-Firebase-ID-Token": "token-w"},
            )
            check("R4: still 200, not 5xx, even though Firebase cleanup failed", resp4.status_code == 200)
            body4 = resp4.get_json()
            check("R4: success True (DB deletion is the primary signal)", body4.get("success") is True)
            check("R4: firebase_cleanup_status pending", body4.get("firebase_cleanup_status") == "pending")
            check("R4: DB side genuinely already deleted", User.query.get(983004) is None)
            check("R4: Auth deletion did NOT occur (Firestore failed first)", FB_W in fake_auth.existing_uids)

            # ==========================================================
            print("\n=== R5 (S1-updated): bare retry with the SAME stale JWT is now rejected; "
                  "genuine retry via re-authentication still completes Firebase cleanup ===")
            # ==========================================================
            fake_firestore_module.fail_at = None  # the transient failure is now gone

            # S1: a bare retry reusing jwt_w (now stale -- its own users
            # row was already deleted by R4's DB pass) must be rejected
            # outright, not treated as a safe idempotent replay -- see
            # test_delete_account_stale_jwt_security.py for the full
            # exploit this closes.
            resp5_bare = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_w}", "X-Firebase-ID-Token": "token-w"},
            )
            check("R5: bare retry with the stale JWT is rejected (401 stale_session), not silently accepted", resp5_bare.status_code == 401 and resp5_bare.get_json().get("error") == "stale_session")
            check("R5: Firestore still NOT cleaned by the rejected bare retry", f"users/{FB_W}" in store)

            # Genuine retry: re-authentication mints a FRESH `users` row
            # for the SAME firebase_uid -- exactly what
            # routes/routes_auth.py::register_user() already does when
            # no existing row is found for a verified firebase_uid, and
            # exactly what this app's own Flutter client is forced into
            # once /api/auth/token 404s for the deleted row (see
            # test_delete_account_retry_mechanism.py for the full trace
            # of why this was already the real retry path, S1 or not).
            db.session.add(User(id=983006, email="d3-w-retry@example.com", firebase_uid=FB_W))
            db.session.commit()
            jwt_w_fresh = jwt_for(983006)

            resp5 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_w_fresh}", "X-Firebase-ID-Token": "token-w"},
            )
            check("R5: genuine retry (fresh JWT, re-authenticated) -> 200", resp5.status_code == 200)
            body5 = resp5.get_json()
            check("R5: firebase_cleanup_status now complete on retry", body5.get("firebase_cleanup_status") == "complete")
            check("R5: Firestore data now actually gone", f"users/{FB_W}" not in store)
            check("R5: Firebase Auth user now actually gone", FB_W not in fake_auth.existing_uids)

            # ==========================================================
            print("\n=== R6 (S1-updated): already-missing Firebase Auth user -> still reported "
                  "complete, but only via a genuinely fresh, re-authenticated identity ===")
            # ==========================================================
            # FB_X's Firestore AND Auth are both already gone from R1.
            # Re-using jwt_x directly (now stale) must be rejected --
            # exactly like R5's bare-retry check above.
            resp6_bare = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_x}", "X-Firebase-ID-Token": "token-x"},
            )
            check("R6: bare retry with FB_X's stale JWT is rejected (401 stale_session)", resp6_bare.status_code == 401 and resp6_bare.get_json().get("error") == "stale_session")

            # A genuinely re-authenticated caller for the same firebase_uid
            # still gets a clean "complete" status (idempotent at the
            # Firebase-cleanup layer -- both U5/U6 already prove
            # cleanup_firebase_account() itself treats "already absent" as
            # success), never an error.
            db.session.add(User(id=983007, email="d3-x-retry@example.com", firebase_uid=FB_X))
            db.session.commit()
            jwt_x_fresh = jwt_for(983007)

            resp6 = client.post(
                "/api/auth/delete-account",
                headers={"Authorization": f"Bearer {jwt_x_fresh}", "X-Firebase-ID-Token": "token-x"},
            )
            check("R6: genuine retry (fresh JWT) -> 200", resp6.status_code == 200)
            body6 = resp6.get_json()
            # already_deleted reflects resolve_firebase_identity() finding
            # NOTHING at all for this firebase_uid -- not the case here,
            # since re-authentication itself just created a fresh `users`
            # row (983007) for FB_X, which this same call now genuinely
            # deletes (zero profiles remain -- those were already gone
            # from R1's hard-delete pass).
            check("R6: already_deleted False (the freshly re-authenticated users row itself was real and just got deleted)", body6.get("already_deleted") is False)
            check("R6: zero profiles left to report (already hard-deleted in R1)", body6.get("hard_deleted_profile_count") == 0 and body6.get("anonymized_profile_count") == 0)
            check("R6: firebase_cleanup_status complete (idempotent no-op on the Firebase side)", body6.get("firebase_cleanup_status") == "complete")

            # ==========================================================
            print("\n=== R7 (Gate6 #14): arbitrary UID in body/query cannot influence cleanup target ===")
            # ==========================================================
            # A brand-new identity, deleted while the request ALSO
            # carries a bogus firebase_uid/profile_id in the body and
            # query string pointing at the untouched bystander uid.
            db.session.add(User(id=983005, email="d3-v@example.com", firebase_uid="d3-fb-user-v"))
            db.session.flush()
            db.session.add(AppUser(id=983105, firebase_uid="d3-fb-user-v", name="User V"))
            db.session.commit()
            fake_verify.token_to_uid["token-v"] = "d3-fb-user-v"
            fake_auth.existing_uids.add("d3-fb-user-v")
            seed(store, "d3-fb-user-v", 1)

            jwt_v = jwt_for(983005)
            resp7 = client.post(
                "/api/auth/delete-account?firebase_uid=" + FB_BYSTANDER + "&user_id=999999&profile_id=888888",
                headers={"Authorization": f"Bearer {jwt_v}", "X-Firebase-ID-Token": "token-v"},
                json={"firebase_uid": FB_BYSTANDER, "user_id": 999999, "profile_id": 888888},
            )
            check("R7: 200 -- request succeeds for the AUTHENTICATED identity only", resp7.status_code == 200)
            check("R7: real target (V) actually deleted", User.query.get(983005) is None)
            check("R7: bystander Firestore doc completely untouched", f"users/{FB_BYSTANDER}" in store)
            check("R7: bystander Firestore profile docs completely untouched", sum(1 for k in store if k.startswith(f"users/{FB_BYSTANDER}/profiles/")) == 2)
            check("R7: bystander Firebase Auth uid completely untouched", FB_BYSTANDER in fake_auth.existing_uids)
            check("R7: bystander Auth uid never appeared in any delete_user call", FB_BYSTANDER not in fake_auth.delete_calls)

            check("No real Firebase call was ever made (fake handled every verify_id_token call)", len(fake_verify.calls) > 0)

        finally:
            fcs_module._default_firestore_module = real_firestore_module
            fcs_module._default_auth_module = real_auth_module
            cleanup_db()


def run_regression(script_name: str, expected_label: str):
    print("\n" + "=" * 70)
    print(f"REGRESSION: re-running {script_name} unchanged")
    print("=" * 70)
    result = subprocess.run(
        [sys.executable, script_name],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True,
        text=True,
    )
    print(result.stdout[-4000:])
    if result.stderr:
        print("---- stderr ----")
        print(result.stderr[-2000:])
    ok = result.returncode == 0
    check(f"{expected_label}: exited 0 (no failed checks)", ok)
    return ok


def main():
    run_unit_tests()
    run_route_tests()
    run_regression("test_account_deletion_service.py", "D1 regression (59 checks)")
    run_regression("test_delete_account_route.py", "D2 regression (35 checks)")

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
