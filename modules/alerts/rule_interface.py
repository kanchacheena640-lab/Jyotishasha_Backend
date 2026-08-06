# modules/alerts/rule_interface.py

"""
Rule Interface -- the contract every rule condition satisfies, plus the
one generic implementation that reads a condition purely from
config/micro_events.json data (a `RuleDefinition`), evaluated against an
`EvaluationContext`. This is the "JSON/Config -> Python evaluates ->
Events returned" boundary: adding a new event, or a new rule on an
existing event, using one of the condition types already implemented
here requires ONLY a config change (modules/alerts/config/
micro_events.json) -- no new Python code. Adding a genuinely new
CONDITION TYPE (not just a new event/rule) is the one case that requires
a code change, and it is isolated to this one file.

Phase 2 expands the condition-type library from single-planet transit
facts (house/sign/motion/nakshatra) to the full signal-source set the
Astrological Rule Library v1 spec calls for -- Planet Combination,
Mahadasha Support, Antardasha Support, Existing Yogas, Natal Support
(house activation), and Relevant Aspect (natal). Every handler still
reads ONLY facts already present on EvaluationContext -- no handler
performs a new astrology calculation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict

from modules.alerts.event_models import EvaluationContext, RuleDefinition
from modules.alerts.exceptions import InvalidRuleValueError, UnsupportedConditionError


class RuleCondition(ABC):
    """Contract: given the full EvaluationContext for the current
    detection run, decide whether this one rule's condition matches.
    Business code (RuleEvaluator) never inspects a rule's
    `condition`/`value` fields itself -- it only ever calls
    `matches()`."""

    @abstractmethod
    def matches(self, context: EvaluationContext) -> bool:
        raise NotImplementedError


# ------------------------------------------------------------
# Single-planet transit conditions (Phase 1, unchanged behavior --
# Transit House / Transit Sign / Planet Motion signal sources).
# ------------------------------------------------------------

def _house_in(context: EvaluationContext, rule: RuleDefinition) -> bool:
    snapshot = context.planet_snapshots.get(rule.planet)
    return snapshot is not None and snapshot.house is not None and snapshot.house in rule.value


def _house_not_in(context: EvaluationContext, rule: RuleDefinition) -> bool:
    snapshot = context.planet_snapshots.get(rule.planet)
    return snapshot is not None and snapshot.house is not None and snapshot.house not in rule.value


def _motion_equals(context: EvaluationContext, rule: RuleDefinition) -> bool:
    snapshot = context.planet_snapshots.get(rule.planet)
    return snapshot is not None and snapshot.motion is not None and snapshot.motion == rule.value


def _sign_in(context: EvaluationContext, rule: RuleDefinition) -> bool:
    snapshot = context.planet_snapshots.get(rule.planet)
    return snapshot is not None and snapshot.sign is not None and snapshot.sign in rule.value


def _nakshatra_in(context: EvaluationContext, rule: RuleDefinition) -> bool:
    snapshot = context.planet_snapshots.get(rule.planet)
    return snapshot is not None and snapshot.nakshatra is not None and snapshot.nakshatra in rule.value


# ------------------------------------------------------------
# Phase 2 -- Planet Combination: are two transiting planets currently
# in the same house (a transit conjunction)? `rule.planet` is the
# rule's own anchor planet; `rule.value` names the other one.
# ------------------------------------------------------------

def _conjunction_with(context: EvaluationContext, rule: RuleDefinition) -> bool:
    snapshot = context.planet_snapshots.get(rule.planet)
    other = context.planet_snapshots.get(rule.value)
    return (
        snapshot is not None and other is not None
        and snapshot.house is not None and snapshot.house == other.house
    )


# ------------------------------------------------------------
# Phase 2 -- Mahadasha Support / Antardasha Support: is the current
# dasha lord one of this rule's listed significator planets? Reuses
# calculate_full_kundali()'s own current_mahadasha/current_antardasha --
# the exact same fields every Premium Generator's phase-context builder
# already reads (e.g. current_love_phase_context.py).
# ------------------------------------------------------------

def _mahadasha_lord_in(context: EvaluationContext, rule: RuleDefinition) -> bool:
    return context.mahadasha_lord is not None and context.mahadasha_lord in rule.value


def _antardasha_lord_in(context: EvaluationContext, rule: RuleDefinition) -> bool:
    return context.antardasha_lord is not None and context.antardasha_lord in rule.value


# ------------------------------------------------------------
# Phase 2 -- Existing Yogas: is a specific yoga (already computed by
# full_kundali_api.calculate_full_kundali(), e.g. "gajakesari_yog")
# currently active in the natal chart? `rule.value` is that yoga's
# config key.
# ------------------------------------------------------------

def _yoga_active(context: EvaluationContext, rule: RuleDefinition) -> bool:
    return context.active_yogas.get(rule.value, False)


# ------------------------------------------------------------
# Phase 2 -- Natal Support / House Activation: is the NATAL lord of a
# given house currently transiting one of a favorable set of houses?
# `rule.value` = {"natal_house": <1-12>, "lord_transit_house_in": [...]}.
# Reuses services/full_kundali_service.derive_house_lords()'s output
# (already resolved into context.house_lords) plus the same current
# planet snapshots every other condition type reads -- a classical
# "is this house's own lord currently strong" cross-reference, not a
# new calculation.
# ------------------------------------------------------------

def _natal_lord_house_in(context: EvaluationContext, rule: RuleDefinition) -> bool:
    natal_house = rule.value["natal_house"]
    favorable_houses = rule.value["lord_transit_house_in"]
    lord_name = context.house_lords.get(f"{natal_house}_house_lord")
    if not lord_name:
        return False
    lord_snapshot = context.planet_snapshots.get(lord_name)
    return lord_snapshot is not None and lord_snapshot.house in favorable_houses


# ------------------------------------------------------------
# Phase 2 -- Relevant Aspect: is the NATAL lord of a given house itself
# natally aspected by one of a listed set of planets? Reuses the
# `aspected_by` field calculate_full_kundali() already attaches to every
# natal planet (calculate_drishti_for_planets()) -- the same field
# context_builder.py's `_planet_summary()` already surfaces for the
# Premium Generators, read independently here.
# `rule.value` = {"natal_house": <1-12>, "aspected_by_any": [...]}.
# ------------------------------------------------------------

def _natal_lord_aspected_by(context: EvaluationContext, rule: RuleDefinition) -> bool:
    natal_house = rule.value["natal_house"]
    aspecting_planets = rule.value["aspected_by_any"]
    lord_name = context.house_lords.get(f"{natal_house}_house_lord")
    if not lord_name:
        return False
    natal_lord = context.natal_planets_by_name.get(lord_name)
    if not natal_lord:
        return False
    aspected_by = natal_lord.get("aspected_by") or []
    return any(planet in aspected_by for planet in aspecting_planets)


# The complete, closed set of condition types this phase supports. Every
# one operates ONLY on facts already present on EvaluationContext -- no
# handler computes anything new about the chart. Registering a new event
# that reuses one of these keys is a config-only change; adding a new
# key here is the one code change this module ever needs.
_CONDITION_HANDLERS: Dict[str, Callable[[EvaluationContext, RuleDefinition], bool]] = {
    "house_in": _house_in,
    "house_not_in": _house_not_in,
    "motion_equals": _motion_equals,
    "sign_in": _sign_in,
    "nakshatra_in": _nakshatra_in,
    "conjunction_with": _conjunction_with,
    "mahadasha_lord_in": _mahadasha_lord_in,
    "antardasha_lord_in": _antardasha_lord_in,
    "yoga_active": _yoga_active,
    "natal_lord_house_in": _natal_lord_house_in,
    "natal_lord_aspected_by": _natal_lord_aspected_by,
}


# ------------------------------------------------------------
# Startup validation -- checks a rule's `value` payload is
# STRUCTURALLY shaped the way its `condition` type's handler above
# expects (right container type, right element types, house numbers
# actually in 1-12), before the rule is ever evaluated. Deliberately
# narrower than the handlers themselves need to be at runtime: these
# validators reject malformed shapes, they do not attempt to confirm a
# planet/sign/yoga name is "real" (that remains a runtime no-match, the
# same as it always was -- see the handler functions above, none of
# which are changed by this section).
# ------------------------------------------------------------

def _is_house_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 12


def _validate_house_list(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise InvalidRuleValueError(f"value must be a non-empty list of house numbers (1-12), got {value!r}")
    if not all(_is_house_number(v) for v in value):
        raise InvalidRuleValueError(f"value must contain only house numbers 1-12, got {value!r}")


_VALID_MOTIONS = ("Direct", "Retrograde")


def _validate_motion_value(value: object) -> None:
    if value not in _VALID_MOTIONS:
        raise InvalidRuleValueError(f"value must be one of {_VALID_MOTIONS}, got {value!r}")


def _validate_string_list(value: object) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise InvalidRuleValueError(f"value must be a non-empty list of non-empty strings, got {value!r}")


def _validate_single_string(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise InvalidRuleValueError(f"value must be a non-empty string, got {value!r}")


def _validate_natal_lord_house_in_value(value: object) -> None:
    if not isinstance(value, dict):
        raise InvalidRuleValueError(
            f"value must be an object with 'natal_house' and 'lord_transit_house_in', got {value!r}"
        )
    missing = [k for k in ("natal_house", "lord_transit_house_in") if k not in value]
    if missing:
        raise InvalidRuleValueError(f"value is missing required field(s) {missing}: {value!r}")
    if not _is_house_number(value["natal_house"]):
        raise InvalidRuleValueError(
            f"value['natal_house'] must be a house number 1-12, got {value['natal_house']!r}"
        )
    _validate_house_list(value["lord_transit_house_in"])


def _validate_natal_lord_aspected_by_value(value: object) -> None:
    if not isinstance(value, dict):
        raise InvalidRuleValueError(
            f"value must be an object with 'natal_house' and 'aspected_by_any', got {value!r}"
        )
    missing = [k for k in ("natal_house", "aspected_by_any") if k not in value]
    if missing:
        raise InvalidRuleValueError(f"value is missing required field(s) {missing}: {value!r}")
    if not _is_house_number(value["natal_house"]):
        raise InvalidRuleValueError(
            f"value['natal_house'] must be a house number 1-12, got {value['natal_house']!r}"
        )
    _validate_string_list(value["aspected_by_any"])


# One validator per condition type, same keys as _CONDITION_HANDLERS --
# deliberately the SAME dict-of-condition-types shape, so a condition
# can never be "known to the validator" but "unknown to the evaluator"
# or vice versa (see validate_rule_condition() below, which checks
# membership directly against _CONDITION_HANDLERS itself, not a second,
# potentially-drifting list of names).
_CONDITION_VALIDATORS: Dict[str, Callable[[object], None]] = {
    "house_in": _validate_house_list,
    "house_not_in": _validate_house_list,
    "motion_equals": _validate_motion_value,
    "sign_in": _validate_string_list,
    "nakshatra_in": _validate_string_list,
    "conjunction_with": _validate_single_string,
    "mahadasha_lord_in": _validate_string_list,
    "antardasha_lord_in": _validate_string_list,
    "yoga_active": _validate_single_string,
    "natal_lord_house_in": _validate_natal_lord_house_in_value,
    "natal_lord_aspected_by": _validate_natal_lord_aspected_by_value,
}


def validate_rule_condition(rule: RuleDefinition) -> None:
    """Validates that `rule.condition` is a known type and that
    `rule.value` is structurally shaped the way that condition requires
    -- called once per rule, by EventRegistry, at config LOAD time (see
    event_registry.py's `load_event_registry()`), not at evaluation
    time. This is what turns a malformed rule into a startup failure
    instead of an `UnsupportedConditionError`/`KeyError`/`TypeError`
    raised the first time the Rule Engine happens to evaluate that rule
    at runtime.

    Raises UnsupportedConditionError for an unrecognized `condition`
    string, or InvalidRuleValueError for a recognized condition whose
    `value` doesn't match its expected shape. event_registry.py catches
    both and re-raises as EventConfigError, so config loading still has
    exactly one exception type callers need to handle.

    Does not change ConfigRuleCondition/the handler functions above in
    any way -- this is a pure pre-flight check layered in front of the
    existing, unmodified evaluation path.
    """
    if rule.condition not in _CONDITION_HANDLERS:
        raise UnsupportedConditionError(
            f"Rule {rule.rule_id!r} uses unsupported condition "
            f"{rule.condition!r}. Supported: {sorted(_CONDITION_HANDLERS)}"
        )
    validator = _CONDITION_VALIDATORS[rule.condition]
    try:
        validator(rule.value)
    except InvalidRuleValueError as exc:
        raise InvalidRuleValueError(f"Rule {rule.rule_id!r}: {exc}") from exc


class ConfigRuleCondition(RuleCondition):
    """The one, generic RuleCondition implementation -- wraps a
    `RuleDefinition` loaded from config and dispatches to the matching
    condition handler above. No event-specific or planet-specific logic
    lives here or anywhere else in code; it is entirely data from
    config/micro_events.json."""

    def __init__(self, rule: RuleDefinition):
        self._rule = rule
        handler = _CONDITION_HANDLERS.get(rule.condition)
        if handler is None:
            raise UnsupportedConditionError(
                f"Rule {rule.rule_id!r} uses unsupported condition "
                f"{rule.condition!r}. Supported: {sorted(_CONDITION_HANDLERS)}"
            )
        self._handler = handler

    @property
    def rule(self) -> RuleDefinition:
        return self._rule

    def matches(self, context: EvaluationContext) -> bool:
        return self._handler(context, self._rule)
