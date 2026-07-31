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

from datetime import datetime, timedelta
from typing import Dict, Optional

from modules.ai_report_engine.cache_repository import ReportCacheRepository
from modules.ai_report_engine.generator_interface import GeneratedReport, ReportGenerator
from modules.models_ai_reports import AIReport


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
