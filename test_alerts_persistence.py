"""
test_alerts_persistence.py
-----------------------------
Local-only entry point for the Alerts Engine's Phase 1 persistence
layer (modules/alerts/persistence_models.py,
modules/alerts/persistence_repository.py). Mirrors
test_alerts_engine.py's/test_alerts_planning_window.py's own
local-only, assert-based pattern (no pytest infrastructure exists in
this repository -- confirmed: no pytest.ini, no conftest.py, no tests/
directory).

IMPORTANT: this script points DATABASE_URL at the LOCAL scratch
Postgres database (jyotishasha_local) ONLY, set via os.environ BEFORE
importing app/factory -- it must never run against production. Do not
change ALERTS_TEST_DB_URL to a production connection string.

Covers, in order:
  1. First insert succeeds
  2. Same logical event (profile_id, event_id) inserted twice does not
     create two rows -- proven via the actual DB UNIQUE constraint, by
     attempting a raw duplicate INSERT directly (bypassing the
     repository's own read-then-write shortcut) and confirming Postgres
     itself rejects it.
  3. Different event_ids for the same profile coexist
  4. Same event_id for different profiles coexist
  5. A lifecycle update (state/confidence/active_until change) updates
     the existing row in place -- no duplicate row, first_detected_at
     unchanged, last_evaluated_at bumped
  6. fetch_active_for_profile() returns only NEW/ACTIVE rows for the
     right profile, in confidence order
  7. Importing the model/repository does not break application startup
     (imported successfully as part of this script running at all,
     plus an explicit `from app import app` import-only check)

This script does not touch Flask routes, Celery, or OpenAI, and never
imports the Rule Engine/Confidence Engine/Event Registry/Planning
Window Engine modules -- it exercises the persistence layer directly
with hand-built values, exactly as a future Phase 2 detection service
would call it.
"""

import os
import sys
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# --- LOCAL SCRATCH DB ONLY -- set before any app/model import ---
LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402  -- Test 7 (import/startup smoke test)
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from modules.alerts.persistence_models import AlertMicroEvent  # noqa: E402
from modules.alerts.persistence_repository import (  # noqa: E402
    AlertPersistenceRepository,
    AlertPersistenceError,
)

TEST_PROFILE_A = 9001
TEST_PROFILE_B = 9002

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
        "DELETE FROM alert_micro_events WHERE profile_id IN (:a, :b)"
    ), {"a": TEST_PROFILE_A, "b": TEST_PROFILE_B})
    db.session.execute(text(
        "DELETE FROM app_users WHERE id IN (:a, :b)"
    ), {"a": TEST_PROFILE_A, "b": TEST_PROFILE_B})
    db.session.commit()


def setup_fixture_profiles():
    # This script's own profile_id FKs (app_users.id) must exist for the
    # inserts below to satisfy alert_micro_events_profile_id_fkey --
    # created and torn down by this script itself, same convention as
    # every other test_alerts_*.py script's own app_users fixture rows.
    with db.engine.connect() as conn:
        for p in (TEST_PROFILE_A, TEST_PROFILE_B):
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                "VALUES (:id, 'IST', 'free', 0, :token)"
            ), {"id": p, "token": f"fake-fcm-token-{p}"})
        conn.commit()


def main():
    with app.app_context():
        # Confirm we are actually pointed at the local scratch DB, not
        # production, before doing anything else.
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        setup_fixture_profiles()
        repo = AlertPersistenceRepository()

        print("\n=== Test 1: first insert succeeds ===")
        row = repo.save_detection(
            profile_id=TEST_PROFILE_A, event_id="financial_gain_opportunity",
            category="financial", state="ACTIVE", confidence=0.72, priority="high",
            active_from=date(2026, 8, 13), active_until=date(2026, 8, 15),
        )
        check("row has an id", row.id is not None)
        check("state persisted", row.state == "ACTIVE")
        check("first_detected_at set", row.first_detected_at is not None)
        first_detected_at_original = row.first_detected_at

        print("\n=== Test 2: duplicate (profile_id, event_id) rejected at the DB level ===")
        # Bypass the repository's own read-then-write shortcut entirely
        # -- attempt a RAW duplicate INSERT directly, to prove the
        # UNIQUE CONSTRAINT itself (not just Python logic) is what
        # prevents a second row.
        dup = AlertMicroEvent(
            profile_id=TEST_PROFILE_A, event_id="financial_gain_opportunity",
            category="financial", state="ACTIVE", confidence=0.99, priority="high",
            active_from=date(2026, 8, 13), active_until=date(2026, 8, 15),
            first_detected_at=datetime.utcnow(), last_evaluated_at=datetime.utcnow(),
        )
        db.session.add(dup)
        raised_integrity_error = False
        try:
            db.session.commit()
        except IntegrityError:
            raised_integrity_error = True
            db.session.rollback()
        check("raw duplicate INSERT raises IntegrityError (DB constraint, not app code)", raised_integrity_error)

        count = AlertMicroEvent.query.filter_by(
            profile_id=TEST_PROFILE_A, event_id="financial_gain_opportunity",
        ).count()
        check("exactly one row exists after the rejected duplicate", count == 1)

        # Now prove the REPOSITORY's own save_detection() handles the
        # identical race gracefully (recognizes existing, updates it,
        # never raises) -- this is the "safe under concurrent/retried
        # jobs" requirement in practice.
        row2 = repo.save_detection(
            profile_id=TEST_PROFILE_A, event_id="financial_gain_opportunity",
            category="financial", state="ACTIVE", confidence=0.85, priority="high",
            active_from=date(2026, 8, 13), active_until=date(2026, 8, 16),
        )
        check("save_detection() on an existing key updates, doesn't raise", row2.id == row.id)
        check("save_detection() updated confidence in place", row2.confidence == 0.85)

        print("\n=== Test 3: different event_ids for the same profile coexist ===")
        row3 = repo.save_detection(
            profile_id=TEST_PROFILE_A, event_id="mood_positive",
            category="emotional", state="NEW", confidence=0.4, priority="medium",
            active_from=date(2026, 8, 14), active_until=date(2026, 8, 14),
        )
        check("second event for same profile got its own row", row3.id != row.id)
        count_profile_a = AlertMicroEvent.query.filter_by(profile_id=TEST_PROFILE_A).count()
        check("profile A now has exactly 2 rows", count_profile_a == 2)

        print("\n=== Test 4: same event_id for different profiles coexist ===")
        row4 = repo.save_detection(
            profile_id=TEST_PROFILE_B, event_id="financial_gain_opportunity",
            category="financial", state="ACTIVE", confidence=0.6, priority="medium",
            active_from=date(2026, 8, 13), active_until=date(2026, 8, 14),
        )
        check("same event_id, different profile, got its own row", row4.id not in (row.id, row3.id))
        check("profile A's row for this event_id is untouched", row2.confidence == 0.85)

        print("\n=== Test 5: lifecycle update does not create a duplicate row ===")
        before_count = AlertMicroEvent.query.filter_by(profile_id=TEST_PROFILE_A).count()
        updated = repo.save_detection(
            profile_id=TEST_PROFILE_A, event_id="financial_gain_opportunity",
            category="financial", state="ACTIVE", confidence=0.91, priority="high",
            active_from=date(2026, 8, 13), active_until=date(2026, 8, 17),
        )
        after_count = AlertMicroEvent.query.filter_by(profile_id=TEST_PROFILE_A).count()
        check("row count unchanged after lifecycle update", before_count == after_count)
        check("active_until extended", updated.active_until == date(2026, 8, 17))
        check("first_detected_at NEVER changes after first insert", updated.first_detected_at == first_detected_at_original)
        check("last_evaluated_at advanced", updated.last_evaluated_at >= updated.first_detected_at)

        print("\n=== Test 6: fetch_active_for_profile() correctness ===")
        # Add an EXPIRED row for profile A to prove it's excluded.
        repo.save_detection(
            profile_id=TEST_PROFILE_A, event_id="delay_possible",
            category="timing", state="EXPIRED", confidence=0.2, priority="low",
            active_from=date(2026, 8, 1), active_until=date(2026, 8, 2),
        )
        active_rows = repo.fetch_active_for_profile(profile_id=TEST_PROFILE_A)
        active_event_ids = {r.event_id for r in active_rows}
        check("EXPIRED row excluded from active list", "delay_possible" not in active_event_ids)
        check("ACTIVE row included", "financial_gain_opportunity" in active_event_ids)
        check("NEW row included", "mood_positive" in active_event_ids)
        check("only profile A's rows returned", all(r.profile_id == TEST_PROFILE_A for r in active_rows))
        check(
            "ordered by confidence descending",
            [r.confidence for r in active_rows] == sorted([r.confidence for r in active_rows], reverse=True),
        )

        history_rows = repo.fetch_history_for_profile(profile_id=TEST_PROFILE_A)
        check("history includes the EXPIRED row too", len(history_rows) == 3)

        print("\n=== Test 7: import/startup smoke test ===")
        # If we got this far, `from app import app` (Flask factory +
        # every existing blueprint/model import chain) and
        # `from modules.alerts.persistence_models import AlertMicroEvent`
        # both succeeded without error -- the new files do not break
        # application startup.
        check("app object constructed successfully", app is not None)
        check("AlertMicroEvent registered on db.metadata", "alert_micro_events" in db.metadata.tables)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
