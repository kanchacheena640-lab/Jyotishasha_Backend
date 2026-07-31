# modules/ai_report_engine/generator_interface.py

"""
Generator contract for the AI Report Lifecycle Manager.

Every segment (Love, Career, Finance, Health, Family, Alerts) must
implement ONE class satisfying this contract (e.g. LoveGenerator,
CareerGenerator, ...). The Lifecycle Manager depends ONLY on this
interface -- it never imports a concrete segment generator itself, and
it never contains segment-specific logic (no astrology, no
Love-specific prompt building, nothing). A caller (a future API layer)
is responsible for choosing which concrete generator to hand the
manager for a given `segment`.

No concrete generator (LoveGenerator, etc.) is implemented here or
anywhere in this phase -- this file defines the shape only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class GeneratedReport:
    """
    What a generator hands back to the Lifecycle Manager for one
    generation call. The manager treats `content_json` as an opaque
    blob -- it never inspects its shape.
    """

    content_json: Dict[str, Any]

    # Optional, explicit expiry for this specific report. Segments with
    # real domain knowledge of "when does this become stale" (e.g. Love's
    # CURRENT_PHASE, which already knows the current Antardasha's end
    # date) should set this. If left None, the Lifecycle Manager applies
    # its own generic, report_type-only fallback policy (see
    # lifecycle_manager.py::default_expiry) -- it never guesses at
    # segment-specific astrology/logic itself.
    expires_at: Optional[datetime] = None

    # Optional provenance, stored as-is on the cache row.
    model_version: Optional[str] = None
    prompt_version: Optional[str] = None
    generator_version: Optional[str] = None


class ReportGenerator(ABC):
    """
    Contract every segment-specific generator must implement.

    A generator's ONLY job is: given a profile, a universal report_type
    (DNA / CURRENT_PHASE / DAILY_INSIGHT), and a language, produce the
    report content. It must know nothing about caching, expiry policy,
    or the `ai_reports` table -- that is entirely the Lifecycle
    Manager's responsibility.
    """

    @abstractmethod
    def generate(
        self,
        *,
        profile_id: int,
        report_type: str,
        language: str,
    ) -> GeneratedReport:
        """
        Produce a fresh report. Must raise an exception on failure (the
        Lifecycle Manager catches it and marks the cache row FAILED) --
        it must never return a partial or empty GeneratedReport to
        signal failure.
        """
        raise NotImplementedError
