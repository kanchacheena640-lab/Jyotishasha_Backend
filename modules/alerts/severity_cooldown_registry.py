# modules/alerts/severity_cooldown_registry.py

"""
Severity + Cooldown Policy Registry (Phase 4).

Deliberately a SEPARATE, additive config/loader -- kept out of
config/micro_events.json, event_registry.py, and event_models.py
entirely, mirroring the exact precedent config/planning_window.json
already set for Phase 3 (see planning_window_engine.py's own
docstring: "Kept as its own file, separate from config/micro_events.json
... so this phase never touches that file"). The Rule Engine's own
catalog and its loader/validator (event_registry.py, event_models.py)
and the Rule Engine's condition logic (rule_interface.py,
rule_evaluator.py, confidence_engine.py) are NOT modified by this
phase.

Severity (LOW/MEDIUM/HIGH/CRITICAL) and cooldown (hours) are PER-EVENT,
config-driven facts -- never derived from confidence, priority, or any
other runtime signal (see this package's Phase 4 architecture
decision: confidence/priority/severity/cooldown stay four genuinely
independent concepts). This loader mirrors event_registry.py's own
validation discipline exactly: fail loudly, at load time, on any
missing/invalid/inconsistent configuration -- never silently guess a
default.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from modules.alerts.event_registry import EventRegistry, get_default_registry
from modules.alerts.exceptions import AlertsEngineError

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "config", "severity_cooldown_policy.json"
)

# The complete, closed severity vocabulary for this phase. CRITICAL is
# supported here even though the current catalog never assigns it (see
# config/severity_cooldown_policy.json's own "_severity_reasoning") --
# a future event MAY use it without any code change.
SEVERITY_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class SeverityCooldownConfigError(AlertsEngineError):
    """Raised when config/severity_cooldown_policy.json is missing,
    malformed, fails field-level validation (unknown severity,
    non-positive cooldown), or drifts out of sync with the Rule
    Engine's own event catalog (a catalog event with no policy entry,
    or a policy entry referencing an event_id that doesn't exist) --
    fails loudly at load time, never silently guesses."""


class EventPolicy:
    """One event's severity + cooldown, as loaded from config. Never
    hand-constructed in business code -- see SeverityCooldownRegistry."""

    __slots__ = ("event_id", "severity", "cooldown_hours")

    def __init__(self, event_id: str, severity: str, cooldown_hours: float):
        self.event_id = event_id
        self.severity = severity
        self.cooldown_hours = cooldown_hours

    def __repr__(self) -> str:
        return f"<EventPolicy event_id={self.event_id!r} severity={self.severity} cooldown_hours={self.cooldown_hours}>"


class SeverityCooldownRegistry:
    """Holds every EventPolicy parsed from config. Read-only once
    constructed -- nothing in this package mutates a loaded registry."""

    def __init__(self, policies: Dict[str, EventPolicy]):
        self._policies = policies

    def get(self, event_id: str) -> EventPolicy:
        policy = self._policies.get(event_id)
        if policy is None:
            raise SeverityCooldownConfigError(
                f"No severity/cooldown policy configured for event_id={event_id!r}"
            )
        return policy

    def severity_of(self, event_id: str) -> str:
        return self.get(event_id).severity

    def cooldown_hours_of(self, event_id: str) -> float:
        return self.get(event_id).cooldown_hours

    def __len__(self) -> int:
        return len(self._policies)


def load_severity_cooldown_policy(
    config_path: Optional[str] = None,
    event_registry: Optional[EventRegistry] = None,
) -> SeverityCooldownRegistry:
    """
    Loads and validates config/severity_cooldown_policy.json (or
    `config_path`, for tests) against the REAL Rule Engine catalog
    (`event_registry`, defaulting to event_registry.get_default_registry()
    -- injectable so tests can validate against a fixture catalog
    instead). Every event_id the Rule Engine can actually produce MUST
    have a policy entry, and every policy entry MUST correspond to a
    real catalog event_id -- no missing coverage, no orphaned config.
    Raises SeverityCooldownConfigError on any problem.
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    registry = event_registry or get_default_registry()

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as exc:
        raise SeverityCooldownConfigError(f"Severity/cooldown policy config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SeverityCooldownConfigError(f"Severity/cooldown policy config is not valid JSON: {path}") from exc

    events_raw = raw.get("events")
    if not isinstance(events_raw, dict) or not events_raw:
        raise SeverityCooldownConfigError(f"Config must contain a non-empty 'events' object: {path}")

    policies: Dict[str, EventPolicy] = {}
    for event_id, entry in events_raw.items():
        if not isinstance(entry, dict):
            raise SeverityCooldownConfigError(
                f"Policy entry for {event_id!r} must be an object, got {entry!r}"
            )

        severity = entry.get("severity")
        if severity not in SEVERITY_LEVELS:
            raise SeverityCooldownConfigError(
                f"Event {event_id!r} has invalid/missing severity {severity!r}; "
                f"must be one of {SEVERITY_LEVELS}"
            )

        cooldown_hours = entry.get("cooldown_hours")
        valid_cooldown = (
            isinstance(cooldown_hours, (int, float))
            and not isinstance(cooldown_hours, bool)
            and cooldown_hours > 0
        )
        if not valid_cooldown:
            raise SeverityCooldownConfigError(
                f"Event {event_id!r} has invalid/missing cooldown_hours {cooldown_hours!r}; "
                f"must be a positive number"
            )

        policies[event_id] = EventPolicy(event_id, severity, float(cooldown_hours))

    # Cross-validate against the REAL Rule Engine catalog -- every
    # event the engine can actually detect MUST have a policy entry,
    # and this config must not silently carry a stale/typo'd entry.
    catalog_ids = set(registry.event_ids())
    policy_ids = set(policies.keys())

    missing_policy = catalog_ids - policy_ids
    if missing_policy:
        raise SeverityCooldownConfigError(
            f"Catalog event(s) with no severity/cooldown policy configured: {sorted(missing_policy)}"
        )

    orphaned_policy = policy_ids - catalog_ids
    if orphaned_policy:
        raise SeverityCooldownConfigError(
            f"Severity/cooldown policy references unknown event_id(s) not in the catalog: "
            f"{sorted(orphaned_policy)}"
        )

    return SeverityCooldownRegistry(policies)


# Process-wide default registry, built lazily -- mirrors
# event_registry.py::get_default_registry()'s identical pattern.
_default_severity_cooldown_registry: Optional[SeverityCooldownRegistry] = None


def get_default_severity_cooldown_registry() -> SeverityCooldownRegistry:
    global _default_severity_cooldown_registry
    if _default_severity_cooldown_registry is None:
        _default_severity_cooldown_registry = load_severity_cooldown_policy()
    return _default_severity_cooldown_registry
