# modules/alerts/micro_event_engine.py

"""
Micro Event Engine -- the orchestrator tying together the full pipeline:

    Planet Data -> Rule Engine -> Detected Micro Events
        -> Confidence Score -> Output JSON

This is the ONLY entry point external callers (a future API route, a
future scheduled job, a future language-generation phase) should use.
It performs no astrology calculation, no OpenAI call, and no natural
language generation -- see this package's __init__.py docstring.

Phase 2 changes (architecture unchanged, intelligence improved):
  - detect() now takes the full `kundali` dict (not just `lagna_sign`),
    since the expanded Rule Library needs Mahadasha/Antardasha/yoga/
    natal-lord facts too, not just current transits. See
    evaluation_context.py.
  - priority is computed per event from this run's own confidence
    (confidence_engine.derive_priority()), against the catalog's own
    priority_thresholds -- no longer a fixed per-event label.
  - Stable Phase: if no normal event clears its threshold, the engine
    evaluates the registry's fallback-marked event(s)
    (EventRegistry.fallback_events()) instead of returning an empty
    list. This is a generic mechanism keyed off the `is_fallback` config
    flag, not a hardcoded check for "stable_phase" by event_id.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from modules.alerts import confidence_engine
from modules.alerts.event_models import DetectedMicroEvent, EvaluationContext
from modules.alerts.event_registry import EventRegistry, get_default_registry
from modules.alerts.evaluation_context import build_evaluation_context
from modules.alerts.rule_evaluator import evaluate_event_rules


class MicroEventEngine:
    def __init__(self, registry: Optional[EventRegistry] = None):
        # Constructor-injected, with a sensible default -- mirrors every
        # Premium Generator's own `repository: Optional[...] = None`
        # pattern, so tests can swap the catalog without touching the
        # rest of the pipeline.
        self._registry = registry or get_default_registry()

    def detect(self, kundali: Dict[str, Any]) -> List[DetectedMicroEvent]:
        """Runs the full pipeline for one chart's current moment and
        returns every event that cleared its own confidence threshold,
        sorted by confidence (highest first). Falls back to the
        registry's fallback-marked event(s) -- Stable Phase -- if
        nothing else was detected, so this never returns an empty list.
        `kundali` must be the dict full_kundali_api.calculate_full_kundali()
        returns."""
        context = build_evaluation_context(kundali)

        detected = self._detect_from(self._registry.all_events(), context)
        if detected:
            return detected

        # Nothing matched -- fall back to whatever event(s) config marks
        # is_fallback (Stable Phase). Evaluated through the exact same
        # rule/confidence/priority pipeline as any other event; nothing
        # about its content is hardcoded here.
        fallback = self._detect_from(self._registry.fallback_events(), context)
        return fallback

    def _detect_from(self, events, context: EvaluationContext) -> List[DetectedMicroEvent]:
        detected: List[DetectedMicroEvent] = []
        thresholds = self._registry.priority_thresholds

        for event in events:
            matched_rules = evaluate_event_rules(event, context)
            confidence = confidence_engine.score(event, matched_rules)
            if confidence is None:
                continue  # did not clear min_rules_required -- not detected

            detected.append(DetectedMicroEvent(
                event_id=event.event_id,
                title=event.title,
                confidence=confidence,
                priority=confidence_engine.derive_priority(confidence, thresholds),
                category=event.category,
                triggered_rules=matched_rules,
            ))

        detected.sort(key=lambda e: e.confidence, reverse=True)
        return detected

    def detect_as_dicts(self, kundali: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Same as detect(), pre-shaped for JSON output (`event_id`,
        `title`, `confidence`, `priority`, `category`,
        `triggered_rules` -- no natural language anywhere)."""
        return [event.to_dict() for event in self.detect(kundali)]

    def detect_as_json(self, kundali: Dict[str, Any]) -> str:
        """Convenience wrapper for callers (e.g. a local validation
        script, a future route) that just want the final JSON string."""
        return json.dumps(self.detect_as_dicts(kundali), indent=2, ensure_ascii=False)
