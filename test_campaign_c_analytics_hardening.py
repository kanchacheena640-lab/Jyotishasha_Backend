"""
test_campaign_c_analytics_hardening.py
---------------------------------------
Campaign C Analytics Hardening -- proves each of the 5 backend-facing
fixes from the Campaign C Analytics Final Audit follow-up:

  A. notification_opened / destination_opened idempotency (P0). Uses the
     REAL POST /api/activity-events route (not a direct service call) so
     this is a genuine end-to-end proof of the exact request shape the
     Flutter client (notification_opened_producer.dart /
     destination_opened_producer.dart) now sends, reusing the
     PRE-EXISTING idempotency_key -> dedupe_key -> partial-unique-index
     infrastructure (already proven generically by
     test_activity_events_ingestion.py's own IDEMPOTENCY section) --
     nothing new was added to that mechanism, only a key is now supplied
     for these two event names.
  B. attempted_count -- delivery_counts total minus PENDING minus
     SUPPRESSED.
  C. retry_exhausted_count / permanent_failure_count -- reliably split
     out of FAILED_PERMANENT using campaign_worker.py's own existing
     'RETRY_EXHAUSTED' error_code sentinel, no schema change.
  D. campaign_conversion_breakdown() -- per-purpose (Report/Ask Now/
     Subscription) conversion counts, same single-touch/24h/last-click
     algorithm, same combined total as before this pass.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else (same convention as every other test_*.py in this
repo). All fixture rows are created with a distinct id range and
deleted at the end.
"""
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("RAZORPAY_KEY_ID", "test-dummy-not-used")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test-dummy-not-used")
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


def iso(dt):
    return dt.isoformat()


UID = 979601  # dedicated, obviously-test-only id, distinct from every other test file's range
FB = "test-fb-campaign-c-hardening"


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token
    from modules.auth.models import User
    from modules.models_activity_events import ActivityEvent
    from modules.models_saved_audience import SavedAudience
    from notifications.campaign_models import NotificationCampaign
    from notifications.campaign_execution_models import (
        NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
    )
    from notifications import campaign_metrics_service as metrics_svc

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        client = app.test_client()
        created_event_ids = []
        created_execution_ids = []
        created_campaign_ids = []
        created_audience_ids = []

        def cleanup():
            for eid in created_event_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            for execution_id in created_execution_ids:
                NotificationCampaignAttempt.query.filter(
                    NotificationCampaignAttempt.delivery_id.in_(
                        db.session.query(NotificationCampaignDelivery.id)
                        .filter(NotificationCampaignDelivery.execution_id == execution_id)
                    )
                ).delete(synchronize_session=False)
                NotificationCampaignDelivery.query.filter_by(execution_id=execution_id).delete(synchronize_session=False)
            NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(created_execution_ids)).delete(synchronize_session=False)
            NotificationCampaign.query.filter(NotificationCampaign.id.in_(created_campaign_ids)).delete(synchronize_session=False)
            SavedAudience.query.filter(SavedAudience.id.in_(created_audience_ids)).delete(synchronize_session=False)
            db.session.execute(text("DELETE FROM activity_events WHERE firebase_uid = :fb"), {"fb": FB})
            User.query.filter_by(id=UID).delete(synchronize_session=False)
            db.session.commit()

        # Pre-run defensive cleanup (a prior aborted run's leftovers must
        # never bleed into this run's own assertions).
        try:
            cleanup()
        except Exception:
            db.session.rollback()

        try:
            db.session.add(User(id=UID, email="campaign-c-hardening@example.com", provider="google", firebase_uid=FB))
            db.session.commit()

            def auth_headers():
                token = create_access_token(identity=str(UID))
                return {"Authorization": f"Bearer {token}"}

            def post_event(event_name, notification_id, campaign_id, idempotency_key=None):
                body = {
                    "event_name": event_name,
                    "occurred_at": iso(datetime.now(timezone.utc)),
                    "platform": "app_android",
                    "notification_context": {"notification_id": notification_id, "campaign_id": campaign_id, "slot": "general"},
                }
                if idempotency_key is not None:
                    body["idempotency_key"] = idempotency_key
                resp = client.post("/api/activity-events", json=body, headers=auth_headers())
                if resp.status_code == 201 and resp.get_json(silent=True) and resp.get_json().get("event_id"):
                    created_event_ids.append(resp.get_json()["event_id"])
                return resp

            # =============================================================
            print("=== A. P0 idempotency -- notification_opened / destination_opened ===")
            # =============================================================
            campaign_a = str(uuid.uuid4())
            campaign_b = str(uuid.uuid4())
            notif_1 = str(uuid.uuid4())  # this Campaign C execution_id, per notification_dispatcher.dart
            notif_2 = str(uuid.uuid4())  # a DIFFERENT campaign notification

            open_key_1 = f"notification_opened_{notif_1}"
            dest_key_1 = f"destination_opened_{notif_1}"

            # A1: duplicate notification_opened (same physical tap re-dispatched,
            # e.g. getInitialMessage() AND onMessageOpenedApp() both firing for
            # the same cold-start tap) -> one stored event.
            r1 = post_event("notification_opened", notif_1, campaign_a, idempotency_key=open_key_1)
            r2 = post_event("notification_opened", notif_1, campaign_a, idempotency_key=open_key_1)
            check("A1: first notification_opened -> 201 written", r1.status_code == 201 and r1.get_json()["status"] == "written")
            check("A1: duplicate (same idempotency_key) -> 200 duplicate, not a second write", r2.status_code == 200 and r2.get_json()["status"] == "duplicate")
            check("A1: campaign_open_counts sees exactly 1 notification_opened, not 2",
                  metrics_svc.campaign_open_counts(campaign_a, environment="local")["notification_opened_count"] == 1)

            # A2: duplicate destination_opened, independently.
            r3 = post_event("destination_opened", notif_1, campaign_a, idempotency_key=dest_key_1)
            r4 = post_event("destination_opened", notif_1, campaign_a, idempotency_key=dest_key_1)
            check("A2: first destination_opened -> 201 written", r3.status_code == 201)
            check("A2: duplicate destination_opened -> 200 duplicate", r4.status_code == 200 and r4.get_json()["status"] == "duplicate")
            check("A2: campaign_open_counts sees exactly 1 destination_opened, not 2",
                  metrics_svc.campaign_open_counts(campaign_a, environment="local")["destination_opened_count"] == 1)

            # A3: opened and destination_opened for the SAME notification_id
            # never collide with each other (different event_name -> different
            # dedupe_key namespace, and this repo's own producers additionally
            # prefix the raw notification_id differently per event).
            counts_a = metrics_svc.campaign_open_counts(campaign_a, environment="local")
            check("A3: notification_opened and destination_opened both recorded, independently, for the same notification_id",
                  counts_a["notification_opened_count"] == 1 and counts_a["destination_opened_count"] == 1)

            # A4: a DIFFERENT campaign notification remains independently
            # countable -- its own idempotency key never collides with notif_1's.
            open_key_2 = f"notification_opened_{notif_2}"
            r5 = post_event("notification_opened", notif_2, campaign_b, idempotency_key=open_key_2)
            check("A4: a different campaign notification's open -> 201 written (not treated as a duplicate)", r5.status_code == 201)
            check("A4: campaign_a's own count is unaffected by campaign_b's open",
                  metrics_svc.campaign_open_counts(campaign_a, environment="local")["notification_opened_count"] == 1)
            check("A4: campaign_b's own count reflects its own, independent open",
                  metrics_svc.campaign_open_counts(campaign_b, environment="local")["notification_opened_count"] == 1)

            # A5: system tray / cold-start duplicate dispatch safety -- exactly
            # the getInitialMessage() + onMessageOpenedApp() double-fire
            # scenario: two independent HTTP requests (as two separate
            # `handleNotificationTap()` invocations would produce), same
            # notification_id, same derived idempotency_key -- already proven
            # safe by A1 above; re-asserted here as its own named scenario per
            # the task's explicit test requirement.
            check("A5: system tray/cold-start duplicate dispatch collapses to exactly one stored open "
                  "(re-verifying A1's own result under this scenario's name)",
                  metrics_svc.campaign_open_counts(campaign_a, environment="local")["notification_opened_count"] == 1)

            # A6: Bell interaction follows the SAME Campaign C identity
            # semantics -- notification_dispatcher.dart's own
            # fromNotificationCenterItem() resolves `notification_id` to the
            # SAME execution_id a push-tap's own `parse()` would (both read
            # `execution_id` off their respective wire shapes) -- so a Bell
            # tap on the SAME notification produces the IDENTICAL idempotency
            # key as the tray tap already recorded, and must collapse with it
            # rather than double-count, even though it is a structurally
            # different client code path (greeting_header_widget.dart, not
            # main.dart).
            r6 = post_event("notification_opened", notif_1, campaign_a, idempotency_key=open_key_1)
            check("A6: a Bell tap on the SAME notification (same execution_id-derived key) -> 200 duplicate, "
                  "not a second open", r6.status_code == 200 and r6.get_json()["status"] == "duplicate")
            check("A6: campaign_open_counts is still exactly 1 after the Bell-path duplicate",
                  metrics_svc.campaign_open_counts(campaign_a, environment="local")["notification_opened_count"] == 1)

            # =============================================================
            print("\n=== B/C. attempted_count, retry_exhausted vs permanent_failure ===")
            # =============================================================
            audience = SavedAudience(name="hardening synthetic", criteria={"version": 1, "filters": {"search": "zzz-no-match-zzz"}}, is_active=True)
            db.session.add(audience)
            db.session.commit()
            created_audience_ids.append(audience.id)

            campaign = NotificationCampaign(
                title="Hardening metrics campaign", body="Body", audience_mode="SAVED_AUDIENCE",
                saved_audience_id=audience.id, draft_criteria={"version": 1, "filters": {}},
                criteria_version=1, draft_criteria_hash="hardening-hash",
                action={"type": "NONE", "target": None, "parameters": {}}, state="COMPLETED",
            )
            db.session.add(campaign)
            db.session.commit()
            created_campaign_ids.append(campaign.id)

            now = datetime.now(timezone.utc)
            execution = NotificationCampaignExecution(
                campaign_id=campaign.id, state="COMPLETED",
                approved_saved_audience_id=audience.id, approved_criteria={"version": 1, "filters": {}},
                approved_criteria_version=1, approved_criteria_hash="hardening-hash",
                approved_title="Hardening metrics campaign", approved_body="Body",
                approved_action={"type": "NONE", "target": None, "parameters": {}},
                baseline_generated_at=now, baseline_matched_user_count=6, baseline_eligible_recipient_count=6,
                baseline_recorded_at=now,
            )
            db.session.add(execution)
            db.session.commit()
            created_execution_ids.append(execution.id)

            def make_delivery(user_id, status, attempts=()):
                delivery = NotificationCampaignDelivery(
                    execution_id=execution.id, user_id=user_id, app_user_id=user_id,
                    status=status, attempt_count=len(attempts),
                )
                db.session.add(delivery)
                db.session.commit()
                for i, (outcome, error_code) in enumerate(attempts, start=1):
                    db.session.add(NotificationCampaignAttempt(
                        delivery_id=delivery.id, attempt_number=i, started_at=now, finished_at=now,
                        outcome=outcome, provider="fcm", error_code=error_code,
                    ))
                db.session.commit()
                return delivery

            # 2 PENDING (never attempted), 1 SUPPRESSED (never attempted),
            # 1 ACCEPTED (1 attempt), 1 FAILED_PERMANENT via genuine permanent
            # rejection (invalid token, first attempt), 1 FAILED_PERMANENT via
            # retry exhaustion (4 attempts, last one carries the
            # RETRY_EXHAUSTED sentinel exactly as campaign_worker.py itself
            # writes it).
            make_delivery(1, "PENDING")
            make_delivery(2, "PENDING")
            make_delivery(3, "SUPPRESSED")
            make_delivery(4, "ACCEPTED", attempts=[("ACCEPTED", None)])
            make_delivery(5, "FAILED_PERMANENT", attempts=[("FAILED_PERMANENT", "INVALID_TOKEN")])
            make_delivery(6, "FAILED_PERMANENT", attempts=[
                ("FAILED_RETRYABLE", "TRANSIENT_ERROR"),
                ("FAILED_RETRYABLE", "TRANSIENT_ERROR"),
                ("FAILED_RETRYABLE", "TRANSIENT_ERROR"),
                ("FAILED_RETRYABLE", "RETRY_EXHAUSTED"),
            ])

            metrics = metrics_svc.execution_metrics(execution, environment="local")
            check("B: target_count == 6 (every frozen delivery, regardless of outcome)", metrics["target_count"] == 6)
            check("B: attempted_count == 3 (target_count minus 2 PENDING minus 1 SUPPRESSED)", metrics["attempted_count"] == 3)
            check("B: delivery_counts still exposes every original status unmodified",
                  metrics["delivery_counts"] == {
                      "PENDING": 2, "ACCEPTED": 1, "FAILED_RETRYABLE": 0,
                      "FAILED_PERMANENT": 2, "UNKNOWN": 0, "SUPPRESSED": 1,
                  })
            check("C: retry_exhausted_count == 1 (only delivery 6, via its RETRY_EXHAUSTED sentinel)",
                  metrics["retry_exhausted_count"] == 1)
            check("C: permanent_failure_count == 1 (only delivery 5, a genuine invalid-token rejection)",
                  metrics["permanent_failure_count"] == 1)
            check("C: retry_exhausted_count + permanent_failure_count == FAILED_PERMANENT total",
                  metrics["retry_exhausted_count"] + metrics["permanent_failure_count"] == metrics["delivery_counts"]["FAILED_PERMANENT"])
            check("Never claims device delivery anywhere in the metrics keys",
                  "delivered" not in [k.lower() for k in metrics.keys()])

            # =============================================================
            print("\n=== D. Conversion breakdown -- mixed purchase purposes ===")
            # =============================================================
            conv_campaign = str(uuid.uuid4())
            click_at = now - timedelta(hours=2)

            def emit_activity(event_name, occurred_at, campaign_id=None, properties=None):
                row = ActivityEvent(
                    event_name=event_name, event_version=1, occurred_at=occurred_at,
                    recorded_at=datetime.now(timezone.utc), firebase_uid=FB, platform="app_android", environment="local",
                    properties=properties or {},
                    notification_context={"notification_id": "n", "campaign_id": campaign_id, "slot": "general"} if campaign_id else None,
                )
                db.session.add(row)
                db.session.commit()
                return row

            # One user, one click, one qualifying REPORT_PURCHASE within window
            # -- proves the single-purpose case attributes to the right bucket.
            emit_activity("destination_opened", click_at, campaign_id=conv_campaign)
            emit_activity("payment_verified", click_at + timedelta(hours=1), properties={"purpose": "REPORT_PURCHASE"})

            breakdown = metrics_svc.campaign_conversion_breakdown(conv_campaign, environment="local")
            check("D1: report_conversion_count == 1", breakdown["report_conversion_count"] == 1)
            check("D1: ask_now_conversion_count == 0", breakdown["ask_now_conversion_count"] == 0)
            check("D1: subscription_conversion_count == 0", breakdown["subscription_conversion_count"] == 0)
            check("D1: conversion_count == sum of the three buckets", breakdown["conversion_count"] == 1)
            check("D1: campaign_conversion_count() (legacy combined API) still returns the same total",
                  metrics_svc.campaign_conversion_count(conv_campaign, environment="local") == 1)

            db.session.execute(text("DELETE FROM activity_events WHERE firebase_uid = :fb"), {"fb": FB})
            db.session.commit()

            # A DIFFERENT user with TWO qualifying purchases of DIFFERENT
            # purposes in the same window -- must contribute to exactly ONE
            # bucket (the earliest qualifying purchase), and the combined
            # total must still be exactly 1, never 2.
            emit_activity("destination_opened", click_at, campaign_id=conv_campaign)
            emit_activity("payment_verified", click_at + timedelta(minutes=30), properties={"purpose": "ASK_NOW_CHAT_PACK"})
            emit_activity("payment_verified", click_at + timedelta(minutes=45), properties={"purpose": "SUBSCRIPTION"})

            breakdown2 = metrics_svc.campaign_conversion_breakdown(conv_campaign, environment="local")
            check("D2: mixed-purpose user attributed to exactly one purpose (the earlier qualifying purchase: Ask Now)",
                  breakdown2["ask_now_conversion_count"] == 1 and breakdown2["subscription_conversion_count"] == 0)
            check("D2: combined conversion_count is still exactly 1, never 2, for one converted user",
                  breakdown2["conversion_count"] == 1)
            check("D2: the sum of the three per-purpose buckets equals conversion_count (no double count anywhere)",
                  breakdown2["report_conversion_count"] + breakdown2["ask_now_conversion_count"] + breakdown2["subscription_conversion_count"]
                  == breakdown2["conversion_count"])

        finally:
            cleanup()

    print(f"\n{'='*60}\nRESULTS: {passed} passed, {failed} failed\n{'='*60}")
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
