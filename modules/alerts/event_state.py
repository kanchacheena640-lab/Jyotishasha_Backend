# modules/alerts/event_state.py

"""
Event State layer (Phase 3) -- classifies one event's day-by-day
detection timeline (produced by planning_window_engine.py, which itself
only reuses the existing, unmodified Rule Engine once per day) into
NEW / ACTIVE / EXPIRED, and computes active_from / active_until /
maximum confidence / which day's triggered_rules to report.

Deliberately a separate, self-contained layer: everything in this file
is a pure function over a list of `DayResult`s -- it knows nothing about
EvaluationContext, the Rule Engine, or how a day's detection was
produced, and the Rule Engine (rule_interface.py / rule_evaluator.py /
confidence_engine.py / event_registry.py) is not modified by this phase
at all. This is what "without modifying the existing Rule Engine" /
"implemented as a separate layer" means in practice: the Rule Engine
still only ever answers "is this event detected right now, for this one
EvaluationContext" (exactly its Phase 1/2 job) -- state, windows, and
new/active/expired classification are entirely this file's concern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from modules.alerts.event_models import TriggeredRule
from modules.alerts.planning_models import EventState, PlannedMicroEvent


@dataclass(frozen=True)
class DayResult:
    """One day's Rule Engine outcome for one event, as produced by
    planning_window_engine.py. `confidence`/`priority`/`triggered_rules`
    are None/empty when the event did not clear its own
    `min_rules_required` threshold that day (the Rule Engine's own,
    unmodified detection criterion -- see confidence_engine.score())."""

    day_offset: int  # 0 = today, 1 = tomorrow, ...
    date: str  # ISO date (YYYY-MM-DD)
    confidence: Optional[float]
    priority: Optional[str]
    triggered_rules: List[TriggeredRule]

    @property
    def is_active(self) -> bool:
        return self.confidence is not None


def classify(day_results: List[DayResult]) -> EventState:
    """`day_results` must be sorted by `day_offset` ascending and
    include `day_offset == 0` (today)."""
    today = next((d for d in day_results if d.day_offset == 0), None)
    if today is None:
        raise ValueError("day_results must include day_offset == 0 (today)")

    if today.is_active:
        return EventState.ACTIVE

    if any(d.is_active for d in day_results if d.day_offset > 0):
        return EventState.NEW

    return EventState.EXPIRED


def summarize(
    event_id: str,
    title: str,
    category: str,
    day_results: List[DayResult],
) -> Optional[PlannedMicroEvent]:
    """Turns one event's full day-by-day timeline into a single
    PlannedMicroEvent, or None if the event is EXPIRED (not active
    today, and never becomes active within the window) -- EXPIRED
    events are simply excluded from the Planning Window's output, the
    same "does not clear the bar" exit Phase 1/2 already uses for a
    single moment, just evaluated across a window of days."""
    state = classify(day_results)
    if state is EventState.EXPIRED:
        return None

    active_days = [d for d in day_results if d.is_active]
    active_days.sort(key=lambda d: d.day_offset)

    # active_from: the first active day. active_until: the last day of
    # the CONTIGUOUS run starting from active_from (a brief gap and a
    # later reappearance within the same 4-day window is rare for real
    # transits; treating the first unbroken streak as "the" occurrence
    # keeps active_from/active_until an intuitive, continuous range for
    # v1 rather than a scattered set of individual days).
    first = active_days[0]
    streak_end = first
    for day in active_days[1:]:
        if day.day_offset == streak_end.day_offset + 1:
            streak_end = day
        else:
            break

    # Maximum confidence, and that day's triggered_rules, across EVERY
    # active day in the window (not just the contiguous streak) -- "the
    # strongest single moment for this event, wherever in the window it
    # falls".
    peak = max(active_days, key=lambda d: d.confidence)

    return PlannedMicroEvent(
        event_id=event_id,
        title=title,
        category=category,
        confidence=peak.confidence,
        priority=peak.priority,
        active_from=first.date,
        active_until=streak_end.date,
        is_new=(state is EventState.NEW),
        is_active=(state is EventState.ACTIVE),
        triggered_rules=peak.triggered_rules,
    )
