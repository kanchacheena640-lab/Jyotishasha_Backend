"""
test_app_install_attributed_ingestion.py
-------------------------------------------------
Task 5A -- proves the new canonical event `app_install_attributed`
(v1): "Google Play install attribution was captured by the Android app
and later associated with an authenticated app lifecycle." NOT GA4
first_open, NOT a raw install counter, NOT app_download_intent (the
website's own click-intent fact), and NOT proof of a user-level
website-to-install conversion -- see event_schemas.py's own
registration comment for the frozen meaning this test file locks in by
name.

Does NOT re-test the full generic boundary/timestamp/auth suite --
that is exhaustively covered by test_activity_events_ingestion.py
already and continues to pass unmodified (see the regression gate).
This file proves: the event is canonical, its {} properties schema,
its campaign_context usage, its authenticated-Android-only platform
restriction (the one genuinely new mechanism this task adds), its
absence from the anonymous endpoint, and that app_download_intent's
own existing platform freedom is completely unaffected by that new
restriction.

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


# Dedicated, obviously-test-only fixture range -- distinct from every
# other activity-events test file's own range.
UID_MAIN = 979301
FB_MAIN = "test-fb-uid-979301"


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token
    from modules.auth.models import User
    from modules.models_user import AppUser
    from modules.activity_events.event_schemas import is_known_event, is_ledger_eligible
    from modules.activity_events.ingestion_policy import (
        CLIENT_INGESTIBLE_EVENTS,
        is_client_ingestible,
        is_platform_allowed_for_event,
        EVENT_PLATFORM_RESTRICTIONS,
    )
    from modules.activity_events.anonymous_ingestion_policy import ANONYMOUS_WEBSITE_EVENTS

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        client = app.test_client()
        created_event_ids = []

        def cleanup():
            for eid in created_event_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            User.query.filter(User.id == UID_MAIN).delete(synchronize_session=False)
            db.session.commit()

        cleanup()  # defensive pre-run cleanup, same convention as sibling files

        try:
            # ---- fixtures ----------------------------------------------------
            db.session.add(User(id=UID_MAIN, email="install-attr-t1@example.com", provider="google", firebase_uid=FB_MAIN))
            db.session.commit()

            def auth_headers():
                token = create_access_token(identity=str(UID_MAIN))
                return {"Authorization": f"Bearer {token}"}

            def post(body):
                resp = client.post("/api/activity-events", json=body, headers=auth_headers())
                if resp.status_code == 201 and resp.get_json(silent=True) and resp.get_json().get("event_id"):
                    created_event_ids.append(resp.get_json()["event_id"])
                return resp

            def post_anonymous(body):
                return client.post("/api/activity-events/anonymous", json=body)

            def base_body(**overrides):
                body = {
                    "event_name": "app_install_attributed",
                    "occurred_at": iso(),
                    "platform": "app_android",
                    "source": "flutter_app",
                }
                body.update(overrides)
                return body

            # ==================================================================
            print("=== 1: app_install_attributed v1 is canonical ===")
            # ==================================================================
            check("1: is_known_event('app_install_attributed', 1) is True", is_known_event("app_install_attributed", 1))
            check("1: is_ledger_eligible('app_install_attributed', 1) is True", is_ledger_eligible("app_install_attributed", 1))
            check("1: present in CLIENT_INGESTIBLE_EVENTS", "app_install_attributed" in CLIENT_INGESTIBLE_EVENTS)
            check("1: is_client_ingestible('app_install_attributed') is True", is_client_ingestible("app_install_attributed"))
            check("1: NOT present in ANONYMOUS_WEBSITE_EVENTS", "app_install_attributed" not in ANONYMOUS_WEBSITE_EVENTS)
            check(
                "1: EVENT_PLATFORM_RESTRICTIONS restricts it to exactly {app_android}",
                EVENT_PLATFORM_RESTRICTIONS.get("app_install_attributed") == frozenset({"app_android"}),
            )
            check("1: is_platform_allowed_for_event helper agrees (app_android)", is_platform_allowed_for_event("app_install_attributed", "app_android"))
            check("1: is_platform_allowed_for_event helper agrees (app_ios rejected)", not is_platform_allowed_for_event("app_install_attributed", "app_ios"))
            check("1: is_platform_allowed_for_event helper agrees (website rejected)", not is_platform_allowed_for_event("app_install_attributed", "website"))
            check("1: unrestricted event (cta_click) is unaffected by the restriction map", is_platform_allowed_for_event("cta_click", "website"))

            # ==================================================================
            print("\n=== 2/12: properties={} accepted, persists correctly ===")
            # ==================================================================
            events_before = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            r2 = post(base_body(properties={}))
            check("2: HTTP 201 written with properties={}", r2.status_code == 201 and r2.get_json().get("status") == "written")
            events_after = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            check("2: exactly one new row", events_after == events_before + 1)

            row2 = db.session.execute(
                text(
                    "SELECT event_name, event_version, platform, source, firebase_uid, profile_id, "
                    "properties, campaign_context FROM activity_events WHERE event_id = :id"
                ),
                {"id": r2.get_json().get("event_id")},
            ).mappings().first()
            check("12: event_name == app_install_attributed", row2 is not None and row2["event_name"] == "app_install_attributed")
            check("12: event_version == 1", row2 is not None and row2["event_version"] == 1)
            check("12: platform == app_android", row2 is not None and row2["platform"] == "app_android")
            check("12: properties == {} exactly", row2 is not None and row2["properties"] == {})
            check("12: firebase_uid server-resolved correctly", row2 is not None and row2["firebase_uid"] == FB_MAIN)

            # ==================================================================
            print("\n=== 3/11: unexpected/PII-shaped properties dropped, never persisted (existing generic sanitizer, unchanged) ===")
            # ==================================================================
            r3 = post(base_body(properties={"utm_source": "should_not_go_here", "email": "user@example.com"}))
            check("3: still 201 (dropped, not rejected -- matches existing codebase convention)", r3.status_code == 201)
            row3 = db.session.execute(
                text("SELECT properties FROM activity_events WHERE event_id = :id"),
                {"id": r3.get_json().get("event_id")},
            ).mappings().first()
            check("3: properties persisted as {} -- nothing from the schema-less allowlist survives", row3 is not None and row3["properties"] == {})
            check("11: no PII key (email) anywhere in the persisted row", row3 is not None and "email" not in row3["properties"])

            # ==================================================================
            print("\n=== 4: campaign_context with allowed UTM fields accepted ===")
            # ==================================================================
            r4 = post(base_body(campaign_context={"utm_source": "google_play_referrer", "utm_medium": "daily_panchang", "utm_campaign": "hero"}))
            check("4: HTTP 201 written with campaign_context", r4.status_code == 201)
            row4 = db.session.execute(
                text("SELECT campaign_context, properties FROM activity_events WHERE event_id = :id"),
                {"id": r4.get_json().get("event_id")},
            ).mappings().first()
            check(
                "4: campaign_context persisted with exactly the 3 UTM fields",
                row4 is not None and row4["campaign_context"] == {"utm_source": "google_play_referrer", "utm_medium": "daily_panchang", "utm_campaign": "hero"},
            )
            check("4: properties remains {} even when campaign_context is populated", row4 is not None and row4["properties"] == {})

            # ==================================================================
            print("\n=== 5: authenticated Android ingestion accepted (already proven above; explicit restatement) ===")
            # ==================================================================
            check("5: platform=app_android accepted -> 201 (see test 2/4 above)", r2.status_code == 201 and r4.status_code == 201)

            # ==================================================================
            print("\n=== 6: anonymous endpoint rejects app_install_attributed ===")
            # ==================================================================
            r6 = post_anonymous({
                "event_name": "app_install_attributed",
                "occurred_at": iso(),
                "session_id": "install-attr-anon-session-1",
                "properties": {},
            })
            check(
                "6: anonymous endpoint -> 400 event_not_anonymous_ingestible",
                r6.status_code == 400 and r6.get_json().get("error") == "event_not_anonymous_ingestible",
            )
            anon_rows = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE event_name = 'app_install_attributed' AND session_id = 'install-attr-anon-session-1'")
            ).scalar()
            check("6: no row was created via the anonymous endpoint", anon_rows == 0)

            # ==================================================================
            print("\n=== 7: website platform cannot produce this event (authenticated endpoint) ===")
            # ==================================================================
            r7 = post(base_body(platform="website", properties={}))
            check(
                "7: platform=website -> 400 invalid_field/platform (new per-event restriction)",
                r7.status_code == 400 and r7.get_json().get("error") == "invalid_field" and r7.get_json().get("field") == "platform",
            )

            # ==================================================================
            print("\n=== 8: iOS platform cannot produce this event ===")
            # ==================================================================
            r8 = post(base_body(platform="app_ios", properties={}))
            check(
                "8: platform=app_ios -> 400 invalid_field/platform (new per-event restriction)",
                r8.status_code == 400 and r8.get_json().get("error") == "invalid_field" and r8.get_json().get("field") == "platform",
            )

            # ==================================================================
            print("\n=== 9: app_download_intent's own platform freedom is completely unaffected ===")
            # ==================================================================
            r9_website = post({
                "event_name": "app_download_intent",
                "occurred_at": iso(),
                "platform": "website",
                "properties": {"cta_location": "daily_panchang_primary_cta"},
            })
            check("9: app_download_intent still accepted from platform=website (unrestricted, unchanged)", r9_website.status_code == 201)
            r9_ios = post({
                "event_name": "app_download_intent",
                "occurred_at": iso(),
                "platform": "app_ios",
                "properties": {"cta_location": "x"},
            })
            check("9: app_download_intent still accepted from platform=app_ios (unrestricted, unchanged)", r9_ios.status_code == 201)

            # ==================================================================
            print("\n=== 10: sibling regression suites re-run separately at the gate (not duplicated here) ===")
            # ==================================================================
            print("  (see Task 5A final report's regression-gate section)")

        finally:
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
