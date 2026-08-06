# modules/alerts/event_models.py

"""
Plain data models for the Micro Event Engine. No behavior lives here --
these are the shapes every other module in modules/alerts/ passes
around. Mirrors the "structured data only, no interpretation" discipline
already used throughout this project's astrology context builders
(services/ai_prediction_lab/*_context.py), but this module owns its own
copy rather than importing theirs -- the Alerts Engine is required to be
completely independent from the Premium Generators.

Phase 2 addition: EvaluationContext -- the richer "Planet Data" bundle
the expanded Rule Library needs (current transits, natal house lords,
Mahadasha/Antardasha lords, active yogas) so rules can express Planet
Combination / Natal Support / Mahadasha Support / Antardasha Support /
Existing Yogas signals, not just a single planet's own transit facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PlanetSnapshot:
    """One planet's current transit position, already resolved against
    the natal Lagna -- exactly the kind of fact
    services/ai_prediction_lab/*_context.py's `_transit_summary()`
    helpers already compute for the Premium Generators, recomputed here
    independently (see modules/alerts/planet_data.py) rather than
    imported from that package."""

    planet: str
    sign: Optional[str]
    house: Optional[int]
    nakshatra: Optional[str]
    motion: Optional[str]


@dataclass(frozen=True)
class EvaluationContext:
    """Everything a rule is allowed to read, for one detection run.
    Built once per run (see modules/alerts/evaluation_context.py) and
    passed to every rule -- rules never fetch data themselves, keeping
    "what data exists" centralized and auditable in one place.

    Every field here is read from data the backend already computes
    (calculate_full_kundali()'s own return dict + transit_engine.py +
    services/full_kundali_service.derive_house_lords()) -- nothing here
    is a new astrology calculation.
    """

    lagna_sign: str
    planet_snapshots: Dict[str, PlanetSnapshot]  # current transits, by planet name
    natal_planets_by_name: Dict[str, Dict[str, Any]]  # raw natal planet dicts (for aspected_by)
    house_lords: Dict[str, str]  # e.g. "10_house_lord" -> "Saturn"
    mahadasha_lord: Optional[str]
    antardasha_lord: Optional[str]
    active_yogas: Dict[str, bool]  # yoga config key -> is_active


@dataclass(frozen=True)
class RuleDefinition:
    """One condition inside a micro-event's rule set, as loaded from
    config/micro_events.json. Never hand-constructed in business code --
    see EventRegistry.

    `planet` is always present for output/display consistency in
    `TriggeredRule`, but not every condition type's handler uses it
    operationally (e.g. "yoga_active" reads the yoga key from `value`
    instead) -- see rule_interface.py for exactly which conditions use
    which fields.
    """

    rule_id: str
    planet: str
    condition: str
    value: Any
    weight: float


@dataclass(frozen=True)
class MicroEventDefinition:
    """One micro-event's full definition, as loaded from
    config/micro_events.json. This is the ONLY place an event's
    identity (id/category) and its detection rules are declared --
    business code never hardcodes an event's logic.

    `priority` is intentionally NOT part of this definition (Phase 2) --
    it is now derived from the confidence a specific detection run
    actually produces (see confidence_engine.derive_priority()), using
    the same actual-matched-rules signal, rather than a fixed label
    authored per event regardless of how strongly it fired.

    `is_fallback` (Phase 2): marks an event as the generic "nothing else
    matched" fallback (see MicroEventEngine.detect()) -- Stable Phase is
    the one event in this catalog with this flag set, but the engine's
    fallback mechanism itself is generic and would work for any event
    marked this way, not a hardcoded reference to "stable_phase"."""

    event_id: str
    title: str
    category: str
    min_rules_required: int
    is_fallback: bool = False
    rules: List[RuleDefinition] = field(default_factory=list)


@dataclass(frozen=True)
class TriggeredRule:
    """One rule that actually matched for a detected event -- part of
    the output's `triggered_rules`. Structured data only, no prose: the
    Micro Event Engine never explains itself in natural language (that
    is explicitly a later phase)."""

    rule_id: str
    planet: str
    condition: str
    value: Any
    weight: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "planet": self.planet,
            "condition": self.condition,
            "value": self.value,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class DetectedMicroEvent:
    """One detected micro-event -- the Micro Event Engine's final
    output shape. `title` is always the fixed catalog string, never
    generated text. `priority` is computed for this specific run (Phase
    2) -- see confidence_engine.derive_priority()."""

    event_id: str
    title: str
    confidence: float
    priority: str
    category: str
    triggered_rules: List[TriggeredRule] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "confidence": round(self.confidence, 3),
            "priority": self.priority,
            "category": self.category,
            "triggered_rules": [r.to_dict() for r in self.triggered_rules],
        }
