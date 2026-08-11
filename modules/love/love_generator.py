# modules/love/love_generator.py

"""
LoveGenerator -- the first concrete ReportGenerator, and the reference
implementation for every future segment generator (Career, Finance,
Health, Family, Alerts).

It inherits BaseAIGenerator (modules/ai_report_engine/base_generator.py,
UNMODIFIED) and overrides ONLY build_context(), build_prompt(), and
compute_expires_at() -- generate() itself is never touched, exactly as
required.

Every calculation and every prompt in this file is a direct call into
the EXISTING AI Prediction Lab (services/ai_prediction_lab/) and the
existing kundali backend (full_kundali_api.py) -- nothing here
recomputes astrology, rewrites a prompt, or duplicates the Lab's logic.
The only new code is the thin routing/adapter logic that:
  (a) maps a `profile_id` to the existing AppUser row's birth details,
  (b) picks which existing Lab context/prompt builder applies for a
      given `report_type`, and
  (c) for CURRENT_PHASE/DAILY_INSIGHT, reads the already-cached upstream
      report text via the existing ReportCacheRepository (read-only --
      this generator never writes to the cache; only the Lifecycle
      Manager does that).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from full_kundali_api import calculate_full_kundali
from modules.models_user import AppUser

from services.ai_prediction_lab.context_builder import build_love_profile_context
from services.ai_prediction_lab.prompt_builder import build_love_profile_prompt
from services.ai_prediction_lab.current_love_phase_context import build_current_love_phase_context
from services.ai_prediction_lab.current_love_phase_prompt_builder import build_current_love_phase_prompt
from services.ai_prediction_lab.daily_transit_context import build_daily_transit_context
from services.ai_prediction_lab.daily_love_prediction_prompt_builder import build_daily_love_prediction_prompt

from modules.ai_report_engine.base_generator import BaseAIGenerator
from modules.ai_report_engine.cache_repository import ReportCacheRepository
from modules.ai_report_engine.exceptions import ContextBuildError, PromptBuildError

SEGMENT = "LOVE"


class LoveGenerator(BaseAIGenerator):
    GENERATOR_VERSION = "love_generator_v1"

    # One prompt template version per report_type -- matches the actual
    # .txt filenames already in services/ai_prediction_lab/prompts/.
    _PROMPT_VERSIONS = {
        "DNA": "love_profile_v1",
        "CURRENT_PHASE": "current_love_phase_v1",
        "DAILY_INSIGHT": "daily_love_prediction_v1",
    }

    def __init__(self, *args, repository: Optional[ReportCacheRepository] = None, **kwargs):
        super().__init__(*args, **kwargs)
        # Read-only use: fetching already-cached upstream LOVE reports
        # (DNA's text for CURRENT_PHASE; DNA + CURRENT_PHASE's text for
        # DAILY_INSIGHT). This generator never calls save_cache/
        # update_cache/invalidate_cache/delete_cache -- writing to the
        # cache remains exclusively the Lifecycle Manager's job.
        self._repository = repository or ReportCacheRepository()

    @property
    def PROMPT_VERSION(self) -> Optional[str]:  # noqa: N802 (matches base class attribute name)
        return self._current_prompt_version

    # ------------------------------------------------------------
    # build_context() -- the only place astrology/backend calls happen,
    # and every one of them is an existing, unmodified function.
    # ------------------------------------------------------------
    def build_context(
        self,
        *,
        profile_id: int,
        report_type: str,
        language: str,
    ) -> Dict[str, Any]:
        self._current_prompt_version = self._PROMPT_VERSIONS.get(report_type)

        birth_details = self._load_birth_details(profile_id)

        # calculate_full_kundali() and build_love_profile_context() are
        # the existing backend/Lab functions, called exactly as
        # test_love.py already calls them -- user_id=None (guest mode)
        # so this generator introduces no new write to UserDashaTimeline
        # or any other existing table (see report's "assumptions" note).
        kundali = calculate_full_kundali(
            name=birth_details["name"],
            dob=birth_details["dob"],
            tob=birth_details["tob"],
            lat=birth_details["lat"],
            lon=birth_details["lon"],
            user_id=None,
            language=language,
        )
        birth_summary = build_love_profile_context(kundali)  # existing Lab context builder

        if report_type == "DNA":
            return {
                "birth_summary": birth_summary,
            }

        if report_type == "CURRENT_PHASE":
            relationship_dna_text = self._read_upstream_text(
                profile_id=profile_id, report_type="DNA", language=language,
            )
            phase_context = build_current_love_phase_context(kundali, birth_summary)  # existing Lab context builder
            return {
                "birth_details": birth_details,
                "relationship_dna": relationship_dna_text,
                "phase_context": phase_context,
            }

        if report_type == "DAILY_INSIGHT":
            relationship_dna_text = self._read_upstream_text(
                profile_id=profile_id, report_type="DNA", language=language,
            )
            current_love_phase_text = self._read_upstream_text(
                profile_id=profile_id, report_type="CURRENT_PHASE", language=language,
            )
            daily_transit_context = build_daily_transit_context(kundali)  # existing Lab context builder
            return {
                "relationship_dna": relationship_dna_text,
                "current_love_phase": current_love_phase_text,
                "daily_transit_context": daily_transit_context,
            }

        raise ContextBuildError(f"LoveGenerator does not support report_type={report_type!r}")

    # ------------------------------------------------------------
    # build_prompt() -- routes to the existing, unmodified Lab prompt
    # builder for this report_type. No prompt wording lives here.
    # ------------------------------------------------------------
    def build_prompt(
        self,
        *,
        context: Dict[str, Any],
        report_type: str,
        language: str,
    ) -> str:
        if report_type == "DNA":
            return build_love_profile_prompt(context["birth_summary"])  # existing Lab prompt builder

        if report_type == "CURRENT_PHASE":
            details = context["birth_details"]
            return build_current_love_phase_prompt(
                birth_date=details["dob"],
                birth_time=details["tob"],
                birth_place=details["pob"],
                relationship_dna=context["relationship_dna"],
                context=context["phase_context"],
                language=language,
            )  # existing Lab prompt builder

        if report_type == "DAILY_INSIGHT":
            return build_daily_love_prediction_prompt(
                relationship_dna=context["relationship_dna"],
                current_love_phase=context["current_love_phase"],
                daily_transit_context=context["daily_transit_context"],
            )  # existing Lab prompt builder

        raise PromptBuildError(f"LoveGenerator does not support report_type={report_type!r}")

    # ------------------------------------------------------------
    # compute_expires_at() -- only CURRENT_PHASE has real domain
    # knowledge of staleness (the current Antardasha's end date,
    # already computed by the existing Lab context builder). DNA and
    # DAILY_INSIGHT return None, deferring entirely to the Lifecycle
    # Manager's generic report_type-based policy (never expires / +1 day).
    # ------------------------------------------------------------
    def compute_expires_at(
        self,
        *,
        context: Dict[str, Any],
        report_type: str,
    ) -> Optional[datetime]:
        if report_type != "CURRENT_PHASE":
            return None

        antardasha_end = ((context.get("phase_context") or {}).get("antardasha") or {}).get("end")
        if not antardasha_end:
            return None  # existing logic didn't expose it -- fall back to Lifecycle Manager policy

        return datetime.strptime(antardasha_end, "%Y-%m-%d")

    # ------------------------------------------------------------
    # Thin adapters (explicitly sanctioned by the task) -- these do not
    # duplicate any existing logic, they only route to it.
    # ------------------------------------------------------------
    def _load_birth_details(self, profile_id: int) -> Dict[str, Any]:
        """profile_id IS AppUser.id (the Phase 1 architecture decision).
        Reads the existing AppUser row -- does not create or modify it."""
        user = AppUser.query.get(profile_id)
        if user is None:
            raise ContextBuildError(f"No AppUser found for profile_id={profile_id}")

        missing = [
            field for field in ("dob", "tob", "pob", "lat", "lng")
            if getattr(user, field, None) in (None, "")
        ]
        if missing:
            raise ContextBuildError(
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

    def _read_upstream_text(self, *, profile_id: int, report_type: str, language: str) -> str:
        """Read-only lookup of an already-cached LOVE report's text via
        the existing, generic ReportCacheRepository. Raises if that
        upstream report hasn't been generated yet -- see this phase's
        implementation report for why sequencing (DNA before
        CURRENT_PHASE before DAILY_INSIGHT) is assumed rather than
        auto-triggered here."""
        row = self._repository.read_cache(
            profile_id=profile_id,
            segment=SEGMENT,
            report_type=report_type,
            language=language,
        )
        if row is None or row.status != "READY" or not row.content_json:
            raise ContextBuildError(
                f"LOVE {report_type} must be generated before it can be used as "
                f"input here (profile_id={profile_id}); no READY cached report found."
            )
        return row.content_json.get("content", "")
