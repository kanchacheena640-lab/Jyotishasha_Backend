"""
test_alert_persistence_ai_fields.py
----------------------------------
Focused tests for the ai_insight/ai_action/ai_generated_at optional-key
handling added to
modules/alerts/persistence_repository.py::synchronize_profile_events()
-- mirrors the exact "only touched when supplied" contract `severity`
already had, proven the same way test_alerts_persistence.py already
proves it for severity.

Uses the LOCAL scratch Postgres DB ONLY.
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

from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402

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


TEST_PROFILE = 9202


def cleanup():
    db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": TEST_PROFILE})
    db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
    db.session.commit()


def make_user(conn, profile_id):
    conn.execute(text(
        "INSERT INTO app_users (id, tz, subscription, asknow_tokens, name, dob, tob, pob, lat, lng) "
        "VALUES (:id, 'IST', 'free', 0, 'Test', '1990-01-01', '10:00', 'Delhi', 28.6, 77.2)"
    ), {"id": profile_id})


def base_event(event_id, **overrides):
    event = {
        "event_id": event_id, "category": "timing", "state": "NEW",
        "confidence": 0.7, "priority": "high",
        "active_from": date(2026, 8, 20), "active_until": date(2026, 8, 22),
    }
    event.update(overrides)
    return event


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()
        with db.engine.connect() as conn:
            make_user(conn, TEST_PROFILE)
            conn.commit()

        repository = AlertPersistenceRepository()

        # ==========================================================
        print("=== A: insert with ai_insight/ai_action/ai_generated_at/triggered_facts supplied ===")
        # ==========================================================
        gen_time = datetime(2026, 8, 20, 6, 0, 0)
        facts = ["Jupiter is currently transiting house 10", "the current Mahadasha lord is Jupiter"]
        repository.synchronize_profile_events(
            profile_id=TEST_PROFILE,
            detected_events=[base_event(
                "opportunity_window",
                ai_insight="test insight", ai_action="test action", ai_generated_at=gen_time,
                triggered_facts=facts,
            )],
        )
        row = repository.read(profile_id=TEST_PROFILE, event_id="opportunity_window")
        check("A: ai_insight persisted on insert", row.ai_insight == "test insight")
        check("A: ai_action persisted on insert", row.ai_action == "test action")
        check("A: ai_generated_at persisted on insert", row.ai_generated_at == gen_time)
        check("A: triggered_facts persisted on insert", row.triggered_facts == facts)

        # ==========================================================
        print("\n=== B: insert with ai_* keys entirely omitted -> NULL, no crash ===")
        # ==========================================================
        repository.synchronize_profile_events(
            profile_id=TEST_PROFILE,
            detected_events=[base_event("delay_possible")],
        )
        row_b = repository.read(profile_id=TEST_PROFILE, event_id="delay_possible")
        check("B: ai_insight NULL when omitted", row_b.ai_insight is None)
        check("B: ai_action NULL when omitted", row_b.ai_action is None)
        check("B: ai_generated_at NULL when omitted", row_b.ai_generated_at is None)
        check("B: triggered_facts NULL when omitted", row_b.triggered_facts is None)

        # ==========================================================
        print("\n=== C: update WITHOUT ai_* keys leaves existing values untouched (never overwritten with NULL) ===")
        # ==========================================================
        repository.synchronize_profile_events(
            profile_id=TEST_PROFILE,
            detected_events=[base_event("opportunity_window", state="ACTIVE")],  # no ai_* keys this time
        )
        row_c = repository.read(profile_id=TEST_PROFILE, event_id="opportunity_window")
        check("C: ai_insight NOT overwritten by an update that omits it", row_c.ai_insight == "test insight")
        check("C: ai_action NOT overwritten by an update that omits it", row_c.ai_action == "test action")
        check("C: state still updates normally alongside", row_c.state == "ACTIVE")

        # ==========================================================
        print("\n=== D: update WITH ai_* keys overwrites correctly ===")
        # ==========================================================
        new_gen_time = datetime(2026, 8, 21, 6, 0, 0)
        repository.synchronize_profile_events(
            profile_id=TEST_PROFILE,
            detected_events=[base_event(
                "opportunity_window", state="ACTIVE",
                ai_insight="updated insight", ai_action="updated action", ai_generated_at=new_gen_time,
            )],
        )
        row_d = repository.read(profile_id=TEST_PROFILE, event_id="opportunity_window")
        check("D: ai_insight updated when explicitly supplied", row_d.ai_insight == "updated insight")
        check("D: ai_action updated when explicitly supplied", row_d.ai_action == "updated action")
        check("D: ai_generated_at updated when explicitly supplied", row_d.ai_generated_at == new_gen_time)

        # ==========================================================
        print("\n=== E: to_dict() includes the new fields ===")
        # ==========================================================
        as_dict = row_d.to_dict()
        check("E: to_dict has ai_insight", as_dict.get("ai_insight") == "updated insight")
        check("E: to_dict has ai_action", as_dict.get("ai_action") == "updated action")
        check("E: to_dict has ai_generated_at as ISO string", as_dict.get("ai_generated_at") == new_gen_time.isoformat())

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
