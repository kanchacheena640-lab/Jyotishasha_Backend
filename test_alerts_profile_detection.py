"""
test_alerts_profile_detection.py
-----------------------------------
Local-only entry point for the Phase 2 Profile-Level Detection Service
(modules/alerts/profile_detection_service.py) and the Phase 2 addition
to the persistence repository
(modules/alerts/persistence_repository.py::synchronize_profile_events()).
Mirrors test_alerts_persistence.py's own local-only, assert-based
pattern (no pytest infrastructure exists in this repository).

IMPORTANT: this script points DATABASE_URL at the LOCAL scratch
Postgres database (jyotishasha_local) ONLY, set before importing
app/factory -- it must never run against production.

Lifecycle transitions (NEW -> ACTIVE -> EXPIRED -> reappearing) are
tested with an INJECTED FAKE planning engine (a stub with the exact
same `.plan(kundali) -> List[PlannedMicroEvent]` contract
PlanningWindowEngine.plan() has) rather than the real, live-transit-
driven engine -- this makes the transitions deterministic and
reproducible on any day this script is run, and tests
ProfileDetectionService's own reconciliation logic in isolation. The
REAL, unmodified PlanningWindowEngine is already covered by
test_alerts_planning_window.py (re-run below as a regression check,
unmodified).
"""

import os
import sys
from datetime import date, datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from modules.alerts.persistence_models import AlertMicroEvent  # noqa: E402
from modules.alerts.persistence_repository import (  # noqa: E402
    AlertPersistenceRepository, AlertPersistenceError,
)
from modules.alerts.planning_models import PlannedMicroEvent  # noqa: E402
from modules.alerts.profile_detection_service import (  # noqa: E402
    ProfileDetectionService, ProfileDataError, DetectionRunFailedError,
)

TEST_PROFILE_A = 9101
TEST_PROFILE_B = 9102
NONEXISTENT_PROFILE = 9999999

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


def cleanup():
    db.session.execute(text(
        "DELETE FROM alert_micro_events WHERE profile_id IN (:a, :b, :c)"
    ), {"a": TEST_PROFILE_A, "b": TEST_PROFILE_B, "c": NONEXISTENT_PROFILE})
    db.session.execute(text(
        "DELETE FROM app_users WHERE id IN (:a, :b)"
    ), {"a": TEST_PROFILE_A, "b": TEST_PROFILE_B})
    db.session.commit()


def make_user(conn, profile_id):
    conn.execute(text(
        "INSERT INTO app_users (id, tz, subscription, asknow_tokens, name, dob, tob, pob, lat, lng) "
        "VALUES (:id, 'IST', 'free', 0, 'Test', '1990-01-01', '10:00', 'Delhi', 28.6, 77.2)"
    ), {"id": profile_id})


def planned(event_id, category, is_active, is_new, confidence=0.7, priority="high",
            active_from="2026-08-13", active_until="2026-08-15"):
    return PlannedMicroEvent(
        event_id=event_id, title=event_id, category=category,
        confidence=confidence, priority=priority,
        active_from=active_from, active_until=active_until,
        is_new=is_new, is_active=is_active, triggered_rules=[],
    )


class FakePlanningEngine:
    """Stub matching PlanningWindowEngine.plan()'s exact contract
    (including Phase 3's optional `day_anchors` parameter, accepted and
    ignored here -- this fake doesn't exercise real sunrise mechanics,
    only ProfileDetectionService's own reconciliation logic) --
    returns a hand-picked, deterministic list instead of running the
    real Rule Engine against live transits."""

    window_days = 4  # ProfileDetectionService reads this to size day_anchors

    def __init__(self, events=None, raise_error=False):
        self._events = events or []
        self._raise_error = raise_error

    def plan(self, kundali, day_anchors=None):
        if self._raise_error:
            raise RuntimeError("Simulated Rule Engine failure")
        return self._events


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE_A)
            make_user(conn, TEST_PROFILE_B)
            conn.commit()

        repo = AlertPersistenceRepository()

        # ------------------------------------------------------------
        print("\n=== Test 1: first successful profile evaluation ===")
        # ------------------------------------------------------------
        engine1 = FakePlanningEngine([
            planned("mood_positive", "emotional", is_active=False, is_new=True),
            planned("financial_gain_opportunity", "financial", is_active=True, is_new=False),
        ])
        service = ProfileDetectionService(planning_engine=engine1, repository=repo)
        result1 = service.evaluate_profile(TEST_PROFILE_A)
        check("2 events detected", result1.events_detected == 2)
        check("2 rows created", result1.created == 2)
        check("0 updated/reactivated/expired on first run", (result1.updated, result1.reactivated, result1.expired) == (0, 0, 0))
        check("duration measured", result1.duration_seconds >= 0)
        check("events_evaluated reflects full catalog size", result1.events_evaluated > 0)

        row_mood = repo.read(profile_id=TEST_PROFILE_A, event_id="mood_positive")
        row_fin = repo.read(profile_id=TEST_PROFILE_A, event_id="financial_gain_opportunity")
        check("mood_positive persisted as NEW", row_mood.state == "NEW")
        check("financial_gain_opportunity persisted as ACTIVE", row_fin.state == "ACTIVE")
        first_detected_at_original = row_fin.first_detected_at

        # ------------------------------------------------------------
        print("\n=== Test 2: repeated evaluation without duplicates ===")
        # ------------------------------------------------------------
        result2 = service.evaluate_profile(TEST_PROFILE_A)  # same engine1, same events
        check("still exactly 2 rows for profile A", AlertMicroEvent.query.filter_by(profile_id=TEST_PROFILE_A).count() == 2)
        check("second identical run reports updated, not created", result2.created == 0 and result2.updated == 2)

        # ------------------------------------------------------------
        print("\n=== Test 3: NEW -> ACTIVE ===")
        # ------------------------------------------------------------
        engine2 = FakePlanningEngine([
            planned("mood_positive", "emotional", is_active=True, is_new=False),  # now ACTIVE (was NEW)
            planned("financial_gain_opportunity", "financial", is_active=True, is_new=False),
        ])
        service_run3 = ProfileDetectionService(planning_engine=engine2, repository=repo)
        result3 = service_run3.evaluate_profile(TEST_PROFILE_A)
        row_mood_after = repo.read(profile_id=TEST_PROFILE_A, event_id="mood_positive")
        check("mood_positive transitioned NEW -> ACTIVE", row_mood_after.state == "ACTIVE")
        check("no duplicate row created for the transition", AlertMicroEvent.query.filter_by(profile_id=TEST_PROFILE_A, event_id="mood_positive").count() == 1)

        # ------------------------------------------------------------
        print("\n=== Test 4: ACTIVE -> EXPIRED ===")
        # ------------------------------------------------------------
        engine3 = FakePlanningEngine([
            planned("financial_gain_opportunity", "financial", is_active=True, is_new=False),
            # mood_positive NOT detected this run
        ])
        service_run4 = ProfileDetectionService(planning_engine=engine3, repository=repo)
        result4 = service_run4.evaluate_profile(TEST_PROFILE_A)
        row_mood_expired = repo.read(profile_id=TEST_PROFILE_A, event_id="mood_positive")
        check("mood_positive transitioned to EXPIRED", row_mood_expired.state == "EXPIRED")
        check("expired count == 1", result4.expired == 1)
        check("row still exists (not deleted)", row_mood_expired is not None)
        check("confidence preserved from last real detection", row_mood_expired.confidence == 0.7)

        # ------------------------------------------------------------
        print("\n=== Test 5: EXPIRED -> reappearing event ===")
        # ------------------------------------------------------------
        engine4 = FakePlanningEngine([
            planned("financial_gain_opportunity", "financial", is_active=True, is_new=False),
            planned("mood_positive", "emotional", is_active=True, is_new=False, confidence=0.55),  # reappears
        ])
        service_run5 = ProfileDetectionService(planning_engine=engine4, repository=repo)
        result5 = service_run5.evaluate_profile(TEST_PROFILE_A)
        row_mood_reappeared = repo.read(profile_id=TEST_PROFILE_A, event_id="mood_positive")
        check("mood_positive reactivated (EXPIRED -> ACTIVE)", row_mood_reappeared.state == "ACTIVE")
        check("reactivated count == 1", result5.reactivated == 1)
        check("still only ONE row for (profile, event) after reappearance", AlertMicroEvent.query.filter_by(profile_id=TEST_PROFILE_A, event_id="mood_positive").count() == 1)
        check("confidence updated to the new detection's value", row_mood_reappeared.confidence == 0.55)
        check("first_detected_at UNCHANGED across expiry+reappearance", row_mood_reappeared.first_detected_at == row_mood.first_detected_at)

        # ------------------------------------------------------------
        print("\n=== Test 6: failed engine evaluation does not expire existing alerts ===")
        # ------------------------------------------------------------
        before_states = {
            r.event_id: (r.state, r.last_evaluated_at)
            for r in repo.fetch_history_for_profile(profile_id=TEST_PROFILE_A)
        }
        failing_engine = FakePlanningEngine(raise_error=True)
        service_fail = ProfileDetectionService(planning_engine=failing_engine, repository=repo)
        raised = False
        try:
            service_fail.evaluate_profile(TEST_PROFILE_A)
        except DetectionRunFailedError:
            raised = True
        check("DetectionRunFailedError raised", raised)

        after_states = {
            r.event_id: (r.state, r.last_evaluated_at)
            for r in repo.fetch_history_for_profile(profile_id=TEST_PROFILE_A)
        }
        check("no existing row's state OR last_evaluated_at changed after a failed run", before_states == after_states)

        # ------------------------------------------------------------
        print("\n=== Test 7: one profile evaluation cannot modify another profile ===")
        # ------------------------------------------------------------
        engine_b = FakePlanningEngine([
            planned("unexpected_expense", "financial", is_active=True, is_new=False),
        ])
        service_b = ProfileDetectionService(planning_engine=engine_b, repository=repo)
        service_b.evaluate_profile(TEST_PROFILE_B)

        profile_a_rows_after = {r.event_id: r.state for r in repo.fetch_history_for_profile(profile_id=TEST_PROFILE_A)}
        profile_b_rows = {r.event_id: r.state for r in repo.fetch_history_for_profile(profile_id=TEST_PROFILE_B)}
        check("profile A untouched by profile B's evaluation", profile_a_rows_after == {eid: after_states[eid][0] for eid in after_states})
        check("profile B has its own, separate row", profile_b_rows == {"unexpected_expense": "ACTIVE"})
        check("profile B's event_id does not leak into profile A", "unexpected_expense" not in profile_a_rows_after)

        # ------------------------------------------------------------
        print("\n=== Test 8: invalid/missing profile fails safely ===")
        # ------------------------------------------------------------
        raised_profile_error = False
        try:
            service.evaluate_profile(NONEXISTENT_PROFILE)
        except ProfileDataError:
            raised_profile_error = True
        check("ProfileDataError raised for nonexistent profile_id", raised_profile_error)
        check("zero rows written for the nonexistent profile", AlertMicroEvent.query.filter_by(profile_id=NONEXISTENT_PROFILE).count() == 0)

        # ------------------------------------------------------------
        print("\n=== Test 9: persistence/transaction failure is surfaced ===")
        # ------------------------------------------------------------
        # Force a REAL DB-level failure: profile_id that violates the
        # actual foreign key constraint (does not exist in app_users).
        # Proves synchronize_profile_events() surfaces the failure
        # (does not swallow it) AND rolls back fully (no partial rows).
        raised_persistence_error = False
        try:
            repo.synchronize_profile_events(
                profile_id=NONEXISTENT_PROFILE,
                detected_events=[{
                    "event_id": "mood_positive", "category": "emotional",
                    "state": "NEW", "confidence": 0.5, "priority": "medium",
                    "active_from": date(2026, 8, 13), "active_until": date(2026, 8, 13),
                }],
            )
        except AlertPersistenceError:
            raised_persistence_error = True
        check("AlertPersistenceError raised on FK violation (not swallowed)", raised_persistence_error)
        check("zero rows committed from the failed batch", AlertMicroEvent.query.filter_by(profile_id=NONEXISTENT_PROFILE).count() == 0)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
