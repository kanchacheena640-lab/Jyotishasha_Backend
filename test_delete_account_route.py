"""
test_delete_account_route.py
----------------------------------
Local-only entry point for D2 (Authenticated Backend Endpoint) --
POST /api/auth/delete-account in routes/routes_auth.py.

Uses the LOCAL scratch Postgres DB ONLY. Uses Flask's real test client
so @jwt_required() and the route's own logic both genuinely execute --
this is NOT a unit test of the D1 service (that's
test_account_deletion_service.py, re-run unchanged by this file's own
final section). firebase_auth.verify_id_token() is monkeypatched --
NO real Firebase call is ever made anywhere in this file.
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
import modules.auth.account_deletion_service as deletion_service_module  # noqa: E402
from modules.auth.account_deletion_service import AccountDeletionError  # noqa: E402

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


USER_IDS = [982001, 982002, 982003, 982004, 982005]
PROFILE_IDS = [982101, 982102, 982103, 982104]

FB_A = "d2-fb-user-a"
FB_B = "d2-fb-user-b"
FB_C = "d2-fb-user-c"
FB_D = "d2-fb-user-d"


def cleanup():
    CurrentEntitlement.query.filter(CurrentEntitlement.profile_id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


class FakeFirebaseVerification:
    """Deterministic, in-process fake for firebase_auth.verify_id_token()
    -- maps a fake "token string" straight to a decoded claims dict. No
    network call, no real Firebase SDK behavior invoked at all."""

    def __init__(self):
        self.calls = []

    def __call__(self, token):
        self.calls.append(token)
        if token == "valid-token-for-a":
            return {"uid": FB_A}
        if token == "valid-token-for-b":
            return {"uid": FB_B}
        if token == "valid-token-for-c":
            return {"uid": FB_C}
        if token == "valid-token-for-d":
            return {"uid": FB_D}
        if token == "malformed-token":
            raise ValueError("simulated: invalid/expired Firebase token")
        raise ValueError(f"simulated: unrecognized token {token!r}")


def jwt_for(users_id: int) -> str:
    with app.app_context():
        return create_access_token(identity=str(users_id))


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        db.session.add(User(id=982001, email="d2-a@example.com", firebase_uid=FB_A))
        db.session.add(User(id=982002, email="d2-b@example.com", firebase_uid=FB_B))
        db.session.add(User(id=982003, email="d2-c@example.com", firebase_uid=FB_C))
        db.session.add(User(id=982004, email="d2-d@example.com", firebase_uid=FB_D))
        db.session.add(User(id=982005, email="d2-e-nofb@example.com", firebase_uid=None))
        db.session.flush()

        db.session.add(AppUser(id=982101, firebase_uid=FB_A, name="User A"))
        db.session.add(AppUser(id=982102, firebase_uid=FB_B, name="User B"))
        db.session.add(AppUser(id=982103, firebase_uid=FB_C, name="User C-1"))
        db.session.add(AppUser(id=982104, firebase_uid=FB_C, name="User C-2"))
        db.session.commit()

        fake_verify = FakeFirebaseVerification()
        routes_auth_module.firebase_auth.verify_id_token = fake_verify

        client = app.test_client()

        # ==============================================================
        print("=== Test 1: unauthenticated (no JWT at all) -> rejected ===")
        # ==============================================================
        resp1 = client.post("/api/auth/delete-account")
        check("Test 1: no Authorization header -> 401", resp1.status_code == 401)
        check("Test 1: User A untouched", User.query.get(982001) is not None)

        # ==============================================================
        print("\n=== Test 2: authenticated but missing Firebase proof -> rejected ===")
        # ==============================================================
        jwt_a = jwt_for(982001)
        resp2 = client.post("/api/auth/delete-account", headers={"Authorization": f"Bearer {jwt_a}"})
        check("Test 2: valid JWT, no X-Firebase-ID-Token -> 401", resp2.status_code == 401)
        check("Test 2: error code is reauthentication_required", resp2.get_json().get("error") == "reauthentication_required")
        check("Test 2: User A untouched", User.query.get(982001) is not None)

        # ==============================================================
        print("\n=== Test 3: malformed/invalid Firebase proof -> rejected ===")
        # ==============================================================
        resp3 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_a}", "X-Firebase-ID-Token": "malformed-token"},
        )
        check("Test 3: verify_id_token raising -> 401", resp3.status_code == 401)
        check("Test 3: error code is invalid_reauthentication", resp3.get_json().get("error") == "invalid_reauthentication")
        check("Test 3: User A untouched", User.query.get(982001) is not None)

        # ==============================================================
        print("\n=== Test 4: backend JWT / Firebase identity MISMATCH -> rejected ===")
        # ==============================================================
        # Authenticated as A (JWT), but presents a validly-verified
        # Firebase token that belongs to B -- must be rejected, and B
        # must never be touched.
        resp4 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_a}", "X-Firebase-ID-Token": "valid-token-for-b"},
        )
        check("Test 4: A's JWT + B's Firebase token -> 403", resp4.status_code == 403)
        check("Test 4: error code is identity_mismatch", resp4.get_json().get("error") == "identity_mismatch")
        check("Test 4: User A untouched", User.query.get(982001) is not None)
        check("Test 4: User B COMPLETELY untouched (the real target of the attempted mismatch)", User.query.get(982002) is not None and AppUser.query.get(982102) is not None)

        # ==============================================================
        print("\n=== Test 6: body/query override attempts are ignored -- never delete another user ===")
        # ==============================================================
        resp6 = client.post(
            "/api/auth/delete-account?firebase_uid=" + FB_B + "&user_id=982002&profile_id=982102",
            headers={"Authorization": f"Bearer {jwt_a}", "X-Firebase-ID-Token": "valid-token-for-b"},
            json={"firebase_uid": FB_B, "user_id": 982002, "profile_id": 982102},
        )
        # Still A's JWT + B's Firebase token -- the mismatch check must
        # still fire regardless of what the body/query also claim.
        check("Test 6: override attempt via body+query still rejected as a mismatch (403), not honored", resp6.status_code == 403)
        check("Test 6: User B still fully untouched despite explicit body/query targeting", User.query.get(982002) is not None and AppUser.query.get(982102) is not None)
        check("Test 6: User A still untouched too (request was rejected, not partially applied)", User.query.get(982001) is not None)

        # ==============================================================
        print("\n=== Test 5: valid, matching identity -> backend deletion succeeds ===")
        # ==============================================================
        resp5 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_a}", "X-Firebase-ID-Token": "valid-token-for-a"},
        )
        check("Test 5: matching identity -> 200", resp5.status_code == 200)
        body5 = resp5.get_json()
        check("Test 5: success=True", body5.get("success") is True)
        check("Test 5: already_deleted=False (first real deletion)", body5.get("already_deleted") is False)
        check("Test 5: hard_deleted_profile_count == 1", body5.get("hard_deleted_profile_count") == 1)
        check("Test 5: User A's users row is now gone", User.query.get(982001) is None)
        check("Test 5: User A's app_users row is now gone", AppUser.query.get(982101) is None)

        # ==============================================================
        print("\n=== Test 8: repeated request with the SAME now-stale JWT -- S1 SECURITY FIX ===")
        # ==============================================================
        # UPDATED (S1): the SAME JWT (now stale -- users.id 982001 no
        # longer exists) is reused, exactly simulating a real
        # double-tap/retry. Previously this was treated as a safe
        # idempotent replay (200, already_deleted=True) -- that was
        # exactly the vulnerable code path (see
        # test_delete_account_stale_jwt_security.py): a stale-but-
        # unexpired JWT is only a bearer credential, and skipping the
        # identity cross-check whenever its own `users` row was already
        # gone let it be paired with ANY other account's genuinely fresh
        # Firebase token to delete that unrelated account. A bare retry
        # with a stale JWT is now correctly REJECTED outright -- a
        # legitimate retry must go through re-authentication first (see
        # test_delete_account_retry_mechanism.py for the full, still-
        # working retry path via /api/auth/register + /api/auth/token).
        resp8 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_a}", "X-Firebase-ID-Token": "valid-token-for-a"},
        )
        check("Test 8: repeated request with a stale JWT is rejected, not treated as success -> 401", resp8.status_code == 401)
        body8 = resp8.get_json()
        check("Test 8: error code is stale_session", body8.get("error") == "stale_session")
        check("Test 8: response is not disguised as an already_deleted success", "already_deleted" not in body8)

        # ==============================================================
        print("\n=== Test 7: multiple AppUser rows under one firebase_uid, via the route ===")
        # ==============================================================
        jwt_c = jwt_for(982003)
        resp7 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_c}", "X-Firebase-ID-Token": "valid-token-for-c"},
        )
        check("Test 7: 200", resp7.status_code == 200)
        body7 = resp7.get_json()
        check("Test 7: both C profiles reported hard-deleted", body7.get("hard_deleted_profile_count") == 2)
        check("Test 7: both AppUser rows actually gone", AppUser.query.get(982103) is None and AppUser.query.get(982104) is None)

        # ==============================================================
        print("\n=== Test 9: injected D1 failure -> proper 500 error, full rollback ===")
        # ==============================================================
        real_delete_fn = routes_auth_module.delete_account_data

        def _boom(resolved):
            raise AccountDeletionError("simulated D1 failure for D2 route test")

        routes_auth_module.delete_account_data = _boom
        jwt_d = jwt_for(982004)
        resp9 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_d}", "X-Firebase-ID-Token": "valid-token-for-d"},
        )
        routes_auth_module.delete_account_data = real_delete_fn

        check("Test 9: injected D1 failure surfaces as 500, not 200", resp9.status_code == 500)
        check("Test 9: error code is deletion_failed", resp9.get_json().get("error") == "deletion_failed")
        check("Test 9: User D untouched (nothing partially applied)", User.query.get(982004) is not None)

        # ==============================================================
        print("\n=== Test 10: an unrelated user (never targeted) is untouched by everything above ===")
        # ==============================================================
        # User B was the mismatch/override target throughout Tests 4/6
        # and was never itself authenticated against in this whole run.
        check("Test 10: User B's users row untouched end-to-end", User.query.get(982002) is not None)
        check("Test 10: User B's app_users row untouched end-to-end", AppUser.query.get(982102) is not None)
        ub = User.query.get(982002)
        check("Test 10: User B's data is byte-for-byte original", ub.email == "d2-b@example.com" and ub.firebase_uid == FB_B)

        # ==============================================================
        print("\n=== Edge case: a users row with no firebase_uid at all cannot pass the cross-check ===")
        # ==============================================================
        jwt_e = jwt_for(982005)
        resp_e = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_e}", "X-Firebase-ID-Token": "valid-token-for-a"},
        )
        check("Edge case: no firebase_uid on the account -> 403, not a crash", resp_e.status_code == 403)

        check("No real Firebase call was ever made (fake handled every call)", len(fake_verify.calls) > 0)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
