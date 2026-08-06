# modules/ai_report_engine/cache_repository.py

"""
Data-access layer for the `ai_reports` cache table. This is the ONLY
module that touches `AIReport`/the database directly -- the Lifecycle
Manager calls these methods and never writes a query itself. Kept
separate so the caching policy (lifecycle_manager.py) can be reasoned
about, and tested, independently of persistence details.

No segment knowledge lives here either -- every method just takes
whatever `segment`/`report_type`/`language` values it's given and
stores/reads them as opaque strings.

Hardening pass: `save_cache()` now handles the existing UNIQUE
constraint on (profile_id, segment, report_type, language) gracefully.
Two concurrent requests for the same, not-yet-cached report can both
reach `save_cache()` (LifecycleManager.get_report() -- unmodified --
still reads-then-generates-then-saves); the loser's INSERT now hits
that UNIQUE constraint and is recovered here by re-reading and
returning the winner's row, instead of letting the IntegrityError
propagate as an unhandled exception. No schema change, no lock, no
change to LifecycleManager -- this is the smallest fix that makes the
existing constraint's own guarantee (at most one row per key) behave
gracefully under the race it was always meant to prevent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.models_ai_reports import AIReport


class ReportCacheRepository:
    def read_cache(
        self,
        *,
        profile_id: int,
        segment: str,
        report_type: str,
        language: str,
    ) -> Optional[AIReport]:
        """The one existing row for this key, if any (the UNIQUE
        constraint on AIReport guarantees there is at most one)."""
        return AIReport.query.filter_by(
            profile_id=profile_id,
            segment=segment,
            report_type=report_type,
            language=language,
        ).first()

    def save_cache(
        self,
        *,
        profile_id: int,
        segment: str,
        report_type: str,
        language: str,
        content_json: Dict[str, Any],
        expires_at: Optional[datetime],
        model_version: Optional[str],
        prompt_version: Optional[str],
        generator_version: Optional[str],
    ) -> AIReport:
        """INSERT a new cache row -- used only when no row exists yet
        for this key (Responsibility #5: cache missing).

        Race-safe: if a concurrent request already inserted the same
        (profile_id, segment, report_type, language) row between this
        caller's own `read_cache()` and this INSERT, the database's
        existing UNIQUE constraint rejects this INSERT with an
        IntegrityError. That is not this caller's failure -- another
        request already produced a valid, saved report for the exact
        same key -- so it is recovered here by rolling back this
        session's failed INSERT and returning the winning row that's
        now actually in the table, instead of raising."""
        row = AIReport(
            profile_id=profile_id,
            segment=segment,
            report_type=report_type,
            language=language,
            content_json=content_json,
            status="READY",
            generated_at=datetime.utcnow(),
            expires_at=expires_at,
            model_version=model_version,
            prompt_version=prompt_version,
            generator_version=generator_version,
        )
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            winner = self.read_cache(
                profile_id=profile_id,
                segment=segment,
                report_type=report_type,
                language=language,
            )
            if winner is None:
                # Not the race we expected (no row actually exists to
                # recover) -- a genuinely different integrity problem.
                # Never swallow that; let it surface as before.
                raise
            return winner
        return row

    def update_cache(
        self,
        row: AIReport,
        *,
        content_json: Dict[str, Any],
        expires_at: Optional[datetime],
        model_version: Optional[str],
        prompt_version: Optional[str],
        generator_version: Optional[str],
    ) -> AIReport:
        """UPDATE the existing row in place -- used when a cached row
        already exists and needs regenerating (Responsibility #6). Never
        inserts a second row for the same key."""
        row.content_json = content_json
        row.status = "READY"
        row.generated_at = datetime.utcnow()
        row.expires_at = expires_at
        row.model_version = model_version
        row.prompt_version = prompt_version
        row.generator_version = generator_version
        db.session.commit()
        return row

    def mark_failed(self, row: AIReport) -> AIReport:
        """Records that the most recent generation attempt for this row
        failed, without touching whatever `content_json` it may already
        hold (a previously-READY row that fails to regenerate keeps
        serving its last good content until a future attempt succeeds)."""
        row.status = "FAILED"
        db.session.commit()
        return row

    def invalidate_cache(self, row: AIReport) -> AIReport:
        """Explicit invalidation (e.g. a future admin action, or a
        segment detecting its own data changed). Forces the next
        `get_report()` call to treat this row as needing regeneration --
        this is the ONLY sanctioned way a DNA report (which otherwise
        never expires) gets regenerated."""
        row.status = "PENDING"
        row.expires_at = None
        db.session.commit()
        return row

    def delete_cache(self, row: AIReport) -> None:
        """Removes the cache row entirely. Not used by the normal
        get/regenerate flow -- available for future administrative
        cleanup (e.g. a profile being deleted)."""
        db.session.delete(row)
        db.session.commit()
