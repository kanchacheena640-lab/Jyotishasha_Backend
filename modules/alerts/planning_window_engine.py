# modules/alerts/planning_window_engine.py

"""
Planning Window Engine (Phase 3, final Alerts architecture) --
converts the Micro Event Engine from "what's active right now" into
"what's active over the next few days", so the app can help a user plan
ahead rather than only react to today's transit.

    Current Transit -> Next N-Day Simulation -> Detected Events (per day)
        -> Active From / Active Until (Event State layer)
        -> JSON Output

This is a layer ON TOP of the existing pipeline, not a replacement or a
redesign of it:
  - The Rule Engine (rule_interface.py, rule_evaluator.py,
    confidence_engine.py, event_registry.py) is used EXACTLY as Phase
    1/2 left it -- called once per (event, day) pair, unmodified.
  - MicroEventEngine (micro_event_engine.py) itself is also untouched;
    this engine doesn't call it, but reimplements the same one-day
    evaluate-all-events loop day-by-day using the identical, unmodified
    building blocks, because MicroEventEngine's own detect() only knows
    about "one EvaluationContext", not a multi-day window.
  - State classification (NEW/ACTIVE/EXPIRED, active_from/active_until,
    max confidence) is entirely event_state.py's job -- a genuinely
    separate layer, per the task's own instruction.
  - Stable Phase fallback is reused as-is (EventRegistry.fallback_events()),
    evaluated only if the whole window produced nothing.

No OpenAI call, no prompt, no natural-language generation anywhere in
this file.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Dict, List, Optional

import pytz

from services.full_kundali_service import derive_house_lords

from modules.alerts import confidence_engine
from modules.alerts.event_models import EvaluationContext
from modules.alerts.event_registry import EventRegistry, get_default_registry
from modules.alerts.evaluation_context import _active_yogas, _natal_planets_by_name
from modules.alerts.event_state import DayResult, summarize
from modules.alerts.future_planet_data import build_planet_snapshots_for_day
from modules.alerts.planning_models import PlannedMicroEvent
from modules.alerts.rule_evaluator import evaluate_event_rules

_DEFAULT_WINDOW_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "config", "planning_window.json"
)
_FALLBACK_DEFAULT_WINDOW_DAYS = 4  # only used if the config file is ever missing


def load_default_window_days(config_path: Optional[str] = None) -> int:
    """Reads config/planning_window.json's `default_window_days` --
    never hardcoded in business code. Falls back to 4 only if the
    config file itself can't be read at all."""
    path = config_path or _DEFAULT_WINDOW_CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(json.load(f)["default_window_days"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return _FALLBACK_DEFAULT_WINDOW_DAYS


def _ist_midnight_today() -> datetime.datetime:
    ist = pytz.timezone("Asia/Kolkata")
    return datetime.datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)


class PlanningWindowEngine:
    def __init__(
        self,
        registry: Optional[EventRegistry] = None,
        window_days: Optional[int] = None,
    ):
        # Same constructor-injection pattern as MicroEventEngine/every
        # Premium Generator -- sensible default, swappable for tests.
        self._registry = registry or get_default_registry()
        self._window_days = window_days or load_default_window_days()

    @property
    def window_days(self) -> int:
        return self._window_days

    def plan(self, kundali: Dict[str, Any]) -> List[PlannedMicroEvent]:
        """Simulates `self.window_days` days starting today (day_offset
        0) and returns one PlannedMicroEvent per event that is NEW or
        ACTIVE somewhere in that window (EXPIRED events -- never active
        at all within the window -- are excluded, same exit criterion
        Phase 1/2 already used for a single moment). Falls back to
        Stable Phase if nothing else qualifies. `kundali` must be the
        dict full_kundali_api.calculate_full_kundali() returns."""
        contexts_by_day = self._build_daily_contexts(kundali)

        planned = self._plan_from(self._registry.all_events(), contexts_by_day)
        if planned:
            return planned

        return self._plan_from(self._registry.fallback_events(), contexts_by_day)

    def _build_daily_contexts(self, kundali: Dict[str, Any]) -> List[EvaluationContext]:
        """Builds one EvaluationContext per day in the window. Every
        field EXCEPT `planet_snapshots` is a natal/dasha/yoga fact that
        does not meaningfully change across a several-day window (a
        Mahadasha/Antardasha spans months to years; yogas and house
        lords are natal, permanent facts) -- computed once here and
        reused across every day, exactly like every Premium Generator's
        own phase-context builder already treats natal facts as
        computed once per run. Only `planet_snapshots` (today's/each
        day's transits) is recomputed per day, via
        future_planet_data.build_planet_snapshots_for_day()."""
        lagna_sign = kundali.get("lagna_sign")
        mahadasha = kundali.get("current_mahadasha") or {}
        antardasha = kundali.get("current_antardasha") or {}

        natal_planets_by_name = _natal_planets_by_name(kundali)
        house_lords = kundali.get("lords") or derive_house_lords(lagna_sign)
        mahadasha_lord = mahadasha.get("mahadasha")
        antardasha_lord = antardasha.get("planet")
        active_yogas = _active_yogas(kundali)

        today_midnight = _ist_midnight_today()

        contexts = []
        for day_offset in range(self._window_days):
            day_ist = today_midnight + datetime.timedelta(days=day_offset)
            contexts.append(EvaluationContext(
                lagna_sign=lagna_sign,
                planet_snapshots=build_planet_snapshots_for_day(lagna_sign, day_ist),
                natal_planets_by_name=natal_planets_by_name,
                house_lords=house_lords,
                mahadasha_lord=mahadasha_lord,
                antardasha_lord=antardasha_lord,
                active_yogas=active_yogas,
            ))
        return contexts

    def _plan_from(self, events, contexts_by_day: List[EvaluationContext]) -> List[PlannedMicroEvent]:
        today_midnight = _ist_midnight_today()
        thresholds = self._registry.priority_thresholds

        planned: List[PlannedMicroEvent] = []
        for event in events:
            day_results: List[DayResult] = []
            for day_offset, context in enumerate(contexts_by_day):
                date_str = (today_midnight + datetime.timedelta(days=day_offset)).strftime("%Y-%m-%d")

                matched_rules = evaluate_event_rules(event, context)
                confidence = confidence_engine.score(event, matched_rules)  # Rule Engine, unmodified

                if confidence is None:
                    day_results.append(DayResult(
                        day_offset=day_offset, date=date_str,
                        confidence=None, priority=None, triggered_rules=[],
                    ))
                else:
                    day_results.append(DayResult(
                        day_offset=day_offset, date=date_str,
                        confidence=confidence,
                        priority=confidence_engine.derive_priority(confidence, thresholds),
                        triggered_rules=matched_rules,
                    ))

            result = summarize(event.event_id, event.title, event.category, day_results)
            if result is not None:
                planned.append(result)

        planned.sort(key=lambda e: e.confidence, reverse=True)
        return planned

    def plan_as_dicts(self, kundali: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [event.to_dict() for event in self.plan(kundali)]

    def plan_as_json(self, kundali: Dict[str, Any]) -> str:
        return json.dumps(self.plan_as_dicts(kundali), indent=2, ensure_ascii=False)
