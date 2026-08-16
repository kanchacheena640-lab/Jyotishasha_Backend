# modules/health/health_generator.py

"""
HealthGenerator -- the fourth concrete ReportGenerator, built to the
exact same shape as modules/love/love_generator.py,
modules/career/career_generator.py, and
modules/finance/finance_generator.py (the reference implementations for
every segment generator: Love, Career, Finance, Health, Family, Alerts).
None of those three files is modified by this file.

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

This adapter logic (`_load_birth_details`/`_read_upstream_text`) is not
shared with LoveGenerator/CareerGenerator/FinanceGenerator by design --
none of those files was modified to extract a shared helper, so this
class carries its own copy, exactly mirroring the reference
implementations' shape rather than introducing a new shared abstraction.

Content produced by this generator is a behavioural/energy-pattern
mirror only -- see prompts/health_profile_v1.txt,
current_health_phase_v1.txt, and health_action_guidance_v1.txt for the
explicit, mandatory medical-safety rule every one of those templates
enforces (no diagnosis, no medicine/treatment recommendation, no
replacing professional medical advice, no fear-inducing language). This
generator itself performs no medical reasoning of any kind -- it only
routes existing astrological facts into those prompts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from full_kundali_api import calculate_full_kundali
from modules.models_user import AppUser

from services.ai_prediction_lab.health_context_builder import build_health_profile_context
from services.ai_prediction_lab.health_prompt_builder import build_health_profile_prompt
from services.ai_prediction_lab.current_health_phase_context import build_current_health_phase_context
from services.ai_prediction_lab.current_health_phase_prompt_builder import build_current_health_phase_prompt
from services.ai_prediction_lab.health_action_context import build_health_action_context
from services.ai_prediction_lab.health_action_guidance_prompt_builder import build_health_action_guidance_prompt
from services.ai_prediction_lab.current_health_timing_context import build_current_health_timing_context
from services.ai_prediction_lab.current_health_timing_prompt_builder import build_current_health_timing_prompt
from services.ai_prediction_lab.current_timing_expiry import compute_current_timing_expiry

from modules.ai_report_engine.base_generator import BaseAIGenerator
from modules.ai_report_engine.cache_repository import ReportCacheRepository
from modules.ai_report_engine.exceptions import ContextBuildError, PromptBuildError

SEGMENT = "HEALTH"


class HealthGenerator(BaseAIGenerator):
    GENERATOR_VERSION = "health_generator_v1"

    # One prompt template version per report_type -- matches the actual
    # .txt filenames in services/ai_prediction_lab/prompts/. Same three
    # universal report_types LOVE/CAREER/FINANCE use (DNA /
    # CURRENT_PHASE / DAILY_INSIGHT) -- see this phase's implementation
    # report for how they map onto "Health DNA" / "Current Health Phase
    # (incl. current strengths, current challenges, wellness focus)" /
    # "Practical Health Guidance".
    _PROMPT_VERSIONS = {
        "DNA": "health_profile_v1",
        "CURRENT_PHASE": "current_health_phase_v1",
        "DAILY_INSIGHT": "health_action_guidance_v1",
        # CURRENT_TIMING -- third layer (DNA -> CURRENT_PHASE ->
        # CURRENT_TIMING). Purely additive; DNA/CURRENT_PHASE entries
        # above are unchanged.
        "CURRENT_TIMING": "current_health_timing_v1",
    }

    def __init__(self, *args, repository: Optional[ReportCacheRepository] = None, **kwargs):
        super().__init__(*args, **kwargs)
        # Read-only use: fetching already-cached upstream HEALTH reports
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

        # calculate_full_kundali() and build_health_profile_context() are
        # the existing backend/Lab functions -- user_id=None (guest mode)
        # so this generator introduces no new write to UserDashaTimeline
        # or any other existing table, same as LoveGenerator/
        # CareerGenerator/FinanceGenerator.
        kundali = calculate_full_kundali(
            name=birth_details["name"],
            dob=birth_details["dob"],
            tob=birth_details["tob"],
            lat=birth_details["lat"],
            lon=birth_details["lon"],
            user_id=None,
            language=language,
        )
        health_summary = build_health_profile_context(kundali)  # existing Lab context builder

        if report_type == "DNA":
            return {
                "health_summary": health_summary,
            }

        if report_type == "CURRENT_PHASE":
            health_dna_text = self._read_upstream_text(
                profile_id=profile_id, report_type="DNA", language=language,
            )
            phase_context = build_current_health_phase_context(kundali, health_summary)  # existing Lab context builder
            return {
                "birth_details": birth_details,
                "health_dna": health_dna_text,
                "phase_context": phase_context,
            }

        if report_type == "DAILY_INSIGHT":
            health_dna_text = self._read_upstream_text(
                profile_id=profile_id, report_type="DNA", language=language,
            )
            current_health_phase_text = self._read_upstream_text(
                profile_id=profile_id, report_type="CURRENT_PHASE", language=language,
            )
            health_action_ctx = build_health_action_context(kundali)  # existing Lab context builder
            return {
                "health_dna": health_dna_text,
                "current_health_phase": current_health_phase_text,
                "health_action_context": health_action_ctx,
            }

        if report_type == "CURRENT_TIMING":
            current_health_phase_text = self._read_upstream_text(
                profile_id=profile_id, report_type="CURRENT_PHASE", language=language,
            )
            timing_context = build_current_health_timing_context(kundali)  # existing Lab context builder
            return {
                "current_health_phase": current_health_phase_text,
                "timing_context": timing_context,
            }

        raise ContextBuildError(f"HealthGenerator does not support report_type={report_type!r}")

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
            return build_health_profile_prompt(context["health_summary"], language=language)  # existing Lab prompt builder

        if report_type == "CURRENT_PHASE":
            details = context["birth_details"]
            return build_current_health_phase_prompt(
                birth_date=details["dob"],
                birth_time=details["tob"],
                birth_place=details["pob"],
                health_dna=context["health_dna"],
                context=context["phase_context"],
                language=language,
            )  # existing Lab prompt builder

        if report_type == "DAILY_INSIGHT":
            return build_health_action_guidance_prompt(
                health_dna=context["health_dna"],
                current_health_phase=context["current_health_phase"],
                health_action_context=context["health_action_context"],
                language=language,
            )  # existing Lab prompt builder

        if report_type == "CURRENT_TIMING":
            return build_current_health_timing_prompt(
                current_health_phase=context["current_health_phase"],
                context=context["timing_context"],
                language=language,
            )  # existing Lab prompt builder

        raise PromptBuildError(f"HealthGenerator does not support report_type={report_type!r}")

    # ------------------------------------------------------------
    # compute_expires_at() -- only CURRENT_PHASE has real domain
    # knowledge of staleness (the current Antardasha's end date,
    # already computed by the existing Lab context builder). DNA and
    # DAILY_INSIGHT return None, deferring entirely to the Lifecycle
    # Manager's generic report_type-based policy (never expires / +1 day)
    # -- same as LoveGenerator/CareerGenerator/FinanceGenerator.
    # ------------------------------------------------------------
    def compute_expires_at(
        self,
        *,
        context: Dict[str, Any],
        report_type: str,
    ) -> Optional[datetime]:
        if report_type == "CURRENT_TIMING":
            # Own expiry policy -- earliest of a relevant fast-moving
            # planet's sign change, or 24 hours. Never None (see
            # current_timing_expiry.py), so this never falls back to
            # the Lifecycle Manager's generic report_type policy.
            return compute_current_timing_expiry(SEGMENT)

        if report_type != "CURRENT_PHASE":
            return None

        antardasha_end = ((context.get("phase_context") or {}).get("antardasha") or {}).get("end")
        if not antardasha_end:
            return None  # existing logic didn't expose it -- fall back to Lifecycle Manager policy

        return datetime.strptime(antardasha_end, "%Y-%m-%d")

    # ------------------------------------------------------------
    # Thin adapters (same shape as LoveGenerator's/CareerGenerator's/
    # FinanceGenerator's, not shared -- see module docstring) -- these
    # do not duplicate any existing logic, they only route to it.
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
        """Read-only lookup of an already-cached HEALTH report's text
        via the existing, generic ReportCacheRepository. Raises if that
        upstream report hasn't been generated yet -- see
        LoveGenerator's/CareerGenerator's/FinanceGenerator's identical
        method for why sequencing (DNA before CURRENT_PHASE before
        DAILY_INSIGHT) is assumed rather than auto-triggered here."""
        row = self._repository.read_cache(
            profile_id=profile_id,
            segment=SEGMENT,
            report_type=report_type,
            language=language,
        )
        if row is None or row.status != "READY" or not row.content_json:
            raise ContextBuildError(
                f"HEALTH {report_type} must be generated before it can be used as "
                f"input here (profile_id={profile_id}); no READY cached report found."
            )
        return row.content_json.get("content", "")
