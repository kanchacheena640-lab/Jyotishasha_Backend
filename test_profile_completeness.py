"""
test_profile_completeness.py
----------------------------------
P0 -- Recover authenticated users with incomplete birth profiles.

Proves GET /api/profile/completeness (modules/auth/routes_profile.py::
profile_completeness()) is a correct, read-only, JWT-only source of
truth for "does this authenticated caller's AppUser have every field
the Premium Report engine's _load_birth_details() requires" --
without ever exposing the underlying dob/tob/pob/lat/lng values.

Covers:
  A. No Authorization header -> 401 (route is genuinely JWT-gated).
  B. JWT for a user_id with no linked AppUser at all ->
     profile_complete=false, reason=no_profile, HTTP 200 (not an
     error -- this is an expected, common state for a brand-new
     Firebase sign-in).
  C. AppUser exists but is missing ALL FIVE required fields ->
     profile_complete=false, reason=missing_fields.
  D. AppUser exists but is missing exactly ONE required field (lng
     only) -> profile_complete=false, reason=missing_fields (proves
     the check is AND-of-all-five, not just "at least one present").
  E. AppUser has all five fields populated -> profile_complete=true,
     reason=null.
  F. Response body never contains the actual dob/tob/pob/lat/lng
     values for either the complete or incomplete case (no PII
     leak through this endpoint).
  G. An empty-string field (as opposed to NULL) is treated the same
     as missing -- matches _load_birth_details()'s own
     `in (None, "")` check exactly.

Uses the LOCAL scratch Postgres DB ONLY. No production access.
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


# Distinct id range, not used by any other test_*.py fixture in this repo.
PROFILE_IDS = list(range(986001, 986011))
USER_IDS = list(range(986101, 986111))


def cleanup():
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


def link_user_to_profile(user_id, profile_id, firebase_uid, **app_user_fields):
    """Same shape test_manual_trial_activation.py's own
    link_user_to_profile() helper uses -- a `users` row and an
    `app_users` row sharing one firebase_uid, which
    resolve_profile_id_from_account_user_id() joins on."""
    db.session.add(User(id=user_id, email=f"completeness-test-{user_id}@example.com",
                         provider="password", firebase_uid=firebase_uid))
    app_user = db.session.get(AppUser, profile_id)
    if app_user is None:
        app_user = AppUser(id=profile_id, firebase_uid=firebase_uid)
        db.session.add(app_user)
    else:
        app_user.firebase_uid = firebase_uid
    for field, value in app_user_fields.items():
        setattr(app_user, field, value)
    db.session.commit()
    return app_user


def bearer(user_id):
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        client = app.test_client()

        # ==========================================================
        print("=== A: no Authorization header -> 401 ===")
        # ==========================================================
        resp_a = client.get("/api/profile/completeness")
        check("A: HTTP 401", resp_a.status_code == 401)

        # ==========================================================
        print("\n=== B: JWT resolves to no AppUser at all -> profile_complete=false, reason=no_profile ===")
        # ==========================================================
        u_b_orphan = 986101
        # A JWT for a user_id with no User row and no AppUser row at all.
        resp_b = client.get("/api/profile/completeness", headers=bearer(u_b_orphan))
        body_b = resp_b.get_json()
        check("B: HTTP 200 (not an error)", resp_b.status_code == 200)
        check("B: profile_complete == false", body_b.get("profile_complete") is False)
        check("B: reason == no_profile", body_b.get("reason") == "no_profile")

        # ==========================================================
        print("\n=== C: AppUser exists but missing ALL required fields -> missing_fields ===")
        # ==========================================================
        p_c, u_c = 986001, 986102
        link_user_to_profile(u_c, p_c, "fb-completeness-c")
        resp_c = client.get("/api/profile/completeness", headers=bearer(u_c))
        body_c = resp_c.get_json()
        check("C: HTTP 200", resp_c.status_code == 200)
        check("C: profile_complete == false", body_c.get("profile_complete") is False)
        check("C: reason == missing_fields", body_c.get("reason") == "missing_fields")

        # ==========================================================
        print("\n=== D: AppUser missing exactly ONE required field (lng) -> still missing_fields ===")
        # ==========================================================
        p_d, u_d = 986002, 986103
        link_user_to_profile(
            u_d, p_d, "fb-completeness-d",
            dob="1990-01-01", tob="10:30", pob="Mumbai, India", lat=19.076,
            # lng intentionally omitted (stays NULL)
        )
        resp_d = client.get("/api/profile/completeness", headers=bearer(u_d))
        body_d = resp_d.get_json()
        check("D: HTTP 200", resp_d.status_code == 200)
        check("D: profile_complete == false (single missing field is enough)", body_d.get("profile_complete") is False)
        check("D: reason == missing_fields", body_d.get("reason") == "missing_fields")

        # ==========================================================
        print("\n=== E: AppUser has all five required fields -> profile_complete=true ===")
        # ==========================================================
        p_e, u_e = 986003, 986104
        link_user_to_profile(
            u_e, p_e, "fb-completeness-e",
            dob="1990-01-01", tob="10:30", pob="Mumbai, India", lat=19.076, lng=72.877,
        )
        resp_e = client.get("/api/profile/completeness", headers=bearer(u_e))
        body_e = resp_e.get_json()
        check("E: HTTP 200", resp_e.status_code == 200)
        check("E: profile_complete == true", body_e.get("profile_complete") is True)
        check("E: reason == null", body_e.get("reason") is None)

        # ==========================================================
        print("\n=== F: response never leaks dob/tob/pob/lat/lng values ===")
        # ==========================================================
        leaked_keys_c = set(body_c.keys()) & {"dob", "tob", "pob", "lat", "lng"}
        leaked_keys_e = set(body_e.keys()) & {"dob", "tob", "pob", "lat", "lng"}
        check("F: incomplete-profile response has no birth-field keys", len(leaked_keys_c) == 0)
        check("F: complete-profile response has no birth-field keys", len(leaked_keys_e) == 0)
        check(
            "F: incomplete-profile response has exactly the two expected keys",
            set(body_c.keys()) == {"profile_complete", "reason"},
        )
        check(
            "F: complete-profile response has exactly the two expected keys",
            set(body_e.keys()) == {"profile_complete", "reason"},
        )

        # ==========================================================
        print("\n=== G: empty-string field is treated the same as missing (matches _load_birth_details) ===")
        # ==========================================================
        p_g, u_g = 986004, 986105
        link_user_to_profile(
            u_g, p_g, "fb-completeness-g",
            dob="1990-01-01", tob="10:30", pob="", lat=19.076, lng=72.877,
        )
        resp_g = client.get("/api/profile/completeness", headers=bearer(u_g))
        body_g = resp_g.get_json()
        check("G: HTTP 200", resp_g.status_code == 200)
        check("G: profile_complete == false (empty string counts as missing)", body_g.get("profile_complete") is False)
        check("G: reason == missing_fields", body_g.get("reason") == "missing_fields")

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
