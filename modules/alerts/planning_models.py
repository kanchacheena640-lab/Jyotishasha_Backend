# modules/alerts/planning_models.py

"""
Plain data models for the Planning Window layer (Phase 3). Kept
entirely separate from event_models.py's Phase 1/2 shapes
(DetectedMicroEvent etc.) -- that file is not modified by this phase.
`PlannedMicroEvent` is a NEW, additional output shape produced by
planning_window_engine.py; it does not replace DetectedMicroEvent,
which MicroEventEngine (Phase 1/2, unmodified) still returns for a
single-moment "right now" detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from modules.alerts.event_models import TriggeredRule


class EventState(str, Enum):
    """The three states the separate Event State layer
    (event_state.py) classifies each event into, across one Planning
    Window run. Only NEW and ACTIVE events are ever returned in the
    final output -- EXPIRED means "not active today and never becomes
    active within this window", the same "does not clear the bar" exit
    already used for non-detected events in Phase 1/2, just evaluated
    across a window of days instead of one moment."""

    NEW = "NEW"        # not active today; becomes active later in the window
    ACTIVE = "ACTIVE"  # active today (regardless of what happens later)
    EXPIRED = "EXPIRED"  # not active today, and never active within the window


@dataclass(frozen=True)
class PlannedMicroEvent:
    """One event's result for a full Planning Window run. `title` is
    always the fixed catalog string, never generated text -- same
    discipline as DetectedMicroEvent. `active_from`/`active_until` are
    ISO date strings (YYYY-MM-DD); `confidence` is the MAXIMUM
    confidence observed across the days this event was active."""

    event_id: str
    title: str
    category: str
    confidence: float
    priority: str
    active_from: str
    active_until: str
    is_new: bool
    is_active: bool
    triggered_rules: List[TriggeredRule] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "priority": self.priority,
            "active_from": self.active_from,
            "active_until": self.active_until,
            "is_new": self.is_new,
            "is_active": self.is_active,
            "triggered_rules": [r.to_dict() for r in self.triggered_rules],
        }
