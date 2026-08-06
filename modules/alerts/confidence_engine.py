# modules/alerts/confidence_engine.py

"""
Confidence Scoring -- turns "which rules matched" into a single
confidence number for one micro-event, and (Phase 2) turns that same
confidence into a High/Medium/Low priority. Deliberately the simplest
possible policy for this phase: confidence is the sum of the matched
rules' own `weight` values (each declared in config, never computed),
capped at 1.0. An event is only considered detected at all once at
least `min_rules_required` of its rules matched (also config-driven,
per event).

Phase 2 -- priority is no longer a fixed label authored per event
(Phase 1); it is derived from the confidence THIS detection run actually
produced, against threshold values read from config
(config/micro_events.json's own "priority_thresholds" section) -- never
hardcoded in this file. This is what makes priority reflect "actual
matched rules": an event needs enough confirming signals to clear the
"high" threshold, regardless of which event it is or how many rules its
catalog entry happens to declare.

No event-specific logic lives here -- both functions work identically
for every event in the catalog.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from modules.alerts.event_models import MicroEventDefinition, TriggeredRule

_MAX_CONFIDENCE = 1.0

# Fallback only for a config that omits "priority_thresholds" entirely
# (e.g. a hand-written test fixture) -- config/micro_events.json's own
# section is what actually governs production behavior.
_DEFAULT_THRESHOLDS = {"high": 0.6, "medium": 0.3}


def score(
    event: MicroEventDefinition,
    matched_rules: List[TriggeredRule],
) -> Optional[float]:
    """Returns the event's confidence in [0.0, 1.0] if it clears its own
    `min_rules_required` threshold, else None (meaning: not detected,
    should not appear in output)."""
    if len(matched_rules) < event.min_rules_required:
        return None

    raw = sum(rule.weight for rule in matched_rules)
    return min(raw, _MAX_CONFIDENCE)


def derive_priority(confidence: float, thresholds: Optional[Dict[str, float]] = None) -> str:
    """Maps a confidence value to "high" / "medium" / "low" using
    config-supplied thresholds (falls back to _DEFAULT_THRESHOLDS only
    when the catalog doesn't declare its own -- production config
    always does). `confidence >= thresholds["high"]` -> high;
    `>= thresholds["medium"]` -> medium; otherwise low."""
    limits = thresholds or _DEFAULT_THRESHOLDS
    if confidence >= limits["high"]:
        return "high"
    if confidence >= limits["medium"]:
        return "medium"
    return "low"
