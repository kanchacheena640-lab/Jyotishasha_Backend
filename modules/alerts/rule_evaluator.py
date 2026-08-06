# modules/alerts/rule_evaluator.py

"""
Rule Evaluator -- for one micro-event definition, checks every one of
its rules against the current EvaluationContext and reports which ones
matched. Knows nothing about confidence scoring, priority, or event
catalogs as a whole (see confidence_engine.py / event_registry.py) --
its only job is "does this one rule currently hold true".
"""

from __future__ import annotations

from typing import List

from modules.alerts.event_models import EvaluationContext, MicroEventDefinition, TriggeredRule
from modules.alerts.rule_interface import ConfigRuleCondition


def evaluate_event_rules(
    event: MicroEventDefinition,
    context: EvaluationContext,
) -> List[TriggeredRule]:
    """Returns the subset of `event`'s rules that matched, given the
    current `context`. A rule referencing a planet with no snapshot
    available, or a natal house lord the chart doesn't resolve, simply
    never matches -- it is not treated as an error, since missing data
    is a legitimate "no signal here" state, not a malformed rule."""
    matched: List[TriggeredRule] = []

    for rule in event.rules:
        condition = ConfigRuleCondition(rule)
        if condition.matches(context):
            matched.append(TriggeredRule(
                rule_id=rule.rule_id,
                planet=rule.planet,
                condition=rule.condition,
                value=rule.value,
                weight=rule.weight,
            ))

    return matched
