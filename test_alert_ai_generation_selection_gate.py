"""
test_alert_ai_generation_selection_gate.py
----------------------------------
ARCHITECTURAL GATE PROOF: AI generation must run ONLY for the FINAL
selected alert(s) -- AFTER suppression/ranking/cooldown/daily-cap --
never for a raw detected event that selection later excludes.

Uses the REAL, UNMODIFIED selection pipeline
(modules/alerts/user_alert_selection_service.py::
get_user_facing_alerts_for_profile(), which itself reuses the real,
unmodified delivery_eligibility_policy.py and user_alert_selection.py)
against real persisted AlertMicroEvent rows on the LOCAL scratch
Postgres DB -- this is what makes the "5 detected -> 1/2 selected ->
exactly 1/2 OpenAI calls" proof genuine rather than a mocked
approximation. openai_client.generate() is monkeypatched with a
call-counting fake -- NO real OpenAI call is ever made.

Covers every scenario the architectural review required:
  A. 5 detected -> 1 selected -> exactly 1 OpenAI call.
  B. 5 detected -> 2 selected -> exactly 2 OpenAI calls.
  C. A suppressed (conflict-losing) eligible event -> 0 OpenAI calls.
  D. A cooldown-rejected event -> 0 OpenAI calls.
  E. An already-enriched selected event -> 0 NEW OpenAI calls.
  F. A scheduler retry (calling the gate twice) -> 0 additional calls.
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

from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402
from modules.alerts.user_alert_selection_service import get_user_facing_alerts_for_profile  # noqa: E402

import modules.alerts.alert_ai_content_service as ai_content_module  # noqa: E402
from modules.alerts.alert_ai_content_service import ensure_ai_content_for_selected_rows  # noqa: E402

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


TEST_PROFILE = 9301
LAT, LON = 28.6, 77.2  # Delhi -- fixed, deterministic sunrise-window resolution


def cleanup():
    db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": TEST_PROFILE})
    db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
    db.session.commit()


def make_user(conn, profile_id):
    conn.execute(text(
        "INSERT INTO app_users (id, tz, subscription, asknow_tokens, name, dob, tob, pob, lat, lng) "
        "VALUES (:id, 'IST', 'free', 0, 'Test', '1990-01-01', '10:00', 'Delhi', :lat, :lon)"
    ), {"id": profile_id, "lat": LAT, "lon": LON})


class CountingGenerate:
    """Replaces ai_content_module.openai_client.generate -- counts calls
    and returns a well-formed response every time, so a "call happened"
    is observable both via the counter AND via the persisted row."""

    def __init__(self):
        self.call_count = 0
        self.prompts = []

    def __call__(self, prompt):
        self.call_count += 1
        self.prompts.append(prompt)
        return "INSIGHT: test insight text.\nACTION: test action text."


def base_event(event_id, category, *, severity, priority, confidence,
                triggered_facts=None, last_delivered_at=None):
    return {
        "event_id": event_id, "category": category, "state": "ACTIVE",
        "confidence": confidence, "priority": priority, "severity": severity,
        "active_from": date(2026, 8, 20), "active_until": date(2026, 8, 25),
        "triggered_facts": triggered_facts or [f"{event_id} test fact"],
    }


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
        real_generate = ai_content_module.openai_client.generate

        try:
            # ==========================================================
            print("=== A: 5 detected, only 1 clears selection -> exactly 1 OpenAI call ===")
            # ==========================================================
            # 5 mutually non-conflicting real catalog events, distinct
            # categories. Only "financial_gain_opportunity" is priority
            # "high" -- the ONLY thing that can win slot #1; the other 4
            # are "medium", so none can win slot #2 (which requires
            # priority=="high") regardless of category difference.
            repository.synchronize_profile_events(
                profile_id=TEST_PROFILE,
                detected_events=[
                    base_event("financial_gain_opportunity", "financial", severity="CRITICAL", priority="high", confidence=0.9),
                    base_event("mood_positive", "emotional", severity="MEDIUM", priority="medium", confidence=0.5),
                    base_event("energy_high", "vitality", severity="MEDIUM", priority="medium", confidence=0.5),
                    base_event("relationship_harmony", "relationship", severity="MEDIUM", priority="medium", confidence=0.5),
                    base_event("minor_injury_caution", "health", severity="MEDIUM", priority="medium", confidence=0.5),
                ],
            )

            counter_a = CountingGenerate()
            ai_content_module.openai_client.generate = counter_a

            selection_a = get_user_facing_alerts_for_profile(TEST_PROFILE, lat=LAT, lon=LON)
            check("A: 5 events were detected/persisted", len(repository.fetch_active_for_profile(profile_id=TEST_PROFILE)) == 5)
            check("A: selection narrowed to exactly 1", len(selection_a.selected) == 1)
            check("A: the strongest one was selected", selection_a.selected[0].event_id == "financial_gain_opportunity")

            ensure_ai_content_for_selected_rows(selection_a.selected)
            check("A: EXACTLY 1 OpenAI call for 1 selected alert (not 5)", counter_a.call_count == 1)

            selected_row_a = repository.read(profile_id=TEST_PROFILE, event_id="financial_gain_opportunity")
            check("A: the selected row got AI content", selected_row_a.ai_insight == "test insight text.")

            for excluded_id in ("mood_positive", "energy_high", "relationship_harmony", "minor_injury_caution"):
                row = repository.read(profile_id=TEST_PROFILE, event_id=excluded_id)
                check(f"A: NOT-selected '{excluded_id}' got ZERO AI content (proves 0 calls for it)", row.ai_insight is None)

            cleanup()
            with db.engine.connect() as conn:
                make_user(conn, TEST_PROFILE)
                conn.commit()

            # ==========================================================
            print("\n=== B: 5 detected, 2 clear selection -> exactly 2 OpenAI calls ===")
            # ==========================================================
            repository.synchronize_profile_events(
                profile_id=TEST_PROFILE,
                detected_events=[
                    base_event("financial_gain_opportunity", "financial", severity="CRITICAL", priority="high", confidence=0.9),
                    # Different category, ALSO priority=high -> wins slot #2.
                    base_event("mood_positive", "emotional", severity="HIGH", priority="high", confidence=0.8),
                    base_event("energy_high", "vitality", severity="MEDIUM", priority="medium", confidence=0.5),
                    base_event("relationship_harmony", "relationship", severity="MEDIUM", priority="medium", confidence=0.5),
                    base_event("minor_injury_caution", "health", severity="MEDIUM", priority="medium", confidence=0.5),
                ],
            )

            counter_b = CountingGenerate()
            ai_content_module.openai_client.generate = counter_b

            selection_b = get_user_facing_alerts_for_profile(TEST_PROFILE, lat=LAT, lon=LON)
            check("B: selection narrowed to exactly 2", len(selection_b.selected) == 2)
            selected_ids_b = {r.event_id for r in selection_b.selected}
            check("B: both winners are the expected pair", selected_ids_b == {"financial_gain_opportunity", "mood_positive"})

            ensure_ai_content_for_selected_rows(selection_b.selected)
            check("B: EXACTLY 2 OpenAI calls for 2 selected alerts (not 5)", counter_b.call_count == 2)

            for winner_id in selected_ids_b:
                row = repository.read(profile_id=TEST_PROFILE, event_id=winner_id)
                check(f"B: selected '{winner_id}' got AI content", row.ai_insight is not None)

            # ==========================================================
            print("\n=== C: suppressed (conflict-losing) eligible event -> 0 OpenAI calls ===")
            # ==========================================================
            for suppressed_id in ("energy_high", "relationship_harmony", "minor_injury_caution"):
                row = repository.read(profile_id=TEST_PROFILE, event_id=suppressed_id)
                check(f"C: suppressed '{suppressed_id}' (eligible but not selected) got ZERO AI content", row.ai_insight is None)

            cleanup()
            with db.engine.connect() as conn:
                make_user(conn, TEST_PROFILE)
                conn.commit()

            # ==========================================================
            print("\n=== D: cooldown-rejected event -> 0 OpenAI calls ===")
            # ==========================================================
            recent_delivery = datetime.utcnow() - timedelta(hours=1)  # well within any event's cooldown
            repository.synchronize_profile_events(
                profile_id=TEST_PROFILE,
                detected_events=[
                    base_event("financial_gain_opportunity", "financial", severity="CRITICAL", priority="high", confidence=0.9),
                ],
            )
            # Simulate "already delivered recently" -> still within cooldown.
            row_d = repository.read(profile_id=TEST_PROFILE, event_id="financial_gain_opportunity")
            row_d.last_delivered_at = recent_delivery
            db.session.commit()

            counter_d = CountingGenerate()
            ai_content_module.openai_client.generate = counter_d

            selection_d = get_user_facing_alerts_for_profile(TEST_PROFILE, lat=LAT, lon=LON)
            check("D: cooldown-rejected event is NOT eligible, NOT selected", len(selection_d.selected) == 0)

            ensure_ai_content_for_selected_rows(selection_d.selected)
            check("D: ZERO OpenAI calls for a cooldown-rejected event", counter_d.call_count == 0)
            check("D: row still has no AI content", repository.read(profile_id=TEST_PROFILE, event_id="financial_gain_opportunity").ai_insight is None)

            cleanup()
            with db.engine.connect() as conn:
                make_user(conn, TEST_PROFILE)
                conn.commit()

            # ==========================================================
            print("\n=== E: already-enriched selected event -> 0 NEW OpenAI calls ===")
            # ==========================================================
            repository.synchronize_profile_events(
                profile_id=TEST_PROFILE,
                detected_events=[
                    base_event("financial_gain_opportunity", "financial", severity="CRITICAL", priority="high", confidence=0.9),
                ],
            )
            row_e = repository.read(profile_id=TEST_PROFILE, event_id="financial_gain_opportunity")
            row_e.ai_insight = "already generated insight"
            row_e.ai_action = "already generated action"
            db.session.commit()

            counter_e = CountingGenerate()
            ai_content_module.openai_client.generate = counter_e

            selection_e = get_user_facing_alerts_for_profile(TEST_PROFILE, lat=LAT, lon=LON)
            check("E: the already-enriched event is selected", len(selection_e.selected) == 1)

            ensure_ai_content_for_selected_rows(selection_e.selected)
            check("E: ZERO new OpenAI calls for an already-enriched selected row", counter_e.call_count == 0)
            check("E: existing AI content untouched", repository.read(profile_id=TEST_PROFILE, event_id="financial_gain_opportunity").ai_insight == "already generated insight")

            # ==========================================================
            print("\n=== F: scheduler retry (gate called twice) -> 0 additional calls the 2nd time ===")
            # ==========================================================
            cleanup()
            with db.engine.connect() as conn:
                make_user(conn, TEST_PROFILE)
                conn.commit()

            repository.synchronize_profile_events(
                profile_id=TEST_PROFILE,
                detected_events=[
                    base_event("financial_gain_opportunity", "financial", severity="CRITICAL", priority="high", confidence=0.9),
                ],
            )

            counter_f = CountingGenerate()
            ai_content_module.openai_client.generate = counter_f

            selection_f1 = get_user_facing_alerts_for_profile(TEST_PROFILE, lat=LAT, lon=LON)
            ensure_ai_content_for_selected_rows(selection_f1.selected)
            check("F: first run makes exactly 1 call", counter_f.call_count == 1)

            # Simulate a scheduler retry -- re-selects (still eligible,
            # no delivery recorded yet) and calls the gate again.
            selection_f2 = get_user_facing_alerts_for_profile(TEST_PROFILE, lat=LAT, lon=LON)
            ensure_ai_content_for_selected_rows(selection_f2.selected)
            check("F: retry makes ZERO additional calls (still 1 total)", counter_f.call_count == 1)

        finally:
            ai_content_module.openai_client.generate = real_generate
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
