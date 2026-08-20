# modules/alerts/profile_detection_service.py

"""
Profile-Level Detection Service (Phase 2). Pure orchestration:

    Profile -> existing astrology data -> existing PlanningWindowEngine
        -> this service -> AlertPersistenceRepository

This file contains NO astrology calculation and NO direct database
access -- it reuses full_kundali_api.calculate_full_kundali() (existing,
unmodified) and modules/alerts/planning_window_engine.py::PlanningWindowEngine
(existing, unmodified) for detection, and hands the result to
modules/alerts/persistence_repository.py::AlertPersistenceRepository.synchronize_profile_events()
(the one new Phase 2 repository method) for persistence. The Rule
Engine, Confidence Engine, and Event Registry are never imported here
directly -- only through PlanningWindowEngine, exactly as the
architecture rule requires.

`_load_birth_details()` is this service's own copy, not shared with
the Premium Generators or modules/alerts/planet_data.py -- same
reasoning already documented in every one of those files: each
consumer owns its own thin adapter rather than introducing a new
cross-package dependency (modules/alerts/ must stay completely
independent from modules/love/, modules/career/, etc. and vice versa).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from full_kundali_api import calculate_full_kundali
from modules.models_user import AppUser

from modules.alerts.alert_ai_content_service import describe_triggered_facts
from modules.alerts.event_registry import EventRegistry, get_default_registry
from modules.alerts.exceptions import AlertsEngineError
from modules.alerts.persistence_repository import (
    AlertPersistenceError,
    AlertPersistenceRepository,
    SyncCounts,
)
from modules.alerts.planning_window_engine import PlanningWindowEngine
from modules.alerts.severity_cooldown_registry import (
    SeverityCooldownRegistry,
    get_default_severity_cooldown_registry,
)
from modules.alerts.sunrise_boundary import SunriseResolutionError, resolve_alert_day_sequence


class ProfileDataError(AlertsEngineError):
    """Raised when `profile_id` doesn't resolve to an AppUser, or that
    AppUser is missing a birth field calculate_full_kundali() requires.
    Mirrors ContextBuildError's role for the Premium Generators, but is
    its own type -- the Alerts Engine's exception hierarchy stays
    completely separate from modules/ai_report_engine/exceptions.py."""


class DetectionRunFailedError(AlertsEngineError):
    """Raised when PlanningWindowEngine.plan() itself raises.
    Persistence is NEVER touched when this is raised -- see
    evaluate_profile()'s ordering, which is what makes "existing
    persisted alerts must not incorrectly become EXPIRED on a failed
    run" true by construction, not by an added guard."""


@dataclass(frozen=True)
class ProfileEvaluationResult:
    """Structured, JSON-serializable result of one evaluate_profile()
    call -- useful for a future scheduler to log/aggregate without
    reading ORM objects directly."""

    profile_id: int
    events_evaluated: int      # catalog size actually run through the Rule Engine (normal + fallback)
    events_detected: int       # len(PlanningWindowEngine.plan()'s own return list)
    created: int
    updated: int
    reactivated: int
    expired: int
    duration_seconds: float
    evaluated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "events_evaluated": self.events_evaluated,
            "events_detected": self.events_detected,
            "created": self.created,
            "updated": self.updated,
            "reactivated": self.reactivated,
            "expired": self.expired,
            "duration_seconds": round(self.duration_seconds, 4),
            "evaluated_at": self.evaluated_at.isoformat(),
        }


class ProfileDetectionService:
    def __init__(
        self,
        planning_engine: Optional[PlanningWindowEngine] = None,
        repository: Optional[AlertPersistenceRepository] = None,
        registry: Optional[EventRegistry] = None,
        severity_cooldown_registry: Optional[SeverityCooldownRegistry] = None,
    ):
        # Same constructor-injection convention every engine in this
        # package already uses (MicroEventEngine, PlanningWindowEngine
        # itself) -- sensible default, swappable for tests. `registry`
        # is accepted separately (not read off `planning_engine`, which
        # exposes no public accessor for it) purely so this service's
        # own `events_evaluated` count stays accurate even when a test
        # injects a custom `planning_engine` built with a fixture
        # registry -- see ProfileEvaluationResult.events_evaluated.
        self._planning_engine = planning_engine or PlanningWindowEngine()
        self._repository = repository or AlertPersistenceRepository()
        self._registry = registry or get_default_registry()
        # Phase 4: used ONLY to look up and persist each detected
        # event's severity (a config-driven, per-row fact) -- this
        # service does NOT evaluate delivery eligibility or send
        # anything; see modules/alerts/delivery_eligibility_policy.py
        # for that (deliberately not called here -- out of this
        # phase's scope).
        self._severity_cooldown_registry = severity_cooldown_registry or get_default_severity_cooldown_registry()

    def evaluate_profile(self, profile_id: int) -> ProfileEvaluationResult:
        """
        Runs one full detection + persistence-synchronization pass for
        `profile_id`. Raises ProfileDataError (profile missing/invalid
        birth data), DetectionRunFailedError (the Planning Window
        Engine itself failed -- persistence untouched), or
        AlertPersistenceError (the synchronization transaction failed
        -- see synchronize_profile_events()'s own atomicity guarantee)
        on failure; never returns a partial/misleading result.
        """
        started = time.monotonic()
        evaluated_at = datetime.utcnow()

        birth_details = self._load_birth_details(profile_id)

        # ---- Phase 3: sunrise-to-sunrise alert-day boundary ----
        # Resolved from the SAME lat/lng _load_birth_details() already
        # validated, BEFORE the kundali/planning call. A failure here
        # (SunriseResolutionError) has exactly the same safety property
        # as a planning failure below: nothing has been persisted yet,
        # and self._repository.synchronize_profile_events() is never
        # reached, so no existing alert for this profile can be falsely
        # expired by an untrustworthy day boundary. Never caught and
        # silently defaulted here -- see sunrise_boundary.py's own
        # docstring for why.
        day_anchors = resolve_alert_day_sequence(
            lat=birth_details["lat"],
            lon=birth_details["lon"],
            count=self._planning_engine.window_days,
        )

        kundali = calculate_full_kundali(
            name=birth_details["name"],
            dob=birth_details["dob"],
            tob=birth_details["tob"],
            lat=birth_details["lat"],
            lon=birth_details["lon"],
            user_id=None,  # guest mode -- same convention every Premium Generator and
                            # modules/alerts/*'s own test scripts already use; introduces
                            # no new write to UserDashaTimeline or any other table.
            language="en",
        )

        # ---- THE transaction-safety boundary ----
        # PlanningWindowEngine.plan() (existing logic, additively
        # extended in Phase 3 with an optional day_anchors parameter --
        # see planning_window_engine.py) runs to completion FIRST.
        # Persistence is not touched until this succeeds -- if it
        # raises, we propagate immediately and
        # synchronize_profile_events() is never called, so no existing
        # row for this profile can be incorrectly expired by a failed
        # run.
        try:
            planned_events = self._planning_engine.plan(kundali, day_anchors=day_anchors)
        except Exception as exc:
            raise DetectionRunFailedError(
                f"PlanningWindowEngine.plan() failed for profile_id={profile_id}: {exc}"
            ) from exc

        # AI-Written Personalized Alert Content addition -- the SAME
        # "today" natal/transit/dasha/yoga facts plan() itself already
        # computed internally, exposed via the small additive accessor
        # above (no new astrology calculation). Built once per profile
        # evaluation. Used ONLY to derive cheap, plain-English
        # triggered_facts below -- NEVER to call OpenAI here. See
        # modules/alerts/alert_ai_content_service.py's own module
        # docstring for the architectural gate this enforces: AI
        # generation happens ONLY later, for the FINAL selected
        # alert(s), via ensure_ai_content_for_selected_rows() -- never
        # here, for every raw detected event.
        evaluation_context = self._planning_engine.build_evaluation_context(
            kundali, day_anchors=day_anchors,
        )

        detected_events: List[Dict[str, Any]] = []
        for event in planned_events:
            entry: Dict[str, Any] = {
                "event_id": event.event_id,
                "category": event.category,
                # PlanningWindowEngine.plan() only ever returns NEW or
                # ACTIVE events (event_state.summarize() returns None,
                # excluded, for EXPIRED) -- this mapping is exhaustive.
                "state": "ACTIVE" if event.is_active else "NEW",
                "confidence": event.confidence,
                "priority": event.priority,
                # Phase 4: config-driven, per event_id, never derived
                # from `event.confidence` above -- see
                # severity_cooldown_registry.py's own docstring.
                "severity": self._severity_cooldown_registry.severity_of(event.event_id),
                "active_from": _parse_iso_date(event.active_from),
                "active_until": _parse_iso_date(event.active_until),
            }

            # Cheap, no OpenAI call, no cost -- computed for EVERY
            # detected event regardless of whether it will later be
            # selected. This is what lets generation happen LATER
            # (after selection, in a separate call/request) without
            # needing to recompute detection facts at that point -- see
            # describe_triggered_facts()'s own docstring.
            facts = describe_triggered_facts(event, evaluation_context)
            if facts:
                entry["triggered_facts"] = facts

            detected_events.append(entry)

        counts: SyncCounts = self._repository.synchronize_profile_events(
            profile_id=profile_id,
            detected_events=detected_events,
            evaluated_at=evaluated_at,
        )

        duration = time.monotonic() - started
        return ProfileEvaluationResult(
            profile_id=profile_id,
            events_evaluated=len(self._registry),
            events_detected=len(planned_events),
            created=counts.created,
            updated=counts.updated,
            reactivated=counts.reactivated,
            expired=counts.expired,
            duration_seconds=duration,
            evaluated_at=evaluated_at,
        )

    # ------------------------------------------------------------
    # Thin adapter -- own copy, not shared (see module docstring).
    # ------------------------------------------------------------
    def _load_birth_details(self, profile_id: int) -> Dict[str, Any]:
        """profile_id IS AppUser.id (same architecture convention every
        Premium Generator already uses). Reads the existing AppUser
        row -- does not create or modify it."""
        user = AppUser.query.get(profile_id)
        if user is None:
            raise ProfileDataError(f"No AppUser found for profile_id={profile_id}")

        missing = [
            field for field in ("dob", "tob", "pob", "lat", "lng")
            if getattr(user, field, None) in (None, "")
        ]
        if missing:
            raise ProfileDataError(
                f"AppUser {profile_id} is missing required birth fields: {missing}"
            )

        return {
            "name": user.name or "User",
            "dob": user.dob,
            "tob": user.tob,
            "pob": user.pob,
            "lat": user.lat,
            "lon": user.lng,
        }


def _parse_iso_date(value: str) -> date:
    """PlannedMicroEvent.active_from/active_until are ISO date strings
    (YYYY-MM-DD) -- see modules/alerts/planning_models.py's own
    docstring. AlertMicroEvent's columns are native `Date`, so this
    service (not the repository, which stays a plain-values consumer)
    is responsible for the conversion."""
    return datetime.strptime(value, "%Y-%m-%d").date()
