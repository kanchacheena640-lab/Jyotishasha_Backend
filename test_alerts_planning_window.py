"""
test_alerts_planning_window.py
--------------------------------
Local-only entry point for the Planning Window Engine (Alerts Engine
Phase 3 -- final architecture). Separate from test_alerts_engine.py
(Phase 1/2's own validation script, left unmodified) since this phase
adds a new layer on top rather than changing the existing one.

Demonstrates:

    Current Transit -> Next 4-Day Simulation -> Detected Events
        -> Active From -> Active Until -> Event State -> JSON Output

This script does not touch Flask, Celery, the database, or any existing
production route, and never calls OpenAI.
"""

import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from full_kundali_api import calculate_full_kundali
from modules.alerts.event_registry import get_default_registry
from modules.alerts.planning_window_engine import PlanningWindowEngine, load_default_window_days

DEMO_PERSON = {
    "name": "Ravi",
    "dob": "1985-03-31",
    "tob": "19:45",
    "lat": 26.8467,
    "lon": 80.9462,
    "language": "en",
}


def main():
    default_window = load_default_window_days()
    print("=" * 60)
    print("CONFIG: PLANNING WINDOW")
    print("=" * 60)
    print(f"default_window_days (from config/planning_window.json): {default_window}")
    assert default_window == 4, "Default planning window should be 4 days per config"

    kundali = calculate_full_kundali(
        name=DEMO_PERSON["name"], dob=DEMO_PERSON["dob"], tob=DEMO_PERSON["tob"],
        lat=DEMO_PERSON["lat"], lon=DEMO_PERSON["lon"], user_id=None,
        language=DEMO_PERSON["language"],
    )
    print(f"Natal Lagna: {kundali['lagna_sign']}")

    # --------------------------------------------------------------
    # Default window (4 days) -- the production default.
    # --------------------------------------------------------------
    print("\n" + "=" * 60)
    print("CURRENT TRANSIT -> NEXT 4-DAY SIMULATION (default config)")
    print("=" * 60)
    engine = PlanningWindowEngine()
    print(f"Engine window_days resolved to: {engine.window_days}")
    planned = engine.plan(kundali)

    print(f"\n{len(planned)} events returned (NEW or ACTIVE within the window):\n")
    for event in planned:
        state = "NEW" if event.is_new else ("ACTIVE" if event.is_active else "?")
        rule_ids = ", ".join(r.rule_id for r in event.triggered_rules)
        print(
            f"  [{state:6s}][{event.priority:6s}] {event.title:35s} "
            f"confidence={event.confidence:.2f}  "
            f"active_from={event.active_from}  active_until={event.active_until}\n"
            f"                       is_new={event.is_new}  is_active={event.is_active}  "
            f"category={event.category}\n"
            f"                       triggered=({rule_ids})"
        )

    new_count = sum(1 for e in planned if e.is_new)
    active_count = sum(1 for e in planned if e.is_active)
    print(f"\nSTATE SUMMARY: NEW={new_count}  ACTIVE={active_count}  "
          f"(EXPIRED events are excluded from output entirely, by design)")

    # --------------------------------------------------------------
    # Configurable window -- prove it's not hardcoded by overriding it.
    # --------------------------------------------------------------
    print("\n" + "=" * 60)
    print("CONFIGURABILITY CHECK -- window_days overridden to 2 and 7")
    print("=" * 60)
    for override in (2, 7):
        custom_engine = PlanningWindowEngine(window_days=override)
        custom_planned = custom_engine.plan(kundali)
        print(f"  window_days={override}: engine.window_days={custom_engine.window_days}, "
              f"{len(custom_planned)} events returned")
        assert custom_engine.window_days == override

    # --------------------------------------------------------------
    # Event State layer, exercised directly and in isolation --
    # proves it's a genuinely separate layer, not baked into the Rule
    # Engine.
    # --------------------------------------------------------------
    print("\n" + "=" * 60)
    print("EVENT STATE LAYER -- exercised directly (separate from the Rule Engine)")
    print("=" * 60)
    from modules.alerts.event_state import DayResult, classify, summarize
    from modules.alerts.planning_models import EventState

    # A synthetic timeline: not active today, becomes active on day 2 -- NEW.
    new_timeline = [
        DayResult(0, "2026-01-01", None, None, []),
        DayResult(1, "2026-01-02", None, None, []),
        DayResult(2, "2026-01-03", 0.5, "medium", []),
        DayResult(3, "2026-01-04", 0.6, "high", []),
    ]
    assert classify(new_timeline) is EventState.NEW
    result = summarize("synthetic_new", "Synthetic New", "test", new_timeline)
    print(f"  NEW example      -> active_from={result.active_from} "
          f"active_until={result.active_until} confidence={result.confidence} "
          f"is_new={result.is_new} is_active={result.is_active}")
    assert result.is_new and not result.is_active
    assert result.active_from == "2026-01-03" and result.active_until == "2026-01-04"
    assert result.confidence == 0.6  # peak, not first-day

    # Active today and tomorrow, then a gap -- ACTIVE, active_until stops
    # at the contiguous streak's end.
    active_timeline = [
        DayResult(0, "2026-01-01", 0.4, "medium", []),
        DayResult(1, "2026-01-02", 0.7, "high", []),
        DayResult(2, "2026-01-03", None, None, []),
        DayResult(3, "2026-01-04", 0.3, "low", []),
    ]
    assert classify(active_timeline) is EventState.ACTIVE
    result = summarize("synthetic_active", "Synthetic Active", "test", active_timeline)
    print(f"  ACTIVE example   -> active_from={result.active_from} "
          f"active_until={result.active_until} confidence={result.confidence} "
          f"is_new={result.is_new} is_active={result.is_active}")
    assert result.is_active and not result.is_new
    assert result.active_from == "2026-01-01" and result.active_until == "2026-01-02"
    assert result.confidence == 0.7  # peak across ALL active days, incl. day 3

    # Never active at all -- EXPIRED, excluded (summarize returns None).
    expired_timeline = [
        DayResult(0, "2026-01-01", None, None, []),
        DayResult(1, "2026-01-02", None, None, []),
        DayResult(2, "2026-01-03", None, None, []),
        DayResult(3, "2026-01-04", None, None, []),
    ]
    assert classify(expired_timeline) is EventState.EXPIRED
    assert summarize("synthetic_expired", "Synthetic Expired", "test", expired_timeline) is None
    print("  EXPIRED example  -> classify()=EXPIRED, summarize()=None (excluded from output)")

    # --------------------------------------------------------------
    # JSON output.
    # --------------------------------------------------------------
    print("\n" + "=" * 60)
    print("JSON OUTPUT")
    print("=" * 60)
    output_json = engine.plan_as_json(kundali)
    print(output_json)

    with open("alerts_planning_window_sample_output.json", "w", encoding="utf-8") as f:
        f.write(output_json)
    print("\n[OK] Sample output saved -> alerts_planning_window_sample_output.json")

    # --------------------------------------------------------------
    # Sanity assertions.
    # --------------------------------------------------------------
    for event in planned:
        assert 0.0 <= event.confidence <= 1.0
        assert event.priority in ("high", "medium", "low")
        assert event.is_new or event.is_active  # never neither (that would be EXPIRED)
        assert event.active_from <= event.active_until
        d = event.to_dict()
        for key in ("event_id", "title", "category", "confidence", "priority",
                    "active_from", "active_until", "is_new", "is_active", "triggered_rules"):
            assert key in d, f"missing output field {key!r}"
    assert isinstance(json.loads(output_json), list)

    # Registry itself is untouched by this phase -- same 23 entries as Phase 2.
    registry = get_default_registry()
    assert len(registry) == 23
    print("\n[OK] All validation assertions passed.")


if __name__ == "__main__":
    main()
