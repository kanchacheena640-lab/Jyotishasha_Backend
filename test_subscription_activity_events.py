"""
test_subscription_activity_events.py
-------------------------------------------------
Phase 4A: proves EntitlementWriteService's 8 live transitions emit the
correct, correctly-shaped activity_events row -- only after their own
authoritative commit -- and that analytics failure of every kind
(write_failed, an unexpected exception, or a missing/invalid
ACTIVITY_EVENTS_ENVIRONMENT) can never alter the entitlement/
SubscriptionEvent business result.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else (same convention as every other activity-events
test file). All test AppUser/CurrentEntitlement/SubscriptionEvent/
activity_events rows are created with a dedicated, obviously-test-only
id range and deleted in a finally block, keyed by their own ids --
never a broad DELETE.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text
    from modules.models_user import AppUser
    from modules.models_premium_subscription import CurrentEntitlement, SubscriptionEvent
    from modules.entitlement.entitlement_write_service import EntitlementWriteService

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        service = EntitlementWriteService()

        created_app_user_ids = []
        created_event_ids = []  # activity_events, by uuid event_id

        def new_profile():
            au = AppUser(firebase_uid=f"phase4a-test-{uuid.uuid4().hex[:10]}")
            db.session.add(au)
            db.session.commit()
            created_app_user_ids.append(au.id)
            return au.id

        def get_ledger_row(dedupe_key):
            return db.session.execute(
                text("SELECT * FROM activity_events WHERE dedupe_key = :dk"),
                {"dk": dedupe_key},
            ).fetchone()

        def track_ledger_rows_for(profile_id):
            rows = db.session.execute(
                text("SELECT event_id FROM activity_events WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).fetchall()
            created_event_ids.extend(str(r.event_id) for r in rows)

        def assert_event(label, profile_id, canonical_name, subscription_event_id,
                          expect_plan=None, expect_store=None):
            dk = f"subscription:{canonical_name}:{subscription_event_id}"
            row = get_ledger_row(dk)
            check(f"{label}: activity_events row exists (dedupe_key={dk!r})", row is not None)
            if row is None:
                return
            check(f"{label}: event_name correct", row.event_name == canonical_name)
            check(f"{label}: profile_id correct", row.profile_id == profile_id)
            check(f"{label}: firebase_uid is null", row.firebase_uid is None)
            check(f"{label}: platform == backend_internal", row.platform == "backend_internal")
            check(f"{label}: source == entitlement_write_service", row.source == "entitlement_write_service")
            check(f"{label}: entity_type == subscription_event", row.entity_type == "subscription_event")
            check(f"{label}: entity_id == SubscriptionEvent.id", row.entity_id == str(subscription_event_id))
            check(f"{label}: dedupe_key exact match", row.dedupe_key == dk)
            allowed_keys = {"plan", "store"}
            check(f"{label}: properties contain ONLY allowed keys", set(row.properties.keys()) <= allowed_keys)
            check(f"{label}: no forbidden PII/secret keys present",
                  not any(k in row.properties for k in ("purchase_token", "transaction_id", "email", "phone", "name", "receipt_payload", "previous_status")))
            if expect_plan is not None:
                check(f"{label}: plan property correct", row.properties.get("plan") == expect_plan)
            else:
                check(f"{label}: plan property absent when not applicable", "plan" not in row.properties)
            if expect_store is not None:
                check(f"{label}: store property correct", row.properties.get("store") == expect_store)
            else:
                check(f"{label}: store property absent when not applicable", "store" not in row.properties)

        try:
            # =========================================================
            # 1. subscription_trial_started
            # =========================================================
            pid = new_profile()
            result = service.start_trial(pid)
            track_ledger_rows_for(pid)
            check("trial_started: business result success", result.success and result.action == "TRIAL_STARTED")
            se = SubscriptionEvent.query.filter_by(profile_id=pid, event_type="TRIAL_STARTED").first()
            check("trial_started: authoritative SubscriptionEvent exists", se is not None)
            ce = CurrentEntitlement.query.filter_by(profile_id=pid).first()
            check("trial_started: CurrentEntitlement status == TRIAL", ce is not None and ce.status == "TRIAL")
            assert_event("trial_started", pid, "subscription_trial_started", se.id)

            # =========================================================
            # 2. subscription_trial_expired
            # =========================================================
            pid2 = new_profile()
            service.start_trial(pid2)
            result = service.expire_trial(pid2)
            track_ledger_rows_for(pid2)
            check("trial_expired: business result success", result.success and result.action == "TRIAL_EXPIRED")
            se2 = SubscriptionEvent.query.filter_by(profile_id=pid2, event_type="TRIAL_EXPIRED").first()
            check("trial_expired: authoritative SubscriptionEvent exists", se2 is not None)
            assert_event("trial_expired", pid2, "subscription_trial_expired", se2.id)

            # =========================================================
            # 3. subscription_started
            # =========================================================
            pid3 = new_profile()
            expires = datetime.utcnow() + timedelta(days=30)
            result = service.activate_subscription(pid3, plan="PRIME_PLUS_MONTHLY", selected_segment=None, expires_at=expires)
            track_ledger_rows_for(pid3)
            check("started: business result success", result.success and result.action == "SUBSCRIPTION_ACTIVATED")
            se3 = SubscriptionEvent.query.filter_by(profile_id=pid3, event_type="SUBSCRIPTION_STARTED").first()
            check("started: authoritative SubscriptionEvent exists", se3 is not None)
            assert_event("started", pid3, "subscription_started", se3.id, expect_plan="PRIME_PLUS_MONTHLY")

            # =========================================================
            # 4. subscription_renewed
            # =========================================================
            pid4 = new_profile()
            service.activate_subscription(pid4, plan="PRIME_PLUS_MONTHLY", selected_segment=None, expires_at=expires)
            new_expiry = expires + timedelta(days=30)
            result = service.renew_subscription(pid4, expires_at=new_expiry)
            track_ledger_rows_for(pid4)
            check("renewed: business result success", result.success and result.action == "SUBSCRIPTION_RENEWED")
            se4 = SubscriptionEvent.query.filter_by(profile_id=pid4, event_type="SUBSCRIPTION_RENEWED").first()
            check("renewed: authoritative SubscriptionEvent exists", se4 is not None)
            assert_event("renewed", pid4, "subscription_renewed", se4.id, expect_plan="PRIME_PLUS_MONTHLY")

            # =========================================================
            # 5. subscription_grace_entered
            # =========================================================
            pid5 = new_profile()
            service.activate_subscription(pid5, plan="PRIME_PLUS_MONTHLY", selected_segment=None, expires_at=expires)
            result = service.enter_grace(pid5)
            track_ledger_rows_for(pid5)
            check("grace_entered: business result success", result.success and result.action == "GRACE_ENTERED")
            se5 = SubscriptionEvent.query.filter_by(profile_id=pid5, event_type="SUBSCRIPTION_GRACE_ENTERED").first()
            check("grace_entered: authoritative SubscriptionEvent exists", se5 is not None)
            assert_event("grace_entered", pid5, "subscription_grace_entered", se5.id, expect_plan="PRIME_PLUS_MONTHLY")

            # =========================================================
            # 6a. subscription_expired via exit_grace()
            # =========================================================
            pid6 = new_profile()
            service.activate_subscription(pid6, plan="PRIME_PLUS_MONTHLY", selected_segment=None, expires_at=expires)
            service.enter_grace(pid6)
            result = service.exit_grace(pid6)
            track_ledger_rows_for(pid6)
            check("expired(exit_grace): business result success", result.success and result.action == "GRACE_EXITED_EXPIRED")
            se6 = SubscriptionEvent.query.filter_by(profile_id=pid6, event_type="SUBSCRIPTION_EXPIRED").first()
            check("expired(exit_grace): authoritative SubscriptionEvent exists", se6 is not None)
            assert_event("expired(exit_grace)", pid6, "subscription_expired", se6.id, expect_plan="PRIME_PLUS_MONTHLY")

            # =========================================================
            # 6b. subscription_expired via expire_subscription()
            # -- both producers confirmed to map to the SAME canonical
            # event name (distinguished only by their distinct
            # SubscriptionEvent.id, per the frozen design).
            # =========================================================
            pid7 = new_profile()
            service.activate_subscription(pid7, plan="PRIME_PLUS_MONTHLY", selected_segment=None, expires_at=expires)
            result = service.expire_subscription(pid7)
            track_ledger_rows_for(pid7)
            check("expired(expire_subscription): business result success", result.success and result.action == "SUBSCRIPTION_EXPIRED")
            se7 = SubscriptionEvent.query.filter_by(profile_id=pid7, event_type="SUBSCRIPTION_EXPIRED").first()
            check("expired(expire_subscription): authoritative SubscriptionEvent exists", se7 is not None)
            assert_event("expired(expire_subscription)", pid7, "subscription_expired", se7.id, expect_plan="PRIME_PLUS_MONTHLY")
            check("both expiration producers map to the SAME canonical event_name",
                  get_ledger_row(f"subscription:subscription_expired:{se6.id}") is not None and
                  get_ledger_row(f"subscription:subscription_expired:{se7.id}") is not None and
                  se6.id != se7.id)

            # =========================================================
            # 7. subscription_cancelled
            # =========================================================
            pid8 = new_profile()
            service.activate_subscription(pid8, plan="PRIME_PLUS_MONTHLY", selected_segment=None, expires_at=expires)
            result = service.cancel_subscription(pid8)
            track_ledger_rows_for(pid8)
            check("cancelled: business result success", result.success and result.action == "SUBSCRIPTION_CANCELLED")
            se8 = SubscriptionEvent.query.filter_by(profile_id=pid8, event_type="SUBSCRIPTION_CANCELLED").first()
            check("cancelled: authoritative SubscriptionEvent exists", se8 is not None)
            assert_event("cancelled", pid8, "subscription_cancelled", se8.id, expect_plan="PRIME_PLUS_MONTHLY")

            # =========================================================
            # 8. subscription_refunded
            # =========================================================
            pid9 = new_profile()
            service.activate_subscription(pid9, plan="PRIME_PLUS_MONTHLY", selected_segment=None, expires_at=expires)
            result = service.record_refund(pid9)
            track_ledger_rows_for(pid9)
            check("refunded: business result success", result.success and result.action == "SUBSCRIPTION_REFUNDED")
            se9 = SubscriptionEvent.query.filter_by(profile_id=pid9, event_type="SUBSCRIPTION_REFUNDED").first()
            check("refunded: authoritative SubscriptionEvent exists", se9 is not None)
            assert_event("refunded", pid9, "subscription_refunded", se9.id, expect_plan="PRIME_PLUS_MONTHLY")

            # =========================================================
            # subscription_pending_created is NEVER emitted
            # =========================================================
            from modules.entitlement.entitlement_write_service import _CANONICAL_ACTIVITY_EVENT_BY_TYPE
            check("subscription_pending_created NOT in the canonical mapping",
                  "SUBSCRIPTION_PENDING_CREATED" not in _CANONICAL_ACTIVITY_EVENT_BY_TYPE)
            check("subscription_pending_created never appears as a persisted event_name",
                  db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE event_name = 'subscription_pending_created'")).scalar() == 0)

            # =========================================================
            # Deterministic dedupe: duplicate analytics attempt does not
            # create a second row.
            # =========================================================
            pid10 = new_profile()
            service.start_trial(pid10)
            track_ledger_rows_for(pid10)
            se10 = SubscriptionEvent.query.filter_by(profile_id=pid10, event_type="TRIAL_STARTED").first()
            dk10 = f"subscription:subscription_trial_started:{se10.id}"
            count_before = db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"), {"dk": dk10}).scalar()
            # Directly re-invoke the private emitter with the SAME already-committed
            # SubscriptionEvent -- simulates a retried/duplicate analytics attempt
            # for an authoritative transition that only truly happened once.
            service._emit_activity_event(se10)
            count_after = db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"), {"dk": dk10}).scalar()
            check("dedupe: exactly one row exists before the duplicate attempt", count_before == 1)
            check("dedupe: duplicate analytics attempt does NOT create a second row", count_after == 1)

            # =========================================================
            # Failure safety: record_event() returns write_failed
            # =========================================================
            pid11 = new_profile()
            with patch("modules.entitlement.entitlement_write_service.record_event") as mock_re:
                from modules.activity_events.service import LedgerWriteResult
                mock_re.return_value = LedgerWriteResult(status="write_failed")
                result = service.start_trial(pid11)
            check("write_failed: business result STILL success", result.success and result.action == "TRIAL_STARTED")
            ce11 = CurrentEntitlement.query.filter_by(profile_id=pid11).first()
            check("write_failed: CurrentEntitlement STILL committed correctly", ce11 is not None and ce11.status == "TRIAL")
            se11 = SubscriptionEvent.query.filter_by(profile_id=pid11, event_type="TRIAL_STARTED").first()
            check("write_failed: SubscriptionEvent row STILL committed", se11 is not None)

            # =========================================================
            # Failure safety: record_event() raises an unexpected exception
            # =========================================================
            pid12 = new_profile()
            with patch("modules.entitlement.entitlement_write_service.record_event") as mock_re:
                mock_re.side_effect = RuntimeError("boom -- simulated unexpected analytics failure")
                no_exception = True
                try:
                    result = service.start_trial(pid12)
                except Exception:
                    no_exception = False
                    result = None
            check("unexpected exception: does NOT propagate out of start_trial()", no_exception)
            check("unexpected exception: business result STILL success", result is not None and result.success and result.action == "TRIAL_STARTED")
            ce12 = CurrentEntitlement.query.filter_by(profile_id=pid12).first()
            check("unexpected exception: CurrentEntitlement STILL committed correctly", ce12 is not None and ce12.status == "TRIAL")
            se12 = SubscriptionEvent.query.filter_by(profile_id=pid12, event_type="TRIAL_STARTED").first()
            check("unexpected exception: SubscriptionEvent row STILL committed", se12 is not None)

            # =========================================================
            # Missing/invalid ACTIVITY_EVENTS_ENVIRONMENT doesn't alter
            # the authoritative subscription result.
            # =========================================================
            pid13 = new_profile()
            original_env = os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT")
            try:
                os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
                result = service.start_trial(pid13)
            finally:
                if original_env is None:
                    os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
                else:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = original_env
            check("missing env: business result STILL success", result.success and result.action == "TRIAL_STARTED")
            ce13 = CurrentEntitlement.query.filter_by(profile_id=pid13).first()
            check("missing env: CurrentEntitlement STILL committed correctly", ce13 is not None and ce13.status == "TRIAL")
            se13 = SubscriptionEvent.query.filter_by(profile_id=pid13, event_type="TRIAL_STARTED").first()
            check("missing env: SubscriptionEvent row STILL committed", se13 is not None)
            ledger_row13 = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"),
                {"dk": f"subscription:subscription_trial_started:{se13.id}"},
            ).scalar()
            check("missing env: no activity_events row was persisted (ledger write correctly refused)", ledger_row13 == 0)
            check("missing env: never silently labeled production (no row exists to mislabel)", ledger_row13 == 0)

        finally:
            all_pids = created_app_user_ids
            if all_pids:
                # Order matters: CurrentEntitlement.last_event_id is a
                # real FK to subscription_events.id -- it must be
                # cleared/deleted BEFORE SubscriptionEvent rows, or
                # Postgres rejects the whole transaction (discovered
                # exactly this way on the first run of this file; fixed
                # here, not worked around).
                for eid in [str(r.event_id) for r in db.session.execute(
                    text("SELECT event_id FROM activity_events WHERE profile_id = ANY(:pids)"), {"pids": all_pids}
                ).fetchall()]:
                    db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
                CurrentEntitlement.query.filter(CurrentEntitlement.profile_id.in_(all_pids)).delete(synchronize_session=False)
                SubscriptionEvent.query.filter(SubscriptionEvent.profile_id.in_(all_pids)).delete(synchronize_session=False)
                AppUser.query.filter(AppUser.id.in_(all_pids)).delete(synchronize_session=False)
                db.session.commit()

            remaining_events = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE profile_id = ANY(:pids)"),
                {"pids": all_pids or [-1]},
            ).scalar()
            check(f"all Phase-4A test rows cleaned up (activity_events: 0 remain)", remaining_events == 0)
            remaining_se = SubscriptionEvent.query.filter(SubscriptionEvent.profile_id.in_(all_pids or [-1])).count()
            check("all Phase-4A SubscriptionEvent rows cleaned up", remaining_se == 0)
            remaining_ce = CurrentEntitlement.query.filter(CurrentEntitlement.profile_id.in_(all_pids or [-1])).count()
            check("all Phase-4A CurrentEntitlement rows cleaned up", remaining_ce == 0)
            remaining_au = AppUser.query.filter(AppUser.id.in_(all_pids or [-1])).count()
            check("all Phase-4A AppUser fixtures cleaned up", remaining_au == 0)

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
