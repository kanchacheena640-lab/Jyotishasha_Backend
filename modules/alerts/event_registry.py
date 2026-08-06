# modules/alerts/event_registry.py

"""
Event Registry -- the single source of truth for which micro-events
exist and what rules detect each one. Loads and validates
config/micro_events.json exactly once per process (mirroring the
process-wide default-registry pattern already used by
modules/ai_report_engine/generator_registry.py for the Premium
Generators, reimplemented independently here rather than imported --
see this package's own __init__.py docstring on why).

Adding a new micro-event, or a new rule on an existing one, requires
ONLY editing config/micro_events.json -- this file never needs a code
change for that. It only changes if the CATALOG's own JSON *shape*
changes (e.g. a new top-level field every event must carry).

Phase 2: events no longer declare a fixed `priority` (see
confidence_engine.derive_priority() -- priority is now computed per
detection run). The registry instead exposes the catalog's
`priority_thresholds` section, and events may declare `is_fallback` --
see event_models.MicroEventDefinition and
micro_event_engine.MicroEventEngine.detect() for how the "Stable Phase"
fallback behavior uses that flag generically.

Hardening pass: every rule's `condition` type and `value` payload shape
is now validated here, at load time, via
rule_interface.validate_rule_condition() -- a malformed rule (an unknown
condition type, or a value that doesn't match what a known condition
type expects) now fails registry loading with EventConfigError instead
of surfacing as an unhandled UnsupportedConditionError/KeyError/TypeError
the first time the Rule Engine happens to evaluate that rule at runtime.
The Rule Engine's own evaluation path (rule_interface.ConfigRuleCondition,
rule_evaluator.py) is unchanged by this -- this is a pre-flight check
layered in front of it, not a redesign of it.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from modules.alerts.event_models import MicroEventDefinition, RuleDefinition
from modules.alerts.exceptions import AlertsEngineError, EventConfigError
from modules.alerts.rule_interface import validate_rule_condition

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "config", "micro_events.json"
)

_REQUIRED_EVENT_FIELDS = ("event_id", "title", "category", "rules")
_REQUIRED_RULE_FIELDS = ("rule_id", "planet", "condition", "value", "weight")
_DEFAULT_PRIORITY_THRESHOLDS = {"high": 0.6, "medium": 0.3}


class EventRegistry:
    """Holds every `MicroEventDefinition` parsed from config, plus the
    catalog's shared `priority_thresholds`. Read-only once constructed
    -- nothing in this package mutates a loaded registry."""

    def __init__(
        self,
        events: List[MicroEventDefinition],
        priority_thresholds: Dict[str, float],
    ):
        self._events_by_id: Dict[str, MicroEventDefinition] = {
            e.event_id: e for e in events
        }
        self._priority_thresholds = priority_thresholds

    def all_events(self) -> List[MicroEventDefinition]:
        """Every event EXCEPT fallback-marked ones -- the normal
        detection pass. See fallback_events()."""
        return [e for e in self._events_by_id.values() if not e.is_fallback]

    def fallback_events(self) -> List[MicroEventDefinition]:
        """Events marked `is_fallback: true` in config (Stable Phase,
        in this catalog) -- only ever evaluated when all_events()
        produces nothing. Generic mechanism: works for any number of
        events carrying this flag, not a hardcoded reference to
        "stable_phase" by name."""
        return [e for e in self._events_by_id.values() if e.is_fallback]

    def get(self, event_id: str) -> Optional[MicroEventDefinition]:
        return self._events_by_id.get(event_id)

    def event_ids(self) -> List[str]:
        return sorted(self._events_by_id)

    @property
    def priority_thresholds(self) -> Dict[str, float]:
        return dict(self._priority_thresholds)

    def __len__(self) -> int:
        return len(self._events_by_id)


def load_event_registry(config_path: Optional[str] = None) -> EventRegistry:
    """Loads and validates config/micro_events.json (or `config_path`,
    for tests) into an EventRegistry. Raises EventConfigError on any
    structural problem -- a malformed catalog must fail loudly at load
    time, not silently produce wrong events later."""
    path = config_path or _DEFAULT_CONFIG_PATH

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as exc:
        raise EventConfigError(f"Micro-event config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EventConfigError(f"Micro-event config is not valid JSON: {path}") from exc

    events_raw = raw.get("events")
    if not isinstance(events_raw, list) or not events_raw:
        raise EventConfigError(f"Micro-event config must contain a non-empty 'events' list: {path}")

    priority_thresholds = raw.get("priority_thresholds") or dict(_DEFAULT_PRIORITY_THRESHOLDS)
    for key in ("high", "medium"):
        if key not in priority_thresholds:
            raise EventConfigError(f"priority_thresholds missing required key {key!r}: {path}")
    if not (0.0 <= priority_thresholds["medium"] <= priority_thresholds["high"] <= 1.0):
        raise EventConfigError(
            f"priority_thresholds must satisfy 0 <= medium <= high <= 1, "
            f"got {priority_thresholds}"
        )

    events: List[MicroEventDefinition] = []
    seen_event_ids = set()
    fallback_count = 0

    for entry in events_raw:
        missing = [f for f in _REQUIRED_EVENT_FIELDS if f not in entry]
        if missing:
            raise EventConfigError(f"Event entry missing required fields {missing}: {entry}")

        event_id = entry["event_id"]
        if event_id in seen_event_ids:
            raise EventConfigError(f"Duplicate event_id in config: {event_id!r}")
        seen_event_ids.add(event_id)

        rules_raw = entry["rules"]
        if not isinstance(rules_raw, list) or not rules_raw:
            raise EventConfigError(f"Event {event_id!r} must declare a non-empty 'rules' list")

        rules: List[RuleDefinition] = []
        seen_rule_ids = set()
        for rule_entry in rules_raw:
            missing_rule = [f for f in _REQUIRED_RULE_FIELDS if f not in rule_entry]
            if missing_rule:
                raise EventConfigError(
                    f"Rule in event {event_id!r} missing required fields {missing_rule}: {rule_entry}"
                )
            rule_id = rule_entry["rule_id"]
            if rule_id in seen_rule_ids:
                raise EventConfigError(f"Duplicate rule_id {rule_id!r} within event {event_id!r}")
            seen_rule_ids.add(rule_id)

            weight = rule_entry["weight"]
            if not isinstance(weight, (int, float)) or not (0.0 <= weight <= 1.0):
                raise EventConfigError(
                    f"Rule {rule_id!r} in event {event_id!r} has invalid weight "
                    f"{weight!r}; must be a number in [0, 1]"
                )

            new_rule = RuleDefinition(
                rule_id=rule_id,
                planet=rule_entry["planet"],
                condition=rule_entry["condition"],
                value=rule_entry["value"],
                weight=float(weight),
            )
            try:
                validate_rule_condition(new_rule)
            except AlertsEngineError as exc:
                raise EventConfigError(
                    f"Event {event_id!r}, rule {rule_id!r}: {exc}"
                ) from exc
            rules.append(new_rule)

        min_rules_required = entry.get("min_rules_required", 1)
        if not isinstance(min_rules_required, int) or min_rules_required < 1:
            raise EventConfigError(
                f"Event {event_id!r} has invalid min_rules_required {min_rules_required!r}; "
                f"must be an integer >= 1"
            )
        if min_rules_required > len(rules):
            raise EventConfigError(
                f"Event {event_id!r} requires min_rules_required={min_rules_required} "
                f"but only declares {len(rules)} rule(s)"
            )

        is_fallback = bool(entry.get("is_fallback", False))
        fallback_count += 1 if is_fallback else 0

        events.append(MicroEventDefinition(
            event_id=event_id,
            title=entry["title"],
            category=entry["category"],
            min_rules_required=min_rules_required,
            is_fallback=is_fallback,
            rules=rules,
        ))

    if fallback_count == 0:
        raise EventConfigError(
            "Micro-event config must declare at least one event with "
            "is_fallback=true (e.g. Stable Phase) so the engine always "
            "has something to return instead of an empty result."
        )

    return EventRegistry(events, priority_thresholds)


# Process-wide default registry, built lazily -- mirrors
# generator_registry.py's get_default_registry() pattern (reimplemented
# independently, not imported; see this package's __init__.py).
_default_registry: Optional[EventRegistry] = None


def get_default_registry() -> EventRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = load_event_registry()
    return _default_registry
