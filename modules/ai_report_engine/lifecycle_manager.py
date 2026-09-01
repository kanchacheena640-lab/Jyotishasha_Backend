# modules/ai_report_engine/lifecycle_manager.py

"""
AI Report Lifecycle Manager.

This is the ONLY entry point Premium AI Reports are meant to go
through, for every segment (Love, Career, Finance, Health, Family,
Alerts) and every report type (DNA, CURRENT_PHASE, DAILY_INSIGHT). A
future API layer must call `ReportLifecycleManager.get_report(...)` and
never talk to a generator or the cache table directly.

This module is completely segment-agnostic. It never imports or
references Love/Career/Finance/Health/Family/Alerts by name; it only
ever sees whatever `segment` string a caller passes in, and uses it
purely as an opaque key to pick a generator out of the dict it was
constructed with. It also never contains astrology or any other
domain-specific logic -- see generator_interface.py for where that
boundary sits.

Regeneration policy is generic across all segments, keyed only on the
three universal `report_type` values:
  - DNA:            generate once; never regenerate on its own. The
                     only way a DNA row regenerates is an explicit
                     `invalidate_cache()` call from outside this flow.
  - CURRENT_PHASE:   regenerate only once `expires_at` has passed. This
                     manager has no generic notion of *when* a "phase"
                     changes -- that is domain knowledge only the
                     segment's own generator has (e.g. Love's current
                     Antardasha end date), so the generator is expected
                     to supply `expires_at` explicitly via
                     GeneratedReport. If it doesn't, the row simply
                     never auto-expires until explicitly invalidated.
  - DAILY_INSIGHT:   generate once per day; regenerate only after
                     expiry. This IS a generic, calendar-only rule, so
                     this manager applies its own default expiry
                     (`generated_at + 1 day`) when the generator doesn't
                     supply one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from modules.ai_report_engine.cache_repository import ReportCacheRepository
from modules.ai_report_engine.exceptions import OpenAICallError
from modules.ai_report_engine.generator_interface import GeneratedReport, ReportGenerator
from modules.models_ai_reports import AIReport

# Phase 4C -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from modules.ai_report_engine.
from modules.activity_events.service import record_event

_activity_events_logger = logging.getLogger("activity_events")


class UnknownSegmentError(Exception):
    """Raised when `get_report()` is called with a `segment` that has no
    registered generator. Deliberately NOT an astrology/business-logic
    error -- it's a wiring error (the caller forgot to register a
    generator), and this manager has no opinion on which segments
    "should" exist."""


class ReportGenerationError(Exception):
    """Wraps whatever exception a generator raised, after the manager
    has already recorded the failure in the cache row."""


class ReportLifecycleManager:
    def __init__(
        self,
        generators: Dict[str, ReportGenerator],
        repository: Optional[ReportCacheRepository] = None,
    ):
        """
        `generators` maps segment string -> ReportGenerator instance,
        e.g. {"LOVE": LoveGenerator(), "CAREER": CareerGenerator(), ...}.
        This manager only ever uses `segment` as a dict key into this
        mapping -- it assigns no meaning to the string itself.
        """
        self._generators = generators
        self._repository = repository or ReportCacheRepository()

    # ------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------
    def get_report(
        self,
        *,
        profile_id: int,
        segment: str,
        report_type: str,
        language: str = "en",
    ) -> dict:
        """
        Responsibilities #1-6 from the Phase 2 spec, in one call:
        read cache -> decide if regeneration is required -> return
        cached report, or generate + save/update + return.
        """
        cache_row = self._repository.read_cache(
            profile_id=profile_id,
            segment=segment,
            report_type=report_type,
            language=language,
        )

        if cache_row is not None and not self._determine_regeneration(cache_row, report_type):
            return cache_row.to_dict()

        generator = self._resolve_generator(segment)

        try:
            result = generator.generate(
                profile_id=profile_id,
                report_type=report_type,
                language=language,
            )
        except Exception as exc:
            if cache_row is not None:
                self._repository.mark_failed(cache_row)
                # Phase 4C -- report_generation_failed. Emitted ONLY here:
                # cache_row already existed (a real, previously-persisted
                # AIReport row) AND mark_failed() just durably committed
                # its authoritative FAILED state above. A first-ever
                # generation failure (cache_row is None) never reaches
                # this branch at all -- no row exists to identify, so no
                # event is emitted for it (see this method's own "if
                # cache_row is not None" guard, unchanged).
                self._emit_ai_report_event(
                    event_name="report_generation_failed",
                    row=cache_row,
                    failure_reason=(
                        "upstream_error" if isinstance(exc, OpenAICallError) else "unknown"
                    ),
                )
            raise ReportGenerationError(
                f"Generation failed for profile_id={profile_id} segment={segment} "
                f"report_type={report_type} language={language}"
            ) from exc

        expires_at = result.expires_at or self._default_expiry(report_type, generated_at=datetime.utcnow())

        if cache_row is None:
            # Responsibility #5: cache missing -> generate, save cache.
            row = self._repository.save_cache(
                profile_id=profile_id,
                segment=segment,
                report_type=report_type,
                language=language,
                content_json=result.content_json,
                expires_at=expires_at,
                model_version=result.model_version,
                prompt_version=result.prompt_version,
                generator_version=result.generator_version,
            )
        else:
            # Responsibility #6: cache expired -> generate, update the
            # SAME row (never a second insert -- the UNIQUE constraint
            # on AIReport would reject one anyway).
            row = self._repository.update_cache(
                cache_row,
                content_json=result.content_json,
                expires_at=expires_at,
                model_version=result.model_version,
                prompt_version=result.prompt_version,
                generator_version=result.generator_version,
            )

        # Phase 4C -- report_generation_completed. Emitted only after
        # save_cache()/update_cache() has already returned, i.e. strictly
        # after that repository call's own commit succeeded. A cached
        # read that never reached this method's generation branch at all
        # (the early `return cache_row.to_dict()` above) never emits
        # anything -- there is nothing new to report.
        self._emit_ai_report_event(event_name="report_generation_completed", row=row)

        return row.to_dict()

    # ------------------------------------------------------------
    # Cache invalidation / deletion pass-throughs (thin wrappers so
    # callers only ever depend on the manager, never the repository).
    # ------------------------------------------------------------
    def invalidate_report(
        self,
        *,
        profile_id: int,
        segment: str,
        report_type: str,
        language: str = "en",
    ) -> Optional[AIReport]:
        row = self._repository.read_cache(
            profile_id=profile_id, segment=segment, report_type=report_type, language=language,
        )
        if row is None:
            return None
        return self._repository.invalidate_cache(row)

    def delete_report(
        self,
        *,
        profile_id: int,
        segment: str,
        report_type: str,
        language: str = "en",
    ) -> bool:
        row = self._repository.read_cache(
            profile_id=profile_id, segment=segment, report_type=report_type, language=language,
        )
        if row is None:
            return False
        self._repository.delete_cache(row)
        return True

    # ------------------------------------------------------------
    # Internal policy (generic -- report_type only, never segment)
    # ------------------------------------------------------------
    def _determine_regeneration(self, cache_row: AIReport, report_type: str) -> bool:
        if cache_row.status in ("PENDING", "FAILED"):
            # No servable content yet, or the last attempt didn't
            # produce any -- always worth trying again.
            return True

        if report_type == "DNA":
            # Generate once; never regenerate on its own once READY.
            # The only way this changes is invalidate_report().
            return False

        # CURRENT_PHASE and DAILY_INSIGHT: regenerate only once expired.
        if cache_row.expires_at is None:
            return False
        return datetime.utcnow() >= cache_row.expires_at

    def _default_expiry(self, report_type: str, generated_at: datetime) -> Optional[datetime]:
        """Generic, report_type-only fallback used ONLY when a
        generator doesn't supply its own `expires_at`. See module
        docstring for why CURRENT_PHASE has no generic default here."""
        if report_type == "DAILY_INSIGHT":
            return generated_at + timedelta(days=1)
        return None

    def _resolve_generator(self, segment: str) -> ReportGenerator:
        generator = self._generators.get(segment)
        if generator is None:
            raise UnknownSegmentError(
                f"No generator registered for segment={segment!r}. "
                f"Registered segments: {sorted(self._generators)}"
            )
        return generator

    # ------------------------------------------------------------
    # Phase 4C -- observational only. Called ONLY after the repository's
    # own commit for this row (save_cache/update_cache/mark_failed) has
    # already succeeded (see each call site). Never influences what
    # get_report() returns or raises.
    # ------------------------------------------------------------
    def _emit_ai_report_event(
        self,
        *,
        event_name: str,
        row: AIReport,
        failure_reason: Optional[str] = None,
    ) -> None:
        # This entire body -- not just the record_event() call -- is
        # wrapped in one try/except, so nothing here (dict-building,
        # dedupe formatting, timestamp conversion) can ever propagate
        # into get_report()'s own caller merely because of an analytics
        # bug.
        try:
            properties: Dict[str, Any] = {"report_type": row.report_type}
            if failure_reason is not None:
                properties["failure_reason"] = failure_reason

            dedupe_key: Optional[str] = None
            if event_name == "report_generation_completed" and row.generated_at is not None:
                # AIReport.generated_at is overwritten fresh on every
                # successful save_cache()/update_cache() -- a real,
                # changing-per-attempt identity, persisted before this
                # point (see this method's own call site). report_
                # generation_failed deliberately gets NO dedupe_key:
                # mark_failed() never touches generated_at, so repeated
                # genuine failures on the same row are indistinguishable
                # by any persisted timestamp -- see this file's own
                # module-level design notes.
                dedupe_key = (
                    f"report_generation_completed:AI_REPORT:{row.id}:"
                    f"{row.generated_at.isoformat()}"
                )

            # occurred_at: for report_generation_completed, AIReport.
            # generated_at is a naive-UTC DateTime (this model's own
            # datetime.utcnow() convention) that was JUST set by
            # save_cache()/update_cache() to describe exactly this
            # completion -- made explicitly timezone-aware here ONLY for
            # this analytics call, never mutating the persisted business
            # column itself. For report_generation_failed there is no
            # equivalent persisted failure timestamp (mark_failed()
            # never touches generated_at, which -- on a regeneration
            # failure -- still holds the PRIOR successful generation's
            # time, not this failure's) -- so the only honest value is
            # the actual moment of this emission.
            if event_name == "report_generation_completed" and row.generated_at is not None:
                occurred_at = row.generated_at.replace(tzinfo=timezone.utc)
            else:
                occurred_at = datetime.now(timezone.utc)

            record_event(
                event_name=event_name,
                occurred_at=occurred_at,
                platform="backend_internal",
                source="ai_report_lifecycle_manager",
                firebase_uid=None,
                profile_id=row.profile_id,
                entity_type="ai_report",
                entity_id=str(row.id),
                properties=properties,
                dedupe_key=dedupe_key,
            )
        except Exception:
            # getattr(..., None) here, not row.id directly: this class
            # accepts a `repository` via dependency injection (see
            # __init__), and at least one existing test exercises
            # get_report() with a duck-typed fake row that does not
            # carry every AIReport attribute. This log line must never
            # itself be the thing that lets an analytics failure escape
            # this method.
            _activity_events_logger.warning(
                "ai_report_lifecycle_manager: unexpected error emitting %s "
                "for AIReport.id=%s (swallowed -- the report result "
                "already decided is unaffected)",
                event_name, getattr(row, "id", None), exc_info=True,
            )
