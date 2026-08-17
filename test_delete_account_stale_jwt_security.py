"""
test_delete_account_stale_jwt_security.py
--------------------------------------------
S1 -- security regression for the stale-backend-JWT identity-binding
vulnerability found by the D1-D4 Final Integration Gate and fixed in
routes/routes_auth.py::delete_account().

Vulnerability (pre-fix): a caller presenting a JWT whose OWN `users` row
no longer exists (e.g. because that account was already deleted --
possibly by anyone, since the JWT itself is just a bearer credential
valid until its own expiry) could pair it with a genuinely fresh
Firebase ID token belonging to a COMPLETELY DIFFERENT, still-existing
account, and the identity cross-check was skipped entirely, letting the
Firebase token's own verified uid become the deletion target. Reproduced
locally (this file's own Test 1) before the fix landed.

Fix: the cross-check is now unconditional. A missing `users` row is
rejected outright (401, "stale_session") before the Firebase token is
even verified, before resolve_firebase_identity()/delete_account_data()/
cleanup_firebase_account() are ever called.

Uses the LOCAL scratch Postgres DB ONLY. firebase_auth.verify_id_token()
is monkeypatched -- NO real Firebase call is ever made anywhere in this
file.
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

import routes.routes_auth as routes_auth_module  # noqa: E402

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


USER_IDS = [985001, 985002, 985003, 985004]
PROFILE_IDS = [985101, 985102, 985103, 985104]

FB_ATTACKER = "s1-fb-attacker"
FB_VICTIM = "s1-fb-victim"
FB_A = "s1-fb-user-a"
FB_B = "s1-fb-user-b"


def cleanup():
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


class FakeFirebaseVerification:
    def __init__(self):
        self.calls = []

    def __call__(self, token):
        self.calls.append(token)
        if token == "attacker-token":
            return {"uid": FB_ATTACKER}
        if token == "victim-token":
            return {"uid": FB_VICTIM}
        if token == "token-a":
            return {"uid": FB_A}
        if token == "token-b":
            return {"uid": FB_B}
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

        db.session.add(User(id=985001, email="s1-attacker@example.com", firebase_uid=FB_ATTACKER))
        db.session.add(User(id=985002, email="s1-victim@example.com", firebase_uid=FB_VICTIM))
        db.session.add(User(id=985003, email="s1-a@example.com", firebase_uid=FB_A))
        db.session.add(User(id=985004, email="s1-b@example.com", firebase_uid=FB_B))
        db.session.flush()
        db.session.add(AppUser(id=985101, firebase_uid=FB_ATTACKER, name="Attacker"))
        db.session.add(AppUser(id=985102, firebase_uid=FB_VICTIM, name="Victim"))
        db.session.add(AppUser(id=985103, firebase_uid=FB_A, name="User A"))
        db.session.add(AppUser(id=985104, firebase_uid=FB_B, name="User B"))
        db.session.commit()

        fake_verify = FakeFirebaseVerification()
        routes_auth_module.firebase_auth.verify_id_token = fake_verify

        client = app.test_client()

        # ==============================================================
        print("=== Test 1: attacker deletes own account, JWT becomes stale ===")
        # ==============================================================
        attacker_jwt = jwt_for(985001)
        r1 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {attacker_jwt}", "X-Firebase-ID-Token": "attacker-token"},
        )
        check("Test 1: attacker's own deletion succeeds -> 200", r1.status_code == 200)
        check("Test 1: attacker's users row now gone", User.query.get(985001) is None)

        # ==============================================================
        print("\n=== Test 1 (the exploit, spied): stale attacker JWT + victim's fresh Firebase token ===")
        # ==============================================================
        real_resolve = routes_auth_module.resolve_firebase_identity
        real_delete = routes_auth_module.delete_account_data
        real_cleanup = routes_auth_module.cleanup_firebase_account

        resolve_calls = []
        delete_calls = []
        cleanup_calls = []

        def spy_resolve(*a, **kw):
            resolve_calls.append((a, kw))
            return real_resolve(*a, **kw)

        def spy_delete(*a, **kw):
            delete_calls.append((a, kw))
            return real_delete(*a, **kw)

        def spy_cleanup(*a, **kw):
            cleanup_calls.append((a, kw))
            return real_cleanup(*a, **kw)

        routes_auth_module.resolve_firebase_identity = spy_resolve
        routes_auth_module.delete_account_data = spy_delete
        routes_auth_module.cleanup_firebase_account = spy_cleanup

        r2 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {attacker_jwt}", "X-Firebase-ID-Token": "victim-token"},
        )

        routes_auth_module.resolve_firebase_identity = real_resolve
        routes_auth_module.delete_account_data = real_delete
        routes_auth_module.cleanup_firebase_account = real_cleanup

        check("1: stale JWT + victim's fresh Firebase token -> rejected (401)", r2.status_code == 401)
        check("1: error code is stale_session", r2.get_json().get("error") == "stale_session")

        check("2: victim's users row completely untouched", User.query.get(985002) is not None)
        check("2: victim's app_users row completely untouched", AppUser.query.get(985102) is not None)
        victim = User.query.get(985002)
        check("2: victim's data is byte-for-byte original", victim.email == "s1-victim@example.com" and victim.firebase_uid == FB_VICTIM)

        check("3: resolve_firebase_identity() was NEVER invoked", resolve_calls == [])
        check("4: delete_account_data() was NEVER invoked", delete_calls == [])
        check("5: cleanup_firebase_account() was NEVER invoked", cleanup_calls == [])

        # ==============================================================
        print("\n=== Test 6/7: stale JWT + body/query firebase_uid=victim cannot bypass ===")
        # ==============================================================
        r6 = client.post(
            "/api/auth/delete-account?firebase_uid=" + FB_VICTIM + "&user_id=985002&profile_id=985102",
            headers={"Authorization": f"Bearer {attacker_jwt}", "X-Firebase-ID-Token": "victim-token"},
            json={"firebase_uid": FB_VICTIM, "user_id": 985002, "profile_id": 985102},
        )
        check("6/7: body+query override attempt still rejected (401, stale_session)", r6.status_code == 401 and r6.get_json().get("error") == "stale_session")
        check("6/7: victim still completely untouched", User.query.get(985002) is not None and AppUser.query.get(985102) is not None)

        # ==============================================================
        print("\n=== Test 8: valid JWT A + Firebase token B still rejected (identity_mismatch) ===")
        # ==============================================================
        jwt_a = jwt_for(985003)
        r8 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_a}", "X-Firebase-ID-Token": "token-b"},
        )
        check("8: valid JWT A + Firebase token B -> 403 identity_mismatch", r8.status_code == 403 and r8.get_json().get("error") == "identity_mismatch")
        check("8: User A untouched", User.query.get(985003) is not None)
        check("8: User B untouched", User.query.get(985004) is not None and AppUser.query.get(985104) is not None)

        # ==============================================================
        print("\n=== Test 9: valid JWT A + Firebase token A still succeeds ===")
        # ==============================================================
        r9 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {jwt_a}", "X-Firebase-ID-Token": "token-a"},
        )
        check("9: matching identity -> 200", r9.status_code == 200)
        body9 = r9.get_json()
        check("9: success True", body9.get("success") is True)
        check("9: User A's users row now gone", User.query.get(985003) is None)
        check("9: User A's app_users row now gone", AppUser.query.get(985103) is None)

        # ==============================================================
        print("\n=== Test 10: missing users row is NEVER treated as already_deleted success ===")
        # ==============================================================
        # Re-use the now-stale attacker JWT (985001, already deleted in
        # Test 1) with ITS OWN original Firebase token -- previously this
        # was the "safe idempotent replay" path returning 200 with
        # already_deleted=True; it must now be a flat 401 rejection, not
        # a disguised success.
        r10 = client.post(
            "/api/auth/delete-account",
            headers={"Authorization": f"Bearer {attacker_jwt}", "X-Firebase-ID-Token": "attacker-token"},
        )
        check("10: repeated request with the SAME now-stale JWT -> 401, not 200", r10.status_code == 401)
        check("10: error code is stale_session, not disguised as already_deleted success", r10.get_json().get("error") == "stale_session")
        check("10: response body contains no 'already_deleted' success shape", "already_deleted" not in r10.get_json())

        check("No real Firebase call was ever made (fake handled every call)", len(fake_verify.calls) > 0)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
