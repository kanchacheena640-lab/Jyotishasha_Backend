"""
test_alerts_severity_cooldown.py
------------------------------------
Local-only entry point for the Phase 4 severity + cooldown policy
layer:
  - modules/alerts/severity_cooldown_registry.py (config loading/
    validation)
  - modules/alerts/delivery_eligibility_policy.py (the pure eligibility
    decision function)
  - the Phase 4 additions to modules/alerts/persistence_models.py /
    persistence_repository.py / profile_detection_service.py (severity
    persisted per row; last_delivered_at never touched by detection)

Most of these tests are PURE function tests (no database, no Flask app
context needed) -- evaluate_delivery_eligibility() and
load_severity_cooldown_policy() take/return plain values with no I/O
of their own. The final section (end-to-end) DOES use the LOCAL
scratch Postgres DB ONLY, exactly like every other test_alerts_*.py
script in this repository, to prove severity is actually persisted
through a real ProfileDetectionService.evaluate_profile() call.
"""

import os
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.alerts.event_registry import get_default_registry  # noqa: E402
from modules.alerts.severity_cooldown_registry import (  # noqa: E402
    load_severity_cooldown_policy, get_default_severity_cooldown_registry,
    SeverityCooldownConfigError, SEVERITY_LEVELS,
)
from modules.alerts.delivery_eligibility_policy import evaluate_delivery_eligibility  # noqa: E402

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
    catalog = get_default_registry()
    policy_registry = get_default_severity_cooldown_registry()

    # ------------------------------------------------------------
    print("=== Test 1: every catalog event has valid severity/cooldown ===")
    # ------------------------------------------------------------
    for event_id in catalog.event_ids():
        try:
            policy = policy_registry.get(event_id)
            check(f"{event_id}: severity {policy.severity} is valid", policy.severity in SEVERITY_LEVELS)
            check(f"{event_id}: cooldown_hours {policy.cooldown_hours} > 0", policy.cooldown_hours > 0)
        except SeverityCooldownConfigError as exc:
            check(f"{event_id}: has a policy entry (none found: {exc})", False)
    check(f"policy registry covers all {len(catalog.event_ids())} catalog events", len(policy_registry) == len(catalog.event_ids()))

    # ------------------------------------------------------------
    print("\n=== Test 2: invalid severity rejected at load time ===")
    # ------------------------------------------------------------
    import json, tempfile
    bad_severity_config = {
        "events": {eid: {"severity": "SUPER_URGENT", "cooldown_hours": 24} for eid in catalog.event_ids()}
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(bad_severity_config, f)
        bad_severity_path = f.name
    raised = False
    try:
        load_severity_cooldown_policy(config_path=bad_severity_path, event_registry=catalog)
    except SeverityCooldownConfigError:
        raised = True
    check("unknown severity value rejected", raised)
    os.unlink(bad_severity_path)

    # ------------------------------------------------------------
    print("\n=== Test 3: invalid cooldown rejected at load time ===")
    # ------------------------------------------------------------
    for bad_value, label in [(-5, "negative"), (0, "zero"), ("soon", "non-numeric"), (None, "missing")]:
        bad_cooldown_config = {
            "events": {eid: {"severity": "LOW", "cooldown_hours": bad_value} for eid in catalog.event_ids()}
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(bad_cooldown_config, f)
            path = f.name
        raised = False
        try:
            load_severity_cooldown_policy(config_path=path, event_registry=catalog)
        except SeverityCooldownConfigError:
            raised = True
        check(f"cooldown_hours={bad_value!r} ({label}) rejected", raised)
        os.unlink(path)

    # ------------------------------------------------------------
    print("\n=== Test 3b: missing catalog coverage / orphaned entry rejected ===")
    # ------------------------------------------------------------
    incomplete_config = {
        "events": {eid: {"severity": "LOW", "cooldown_hours": 24}
                   for eid in list(catalog.event_ids())[:-1]}  # drop one event
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(incomplete_config, f)
        path = f.name
    raised = False
    try:
        load_severity_cooldown_policy(config_path=path, event_registry=catalog)
    except SeverityCooldownConfigError:
        raised = True
    check("config missing coverage for a real catalog event is rejected", raised)
    os.unlink(path)

    orphaned_config = {
        "events": {eid: {"severity": "LOW", "cooldown_hours": 24} for eid in catalog.event_ids()}
    }
    orphaned_config["events"]["not_a_real_event_id"] = {"severity": "LOW", "cooldown_hours": 24}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(orphaned_config, f)
        path = f.name
    raised = False
    try:
        load_severity_cooldown_policy(config_path=path, event_registry=catalog)
    except SeverityCooldownConfigError:
        raised = True
    check("config referencing an unknown event_id is rejected", raised)
    os.unlink(path)

    # ------------------------------------------------------------
    print("\n=== Test 4: NEW is eligible (fresh event, never delivered) ===")
    # ------------------------------------------------------------
    now = datetime(2026, 8, 13, 12, 0, 0)
    result = evaluate_delivery_eligibility(
        event_id="mood_positive", state="NEW", confidence=0.7,
        last_delivered_at=None, now=now,
    )
    check("NEW, never delivered, confidence above threshold -> eligible", result.eligible)
    check("reason is informative", result.reason == "eligible")
    check("severity reported matches config", result.severity == "LOW")
    check("next_eligible_at is now + cooldown", result.next_eligible_at == now + timedelta(hours=24))

    # ------------------------------------------------------------
    print("\n=== Test 5: ACTIVE immediately after delivery is blocked ===")
    # ------------------------------------------------------------
    just_delivered = now - timedelta(minutes=5)
    result = evaluate_delivery_eligibility(
        event_id="mood_positive", state="ACTIVE", confidence=0.7,
        last_delivered_at=just_delivered, now=now,
    )
    check("ACTIVE, delivered 5 minutes ago -> NOT eligible (cooldown active)", not result.eligible)
    check("reason mentions cooldown", "cooldown" in result.reason)
    check("next_eligible_at == last_delivered_at + cooldown", result.next_eligible_at == just_delivered + timedelta(hours=24))

    # ------------------------------------------------------------
    print("\n=== Test 6: ACTIVE after cooldown has elapsed is eligible again ===")
    # ------------------------------------------------------------
    delivered_yesterday = now - timedelta(hours=25)  # mood_positive cooldown is 24h
    result = evaluate_delivery_eligibility(
        event_id="mood_positive", state="ACTIVE", confidence=0.7,
        last_delivered_at=delivered_yesterday, now=now,
    )
    check("ACTIVE, cooldown elapsed -> eligible again", result.eligible)

    # ------------------------------------------------------------
    print("\n=== Test 7: EXPIRED is never eligible ===")
    # ------------------------------------------------------------
    result_expired_fresh = evaluate_delivery_eligibility(
        event_id="mood_positive", state="EXPIRED", confidence=0.9,
        last_delivered_at=None, now=now,
    )
    check("EXPIRED, never delivered, high confidence -> still NOT eligible", not result_expired_fresh.eligible)
    check("EXPIRED reason is explicit", result_expired_fresh.reason == "event is EXPIRED")
    check("EXPIRED next_eligible_at is None (no clock-based wait applies)", result_expired_fresh.next_eligible_at is None)

    result_expired_after_cooldown = evaluate_delivery_eligibility(
        event_id="mood_positive", state="EXPIRED", confidence=0.9,
        last_delivered_at=now - timedelta(days=30), now=now,
    )
    check("EXPIRED, long past cooldown -> STILL NOT eligible (state overrides cooldown)", not result_expired_after_cooldown.eligible)

    # ------------------------------------------------------------
    print("\n=== Test 8: reactivated event during cooldown is blocked ===")
    # ------------------------------------------------------------
    # "Reactivated" = state is ACTIVE/NEW again after having been
    # EXPIRED -- from the policy's own point of view this is
    # indistinguishable from any other ACTIVE/NEW event; it is governed
    # by the exact same last_delivered_at check.
    result = evaluate_delivery_eligibility(
        event_id="unexpected_expense", state="ACTIVE", confidence=0.8,  # cooldown_hours=12
        last_delivered_at=now - timedelta(hours=2), now=now,
    )
    check("reactivated event, delivered 2h ago (cooldown=12h) -> blocked", not result.eligible)

    # ------------------------------------------------------------
    print("\n=== Test 9: reactivated event after cooldown is eligible ===")
    # ------------------------------------------------------------
    result = evaluate_delivery_eligibility(
        event_id="unexpected_expense", state="ACTIVE", confidence=0.8,
        last_delivered_at=now - timedelta(hours=13), now=now,  # cooldown_hours=12, elapsed
    )
    check("reactivated event, delivered 13h ago (cooldown=12h) -> eligible", result.eligible)

    # ------------------------------------------------------------
    print("\n=== Test 10: low-confidence event handling ===")
    # ------------------------------------------------------------
    thresholds = catalog.priority_thresholds
    below_medium = thresholds["medium"] - 0.01
    result = evaluate_delivery_eligibility(
        event_id="mood_positive", state="NEW", confidence=below_medium,
        last_delivered_at=None, now=now,
    )
    check(f"confidence {below_medium:.3f} below medium threshold {thresholds['medium']:.3f} -> NOT eligible", not result.eligible)
    check("low-confidence reason mentions confidence", "confidence" in result.reason)
    check("low-confidence next_eligible_at is None (no clock-based wait)", result.next_eligible_at is None)

    at_threshold = thresholds["medium"]
    result_at = evaluate_delivery_eligibility(
        event_id="mood_positive", state="NEW", confidence=at_threshold,
        last_delivered_at=None, now=now,
    )
    check("confidence exactly AT the threshold -> eligible (>=, not >)", result_at.eligible)

    # ------------------------------------------------------------
    print("\n=== Test 11: next_eligible_at correctness ===")
    # ------------------------------------------------------------
    delivered_at = datetime(2026, 8, 10, 6, 0, 0)
    result = evaluate_delivery_eligibility(
        event_id="foreign_travel_opportunity", state="ACTIVE", confidence=0.9,  # cooldown_hours=72
        last_delivered_at=delivered_at, now=delivered_at + timedelta(hours=1),
    )
    check("next_eligible_at == last_delivered_at + this event's OWN cooldown (72h)", result.next_eligible_at == delivered_at + timedelta(hours=72))

    # ------------------------------------------------------------
    print("\n=== Test 12: different events maintain independent cooldowns ===")
    # ------------------------------------------------------------
    same_delivered_at = now - timedelta(hours=13)
    result_short_cooldown = evaluate_delivery_eligibility(  # unexpected_expense: 12h
        event_id="unexpected_expense", state="ACTIVE", confidence=0.8,
        last_delivered_at=same_delivered_at, now=now,
    )
    result_long_cooldown = evaluate_delivery_eligibility(  # foreign_travel_opportunity: 72h
        event_id="foreign_travel_opportunity", state="ACTIVE", confidence=0.8,
        last_delivered_at=same_delivered_at, now=now,
    )
    check("same last_delivered_at, short-cooldown event -> eligible", result_short_cooldown.eligible)
    check("same last_delivered_at, long-cooldown event -> still blocked", not result_long_cooldown.eligible)

    # ------------------------------------------------------------
    print("\n=== Test 13: different profiles maintain independent cooldowns (policy is stateless per call) ===")
    # ------------------------------------------------------------
    # The eligibility function takes last_delivered_at as an explicit
    # input -- it has no shared/global state, so two profiles with
    # different delivery histories for the SAME event_id necessarily
    # get independent answers just by construction. Proven explicitly:
    profile_a_result = evaluate_delivery_eligibility(
        event_id="mood_positive", state="ACTIVE", confidence=0.7,
        last_delivered_at=now - timedelta(hours=1), now=now,  # profile A delivered 1h ago
    )
    profile_b_result = evaluate_delivery_eligibility(
        event_id="mood_positive", state="ACTIVE", confidence=0.7,
        last_delivered_at=None, now=now,  # profile B never delivered
    )
    check("profile A (recently delivered) -> blocked", not profile_a_result.eligible)
    check("profile B (never delivered), same event_id, same moment -> eligible", profile_b_result.eligible)

    print(f"\n{'='*50}\nPURE-FUNCTION RESULT: {passed} passed, {failed} failed so far\n{'='*50}")

    # ------------------------------------------------------------
    print("\n=== Test 14: end-to-end -- severity persisted, existing lifecycle intact ===")
    # ------------------------------------------------------------
    from app import app
    from extensions import db
    from sqlalchemy import text
    from modules.alerts.persistence_repository import AlertPersistenceRepository
    from modules.alerts.profile_detection_service import ProfileDetectionService

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", f"Refusing to run -- got {current_db!r}"

        TEST_PROFILE = 9301
        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": TEST_PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
        db.session.commit()

        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, name, dob, tob, pob, lat, lng) "
                "VALUES (:id, 'IST', 'free', 0, 'Ravi', '1985-03-31', '19:45', 'Lucknow', 26.8467, 80.9462)"
            ), {"id": TEST_PROFILE})
            conn.commit()

        repo = AlertPersistenceRepository()
        service = ProfileDetectionService(repository=repo)  # real engine, real severity registry
        result = service.evaluate_profile(TEST_PROFILE)
        check("evaluate_profile() still succeeds with Phase 4 wiring active", result.events_detected >= 1)

        rows = repo.fetch_history_for_profile(profile_id=TEST_PROFILE)
        check("at least one row persisted", len(rows) >= 1)
        check("every persisted row has a valid severity", all(r.severity in SEVERITY_LEVELS for r in rows))
        check("last_delivered_at is NULL on every row (Phase 4 never marks delivery)", all(r.last_delivered_at is None for r in rows))

        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": TEST_PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
        db.session.commit()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
