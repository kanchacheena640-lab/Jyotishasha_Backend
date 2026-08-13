"""
test_alerts_scheduler.py
----------------------------
Local-only entry point for Phase 6 (isolated Alerts scheduler & batch
processing) -- modules/alerts/alerts_scheduler.py::run_daily_alerts_job().

Uses the LOCAL scratch Postgres DB ONLY. `send_push_notification` is
monkeypatched -- no real FCM call is ever made. Detection is
controlled via an injectable spy/fake ProfileDetectionService-shaped
object (no real astrology needed to test the SCHEDULER's own
orchestration -- real detection is already covered by
test_alerts_profile_detection.py).
"""

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from modules.models_ai_reports import AI_REPORT_SEGMENTS  # noqa: E402
from modules.entitlement.entitlement_models import EntitlementSnapshot, TrialStatus, SubscriptionStatus  # noqa: E402
from modules.alerts.persistence_repository import AlertPersistenceRepository, AlertPersistenceError  # noqa: E402
from modules.alerts.profile_detection_service import ProfileDataError, DetectionRunFailedError  # noqa: E402
import modules.alerts.alert_delivery_service as delivery_module  # noqa: E402
from modules.alerts.alerts_scheduler import (  # noqa: E402
    run_daily_alerts_job, _fetch_candidate_profile_ids,
    _ADVISORY_LOCK_CLASS_ID, _ADVISORY_LOCK_OBJECT_ID,
)
from notifications.notification_models import UserNotification  # noqa: E402

ALL_SEGMENTS = list(AI_REPORT_SEGMENTS)

# Distinct profile ids per scenario, all in one dedicated range.
P_ENTITLED = 9601
P_NOT_ENTITLED = 9602
P_NO_TOKEN = 9603
P_INVALID_BIRTH = 9604
P_UNEXPECTED_FAILURE = 9605
P_AFTER_FAILURE = 9606
P_BATCH_A, P_BATCH_B, P_BATCH_C = 9607, 9608, 9609
P_FINALIZATION_FAIL = 9610

ALL_TEST_PROFILES = [
    P_ENTITLED, P_NOT_ENTITLED, P_NO_TOKEN, P_INVALID_BIRTH, P_UNEXPECTED_FAILURE,
    P_AFTER_FAILURE, P_BATCH_A, P_BATCH_B, P_BATCH_C, P_FINALIZATION_FAIL,
]

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


class MultiProfileFakeEntitlementService:
    """Per-profile-aware fake -- lets one job run exercise several
    different entitlement outcomes at once."""

    def __init__(self, entitled_profile_ids):
        self._entitled = set(entitled_profile_ids)

    def get_current_entitlement(self, profile_id):
        if profile_id in self._entitled:
            return EntitlementSnapshot(
                profile_id=profile_id, status="TRIAL", plan=None, selected_segment=None,
                trial=TrialStatus(is_active=True),
                subscription=SubscriptionStatus(is_active=False, status="PENDING"),
                accessible_segments=ALL_SEGMENTS,
            )
        return EntitlementSnapshot(
            profile_id=profile_id, status="PENDING", plan=None, selected_segment=None,
            trial=TrialStatus(is_active=False),
            subscription=SubscriptionStatus(is_active=False, status="PENDING"),
            accessible_segments=[],
        )


@dataclass
class FakeEvalResult:
    events_detected: int


class SpyDetectionService:
    """Records every profile_id it's called for (proving/disproving
    "detection ran before entitlement check" style assertions) and
    dispatches to a per-profile configured behavior."""

    def __init__(self, repo):
        self._repo = repo
        self._behaviors = {}
        self.calls = []

    def configure(self, profile_id, behavior):
        self._behaviors[profile_id] = behavior

    def evaluate_profile(self, profile_id):
        self.calls.append(profile_id)
        behavior = self._behaviors.get(profile_id)
        if behavior is None:
            raise AssertionError(f"SpyDetectionService: no behavior configured for profile_id={profile_id}")
        return behavior()


class FakeFcmSender:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def __call__(self, *, token, title, body, data=None, android_tag=None):
        self.calls.append({"token": token, "event_id": (data or {}).get("event_id")})
        return self.result


def _detects_one_active_event(repo, profile_id, event_id, now, confidence=0.7):
    """Simulates a successful detection run that persists ONE
    NEW/ACTIVE event via the REAL Phase 1 repository (exactly what
    ProfileDetectionService would do), without running real astrology."""
    def _behavior():
        repo.save_detection(
            profile_id=profile_id, event_id=event_id, category="emotional",
            state="NEW", confidence=confidence, priority="high",
            active_from=date(now.year, now.month, now.day),
            active_until=date(now.year, now.month, now.day),
            evaluated_at=now,
        )
        return FakeEvalResult(events_detected=1)
    return _behavior


def cleanup():
    for p in ALL_TEST_PROFILES:
        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": p})
        db.session.execute(text("DELETE FROM user_notifications WHERE user_id = :p"), {"p": p})
        db.session.execute(text("DELETE FROM current_entitlements WHERE profile_id = :p"), {"p": p})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": p})
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()
        with db.engine.connect() as conn:
            for p, token in [
                (P_ENTITLED, "tok"), (P_NOT_ENTITLED, "tok"), (P_NO_TOKEN, None),
                (P_INVALID_BIRTH, "tok"), (P_UNEXPECTED_FAILURE, "tok"), (P_AFTER_FAILURE, "tok"),
                (P_BATCH_A, "tok"), (P_BATCH_B, "tok"), (P_BATCH_C, "tok"), (P_FINALIZATION_FAIL, "tok"),
            ]:
                conn.execute(text(
                    "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                    "VALUES (:id, 'IST', 'free', 0, :token)"
                ), {"id": p, "token": token})
            # Candidate pre-filter reads current_entitlements.profile_id --
            # every test profile needs a row here for the scheduler to
            # even consider it (content is irrelevant; the injected
            # FakeEntitlementService, not this row, decides the real
            # yes/no outcome).
            for p in ALL_TEST_PROFILES:
                conn.execute(text(
                    "INSERT INTO current_entitlements (profile_id, status, created_at, updated_at) "
                    "VALUES (:p, 'PENDING', now(), now())"
                ), {"p": p})
            conn.commit()

        repo = AlertPersistenceRepository()
        now = datetime(2026, 8, 14, 12, 0, 0)
        sender = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender

        # ==============================================================
        print("=== Test 1/2/3/4/5: entitled/not-entitled/no-token/invalid-birth/unexpected-failure, all in one batch ===")
        # ==============================================================
        entitlement = MultiProfileFakeEntitlementService(
            entitled_profile_ids=[P_ENTITLED, P_NO_TOKEN, P_INVALID_BIRTH, P_UNEXPECTED_FAILURE, P_AFTER_FAILURE]
        )
        spy = SpyDetectionService(repo)
        spy.configure(P_ENTITLED, _detects_one_active_event(repo, P_ENTITLED, "mood_positive", now))

        def _raise_profile_data_error():
            raise ProfileDataError("missing birth fields (test)")
        spy.configure(P_INVALID_BIRTH, _raise_profile_data_error)

        def _raise_unexpected():
            raise RuntimeError("simulated unexpected detection crash")
        spy.configure(P_UNEXPECTED_FAILURE, _raise_unexpected)

        spy.configure(P_AFTER_FAILURE, _detects_one_active_event(repo, P_AFTER_FAILURE, "energy_high", now))

        summary = run_daily_alerts_job(
            entitlement_service=entitlement, detection_service=spy, repository=repo, now=now,
        )

        check("Test 1: entitled profile processed (detection called)", P_ENTITLED in spy.calls)
        check("Test 1: entitled profile's alert delivered", summary.alerts_delivered >= 1)
        row = repo.read(profile_id=P_ENTITLED, event_id="mood_positive")
        check("Test 1: last_delivered_at set for the entitled profile", row.last_delivered_at == now)

        check("Test 2: non-entitled profile SKIPPED, detection never called for it", P_NOT_ENTITLED not in spy.calls)
        check("Test 2: entitlement_skipped counted", summary.entitlement_skipped >= 1)

        check("Test 3: missing-token profile skipped, detection never called for it", P_NO_TOKEN not in spy.calls)
        check("Test 3: missing_token_skipped counted", summary.missing_token_skipped == 1)

        check("Test 4: invalid birth data isolated -> invalid_profile_skipped counted", summary.invalid_profile_skipped == 1)

        check("Test 5: unexpected detection failure counted as a failure", summary.failures >= 1)
        check("Test 5: profile AFTER the failure still processed (job did not stop)", P_AFTER_FAILURE in spy.calls)
        row_after = repo.read(profile_id=P_AFTER_FAILURE, event_id="energy_high")
        check("Test 5: profile after the failure delivered successfully", row_after.last_delivered_at == now)

        # ==============================================================
        print("\n=== Test 6: multiple batches process correctly ===")
        # ==============================================================
        entitlement_batch = MultiProfileFakeEntitlementService(entitled_profile_ids=[P_BATCH_A, P_BATCH_B, P_BATCH_C])
        spy_batch = SpyDetectionService(repo)
        for p, eid in [(P_BATCH_A, "mood_low"), (P_BATCH_B, "mood_low"), (P_BATCH_C, "mood_low")]:
            spy_batch.configure(p, _detects_one_active_event(repo, p, eid, now))

        summary_batch = run_daily_alerts_job(
            entitlement_service=entitlement_batch, detection_service=spy_batch, repository=repo,
            batch_size=1, now=now,  # forces at least 3 internal fetch iterations for 3 candidates
        )
        check("Test 6: all 3 profiles across multiple batches processed", set(spy_batch.calls) == {P_BATCH_A, P_BATCH_B, P_BATCH_C})
        check("Test 6: profiles_scanned reflects the whole candidate set, not just one batch", summary_batch.profiles_scanned >= 3)

        page1 = _fetch_candidate_profile_ids(batch_size=1, offset=0)
        page2 = _fetch_candidate_profile_ids(batch_size=1, offset=1)
        check("Test 12: candidate fetch is bounded -- exactly `batch_size` rows per call, not the whole table", len(page1) <= 1 and len(page2) <= 1)

        # ==============================================================
        print("\n=== Test 7: repeated job execution does not duplicate delivery inside cooldown ===")
        # ==============================================================
        entitlement2 = MultiProfileFakeEntitlementService(entitled_profile_ids=[P_ENTITLED])
        spy2 = SpyDetectionService(repo)
        # Second run: same event still active (already delivered in Test 1).
        def _still_active():
            return FakeEvalResult(events_detected=1)  # row already exists from Test 1; no new write needed
        spy2.configure(P_ENTITLED, _still_active)

        sender_before_count = len(sender.calls)
        summary2 = run_daily_alerts_job(entitlement_service=entitlement2, detection_service=spy2, repository=repo, now=now + timedelta(minutes=1))
        check("Test 7: repeated run within cooldown delivers nothing new", summary2.alerts_delivered == 0)
        check("Test 7: cooldown_or_eligibility_skipped counted instead", summary2.cooldown_or_eligibility_skipped >= 1)
        check("Test 7: no new FCM call happened", len(sender.calls) == sender_before_count)

        # ==============================================================
        print("\n=== Test 8: overlapping execution protection ===")
        # ==============================================================
        lock_conn = db.engine.connect()
        held = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:c, :o)"),
            {"c": _ADVISORY_LOCK_CLASS_ID, "o": _ADVISORY_LOCK_OBJECT_ID},
        ).scalar()
        check("Test 8 setup: manually acquired the job's own lock from a separate connection", bool(held))

        entitlement3 = MultiProfileFakeEntitlementService(entitled_profile_ids=[P_ENTITLED])
        spy3 = SpyDetectionService(repo)
        summary3 = run_daily_alerts_job(entitlement_service=entitlement3, detection_service=spy3, repository=repo, now=now)
        check("Test 8: overlapping run reports lock_acquired=False", not summary3.lock_acquired)
        check("Test 8: overlapping run did ZERO work", summary3.profiles_scanned == 0 and len(spy3.calls) == 0)

        lock_conn.execute(text("SELECT pg_advisory_unlock(:c, :o)"), {"c": _ADVISORY_LOCK_CLASS_ID, "o": _ADVISORY_LOCK_OBJECT_ID})
        lock_conn.close()

        spy4 = SpyDetectionService(repo)
        spy4.configure(P_ENTITLED, lambda: FakeEvalResult(events_detected=1))  # row already exists; just needs a valid behavior
        summary4 = run_daily_alerts_job(entitlement_service=entitlement3, detection_service=spy4, repository=repo, now=now)
        check("Test 8: after releasing, a new run CAN acquire the lock again", summary4.lock_acquired)

        # ==============================================================
        print("\n=== Test 9/10: successful alerts reach Phase-5 delivery; finalization failure is not blindly resent ===")
        # ==============================================================
        class FlakyRepository(AlertPersistenceRepository):
            def __init__(self, fail_event_id):
                super().__init__()
                self._fail_event_id = fail_event_id
                self.finalize_calls = []

            def finalize_delivery(self, **kwargs):
                self.finalize_calls.append(kwargs["event_id"])
                if kwargs["event_id"] == self._fail_event_id:
                    raise AlertPersistenceError("simulated finalization failure")
                return super().finalize_delivery(**kwargs)

        flaky_repo = FlakyRepository(fail_event_id="stress_high")
        flaky_repo.save_detection(
            profile_id=P_FINALIZATION_FAIL, event_id="stress_high", category="vitality",
            state="NEW", confidence=0.9, priority="high",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14), evaluated_at=now,
        )
        entitlement5 = MultiProfileFakeEntitlementService(entitled_profile_ids=[P_FINALIZATION_FAIL])
        spy5 = SpyDetectionService(flaky_repo)
        spy5.configure(P_FINALIZATION_FAIL, lambda: FakeEvalResult(events_detected=1))

        sender5 = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender5
        summary5 = run_daily_alerts_job(entitlement_service=entitlement5, detection_service=spy5, repository=flaky_repo, now=now)

        check("Test 9: FCM was genuinely called (physical send succeeded)", len(sender5.calls) == 1)
        check("Test 10: finalization failure counted as a failure, not a silent success", summary5.failures == 1)
        check("Test 10: finalize_delivery() was attempted exactly ONCE for this event this run (no blind resend)", flaky_repo.finalize_calls.count("stress_high") == 1)
        check("Test 10: alerts_delivered NOT incremented for the finalization-failed alert", summary5.alerts_delivered == 0)

        # ==============================================================
        print("\n=== Test 11: no generic notification code invoked ===")
        # ==============================================================
        import inspect
        import modules.alerts.alerts_scheduler as scheduler_module
        source = inspect.getsource(scheduler_module)
        check("scheduler does not import services.event_scheduler", "services.event_scheduler" not in source and "from services import event_scheduler" not in source)
        check("scheduler does not import services.notification_builder", "notification_builder" not in source)
        check("scheduler never references AstroEvent", "AstroEvent" not in source)
        check("scheduler never references NotificationLog", "NotificationLog" not in source)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
