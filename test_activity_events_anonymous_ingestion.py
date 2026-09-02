"""
test_activity_events_anonymous_ingestion.py
-------------------------------------------------
Task 2B focused tests: POST /api/activity-events/anonymous and its
supporting modules (anonymous_ingestion_policy, anonymous_ingestion_
service). Does NOT re-test Phase 2/3's own foundation or the
authenticated endpoint's full behavior -- see
test_activity_events_foundation.py and test_activity_events_ingestion.py
for those; this file's own AUTH-REGRESSION section only smoke-checks
that the authenticated route is untouched and still JWT-required. The
full existing suites (foundation/ingestion/analytics/signup/login/
subscription) are re-run separately as part of Task 2B's regression
gate, not duplicated here.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else (same convention as every other test_activity_
events_*.py file in this repo). Every activity_events row this file
creates is deleted in a finally block, keyed by its own event_id --
never a broad DELETE. No User/AppUser/AIReport row is ever created by
this file (Q verifies none are created as a side effect either).
"""

import os
import sys
from datetime import datetime, timedelta, timezone

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


ENDPOINT = "/api/activity-events/anonymous"


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        client = app.test_client()
        created_event_ids = []

        def cleanup_events():
            for eid in created_event_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()

        def post(body):
            resp = client.post(ENDPOINT, json=body)
            if resp.status_code == 201 and resp.get_json(silent=True) and resp.get_json().get("event_id"):
                created_event_ids.append(resp.get_json()["event_id"])
            return resp

        def base_body(**overrides):
            body = {
                "event_name": "cta_click",
                "occurred_at": iso(),
                "session_id": "anon-sess-0001",
                "properties": {"cta_id": "home_ask_now_hero", "screen_name": "dashboard_home"},
            }
            body.update(overrides)
            return body

        users_before = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
        app_users_before = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()

        try:
            # =================================================================
            # A. Each approved anonymous event accepted with a valid payload
            # =================================================================
            print("A. approved events accepted")
            r = post(base_body(event_name="cta_click", properties={"cta_id": "x", "screen_name": "y"}))
            check("A1: cta_click -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            r = post(base_body(event_name="feature_used", properties={"feature_name": "kundali_generate"}))
            check("A2: feature_used -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            r = post(base_body(
                event_name="app_download_intent",
                properties={"cta_location": "sticky_footer"},
                campaign_context={"utm_source": "site_global", "utm_medium": "sticky_cta", "utm_campaign": "app_download"},
            ))
            check("A3: app_download_intent -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            r = post(base_body(event_name="report_discovery_viewed", properties={"report_type": "love"}))
            check("A4: report_discovery_viewed -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            r = post(base_body(event_name="subscription_discovery_viewed", properties={"plan": "monthly", "placement": "explore"}))
            check("A5: subscription_discovery_viewed -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            # =================================================================
            # B. Every non-allowlisted canonical event rejected
            # =================================================================
            print("B. non-allowlisted canonical events rejected")
            for name in (
                "login_completed", "signup_completed", "session_start",
                "payment_verified", "subscription_started", "notification_sent",
                "report_viewed", "asknow_entry_viewed", "report_generation_completed",
            ):
                r = post(base_body(event_name=name, properties={}))
                check(
                    f"B: {name} -> 400 event_not_anonymous_ingestible",
                    r.status_code == 400 and r.get_json().get("error") == "event_not_anonymous_ingestible",
                )

            # =================================================================
            # C. Unknown event rejected
            # =================================================================
            print("C. unknown event")
            r = post(base_body(event_name="totally_fake_event_xyz", properties={}))
            check("C: unknown event -> 400 unknown_event", r.status_code == 400 and r.get_json().get("error") == "unknown_event")

            # =================================================================
            # D. page_view rejected
            # =================================================================
            print("D. page_view rejected")
            r = post(base_body(event_name="page_view", properties={}))
            check(
                "D: page_view -> 400 event_not_anonymous_ingestible (never reaches ledger-eligibility check)",
                r.status_code == 400 and r.get_json().get("error") == "event_not_anonymous_ingestible",
            )

            # =================================================================
            # E. platform cannot be spoofed
            # =================================================================
            print("E. platform cannot be spoofed")
            r = post(base_body(platform="app_android"))
            check("E: platform in body -> 400 forbidden_field", r.status_code == 400 and r.get_json().get("error") == "forbidden_field" and r.get_json().get("field") == "platform")

            # =================================================================
            # F. environment cannot be supplied/overridden
            # =================================================================
            print("F. environment cannot be supplied")
            r = post(base_body(environment="production"))
            check("F: environment in body -> 400 forbidden_field", r.status_code == 400 and r.get_json().get("error") == "forbidden_field" and r.get_json().get("field") == "environment")

            # =================================================================
            # G. firebase_uid/profile_id cannot be supplied
            # =================================================================
            print("G. identity fields cannot be supplied")
            r = post(base_body(firebase_uid="some-uid"))
            check("G1: firebase_uid in body -> 400 forbidden_field", r.status_code == 400 and r.get_json().get("field") == "firebase_uid")
            r = post(base_body(profile_id=123))
            check("G2: profile_id in body -> 400 forbidden_field", r.status_code == 400 and r.get_json().get("field") == "profile_id")

            # =================================================================
            # H. backend-owned fields rejected
            # =================================================================
            print("H. backend-owned fields rejected")
            for field, value in (
                ("event_id", "11111111-1111-1111-1111-111111111111"),
                ("recorded_at", iso()),
                ("correlation_id", "corr-1"),
                ("dedupe_key", "dk-1"),
                ("anonymous_id", "anon-1"),
                ("entity_type", "ai_report"),
                ("entity_id", "1"),
                ("source", "web"),
                ("notification_context", {"notification_id": "n1"}),
                ("idempotency_key", "idem-1"),
            ):
                r = post(base_body(**{field: value}))
                check(f"H: {field} in body -> 400 forbidden_field", r.status_code == 400 and r.get_json().get("field") == field)

            # =================================================================
            # I. missing session_id rejected
            # =================================================================
            print("I. missing session_id")
            body_no_session = base_body()
            del body_no_session["session_id"]
            r = post(body_no_session)
            check("I: missing session_id -> 400 invalid_field session_id", r.status_code == 400 and r.get_json().get("field") == "session_id")

            # =================================================================
            # J. malformed/oversized session_id rejected
            # =================================================================
            print("J. malformed/oversized session_id")
            r = post(base_body(session_id="bad session! id"))
            check("J1: session_id with disallowed chars -> 400 invalid_field", r.status_code == 400 and r.get_json().get("field") == "session_id")
            r = post(base_body(session_id="x" * 65))
            check("J2: session_id over 64 chars -> 400 invalid_field", r.status_code == 400 and r.get_json().get("field") == "session_id")
            r = post(base_body(session_id=""))
            check("J3: empty session_id -> 400 invalid_field", r.status_code == 400 and r.get_json().get("field") == "session_id")

            # =================================================================
            # K. invalid occurred_at
            # =================================================================
            print("K. invalid occurred_at")
            r = post(base_body(occurred_at=iso(tz=False)))
            check("K1: naive occurred_at -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")
            r = post(base_body(occurred_at=iso(offset=timedelta(hours=1))))
            check("K2: 1h in the future -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")
            r = post(base_body(occurred_at=iso(offset=-timedelta(days=10))))
            check("K3: 10 days old -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")
            r = post(base_body(occurred_at="not-a-timestamp"))
            check("K4: malformed occurred_at -> 400 invalid_occurred_at", r.status_code == 400 and r.get_json().get("error") == "invalid_occurred_at")

            # =================================================================
            # L. properties schema enforcement (unknown key dropped, not rejected)
            # =================================================================
            print("L. properties schema enforcement")
            r = post(base_body(event_name="cta_click", properties={"cta_id": "x", "screen_name": "y", "bogus_key": "z"}))
            check("L1: unknown property key -> still 201 written (dropped, not rejected)", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(text("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).scalar()
                check("L2: unknown property key absent from persisted row", "bogus_key" not in row)
                check("L3: allowlisted keys retained", row.get("cta_id") == "x" and row.get("screen_name") == "y")

            r = post(base_body(properties=["not", "a", "dict"]))
            check("L4: properties as a list -> 400 invalid_field properties", r.status_code == 400 and r.get_json().get("field") == "properties")

            # =================================================================
            # M. nested/oversized properties rejected
            # =================================================================
            print("M. nested/oversized properties rejected")
            r = post(base_body(properties={"cta_id": {"nested": "dict"}, "screen_name": "y"}))
            check("M1: nested dict value -> 400 invalid_field properties", r.status_code == 400 and r.get_json().get("field") == "properties")
            oversized = {f"k{i}": "v" for i in range(21)}
            r = post(base_body(properties=oversized))
            check("M2: >20 property keys -> 400 invalid_field properties", r.status_code == 400 and r.get_json().get("field") == "properties")
            r = post(base_body(properties={"cta_id": "x" * 257, "screen_name": "y"}))
            check("M3: oversized string value -> 400 invalid_field properties", r.status_code == 400 and r.get_json().get("field") == "properties")

            # =================================================================
            # N. campaign_context accepted for approved keys
            # =================================================================
            print("N. campaign_context approved keys")
            r = post(base_body(
                event_name="app_download_intent",
                properties={"cta_location": "hero"},
                campaign_context={"utm_source": "newsletter", "utm_medium": "email", "utm_campaign": "launch"},
            ))
            check("N1: valid campaign_context -> 201 written", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(text("SELECT campaign_context FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).scalar()
                check("N2: campaign_context persisted with exact values", row == {"utm_source": "newsletter", "utm_medium": "email", "utm_campaign": "launch"})

            # =================================================================
            # O. unsafe referrer query/fragment does NOT persist
            # =================================================================
            print("O. referrer normalization")
            r = post(base_body(campaign_context={"referrer": "https://example.com/landing/page?utm_source=evil&secret=abc123#frag"}))
            check("O1: referrer with query+fragment -> 201 written", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(text("SELECT campaign_context FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).scalar()
                check("O2: persisted referrer has no query string", row is not None and "?" not in row.get("referrer", "?"))
                check("O3: persisted referrer has no fragment", row is not None and "#" not in row.get("referrer", "#"))
                check("O4: persisted referrer is exactly origin+path", row is not None and row.get("referrer") == "https://example.com/landing/page")

            r = post(base_body(campaign_context={"referrer": "not-a-url-at-all"}))
            check("O5: unparseable referrer -> still 201 written (soft-dropped, not rejected)", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(text("SELECT campaign_context FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).scalar()
                check("O6: unparseable referrer key absent from persisted row", not row or "referrer" not in row)

            # =================================================================
            # P. forbidden PII/sensitive keys/values do not persist
            # =================================================================
            print("P. PII/sensitive keys/values do not persist")
            r = post(base_body(properties={"cta_id": "user@example.com", "screen_name": "home"}))
            check("P1: PII-shaped value in an allowlisted key -> still 201 written (dropped)", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(text("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).scalar()
                check("P2: PII-shaped cta_id value dropped from persisted row", "cta_id" not in row)
                check("P3: unaffected sibling key retained", row.get("screen_name") == "home")

            r = post(base_body(properties={"cta_id": "x", "screen_name": "y", "dob": "1990-01-01"}))
            check("P4: dob key (not in cta_click schema) -> still 201 written (dropped)", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(text("SELECT properties FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).scalar()
                check("P5: dob key absent from persisted row", "dob" not in row)

            r = post(base_body(campaign_context={"utm_source": "a", "email": "x@y.com"}))
            check("P6: forbidden campaign_context key -> still 201 written (dropped)", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(text("SELECT campaign_context FROM activity_events WHERE event_id = :id"), {"id": r.get_json()["event_id"]}).scalar()
                check("P7: forbidden campaign_context key absent from persisted row", not row or "email" not in row)

            # =================================================================
            # Q. no users/app_users/profile identity records created
            # =================================================================
            print("Q. no identity records created as a side effect")
            users_after = db.session.execute(text("SELECT COUNT(*) FROM users")).scalar()
            app_users_after = db.session.execute(text("SELECT COUNT(*) FROM app_users")).scalar()
            check("Q1: users table row count unchanged", users_after == users_before)
            check("Q2: app_users table row count unchanged", app_users_after == app_users_before)

            # =================================================================
            # R. resulting row shape
            # =================================================================
            print("R. resulting row shape")
            r = post(base_body(event_name="cta_click", session_id="anon-sess-shape-check", properties={"cta_id": "a", "screen_name": "b"}))
            check("R1: write succeeds", r.status_code == 201)
            if r.status_code == 201:
                row = db.session.execute(
                    text(
                        "SELECT platform, environment, firebase_uid, profile_id, session_id, "
                        "event_name, event_version FROM activity_events WHERE event_id = :id"
                    ),
                    {"id": r.get_json()["event_id"]},
                ).mappings().first()
                check("R2: platform = website", row["platform"] == "website")
                check("R3: environment resolved server-side (matches ACTIVITY_EVENTS_ENVIRONMENT)", row["environment"] == os.environ["ACTIVITY_EVENTS_ENVIRONMENT"])
                check("R4: firebase_uid IS NULL", row["firebase_uid"] is None)
                check("R5: profile_id IS NULL", row["profile_id"] is None)
                check("R6: session_id matches request", row["session_id"] == "anon-sess-shape-check")
                check("R7: event_name matches request", row["event_name"] == "cta_click")
                check("R8: event_version defaults to 1", row["event_version"] == 1)

            # =================================================================
            # S. existing authenticated endpoint smoke-check (untouched)
            # =================================================================
            print("S. authenticated endpoint unchanged (smoke check)")
            r = client.post("/api/activity-events", json={"event_name": "cta_click", "occurred_at": iso(), "platform": "app_android", "properties": {}})
            check("S: authenticated endpoint still requires JWT -> 401 with no auth header", r.status_code == 401)

        finally:
            cleanup_events()

    print("\n==================================================")
    print(f"RESULT: {passed} passed, {failed} failed")
    print("==================================================")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
