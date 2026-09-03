"""
test_activity_events_ingestion.py
-------------------------------------------------
Focused tests for Phase 3 Step 3: POST /api/activity-events and its
supporting modules (ingestion_policy, request_identity,
ingestion_validation, ingestion_service). Does NOT re-test Phase 2's
own foundation (model/validator/service) -- see
test_activity_events_foundation.py for that; this file's REGRESSION
section only confirms that suite still passes unmodified.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else (same convention as test_app_version_policy.py).
All test User/AppUser/AIReport/activity_events rows are created with a
distinct id range and deleted in a finally block, keyed by their own
ids -- never a broad DELETE.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
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


def iso(offset=timedelta(0), tz=True):
    dt = datetime.now(timezone.utc) + offset
    return dt.isoformat() if tz else dt.replace(tzinfo=None).isoformat()


# =====================================================================
# Fixture ids -- a dedicated, obviously-test-only range.
# =====================================================================
UID_WITH_APPUSER = 979101          # User + one AppUser (normal case)
UID_NO_FIREBASE = 979102           # User, firebase_uid=None (password provider)
UID_ORPHAN_FIREBASE = 979103       # User with firebase_uid, no AppUser row
UID_OTHER_PROFILE = 979104         # separate User + AppUser (ownership-rejection case)

FB_WITH_APPUSER = "test-fb-uid-979101"
FB_ORPHAN = "test-fb-uid-979103"
FB_OTHER = "test-fb-uid-979104"


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token
    from modules.auth.models import User
    from modules.models_user import AppUser
    from modules.models_ai_reports import AIReport

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        client = app.test_client()

        created_event_ids = []
        created_appuser_ids = []
        created_report_ids = []

        def cleanup_users():
            User.query.filter(User.id.in_([
                UID_WITH_APPUSER, UID_NO_FIREBASE, UID_ORPHAN_FIREBASE, UID_OTHER_PROFILE,
            ])).delete(synchronize_session=False)
            db.session.commit()

        def cleanup_appusers_reports():
            if created_report_ids:
                AIReport.query.filter(AIReport.id.in_(created_report_ids)).delete(synchronize_session=False)
            if created_appuser_ids:
                AppUser.query.filter(AppUser.id.in_(created_appuser_ids)).delete(synchronize_session=False)
            db.session.commit()

        def cleanup_events():
            for eid in created_event_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()

        def run_cleanup_steps():
            """Phase 3 Step 5 fix: each step is individually guarded so one
            failing step cannot prevent the others from being attempted.
            Failures are collected and reported, never silently
            swallowed -- a run whose cleanup partially failed must not be
            able to claim a fully clean result."""
            errors = []
            for step_name, step_fn in (
                ("cleanup_events", cleanup_events),
                ("cleanup_appusers_reports", cleanup_appusers_reports),
                ("cleanup_users", cleanup_users),
            ):
                try:
                    step_fn()
                except Exception as exc:
                    db.session.rollback()
                    errors.append((step_name, exc))
            return errors

        # ---- Phase 3 Step 5 fix: defensive pre-run cleanup FIRST, baseline
        # counts captured only AFTER it succeeds -- a prior aborted run's
        # leftover rows must not be folded into this run's "before" count
        # (which would otherwise make a perfectly clean run's own
        # end-of-run baseline comparison fail spuriously).
        pre_run_errors = run_cleanup_steps()
        if pre_run_errors:
            for step_name, exc in pre_run_errors:
                print(f"  WARN: pre-run cleanup step '{step_name}' failed: {exc}")

        users_before = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        app_users_before = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()
        ai_reports_before = db.session.execute(text("SELECT COUNT(*) FROM ai_reports")).scalar()

        try:
            # ---- fixtures --------------------------------------------------
            db.session.add(User(id=UID_WITH_APPUSER, email="ae-t1@example.com", provider="google", firebase_uid=FB_WITH_APPUSER))
            db.session.add(User(id=UID_NO_FIREBASE, email="ae-t2@example.com", provider="password", firebase_uid=None))
            db.session.add(User(id=UID_ORPHAN_FIREBASE, email="ae-t3@example.com", provider="google", firebase_uid=FB_ORPHAN))
            db.session.add(User(id=UID_OTHER_PROFILE, email="ae-t4@example.com", provider="google", firebase_uid=FB_OTHER))
            db.session.commit()

            app_user_main = AppUser(firebase_uid=FB_WITH_APPUSER)
            app_user_other = AppUser(firebase_uid=FB_OTHER)
            db.session.add(app_user_main)
            db.session.add(app_user_other)
            db.session.commit()
            created_appuser_ids.extend([app_user_main.id, app_user_other.id])

            owned_report = AIReport(
                profile_id=app_user_main.id, segment="love", report_type="dna",
                language="en", status="READY",
            )
            other_report = AIReport(
                profile_id=app_user_other.id, segment="career", report_type="dna",
                language="en", status="READY",
            )
            db.session.add(owned_report)
            db.session.add(other_report)
            db.session.commit()
            created_report_ids.extend([owned_report.id, other_report.id])

            def auth_headers(user_id):
                token = create_access_token(identity=str(user_id))
                return {"Authorization": f"Bearer {token}"}

            def post(body, headers=None):
                h = headers if headers is not None else auth_headers(UID_WITH_APPUSER)
                resp = client.post("/api/activity-events", json=body, headers=h)
                if resp.status_code == 201 and resp.get_json(silent=True) and resp.get_json().get("event_id"):
                    created_event_ids.append(resp.get_json()["event_id"])
                return resp

            def base_body(**overrides):
                body = {
                    "event_name": "cta_click",
                    "occurred_at": iso(),
                    "platform": "app_android",
                    "properties": {"cta_id": "ingest-test", "screen_name": "home"},
                }
                body.update(overrides)
                return body

            # =================================================================
            # AUTH
            # =================================================================
            print("AUTH")
            r = client.post("/api/activity-events", json=base_body())
            check("no JWT -> 401", r.status_code == 401)

            r = client.post("/api/activity-events", json=base_body(), headers={"Authorization": "Bearer not-a-real-jwt"})
            # flask_jwt_extended's own, existing, codebase-wide behavior for
            # an undecodable token is 422 (not 401) -- confirmed against
            # this exact route, not assumed. 401 is reserved for "missing"
            # token; this route doesn't override that framework default.
            check("invalid/undecodable JWT -> 422 (flask_jwt_extended's own behavior)", r.status_code == 422)

            bad_token = create_access_token(identity="not-an-int")
            r = client.post("/api/activity-events", json=base_body(), headers={"Authorization": f"Bearer {bad_token}"})
            check("malformed JWT identity -> 401", r.status_code == 401)

            for spoof_field, spoof_value in (
                ("firebase_uid", "someone-elses-uid"),
                ("profile_id", 1),
                ("event_id", "11111111-1111-1111-1111-111111111111"),
                ("recorded_at", iso()),
                ("environment", "production"),
                ("correlation_id", "x"),
                ("dedupe_key", "x"),
            ):
                r = post(base_body(**{spoof_field: spoof_value}))
                check(f"body identity/backend-field spoof '{spoof_field}' -> 400 forbidden_field",
                      r.status_code == 400 and r.get_json().get("error") == "forbidden_field" and r.get_json().get("field") == spoof_field)

            # =================================================================
            # EVENT OWNERSHIP
            # =================================================================
            print("EVENT OWNERSHIP")
            from modules.activity_events.ingestion_policy import CLIENT_INGESTIBLE_EVENTS, is_client_ingestible
            # Phase 5D.2 -- login_completed added to the original Phase 3
            # Step 2 set of 10, making 11. Task 5A -- app_install_attributed
            # added, making 12 (see test_app_install_attributed_ingestion.py
            # for that event's own full coverage, including its unique
            # platform restriction -- not duplicated here). Count re-derived
            # from the real module below, not asserted blind.
            check("exactly 12 client-ingestible events frozen", len(CLIENT_INGESTIBLE_EVENTS) == 12)
            for name in ("session_start", "login_completed", "app_download_intent", "cta_click", "feature_used",
                         "asknow_entry_viewed", "report_discovery_viewed", "report_viewed",
                         "report_downloaded", "subscription_discovery_viewed", "notification_opened",
                         "app_install_attributed"):
                check(f"{name} recognized as client-ingestible", is_client_ingestible(name))
            check("page_view NOT client-ingestible", not is_client_ingestible("page_view"))
            check("payment_verified NOT client-ingestible", not is_client_ingestible("payment_verified"))
            # Phase 5D.2 -- signup_completed (login_completed's own "I.
            # Core" sibling) was explicitly audited as BACKEND-owned
            # (Phase 5D.1) and must remain excluded from this endpoint.
            check("signup_completed NOT client-ingestible (backend-owned, Phase 5D.1)", not is_client_ingestible("signup_completed"))

            r = post(base_body(event_name="page_view"))
            check("page_view via HTTP -> 400 event_not_client_ingestible", r.status_code == 400 and r.get_json().get("error") == "event_not_client_ingestible")

            r = post(base_body(event_name="payment_verified"))
            check("payment_verified via HTTP -> 400 event_not_client_ingestible", r.status_code == 400 and r.get_json().get("error") == "event_not_client_ingestible")

            # Phase 5D.2 -- signup_completed via this same authenticated
            # client endpoint must still be rejected -- making
            # login_completed client-ingestible does not make the client
            # authoritative for signup_completed (backend-owned, Phase
            # 5D.1) or any other backend-only business event.
            r = post(base_body(event_name="signup_completed", properties={"provider": "google"}))
            check("signup_completed via HTTP -> 400 event_not_client_ingestible (still backend-only)",
                  r.status_code == 400 and r.get_json().get("error") == "event_not_client_ingestible")

            r = post(base_body(event_name="totally_not_a_real_event"))
            check("unknown event name -> 400 unknown_event", r.status_code == 400 and r.get_json().get("error") == "unknown_event")

            r = post(base_body(event_name="session_start", properties={"entry_point": "home"}))
            check("session_start (real client event) -> 201", r.status_code == 201)

            # =================================================================
            # TIMESTAMP
            # =================================================================
            print("TIMESTAMP")
            r = post(base_body(occurred_at=iso()))
            check("valid occurred_at -> 201", r.status_code == 201)

            body_missing = base_body()
            del body_missing["occurred_at"]
            r = post(body_missing)
            check("missing occurred_at -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")

            r = post(base_body(occurred_at="not-a-timestamp"))
            check("malformed occurred_at -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")

            r = post(base_body(occurred_at=iso(tz=False)))
            check("occurred_at missing timezone -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")

            r = post(base_body(occurred_at=iso(timedelta(minutes=5))))
            check("occurred_at exactly +5min -> 201 (boundary accepted)", r.status_code == 201)

            r = post(base_body(occurred_at=iso(timedelta(minutes=5, seconds=30))))
            check("occurred_at >5min future -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")

            # Comfortably inside the 7-day boundary, not exactly on it --
            # an exact tie against a live moving clock is inherently
            # flaky (real request-processing latency between computing
            # this value and the server's own now() pushes an exactly-
            # -7d timestamp to appear very slightly MORE than 7 days old
            # by the time it's checked, unlike the future-skew boundary
            # below where the same latency makes it safer, not riskier).
            r = post(base_body(occurred_at=iso(-timedelta(days=6, hours=23, minutes=59))))
            check("occurred_at just inside -7d boundary -> 201 (accepted)", r.status_code == 201)

            r = post(base_body(occurred_at=iso(-timedelta(days=7, minutes=1))))
            check("occurred_at >7d old -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")

            # =================================================================
            # BOUNDARY
            # =================================================================
            print("BOUNDARY")
            huge_body = base_body(properties={"cta_id": "x" * 9000, "screen_name": "home"})
            r = post(huge_body)
            check(">8KB body -> 413", r.status_code == 413)

            r = post(base_body(properties={f"k{i}": "v" for i in range(25)}))
            check(">20 properties keys -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(campaign_context={f"utm_source": "g", **{f"k{i}": "v" for i in range(12)}}))
            check(">10 campaign_context keys -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(notification_context={f"k{i}": "v" for i in range(8)}))
            check(">6 notification_context keys -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(properties={"cta_id": "x" * 300, "screen_name": "home"}))
            check(">256 char string value -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(properties={"cta_id": {"nested": True}, "screen_name": "home"}))
            check("nested dict value -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(properties={"cta_id": [1, 2, 3], "screen_name": "home"}))
            check("nested list value -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(properties={"cta_id": float("nan"), "screen_name": "home"}))
            check("NaN value -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(properties={"cta_id": float("inf"), "screen_name": "home"}))
            check("Infinity value -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(properties={"cta_id": "user@example.com", "screen_name": "home"}))
            check("embedded email -> 201, key dropped not persisted", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("embedded-email value not stored", "cta_id" not in row.properties and row.properties.get("screen_name") == "home")

            r = post(base_body(properties={"cta_id": "call 9876543210 now", "screen_name": "home"}))
            check("embedded phone (substring) -> 201, key dropped not persisted", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("embedded-phone value not stored", "cta_id" not in row.properties)

            fake_jwt_value = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dGhpc2lzbm90cmVhbA"
            r = post(base_body(properties={"cta_id": fake_jwt_value, "screen_name": "home"}))
            check("JWT-shaped value -> 201, key dropped not persisted", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("JWT-shaped value not stored", "cta_id" not in row.properties)

            r = post(base_body(**{"totally_unexpected_top_level_field": "x"}))
            check("unknown top-level field -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            for forbidden_field in ("event_id", "recorded_at", "environment", "firebase_uid", "profile_id", "correlation_id", "dedupe_key"):
                r = post(base_body(**{forbidden_field: "x"}))
                check(f"forbidden backend-controlled field '{forbidden_field}' -> 400 forbidden_field",
                      r.status_code == 400 and r.get_json().get("error") == "forbidden_field")

            # =================================================================
            # PII REGRESSION (Phase 3 Step 5, Fix 2 -- retuned phone heuristic)
            # =================================================================
            print("PII REGRESSION")
            from modules.activity_events.ingestion_validation import _looks_like_phone, _value_content_policy_hit

            must_flag_as_phone = [
                "9876543210",
                "+919876543210",
                "+91 9876543210",
                "98765 43210",
                "98765-43210",
                "call me at 9876543210 tomorrow",
            ]
            for val in must_flag_as_phone:
                check(f"phone heuristic flags {val!r}", _looks_like_phone(val))
                check(f"content policy drops {val!r} (phone)", _value_content_policy_hit(val))

            must_not_flag_as_phone = [
                "550e8400-e29b-41d4-a716-446655440000",
                "3f8a1c02-9b64-4e11-8a20-772104459900",
                "A1B2C3D4-E5F6-4789-ABCD-1234567890AB",  # uppercase UUID variant
                "20260901",
                "ORD12345",
                "home_screen",
                "google_organic",
                "panchang",
            ]
            for val in must_not_flag_as_phone:
                check(f"phone heuristic does NOT flag {val!r}", not _looks_like_phone(val))

            # End-to-end confirmation for the two cases the Step 4 audit
            # specifically demonstrated as broken: a UUID-shaped
            # notification_id and a date-like numeric report_type-ish
            # value must both survive all the way into the persisted row.
            r = post(base_body(event_name="notification_opened", properties={},
                                notification_context={"notification_id": "550e8400-e29b-41d4-a716-446655440000"}))
            check("UUID notification_id -> 201", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT notification_context FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("UUID notification_id persisted, NOT dropped as phone-like",
                      row.notification_context.get("notification_id") == "550e8400-e29b-41d4-a716-446655440000")

            # Phase 3 Step 5 found this survived Phase 3's own (fixed)
            # layer but was still dropped by Phase 2's separate,
            # independent, then-unmodified phone check -- reported as an
            # out-of-scope residual rather than hidden. Phase 3 Step 6
            # fixed that second layer too (event_schemas.py's own
            # _PHONE_RE lower bound raised 8->10, verified in
            # test_activity_events_foundation.py). This now asserts the
            # intended FINAL end-to-end behavior: the value survives BOTH
            # layers and actually reaches the persisted row.
            r = post(base_body(properties={"cta_id": "20260901", "screen_name": "home"}))
            check("8-digit date-like cta_id -> 201", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("8-digit date-like cta_id ('20260901') survives BOTH layers and is persisted",
                      row.properties.get("cta_id") == "20260901")

            # Re-confirm the original genuine-phone-in-properties case (from
            # the BOUNDARY section above) is still caught under the new
            # heuristic -- not just the isolated unit check.
            r = post(base_body(properties={"cta_id": "9876543210", "screen_name": "home"}))
            check("bare 10-digit phone in properties -> 201, still dropped", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("bare 10-digit phone value not stored", "cta_id" not in row.properties and row.properties.get("screen_name") == "home")

            # =================================================================
            # IDENTITY
            # =================================================================
            print("IDENTITY")
            r = post(base_body(), headers=auth_headers(UID_NO_FIREBASE))
            check("firebase_uid NULL on User -> 201 (authenticated, identity fields null)", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT firebase_uid, profile_id FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("firebase_uid stored as NULL", row.firebase_uid is None)
                check("profile_id stored as NULL", row.profile_id is None)

            r = post(base_body(), headers=auth_headers(UID_ORPHAN_FIREBASE))
            check("firebase_uid present, AppUser absent -> 201", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT firebase_uid, profile_id FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("firebase_uid populated", row.firebase_uid == FB_ORPHAN)
                check("profile_id NULL (no AppUser row)", row.profile_id is None)

            r = post(base_body(), headers=auth_headers(UID_WITH_APPUSER))
            check("exactly one AppUser -> 201, profile_id populated", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT profile_id FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("profile_id matches the resolved AppUser", row.profile_id == app_user_main.id)

            # Duplicate AppUser rows -- via mocking, NOT a real second DB row
            # (the partial unique index would reject that anyway).
            class _FakeAppUser:
                def __init__(self, id_):
                    self.id = id_

            with patch("modules.activity_events.request_identity.AppUser") as mock_appuser:
                mock_appuser.query.filter_by.return_value.all.return_value = [_FakeAppUser(9001), _FakeAppUser(9002)]
                events_before_anomaly = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
                r = post(base_body(), headers=auth_headers(UID_WITH_APPUSER))
                events_after_anomaly = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            check("duplicate AppUser rows -> 409 identity_integrity_anomaly", r.status_code == 409 and r.get_json().get("error") == "identity_integrity_anomaly")
            check("duplicate AppUser rows -> NO row written", events_after_anomaly == events_before_anomaly)

            users_after_identity = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            app_users_after_identity = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()
            check("no User rows created by identity resolution (net of test fixtures)", users_after_identity == users_before + 4)
            check("no AppUser rows created by identity resolution (net of test fixtures)", app_users_after_identity == app_users_before + 2)

            # =================================================================
            # IDEMPOTENCY
            # =================================================================
            print("IDEMPOTENCY")
            idem_key = "idem-test-key-001"
            r1 = post(base_body(idempotency_key=idem_key), headers=auth_headers(UID_WITH_APPUSER))
            r2 = post(base_body(idempotency_key=idem_key), headers=auth_headers(UID_WITH_APPUSER))
            check("first request with idempotency_key -> 201 written", r1.status_code == 201 and r1.get_json().get("status") == "written")
            check("retry with SAME idempotency_key + same user -> 200 duplicate", r2.status_code == 200 and r2.get_json().get("status") == "duplicate")

            r3 = post(base_body(idempotency_key=idem_key), headers=auth_headers(UID_ORPHAN_FIREBASE))
            check("SAME idempotency_key, DIFFERENT user -> 201 (no cross-account collision)", r3.status_code == 201)

            r4 = post(base_body())
            r5 = post(base_body())
            check("no idempotency_key -> distinct events both succeed", r4.status_code == 201 and r5.status_code == 201 and r4.get_json()["event_id"] != r5.get_json()["event_id"])

            # =================================================================
            # REPORTS
            # =================================================================
            print("REPORTS")
            r = post(base_body(event_name="report_viewed", entity_type="ai_report", entity_id=str(owned_report.id), properties={}), headers=auth_headers(UID_WITH_APPUSER))
            check("report_viewed on OWNED report -> 201", r.status_code == 201)

            r = post(base_body(event_name="report_viewed", entity_type="ai_report", entity_id=str(other_report.id), properties={}), headers=auth_headers(UID_WITH_APPUSER))
            check("report_viewed on OTHER profile's report -> 403 entity_not_owned", r.status_code == 403 and r.get_json().get("error") == "entity_not_owned")

            r = post(base_body(event_name="report_downloaded", entity_type="ai_report", entity_id=str(owned_report.id), properties={}), headers=auth_headers(UID_ORPHAN_FIREBASE))
            check("report_downloaded with profile_id absent -> 403 entity_not_owned", r.status_code == 403 and r.get_json().get("error") == "entity_not_owned")

            r = post(base_body(event_name="report_viewed", entity_type="order", entity_id=str(owned_report.id), properties={}), headers=auth_headers(UID_WITH_APPUSER))
            check("invalid entity_type ('order') -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(event_name="report_viewed", entity_type="ai_report", entity_id="not-a-number", properties={}), headers=auth_headers(UID_WITH_APPUSER))
            check("invalid entity_id (non-numeric) -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            r = post(base_body(event_name="cta_click", entity_type="ai_report", entity_id=str(owned_report.id)))
            check("entity fields on an unrelated event (cta_click) -> 400 invalid_field", r.status_code == 400 and r.get_json().get("error") == "invalid_field")

            # =================================================================
            # PERSISTENCE
            # =================================================================
            print("PERSISTENCE")
            r = post(base_body())
            check("valid persistence -> 201", r.status_code == 201)
            if r.status_code == 201:
                from sqlalchemy import text as _t
                row = db.session.execute(_t("SELECT environment, recorded_at, occurred_at FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).fetchone()
                check("environment is backend-controlled (populated, never from client)", row.environment is not None)
                check("recorded_at is DB-controlled (populated)", row.recorded_at is not None)

            with patch("modules.activity_events.ingestion_service.record_event") as mock_record:
                from modules.activity_events.service import LedgerWriteResult
                mock_record.return_value = LedgerWriteResult(status="write_failed")
                r = post(base_body())
            check("ledger write failure -> 503", r.status_code == 503 and r.get_json().get("error") == "temporarily_unavailable")

            # Phase 4 prerequisite fix, requirement E: a missing/invalid
            # ACTIVITY_EVENTS_ENVIRONMENT must surface through this
            # endpoint exactly like any other ledger-write failure --
            # controlled 503, no exception/config detail in the body --
            # not a 500 or an uncaught exception. Saved/restored exactly.
            _original_env_for_e = os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT")
            try:
                os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
                r = post(base_body())
                check("E: missing ACTIVITY_EVENTS_ENVIRONMENT -> 503, not 500/exception", r.status_code == 503)
                check("E: missing env -> controlled body, no config/exception detail leaked",
                      r.get_json() == {"error": "temporarily_unavailable"})

                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "staging"  # not in ALLOWED_ENVIRONMENTS
                r = post(base_body())
                check("E: invalid ACTIVITY_EVENTS_ENVIRONMENT -> 503, not 500/exception", r.status_code == 503)
                check("E: invalid env -> controlled body, no config/exception detail leaked",
                      r.get_json() == {"error": "temporarily_unavailable"})
            finally:
                if _original_env_for_e is None:
                    os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
                else:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = _original_env_for_e
                check("E: ACTIVITY_EVENTS_ENVIRONMENT restored after test", os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT") == _original_env_for_e)

        finally:
            final_cleanup_errors = run_cleanup_steps()

        # Cleanup failures are reported, not hidden -- a run whose cleanup
        # partially failed must not be able to claim "fully clean".
        check("final cleanup completed with no errors", len(final_cleanup_errors) == 0)
        for step_name, exc in final_cleanup_errors:
            print(f"  FAIL DETAIL: cleanup step '{step_name}' raised: {exc}")

        # Independently verify activity_events test rows are actually gone
        # -- not inferred from "cleanup didn't raise", checked directly.
        remaining_events = 0
        for eid in created_event_ids:
            remaining_events += db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE event_id = :id"), {"id": eid}).scalar()
        check(f"all {len(created_event_ids)} ingestion test rows cleaned up (0 remain)", remaining_events == 0)

        users_final = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        app_users_final = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()
        ai_reports_final = db.session.execute(text("SELECT COUNT(*) FROM ai_reports")).scalar()
        check("users table back to baseline", users_final == users_before)
        check("app_users table back to baseline", app_users_final == app_users_before)
        check("ai_reports table back to baseline", ai_reports_final == ai_reports_before)

    # =====================================================================
    # REGRESSION
    # =====================================================================
    print("REGRESSION")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    foundation = subprocess.run(
        [sys.executable, "test_activity_events_foundation.py"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    check("existing Phase-2 foundation suite still passes unmodified", foundation.returncode == 0)
    if foundation.returncode != 0:
        print(foundation.stdout)
        print(foundation.stderr)

    import_check = subprocess.run(
        [sys.executable, "-c", "from app import app; print('OK')"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    check("app imports cleanly", import_check.returncode == 0 and "OK" in import_check.stdout)

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
