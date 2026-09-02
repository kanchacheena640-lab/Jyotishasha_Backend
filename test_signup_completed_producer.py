"""
test_signup_completed_producer.py
-------------------------------------------------
Phase 5D.1 -- proves routes/routes_profile_bootstrap.py's new
signup_completed producer:

  A. First-ever bootstrap for a firebase_uid (created == True, commit
     succeeds) -> exactly one signup_completed row.
  B. A second bootstrap for the SAME firebase_uid (created == False,
     the AppUser already exists) -> zero additional signup_completed
     rows -- also covers "retry after successful first creation".
  C. A business failure BEFORE db.session.commit() (kundali calculation
     raises) -> zero signup_completed rows, bootstrap returns 500.
  D. A commit failure (db.session.commit() itself raises) -> zero
     signup_completed rows, bootstrap returns 500.
  E. An analytics (record_event) failure AFTER a successful business
     commit -> bootstrap's own business result (200/ok=True/profileId)
     is completely unaffected.
  F. Structural proof (source inspection, same technique
     test_manual_trial_activation.py already uses) that the emission
     call is textually after db.session.commit() and gated on
     `if created:`.
  G-K. The persisted row's exact shape: event_name, event_version,
     profile_id, firebase_uid, properties == {}, dedupe_key.
  M. No PII/birth-detail key ever appears in the row's properties.
  N. signup_completed remains absent from CLIENT_INGESTIBLE_EVENTS.
  O. The frozen EVENT_SCHEMAS entry for signup_completed v1 is
     unchanged ({"provider"} allowed, still optional).

Uses the LOCAL scratch Postgres DB ONLY. No production access. All test
AppUser/activity_events rows are created under a dedicated, obviously-
test-only firebase_uid prefix and deleted in a finally block.
"""

import inspect
import os
import sys
import uuid
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


_FAKE_KUNDALI = {
    "lagna_sign": "Aries",
    "rashi": "Taurus",
    "planets": [{"name": "Moon", "nakshatra": "Rohini"}],
}


def _fake_verify(token):
    # Same technique test_manual_trial_activation.py's test B already
    # uses -- the bearer token itself IS the fake firebase_uid.
    return {"uid": token}


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        from modules.models_user import AppUser
        from modules.models_activity_events import ActivityEvent
        from modules.activity_events.event_schemas import EVENT_SCHEMAS
        from modules.activity_events.ingestion_policy import CLIENT_INGESTIBLE_EVENTS
        import routes.routes_profile_bootstrap as bootstrap_module

        client = app.test_client()
        created_firebase_uids = []

        def cleanup():
            for fb_uid in created_firebase_uids:
                au = AppUser.query.filter_by(firebase_uid=fb_uid).first()
                if au is not None:
                    ActivityEvent.query.filter_by(profile_id=au.id).delete(synchronize_session=False)
                    db.session.delete(au)
            db.session.commit()

        def post_bootstrap(fb_uid, dob="1990-05-15", tob="10:30", pob="Lucknow"):
            return client.post(
                "/api/user/bootstrap",
                json={
                    "name": "Signup Test",
                    "email": "signup-test@example.com",
                    "dob": dob,
                    "tob": tob,
                    "pob": pob,
                    "lat": 26.8467,
                    "lng": 80.9462,
                    "lang": "en",
                },
                headers={"Authorization": f"Bearer {fb_uid}"},
            )

        real_verify = bootstrap_module.firebase_auth.verify_id_token
        real_calculate = bootstrap_module.calculate_full_kundali
        bootstrap_module.firebase_auth.verify_id_token = _fake_verify
        bootstrap_module.calculate_full_kundali = lambda **kwargs: dict(_FAKE_KUNDALI)

        try:
            # ==========================================================
            print("=== A: first-ever bootstrap (created=True) -> exactly one signup_completed ===")
            # ==========================================================
            fb_a = f"phase5d1-signup-a-{uuid.uuid4().hex[:10]}"
            created_firebase_uids.append(fb_a)

            resp_a = post_bootstrap(fb_a)
            body_a = resp_a.get_json()
            check("A: HTTP 200", resp_a.status_code == 200)
            check("A: ok == true", body_a.get("ok") is True)

            app_user_a = AppUser.query.filter_by(firebase_uid=fb_a).first()
            check("A: AppUser was created", app_user_a is not None)

            rows_a = ActivityEvent.query.filter_by(
                event_name="signup_completed", profile_id=app_user_a.id,
            ).all()
            check("A: exactly one signup_completed row", len(rows_a) == 1)

            row_a = rows_a[0] if rows_a else None
            # ==========================================================
            print("\n=== G/H/I/J/K: the persisted row's exact shape ===")
            # ==========================================================
            check("G: event_name == signup_completed", row_a is not None and row_a.event_name == "signup_completed")
            check("G: event_version == 1", row_a is not None and row_a.event_version == 1)
            check("H: profile_id == the newly-created AppUser.id", row_a is not None and row_a.profile_id == app_user_a.id)
            check("I: firebase_uid == the authenticated firebase uid", row_a is not None and row_a.firebase_uid == fb_a)
            check("J: properties == {} exactly", row_a is not None and row_a.properties == {})
            check(
                "K: dedupe_key == signup_completed:APP_USER:<id>",
                row_a is not None and row_a.dedupe_key == f"signup_completed:APP_USER:{app_user_a.id}",
            )
            check("K: platform == backend_internal", row_a is not None and row_a.platform == "backend_internal")
            check("K: source == user_bootstrap", row_a is not None and row_a.source == "user_bootstrap")
            check("K: no entity_type/entity_id was invented", row_a is not None and row_a.entity_type is None and row_a.entity_id is None)

            # ==========================================================
            print("\n=== B/L: a second bootstrap for the SAME firebase_uid (created=False) -> no new row ===")
            # ==========================================================
            resp_b = post_bootstrap(fb_a)  # same user, e.g. AddProfilePage/edit flow
            body_b = resp_b.get_json()
            check("B: HTTP 200 (routine update succeeds)", resp_b.status_code == 200)
            check("B: ok == true", body_b.get("ok") is True)

            rows_b = ActivityEvent.query.filter_by(
                event_name="signup_completed", profile_id=app_user_a.id,
            ).all()
            check("B/L: still exactly one signup_completed row (no duplicate)", len(rows_b) == 1)

            # ==========================================================
            print("\n=== C: a business failure BEFORE commit -> zero signup_completed ===")
            # ==========================================================
            fb_c = f"phase5d1-signup-c-{uuid.uuid4().hex[:10]}"
            created_firebase_uids.append(fb_c)

            def _raise_kundali(**kwargs):
                raise RuntimeError("simulated kundali calculation failure")

            bootstrap_module.calculate_full_kundali = _raise_kundali
            try:
                resp_c = post_bootstrap(fb_c)
            finally:
                bootstrap_module.calculate_full_kundali = lambda **kwargs: dict(_FAKE_KUNDALI)

            check("C: HTTP 500 (business failure surfaced, not swallowed)", resp_c.status_code == 500)
            app_user_c = AppUser.query.filter_by(firebase_uid=fb_c).first()
            check("C: no AppUser was created either", app_user_c is None)
            rows_c = ActivityEvent.query.filter_by(event_name="signup_completed", firebase_uid=fb_c).all()
            check("C: zero signup_completed rows", len(rows_c) == 0)

            # ==========================================================
            print("\n=== D: a commit failure -> zero signup_completed ===")
            # ==========================================================
            fb_d = f"phase5d1-signup-d-{uuid.uuid4().hex[:10]}"
            created_firebase_uids.append(fb_d)

            with patch.object(db.session, "commit", side_effect=RuntimeError("simulated commit failure")):
                resp_d = post_bootstrap(fb_d)
            db.session.rollback()  # clear the failed session state for what follows

            check("D: HTTP 500 (commit failure surfaced, not swallowed)", resp_d.status_code == 500)
            rows_d = ActivityEvent.query.filter_by(event_name="signup_completed", firebase_uid=fb_d).all()
            check("D: zero signup_completed rows", len(rows_d) == 0)
            # The AppUser row itself: get_or_create_app_user() staged an
            # add() that was never committed (commit raised) -- since
            # this test's own db.session was rolled back above, nothing
            # from that half-open transaction persists either.
            app_user_d = AppUser.query.filter_by(firebase_uid=fb_d).first()
            check("D: no AppUser row persisted (commit never actually landed)", app_user_d is None)

            # ==========================================================
            print("\n=== E: analytics failure AFTER a successful commit -> business result unaffected ===")
            # ==========================================================
            fb_e = f"phase5d1-signup-e-{uuid.uuid4().hex[:10]}"
            created_firebase_uids.append(fb_e)

            with patch.object(
                bootstrap_module, "record_event",
                side_effect=RuntimeError("simulated analytics failure"),
            ):
                resp_e = post_bootstrap(fb_e)
            body_e = resp_e.get_json()

            check("E: HTTP 200 (business result unaffected by analytics failure)", resp_e.status_code == 200)
            check("E: ok == true", body_e.get("ok") is True)
            check("E: profileId present in response", body_e.get("profileId") is not None)
            app_user_e = AppUser.query.filter_by(firebase_uid=fb_e).first()
            check("E: AppUser WAS still created (business commit unaffected)", app_user_e is not None)
            rows_e = ActivityEvent.query.filter_by(event_name="signup_completed", firebase_uid=fb_e).all()
            check("E: no signup_completed row (the simulated analytics failure was swallowed)", len(rows_e) == 0)

            # ==========================================================
            print("\n=== F: structural proof -- emission is textually after commit(), gated on `if created:` ===")
            # ==========================================================
            src = inspect.getsource(bootstrap_module.bootstrap_user_profile)
            commit_idx = src.index("db.session.commit()")
            gate_idx = src.index("if created:")
            # The exact call-site text (not the generic substring, which
            # also matches this function's own explanatory comment
            # mentioning _emit_signup_completed() ABOVE the real gate).
            emit_idx = src.index("_emit_signup_completed(firebase_uid=")
            check("F: 'if created:' appears after db.session.commit()", gate_idx > commit_idx)
            check("F: the _emit_signup_completed(...) CALL appears after 'if created:'", emit_idx > gate_idx)

            # ==========================================================
            print("\n=== M: no PII/birth-detail key ever enters the ledger row ===")
            # ==========================================================
            forbidden_keys = {
                "name", "email", "dob", "tob", "pob", "lat", "lng",
                "lagna", "moon_sign", "nakshatra", "phone",
            }
            check(
                "M: signup_completed properties contain no PII/birth-detail keys",
                not (set(row_a.properties.keys()) & forbidden_keys) if row_a is not None else False,
            )

            # ==========================================================
            print("\n=== N/O: frozen contract unchanged ===")
            # ==========================================================
            check(
                "N: signup_completed is still NOT client-ingestible",
                "signup_completed" not in CLIENT_INGESTIBLE_EVENTS,
            )
            check(
                "O: EVENT_SCHEMAS[('signup_completed', 1)] properties unchanged ({'provider'})",
                EVENT_SCHEMAS[("signup_completed", 1)]["properties"] == frozenset({"provider"}),
            )
            check(
                "O: signup_completed remains ledger_eligible",
                EVENT_SCHEMAS[("signup_completed", 1)]["ledger_eligible"] is True,
            )

        finally:
            bootstrap_module.firebase_auth.verify_id_token = real_verify
            bootstrap_module.calculate_full_kundali = real_calculate
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
