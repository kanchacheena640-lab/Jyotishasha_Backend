"""
test_alert_ai_content_service.py
----------------------------------
Focused tests for modules/alerts/alert_ai_content_service.py's two
halves (see that module's own docstring for the architectural gate
this split enforces):

  1. describe_triggered_facts() -- PURE, no OpenAI, safe to call for
     every detected event.
  2. build_alert_ai_content_from_facts() -- the ONLY function that
     calls OpenAI, operating purely on persisted strings (title/
     category/facts), no live detection objects needed.

ensure_ai_content_for_selected_rows() (the post-selection orchestrator)
is proven end-to-end, against the real selection pipeline, in
test_alert_ai_generation_selection_gate.py -- not duplicated here.

NO REAL OPENAI CALL IS EVER MADE -- services.ai_prediction_lab.
openai_client.generate() is monkeypatched for every scenario. No
database is touched at all (this module is pure functions over plain
dataclasses/strings).
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.alerts.event_models import EvaluationContext, PlanetSnapshot, TriggeredRule  # noqa: E402
from modules.alerts.planning_models import PlannedMicroEvent  # noqa: E402

import modules.alerts.alert_ai_content_service as ai_content_module  # noqa: E402
from modules.alerts.alert_ai_content_service import (  # noqa: E402
    AlertAIContent,
    _describe_rule,
    build_alert_ai_content_from_facts,
    describe_triggered_facts,
)

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


def make_context(**overrides):
    defaults = dict(
        lagna_sign="Aries",
        planet_snapshots={
            "Jupiter": PlanetSnapshot(planet="Jupiter", sign="Sagittarius", house=10, nakshatra="Purva Ashadha", motion="Direct"),
            "Venus": PlanetSnapshot(planet="Venus", sign="Libra", house=9, nakshatra="Swati", motion="Direct"),
        },
        natal_planets_by_name={},
        house_lords={"10_house_lord": "Jupiter"},
        mahadasha_lord="Jupiter",
        antardasha_lord="Venus",
        active_yogas={"rajya_sambandh_rajyog": True},
    )
    defaults.update(overrides)
    return EvaluationContext(**defaults)


def make_event(triggered_rules, event_id="opportunity_window", category="timing", title="Opportunity Window"):
    return PlannedMicroEvent(
        event_id=event_id, title=title, category=category,
        confidence=0.7, priority="high",
        active_from="2026-08-20", active_until="2026-08-22",
        is_new=True, is_active=True, triggered_rules=triggered_rules,
    )


def main():
    # ==========================================================
    print("=== _describe_rule: translates each condition type using real context facts ===")
    # ==========================================================
    context = make_context()

    house_rule = TriggeredRule(rule_id="jupiter_house", planet="Jupiter", condition="house_in", value=[1, 4, 5, 7, 9, 10], weight=0.2)
    check("house_in: uses the ACTUAL current house from context", _describe_rule(house_rule, context) == "Jupiter is currently transiting house 10")

    maha_rule = TriggeredRule(rule_id="maha", planet="Jupiter", condition="mahadasha_lord_in", value=["Jupiter", "Venus"], weight=0.15)
    check("mahadasha_lord_in: uses context.mahadasha_lord", _describe_rule(maha_rule, context) == "the current Mahadasha lord is Jupiter")

    unknown_rule = TriggeredRule(rule_id="x", planet="Mars", condition="totally_unknown_condition", value=None, weight=0.1)
    check("unknown condition type -> None, never raises", _describe_rule(unknown_rule, context) is None)

    # ==========================================================
    print("\n=== describe_triggered_facts: PURE, no OpenAI call at all ===")
    # ==========================================================
    calls = []
    ai_content_module.openai_client.generate = lambda prompt: calls.append(prompt) or "unused"

    event = make_event(triggered_rules=[house_rule, maha_rule])
    facts = describe_triggered_facts(event, context)
    check("facts list has 2 entries", len(facts) == 2)
    check("facts contain the house fact", "Jupiter is currently transiting house 10" in facts)
    check("facts contain the mahadasha fact", "the current Mahadasha lord is Jupiter" in facts)
    check("describe_triggered_facts NEVER calls OpenAI -- purely descriptive", len(calls) == 0)

    empty_event = make_event(triggered_rules=[])
    check("no triggered_rules -> empty facts list, not an error", describe_triggered_facts(empty_event, context) == [])
    check("still no OpenAI call", len(calls) == 0)

    # ==========================================================
    print("\n=== build_alert_ai_content_from_facts: empty facts -> None, OpenAI never called ===")
    # ==========================================================
    result_empty = build_alert_ai_content_from_facts(title="Opportunity Window", category="timing", facts=[])
    check("empty facts -> None", result_empty is None)
    check("OpenAI never called for empty facts", len(calls) == 0)

    # ==========================================================
    print("\n=== build_alert_ai_content_from_facts: well-formed OpenAI response -> AlertAIContent ===")
    # ==========================================================
    def fake_generate_good(prompt):
        calls.append(prompt)
        return (
            "INSIGHT: A supportive window is opening for career recognition or a financial opportunity.\n"
            "ACTION: Take the step you've been hesitant about -- send that proposal or application today."
        )

    ai_content_module.openai_client.generate = fake_generate_good
    calls.clear()
    result = build_alert_ai_content_from_facts(title="Opportunity Window", category="timing", facts=facts)
    check("valid response -> AlertAIContent returned", isinstance(result, AlertAIContent))
    check("insight parsed correctly", result is not None and result.insight.startswith("A supportive window"))
    check("action parsed correctly", result is not None and result.action.startswith("Take the step"))
    check("prompt sent to OpenAI includes the real fact string, not a live object", len(calls) == 1 and "Jupiter is currently transiting house 10" in calls[0])
    check("prompt includes the title/category framing", "Event: Opportunity Window" in calls[0])

    # ==========================================================
    print("\n=== build_alert_ai_content_from_facts: malformed OpenAI response -> None ===")
    # ==========================================================
    ai_content_module.openai_client.generate = lambda prompt: "This response has no labeled INSIGHT or ACTION lines at all."
    result_malformed = build_alert_ai_content_from_facts(title="Opportunity Window", category="timing", facts=facts)
    check("malformed response -> None", result_malformed is None)

    ai_content_module.openai_client.generate = lambda prompt: "INSIGHT: only insight, no action line"
    result_partial = build_alert_ai_content_from_facts(title="Opportunity Window", category="timing", facts=facts)
    check("only INSIGHT present, ACTION missing -> None (not a half-valid result)", result_partial is None)

    # ==========================================================
    print("\n=== build_alert_ai_content_from_facts: OpenAI failure/timeout -> None, never raises ===")
    # ==========================================================
    def fake_generate_boom(prompt):
        raise RuntimeError("simulated OpenAI timeout")

    ai_content_module.openai_client.generate = fake_generate_boom
    threw = False
    try:
        result_failure = build_alert_ai_content_from_facts(title="Opportunity Window", category="timing", facts=facts)
    except Exception:
        threw = True
        result_failure = "EXCEPTION"
    check("OpenAI exception never propagates to the caller", threw is False)
    check("OpenAI exception -> None result", result_failure is None)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
