"""
test_alerts_selection_service.py
----------------------------------
Local-only entry point for the Alerts Product Hardening change --
the DB-touching orchestration layer:
  - modules/alerts/persistence_repository.py::count_delivered_since()
  - modules/alerts/user_alert_selection_service.py::get_user_facing_alerts_for_profile()
  - modules/alerts/alerts_scheduler.py's wiring of both into
    run_daily_alerts_job()

Uses the LOCAL scratch Postgres DB ONLY, exactly like every other
test_alerts_*.py script. `send_push_notification` is monkeypatched --
no real FCM call is ever made.
"""

import os
import sys
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
from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402
from modules.alerts.profile_detection_service import ProfileDataError, DetectionRunFailedError  # noqa: E402
import modules.alerts.alert_delivery_service as delivery_module  # noqa: E402
from modules.alerts.alerts_scheduler import run_daily_alerts_job  # noqa: E402
from modules.alerts.user_alert_selection_service import (  # noqa: E402
    get_user_facing_alerts_for_profile,
    resolve_daily_cap_window_start,
)

ALL_SEGMENTS = list(AI_REPORT_SEGMENTS)

P_MULTI = 9701          # many eligible, non-conflicting candidates
P_CONFLICT = 9702       # a real conflicting pair + one distinct-category candidate
P_RERUN_CAP = 9703      # rerun-vs-daily-cap scenario

ALL_TEST_PROFILES = [P_MULTI, P_CONFLICT, P_RERUN_CAP]

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


class SingleProfileFakeEntitlementService:
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


class FakeFcmSender:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def __call__(self, *, token, title, body, data=None, android_tag=None):
        self.calls.append((data or {}).get("event_id"))
        return self.result


class FixedResultDetectionService:
    """Real detection is out of scope here (already covered elsewhere)
    -- this fake just reports "N events detected" without touching
    persistence itself; the test seeds AlertMicroEvent rows directly
    via the real repository, exactly mirroring what
    ProfileDetectionService.evaluate_profile() would have already
    persisted by the time the scheduler reaches the selection step."""

    def __init__(self, events_detected_by_profile):
        self._counts = events_detected_by_profile

    def evaluate_profile(self, profile_id):
        from dataclasses import dataclass

        @dataclass
        class _Result:
            events_detected: int
        return _Result(events_detected=self._counts.get(profile_id, 0))


def seed(repo, profile_id, event_id, category, severity, priority, confidence, evaluated_at):
    repo.save_detection(
        profile_id=profile_id, event_id=event_id, category=category,
        state="NEW", confidence=confidence, priority=priority,
        active_from=date(evaluated_at.year, evaluated_at.month, evaluated_at.day),
        active_until=date(evaluated_at.year, evaluated_at.month, evaluated_at.day),
        evaluated_at=evaluated_at,
    )
    row = repo.read(profile_id=profile_id, event_id=event_id)
    row.severity = severity
    db.session.commit()


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
            for p in ALL_TEST_PROFILES:
                conn.execute(text(
                    "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                    "VALUES (:id, 'IST', 'free', 0, 'tok')"
                ), {"id": p})
                conn.execute(text(
                    "INSERT INTO current_entitlements (profile_id, status, created_at, updated_at) "
                    "VALUES (:p, 'PENDING', now(), now())"
                ), {"p": p})
            conn.commit()

        repo = AlertPersistenceRepository()
        now = datetime(2026, 8, 14, 12, 0, 0)

        # ==============================================================
        print("=== Test A: get_user_facing_alerts_for_profile() narrows a real multi-candidate pool ===")
        # ==============================================================
        seed(repo, P_MULTI, "financial_gain_opportunity", "financial", "HIGH", "high", 0.9, now)
        seed(repo, P_MULTI, "mood_positive", "emotional", "LOW", "high", 0.85, now)
        seed(repo, P_MULTI, "learning_focus", "learning", "LOW", "medium", 0.5, now)
        seed(repo, P_MULTI, "stress_high", "vitality", "MEDIUM", "medium", 0.4, now)

        selection = get_user_facing_alerts_for_profile(P_MULTI, now=now, repository=repo, lat=None, lon=None)
        selected_ids = {r.event_id for r in selection.selected}
        check("4 persisted eligible candidates -> at most 2 selected", len(selection.selected) <= 2)
        check("eligible_count reflects all 4 real eligible rows", selection.eligible_count == 4)
        check("strongest (financial_gain_opportunity) selected", "financial_gain_opportunity" in selected_ids)
        check("second (mood_positive, distinct category, high priority) selected", "mood_positive" in selected_ids)
        check("weaker medium-priority candidates NOT selected", selected_ids == {"financial_gain_opportunity", "mood_positive"})

        # ==============================================================
        print("\n=== Test B: real conflicting pair never both selected end-to-end ===")
        # ==============================================================
        seed(repo, P_CONFLICT, "mood_low", "emotional", "LOW", "high", 0.8, now)
        seed(repo, P_CONFLICT, "mood_positive", "emotional", "LOW", "high", 0.75, now)
        seed(repo, P_CONFLICT, "travel_opportunity", "travel", "MEDIUM", "high", 0.6, now)

        selection_b = get_user_facing_alerts_for_profile(P_CONFLICT, now=now, repository=repo, lat=None, lon=None)
        ids_b = {r.event_id for r in selection_b.selected}
        check("mood_low and mood_positive never both selected", not ({"mood_low", "mood_positive"} <= ids_b))
        check("exactly 2 selected (stronger of the conflict pair + distinct-category)", len(selection_b.selected) == 2)
        check("travel_opportunity (distinct category, high priority) selected", "travel_opportunity" in ids_b)

        # ==============================================================
        print("\n=== Test C: scheduler end-to-end -- max 2 delivered, correct counters ===")
        # ==============================================================
        sender = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender
        entitlement = SingleProfileFakeEntitlementService([P_MULTI])
        detection = FixedResultDetectionService({P_MULTI: 4})

        summary = run_daily_alerts_job(
            entitlement_service=entitlement, detection_service=detection, repository=repo, now=now,
        )
        check("alerts_attempted capped at 2 for this profile", summary.alerts_attempted == 2)
        check("alerts_delivered == 2 (both selected alerts sent)", summary.alerts_delivered == 2)
        check("selection_suppressed counts the 2 eligible-but-unselected alerts", summary.selection_suppressed == 2)
        check("exactly 2 real FCM sends happened", len(sender.calls) == 2)
        check("no more than 2 Bell rows created for this profile", db.session.execute(
            text("SELECT COUNT(*) FROM user_notifications WHERE user_id = :p"), {"p": P_MULTI}
        ).scalar() == 2)

        # ==============================================================
        print("\n=== Test D: rerun does not bypass the daily cap (scheduler level) ===")
        # ==============================================================
        # A brand-new profile: seed 2 alerts, deliver both in run #1
        # (reaching the daily cap), then seed a THIRD, entirely fresh,
        # never-delivered (therefore individually cooldown-clear)
        # event and rerun a few minutes later. The cap -- not any
        # per-event cooldown -- must still block it.
        seed(repo, P_RERUN_CAP, "financial_gain_opportunity", "financial", "HIGH", "high", 0.9, now)
        seed(repo, P_RERUN_CAP, "mood_positive", "emotional", "LOW", "high", 0.85, now)

        sender_d = FakeFcmSender(result=True)
        delivery_module.send_push_notification = sender_d
        entitlement_d = SingleProfileFakeEntitlementService([P_RERUN_CAP])
        detection_d1 = FixedResultDetectionService({P_RERUN_CAP: 2})

        summary_d1 = run_daily_alerts_job(
            entitlement_service=entitlement_d, detection_service=detection_d1, repository=repo, now=now,
        )
        check("run #1: both alerts delivered (cap reached)", summary_d1.alerts_delivered == 2)

        # New, previously-nonexistent event -- individually fully
        # eligible (never delivered before, so no cooldown at all).
        seed(repo, P_RERUN_CAP, "learning_focus", "learning", "LOW", "high", 0.8, now + timedelta(minutes=5))
        detection_d2 = FixedResultDetectionService({P_RERUN_CAP: 3})

        summary_d2 = run_daily_alerts_job(
            entitlement_service=entitlement_d, detection_service=detection_d2, repository=repo,
            now=now + timedelta(minutes=10),
        )
        check("run #2: the fresh, individually-eligible 3rd event is NOT delivered", summary_d2.alerts_delivered == 0)
        check("run #2: it is counted as selection_suppressed (daily cap), not delivered", summary_d2.selection_suppressed >= 1)
        check("run #2: no new FCM call for the capped profile", len(sender_d.calls) == 2)
        row_learning = repo.read(profile_id=P_RERUN_CAP, event_id="learning_focus")
        check("run #2: the capped event's last_delivered_at remains untouched", row_learning.last_delivered_at is None)

        # ==============================================================
        print("\n=== Test E: daily-cap window boundary is timezone-correct at the SQL level ===")
        # ==============================================================
        # Directly guards against a real bug caught during development:
        # resolve_current_alert_day_start() returns a TZ-AWARE,
        # IST-labeled datetime, while last_delivered_at is a naive
        # "timestamp without time zone" column -- and this Postgres
        # session's own timezone is Asia/Calcutta, so a naive/aware
        # comparison does NOT error, it silently reinterprets the naive
        # side as IST wall-clock time, shifting the effective boundary
        # by 5.5 hours. resolve_daily_cap_window_start() must always
        # return a NAIVE, UTC-equivalent value.
        since = resolve_daily_cap_window_start(None, None, now)
        check("resolve_daily_cap_window_start() returns a naive datetime", since.tzinfo is None)
        expected_utc = datetime(2026, 8, 13, 18, 30, 0)  # IST midnight of 2026-08-14, in UTC
        check("value is the correct UTC-equivalent instant (IST-midnight fallback)", since == expected_utc)

        just_before = since - timedelta(minutes=1)
        just_after = since + timedelta(minutes=1)
        r_before = db.session.execute(text("SELECT :v >= :since"), {"v": just_before, "since": since}).scalar()
        r_after = db.session.execute(text("SELECT :v >= :since"), {"v": just_after, "since": since}).scalar()
        check("SQL comparison: 1 minute before window start correctly excluded", r_before is False)
        check("SQL comparison: 1 minute after window start correctly included", r_after is True)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
