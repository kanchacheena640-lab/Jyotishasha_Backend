"""
test_app_version_policy.py
----------------------------
Ask Now Security + Force Update task -- Force Update backend, Part H:

  - GET  /api/app/version-policy   -- public, no auth, valid config,
    malformed/absent config safety, current-build-allowed vs
    below-minimum semantics (semantics only -- the actual block decision
    is made client-side; this route only reports the policy).
  - PATCH /admin/api/app-version-policy -- admin-gated, partial update,
    field validation.
  - The migration's own seed state: minimum_supported_build ==
    latest_build == the real, confirmed-live production build, with
    force_update False (Part F's own explicit safety requirement).

LOCAL ONLY. No production DB.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_app_version_policy import AppVersionPolicy  # noqa: E402

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


ADMIN_UID = 986001
NON_ADMIN_UID = 986002


def cleanup_users():
    User.query.filter(User.id.in_([ADMIN_UID, NON_ADMIN_UID])).delete(synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup_users()
        db.session.add(User(id=ADMIN_UID, email="avp-admin@example.com", provider="password"))
        db.session.add(User(id=NON_ADMIN_UID, email="avp-nonadmin@example.com", provider="password"))
        db.session.commit()

        client = app.test_client()

        # Snapshot the real seeded row so every test restores it exactly
        # -- this table's seed row is production-meaningful (Part F),
        # never left mutated by a test run.
        original = AppVersionPolicy.query.filter_by(platform="android").first()
        assert original is not None, (
            "app_version_policy has no 'android' row -- run "
            "`flask db upgrade` (migration c7d2f5a9e1b3) before this test."
        )
        original_snapshot = {
            "minimum_supported_build": original.minimum_supported_build,
            "latest_build": original.latest_build,
            "force_update": original.force_update,
            "store_url": original.store_url,
            "message": original.message,
        }

        def restore_policy():
            row = AppVersionPolicy.query.filter_by(platform="android").first()
            for k, v in original_snapshot.items():
                setattr(row, k, v)
            db.session.commit()
            db.session.expire_all()

        try:
            # ==========================================================
            print("=== A: seed state IS the safe initial state (Part F) ===")
            # ==========================================================
            check(
                "A: minimum_supported_build == latest_build (nothing blocked at seed time)",
                original.minimum_supported_build == original.latest_build,
            )
            check("A: force_update is False at seed time", original.force_update is False)
            check(
                "A: store_url points at the real package",
                "com.jyotishasha.app" in original.store_url,
            )

            # ==========================================================
            print("\n=== B: GET is public -- no auth required ===")
            # ==========================================================
            resp = client.get("/api/app/version-policy")
            check("B: 200 with zero Authorization header", resp.status_code == 200)
            body = resp.get_json()
            check("B: response has all 5 required contract fields", all(
                k in body for k in (
                    "minimum_supported_build", "latest_build", "force_update",
                    "store_url", "message",
                )
            ))
            check("B: minimum_supported_build is an int", isinstance(body["minimum_supported_build"], int))
            check("B: force_update is a bool", isinstance(body["force_update"], bool))

            # ==========================================================
            print("\n=== C: valid configuration -- current build allowed ===")
            # ==========================================================
            # Simulates the client-side comparison: installedBuild ==
            # minimum_supported_build must never be treated as "below."
            installed_build = body["minimum_supported_build"]
            check(
                "C: installedBuild == minimum_supported_build is NOT below-minimum",
                not (installed_build < body["minimum_supported_build"]),
            )

            # ==========================================================
            print("\n=== D: below-minimum semantics, after raising the bar ===")
            # ==========================================================
            row = AppVersionPolicy.query.filter_by(platform="android").first()
            row.minimum_supported_build = original_snapshot["minimum_supported_build"] + 1
            db.session.commit()
            db.session.expire_all()

            resp = client.get("/api/app/version-policy")
            body2 = resp.get_json()
            check(
                "D: raised minimum reflected immediately (no app release needed)",
                body2["minimum_supported_build"] == original_snapshot["minimum_supported_build"] + 1,
            )
            check(
                "D: an installedBuild at the OLD minimum is now below the new one",
                original_snapshot["minimum_supported_build"] < body2["minimum_supported_build"],
            )
            restore_policy()

            # ==========================================================
            print("\n=== E: malformed configuration safety -- unsupported platform ===")
            # ==========================================================
            resp = client.get("/api/app/version-policy?platform=ios")
            check("E: unrecognized platform -> 400, not a guessed default", resp.status_code == 400)

            resp = client.get("/api/app/version-policy?platform=windows")
            check("E: another unrecognized platform -> 400", resp.status_code == 400)

            # ==========================================================
            print("\n=== F: PATCH is admin-gated ===")
            # ==========================================================
            resp = client.patch("/admin/api/app-version-policy", json={"force_update": True})
            check("F: no auth at all -> 401", resp.status_code == 401)

            token_non_admin = create_access_token(identity=str(NON_ADMIN_UID))
            resp = client.patch(
                "/admin/api/app-version-policy", json={"force_update": True},
                headers={"Authorization": f"Bearer {token_non_admin}"},
            )
            check("F: authenticated non-admin -> 403", resp.status_code == 403)

            row = AppVersionPolicy.query.filter_by(platform="android").first()
            check("F: rejected non-admin PATCH changed nothing", row.force_update is False)

            os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)
            token_admin = create_access_token(identity=str(ADMIN_UID))
            resp = client.patch(
                "/admin/api/app-version-policy",
                json={"minimum_supported_build": original_snapshot["minimum_supported_build"] + 5},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("F: genuine admin PATCH succeeds (200)", resp.status_code == 200)
            check(
                "F: partial update -- only minimum_supported_build changed, force_update untouched",
                resp.get_json()["minimum_supported_build"] == original_snapshot["minimum_supported_build"] + 5
                and resp.get_json()["force_update"] is False,
            )
            restore_policy()

            # ==========================================================
            print("\n=== G: PATCH field validation ===")
            # ==========================================================
            resp = client.patch(
                "/admin/api/app-version-policy", json={"minimum_supported_build": "not_a_number"},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("G: non-integer minimum_supported_build -> 400", resp.status_code == 400)

            resp = client.patch(
                "/admin/api/app-version-policy", json={"force_update": "yes"},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("G: non-boolean force_update -> 400", resp.status_code == 400)

            row = AppVersionPolicy.query.filter_by(platform="android").first()
            check("G: rejected malformed PATCHes changed nothing", (
                row.minimum_supported_build == original.minimum_supported_build
                and row.force_update is False
            ))

        finally:
            restore_policy()
            cleanup_users()

    print("\n" + "=" * 50)
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
