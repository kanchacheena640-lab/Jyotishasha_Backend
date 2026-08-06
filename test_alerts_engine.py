"""
test_alerts_engine.py
----------------------
Local-only entry point for the Micro Event Engine (Alerts Engine).
Mirrors test_love.py's/test_career.py's/etc.'s local-only pattern, but
exercises modules/alerts/ instead -- a completely independent module,
so this script imports nothing from services/ai_prediction_lab or any
Premium Generator.

Phase 2 -- demonstrates the expanded Astrological Rule Library:
increased rule coverage per event, confidence distribution across a
richer signal set, dynamic priority derived from actual matched rules,
and Stable Phase fallback behavior.

This script does not touch Flask, Celery, the database, or any existing
production route, and never calls OpenAI -- this remains detection
only, no language generation.
"""

import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from full_kundali_api import calculate_full_kundali
from modules.alerts.event_registry import get_default_registry
from modules.alerts.evaluation_context import build_evaluation_context
from modules.alerts.micro_event_engine import MicroEventEngine

# Same demo birth data every Premium Generator's own test script uses
# (Ravi, Lucknow, Uttar Pradesh, India). The Micro Event Engine's
# results still depend on today's live transits, so they will differ
# run to run as time passes -- only the RULE COVERAGE and MECHANISM are
# what this script actually validates.
DEMO_PERSON = {
    "name": "Ravi",
    "dob": "1985-03-31",
    "tob": "19:45",
    "lat": 26.8467,
    "lon": 80.9462,
    "language": "en",
}


def main():
    registry = get_default_registry()
    print("=" * 60)
    print("EVENT REGISTRY (Phase 2 -- expanded rule coverage)")
    print("=" * 60)
    normal_events = registry.all_events()
    fallback_events = registry.fallback_events()
    print(f"Loaded {len(registry)} events total "
          f"({len(normal_events)} normal + {len(fallback_events)} fallback)")
    print(f"Priority thresholds: {registry.priority_thresholds}")
    print()
    rule_counts = [len(e.rules) for e in normal_events]
    print(f"Rules per normal event: min={min(rule_counts)} max={max(rule_counts)} "
          f"avg={sum(rule_counts)/len(rule_counts):.1f}")
    for event in sorted(normal_events, key=lambda e: e.event_id):
        condition_types = sorted({r.condition for r in event.rules})
        print(f"  {event.event_id:38s} rules={len(event.rules)}  "
              f"signal_types={condition_types}")
    print(f"  Fallback event(s): {[e.event_id for e in fallback_events]}")

    print("\n" + "=" * 60)
    print("STAGE 1: PLANET DATA + NATAL SUPPORT DATA")
    print("=" * 60)
    kundali = calculate_full_kundali(
        name=DEMO_PERSON["name"], dob=DEMO_PERSON["dob"], tob=DEMO_PERSON["tob"],
        lat=DEMO_PERSON["lat"], lon=DEMO_PERSON["lon"], user_id=None,
        language=DEMO_PERSON["language"],
    )
    context = build_evaluation_context(kundali)
    print(f"Natal Lagna: {context.lagna_sign}")
    print(f"Mahadasha lord: {context.mahadasha_lord}  Antardasha lord: {context.antardasha_lord}")
    active = [k for k, v in context.active_yogas.items() if v]
    print(f"Active natal yogas: {active}")
    for planet, snap in context.planet_snapshots.items():
        print(f"  {planet:8s} sign={snap.sign:12s} house={snap.house} "
              f"nakshatra={snap.nakshatra} motion={snap.motion}")

    print("\n" + "=" * 60)
    print("STAGE 2-4: RULE ENGINE -> DETECTED EVENTS -> CONFIDENCE -> PRIORITY")
    print("=" * 60)
    engine = MicroEventEngine(registry=registry)
    detected = engine.detect(kundali)

    for event in detected:
        rule_ids = ", ".join(r.rule_id for r in event.triggered_rules)
        print(
            f"  [{event.priority:6s}] {event.title:35s} "
            f"confidence={event.confidence:.2f}  matched_rules={len(event.triggered_rules)}  "
            f"category={event.category:12s}\n"
            f"           triggered=({rule_ids})"
        )

    print("\n" + "=" * 60)
    print("CONFIDENCE / PRIORITY DISTRIBUTION")
    print("=" * 60)
    by_priority = {"high": 0, "medium": 0, "low": 0}
    for event in detected:
        by_priority[event.priority] += 1
    print(f"  high={by_priority['high']}  medium={by_priority['medium']}  low={by_priority['low']}")
    print(f"  total detected: {len(detected)}")

    print("\n" + "=" * 60)
    print("STABLE PHASE BEHAVIOUR CHECK")
    print("=" * 60)
    # Build a registry with only impossible-to-match events (a house
    # that doesn't exist) to force the "nothing matched" path and prove
    # Stable Phase fires -- via the SAME generic is_fallback mechanism,
    # not a special code path for this test.
    from modules.alerts.event_registry import EventRegistry
    from modules.alerts.event_models import MicroEventDefinition, RuleDefinition

    impossible_event = MicroEventDefinition(
        event_id="impossible_test_event",
        title="Impossible Test Event",
        category="test",
        min_rules_required=1,
        is_fallback=False,
        rules=[RuleDefinition(
            rule_id="impossible_house", planet="Moon", condition="house_in", value=[], weight=1.0,
        )],
    )
    stable_phase_def = registry.get("stable_phase")
    forced_empty_registry = EventRegistry([impossible_event, stable_phase_def], registry.priority_thresholds)
    forced_engine = MicroEventEngine(registry=forced_empty_registry)
    forced_result = forced_engine.detect(kundali)
    print(f"  With a registry that can never match a normal event: "
          f"{[e.event_id for e in forced_result]}")
    assert len(forced_result) == 1 and forced_result[0].event_id == "stable_phase", (
        "Stable Phase fallback did not fire as expected"
    )
    print("  [OK] Stable Phase correctly returned instead of an empty result.")

    print("\n" + "=" * 60)
    print("STAGE 5: JSON OUTPUT (real chart)")
    print("=" * 60)
    output_json = engine.detect_as_json(kundali)
    print(output_json)

    with open("alerts_engine_sample_output.json", "w", encoding="utf-8") as f:
        f.write(output_json)
    print("\n[OK] Sample output saved -> alerts_engine_sample_output.json")

    # Sanity assertions -- this script doubles as the local validation
    # this phase's deliverable calls for.
    assert len(registry) == 23, f"Expected 23 catalog entries (22 events + Stable Phase), found {len(registry)}"
    assert len(normal_events) == 22
    assert len(fallback_events) == 1 and fallback_events[0].event_id == "stable_phase"
    assert min(rule_counts) >= 5, "Every normal event should have at least 5 rules"
    for event in detected:
        assert 0.0 <= event.confidence <= 1.0
        assert event.priority in ("high", "medium", "low")
        assert len(event.triggered_rules) >= 1
    assert isinstance(json.loads(output_json), list)
    print("\n[OK] All validation assertions passed.")


if __name__ == "__main__":
    main()
