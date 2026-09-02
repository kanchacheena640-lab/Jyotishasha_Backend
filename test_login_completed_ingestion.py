"""
test_login_completed_ingestion.py
-------------------------------------------------
Phase 5D.2 -- proves login_completed's new client-ingestion
unblocker: modules/activity_events/ingestion_policy.py's
CLIENT_INGESTIBLE_EVENTS now includes login_completed, and every
existing Phase 3 contract (auth, identity resolution, sanitizer,
dedupe, timestamp/platform/source handling) continues to apply to it
UNCHANGED -- nothing here is special-cased for this one event.

Does NOT re-test the full generic boundary/timestamp/auth suite --
that is exhaustively covered by test_activity_events_ingestion.py
already and continues to pass unmodified (see the regression gate).
This file only proves the generic machinery correctly applies to
login_completed specifically, plus login_completed's own two new
identity-shape cases (no AppUser yet / AppUser already exists) that
no existing test file exercises for this event.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else (same convention as every other activity-events
test file). All test User/AppUser/activity_events rows are created
with a distinct, obviously-test-only id range and deleted in a finally
block, keyed by their own ids -- never a broad DELETE.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

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


def iso(offset=timedelta(0)):
    return (datetime.now(timezone.utc) + offset).isoformat()


# Dedicated, obviously-test-only fixture range -- distinct from
# test_activity_events_ingestion.py's own 979101-979104 range.
UID_WITH_APPUSER = 979201   # User + AppUser (G: resolves profile_id)
UID_ORPHAN = 979202         # User, firebase_uid set, NO AppUser row (F: profile_id NULL)

FB_WITH_APPUSER = "test-fb-uid-979201"
FB_ORPHAN = "test-fb-uid-979202"


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token
    from modules.auth.models import User
    from modules.models_user import AppUser
    from modules.activity_events.ingestion_policy import CLIENT_INGESTIBLE_EVENTS, is_client_ingestible

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        client = app.test_client()
        created_event_ids = []
        created_appuser_ids = []

        def cleanup():
            for eid in created_event_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            if created_appuser_ids:
                AppUser.query.filter(AppUser.id.in_(created_appuser_ids)).delete(synchronize_session=False)
            User.query.filter(User.id.in_([UID_WITH_APPUSER, UID_ORPHAN])).delete(synchronize_session=False)
            db.session.commit()

        cleanup()  # defensive pre-run cleanup, same convention as sibling files

        try:
            # ---- fixtures ----------------------------------------------------
            db.session.add(User(id=UID_WITH_APPUSER, email="login-t1@example.com", provider="google", firebase_uid=FB_WITH_APPUSER))
            db.session.add(User(id=UID_ORPHAN, email="login-t2@example.com", provider="google", firebase_uid=FB_ORPHAN))
            db.session.commit()

            app_user = AppUser(firebase_uid=FB_WITH_APPUSER)
            db.session.add(app_user)
            db.session.commit()
            created_appuser_ids.append(app_user.id)

            def auth_headers(user_id):
                token = create_access_token(identity=str(user_id))
                return {"Authorization": f"Bearer {token}"}

            def post(body, headers=None):
                h = headers if headers is not None else auth_headers(UID_WITH_APPUSER)
                resp = client.post("/api/activity-events", json=body, headers=h)
                if resp.status_code == 201 and resp.get_json(silent=True) and resp.get_json().get("event_id"):
                    created_event_ids.append(resp.get_json()["event_id"])
                return resp

            def base_body(user_id=UID_WITH_APPUSER, **overrides):
                body = {
                    "event_name": "login_completed",
                    "occurred_at": iso(),
                    "platform": "app_android",
                    "source": "flutter_app",
                    "properties": {"method": "google"},
                }
                body.update(overrides)
                return body

            # ==================================================================
            print("=== A: login_completed is now in CLIENT_INGESTIBLE_EVENTS ===")
            # ==================================================================
            check("A: login_completed present in CLIENT_INGESTIBLE_EVENTS", "login_completed" in CLIENT_INGESTIBLE_EVENTS)
            check("A: is_client_ingestible('login_completed') is True", is_client_ingestible("login_completed"))

            # ==================================================================
            print("\n=== B/C/D/E/G: authenticated login_completed (existing AppUser) is accepted and persists correctly ===")
            # ==================================================================
            events_before = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()

            r_g = post(base_body(user_id=UID_WITH_APPUSER), headers=auth_headers(UID_WITH_APPUSER))
            body_g = r_g.get_json()
            check("B: HTTP 201 (written)", r_g.status_code == 201)
            check("B: status == written", body_g.get("status") == "written")

            events_after = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            check("S: exactly one new activity_events row", events_after == events_before + 1)

            row_g = db.session.execute(
                text("SELECT event_name, event_version, firebase_uid, profile_id, properties, platform, source "
                     "FROM activity_events WHERE event_id = :id"),
                {"id": body_g.get("event_id")},
            ).mappings().first()

            check("C: event_name == login_completed", row_g is not None and row_g["event_name"] == "login_completed")
            check("C: event_version == 1", row_g is not None and row_g["event_version"] == 1)
            check("D: properties == {'method': 'google'} exactly", row_g is not None and row_g["properties"] == {"method": "google"})
            check("E: firebase_uid server-resolved to the authenticated user's own uid", row_g is not None and row_g["firebase_uid"] == FB_WITH_APPUSER)
            check("G: profile_id resolves to the existing AppUser.id", row_g is not None and row_g["profile_id"] == app_user.id)
            check("R: platform stored as given", row_g is not None and row_g["platform"] == "app_android")
            check("R: source stored as given", row_g is not None and row_g["source"] == "flutter_app")

            # ==================================================================
            print("\n=== F: login_completed succeeds with NO AppUser yet -- profile_id NULL ===")
            # ==================================================================
            r_f = post(base_body(user_id=UID_ORPHAN), headers=auth_headers(UID_ORPHAN))
            body_f = r_f.get_json()
            check("F: HTTP 201 (written) even though no AppUser exists for this firebase_uid", r_f.status_code == 201)

            row_f = db.session.execute(
                text("SELECT firebase_uid, profile_id FROM activity_events WHERE event_id = :id"),
                {"id": body_f.get("event_id")},
            ).mappings().first()
            check("F: firebase_uid still correctly resolved", row_f is not None and row_f["firebase_uid"] == FB_ORPHAN)
            check("F: profile_id is NULL (no AppUser row exists)", row_f is not None and row_f["profile_id"] is None)

            no_appuser = AppUser.query.filter_by(firebase_uid=FB_ORPHAN).first()
            check("F: login_completed did NOT create an AppUser as a side effect", no_appuser is None)

            # ==================================================================
            print("\n=== H/I: authentication requirement unchanged ===")
            # ==================================================================
            r_h = client.post("/api/activity-events", json=base_body())
            check("H: no JWT -> 401", r_h.status_code == 401)

            r_i = client.post("/api/activity-events", json=base_body(), headers={"Authorization": "Bearer not-a-real-jwt"})
            # Same established, pre-existing behavior test_activity_events_
            # ingestion.py already documents: an undecodable token is 422
            # (flask_jwt_extended's own behavior), not 401 -- unchanged here.
            check("I: undecodable/invalid JWT -> 422 (existing behavior, unchanged)", r_i.status_code == 422)

            # ==================================================================
            print("\n=== J/K: business-truth boundary unaffected -- backend-only events still rejected ===")
            # ==================================================================
            r_j = post(base_body(event_name="signup_completed", properties={"provider": "google"}))
            check("J: signup_completed via this endpoint -> 400 event_not_client_ingestible (still backend-only)",
                  r_j.status_code == 400 and r_j.get_json().get("error") == "event_not_client_ingestible")
            signup_rows = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE event_name = 'signup_completed' AND firebase_uid = :fb"),
                {"fb": FB_WITH_APPUSER},
            ).scalar()
            check("J: no signup_completed row was created", signup_rows == 0)

            r_k = post(base_body(event_name="payment_verified", properties={}))
            check("K: payment_verified (representative financial event) -> 400 event_not_client_ingestible",
                  r_k.status_code == 400 and r_k.get_json().get("error") == "event_not_client_ingestible")

            # ==================================================================
            print("\n=== L/M: sanitizer unchanged -- unknown/sensitive properties never persisted ===")
            # ==================================================================
            r_l = post(base_body(properties={"method": "google", "totally_made_up_key": "x"}))
            check("L: unknown property key -> still 201 (dropped silently, not rejected)", r_l.status_code == 201)
            row_l = db.session.execute(
                text("SELECT properties FROM activity_events WHERE event_id = :id"),
                {"id": r_l.get_json().get("event_id")},
            ).mappings().first()
            check("L: unknown key never entered persisted properties", row_l is not None and "totally_made_up_key" not in row_l["properties"])
            check("L: legitimate method key still kept", row_l is not None and row_l["properties"].get("method") == "google")

            r_m1 = post(base_body(properties={"method": "google", "email": "user@example.com"}))
            check("M: sensitive key present -> still 201 (dropped, not rejected)", r_m1.status_code == 201)
            row_m1 = db.session.execute(
                text("SELECT properties FROM activity_events WHERE event_id = :id"),
                {"id": r_m1.get_json().get("event_id")},
            ).mappings().first()
            check("M: forbidden 'email' key never entered persisted properties", row_m1 is not None and "email" not in row_m1["properties"])
            check("M: legitimate 'method' key unaffected by the dropped sensitive key", row_m1 is not None and row_m1["properties"].get("method") == "google")

            r_m2 = post(base_body(properties={"method": "user@example.com"}))
            check("M: PII-SHAPED VALUE in an allowed key ('method') -> still 201 (dropped, not rejected)", r_m2.status_code == 201)
            row_m2 = db.session.execute(
                text("SELECT properties FROM activity_events WHERE event_id = :id"),
                {"id": r_m2.get_json().get("event_id")},
            ).mappings().first()
            check("M: 'method' dropped when its VALUE looks like an email", row_m2 is not None and "method" not in row_m2["properties"])

            # ==================================================================
            print("\n=== N/O: no special dedupe -- two genuine login events without an idempotency_key both record ===")
            # ==================================================================
            r_n1 = post(base_body())
            r_n2 = post(base_body())
            check("N/O: first login_completed (no idempotency_key) -> 201", r_n1.status_code == 201)
            check("N/O: second, separate login_completed (no idempotency_key) -> ALSO 201, not deduped", r_n2.status_code == 201)
            check("N/O: two distinct event_ids -- genuinely two rows, no once-ever rule", r_n1.get_json().get("event_id") != r_n2.get_json().get("event_id"))

            # ==================================================================
            print("\n=== P: existing generic idempotency_key behavior still applies uniformly ===")
            # ==================================================================
            idem_key = "phase5d2-idem-test-key"
            r_p1 = post(base_body(idempotency_key=idem_key))
            r_p2 = post(base_body(idempotency_key=idem_key))  # SAME user, SAME key
            check("P: first request with idempotency_key -> 201 written", r_p1.status_code == 201)
            check("P: retry with the SAME idempotency_key + same user -> 200 duplicate", r_p2.status_code == 200 and r_p2.get_json().get("status") == "duplicate")

            # ==================================================================
            print("\n=== Q: session_id accepted through the existing generic contract ===")
            # ==================================================================
            r_q = post(base_body(session_id="phase5d2-session-abc"))
            check("Q: session_id accepted -> 201", r_q.status_code == 201)
            row_q = db.session.execute(
                text("SELECT session_id FROM activity_events WHERE event_id = :id"),
                {"id": r_q.get_json().get("event_id")},
            ).mappings().first()
            check("Q: session_id persisted exactly as given", row_q is not None and row_q["session_id"] == "phase5d2-session-abc")

            # ==================================================================
            print("\n=== R: timestamp validation unchanged for login_completed ===")
            # ==================================================================
            r_r1 = post(base_body(occurred_at=None))
            check("R: missing occurred_at -> 400 invalid_occurred_at (unchanged generic rule)",
                  r_r1.status_code == 400 and r_r1.get_json().get("error") == "invalid_occurred_at")

            r_r2 = post(base_body(occurred_at="not-a-real-timestamp"))
            check("R: malformed occurred_at -> 400 invalid_occurred_at (unchanged generic rule)",
                  r_r2.status_code == 400 and r_r2.get_json().get("error") == "invalid_occurred_at")

        finally:
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
