# modules/premium_report/premium_report_service.py

"""
PremiumReportService -- the ONLY business layer between the API and the
AI Report Engine (Lifecycle Manager / Generator Registry / LoveGenerator,
all frozen, all unmodified by this file).

    API -> PremiumReportService -> EntitlementService (access check)
                                 -> LifecycleManager -> GeneratorRegistry -> LoveGenerator

The controller (routes/routes_premium_report.py) now does only three
things: parse the HTTP request, call get_report() here, and translate
whatever PremiumReportError subclass it catches into an HTTP response.
Every other decision -- access control, entitlement gating, usage
tracking, and engine-exception translation -- lives here.

get_report() is the single entry point/service boundary for serving a
premium report, and validate_entitlement_access() is called exactly
once from it, before any cache lookup, lifecycle-manager work, AI
generation, or PDF generation begins. It consolidates what were
previously two separate placeholder hooks (validate_trial_access /
validate_subscription) into one real check backed by
EntitlementService (read-only, injected/lazily resolved here, never
modified) -- calling EntitlementService.has_access() from two places
would mean evaluating entitlement twice for the same request, which is
exactly what this method exists to avoid.

validate_profile_access() and track_usage() remain placeholders ONLY:
they always allow / do nothing in this phase, exactly as instructed.
validate_profile_access is a distinct concern (does current_user_id own
profile_id) from entitlement/billing access, and stays a no-op until
Authentication is wired in.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from modules.ai_report_engine import (
    ReportGenerationError,
    ReportLifecycleManager,
    UnknownSegmentError,
    get_default_registry,
)
from modules.entitlement import EntitlementService
from modules.models_ai_reports import AI_REPORT_SEGMENTS

from modules.premium_report.exceptions import (
    InvalidRequestError,
    PremiumReportError,
    ProfileNotFoundError,
    ReportGenerationFailedError,
    ReportTypeNotSupportedError,
    ReportValidationFailedError,
    SegmentNotSupportedError,
    SubscriptionRequiredError,
    TrialExpiredError,
)


class PremiumReportService:
    def __init__(
        self,
        lifecycle_manager: Optional[ReportLifecycleManager] = None,
        entitlement_service: Optional[EntitlementService] = None,
    ):
        self._lifecycle_manager = lifecycle_manager or ReportLifecycleManager(
            generators=get_default_registry().as_dict()
        )
        self._entitlement_service = entitlement_service or EntitlementService()

    # ------------------------------------------------------------
    # Public entry point -- the only method the controller calls.
    # ------------------------------------------------------------
    def get_report(
        self,
        *,
        current_user_id: Optional[int],
        profile_id: Optional[int],
        segment: Optional[str],
        report_type: Optional[str],
        language: str = "en",
    ) -> Dict[str, Any]:
        self._validate_request(profile_id=profile_id, segment=segment, report_type=report_type)

        # Placeholder gate -- currently a no-op that always allows.
        # Will later raise ProfileAccessDeniedError without any change
        # to this method's shape, the controller, or the AI Report
        # Engine.
        self.validate_profile_access(current_user_id=current_user_id, profile_id=profile_id)

        # THE single entitlement/access check for this request -- see
        # validate_entitlement_access()'s docstring for why this is the
        # only place it's called. Everything below this line (cache,
        # lifecycle manager, AI generation) only runs if access is
        # granted.
        self.validate_entitlement_access(profile_id=profile_id, segment=segment)

        try:
            cache_row = self._lifecycle_manager.get_report(
                profile_id=profile_id,
                segment=segment,
                report_type=report_type,
                language=language,
            )
        except UnknownSegmentError as exc:
            raise SegmentNotSupportedError(str(exc)) from exc
        except ReportGenerationError as exc:
            raise self._translate_generation_error(exc) from exc

        self.track_usage(profile_id=profile_id, segment=segment, report_type=report_type)

        return self._shape_response(cache_row)

    # ------------------------------------------------------------
    # Future integration hooks -- placeholders ONLY this phase.
    # ------------------------------------------------------------
    def validate_profile_access(self, *, current_user_id: Optional[int], profile_id: Optional[int]) -> None:
        """
        FUTURE (Authentication phase): verify `current_user_id` owns
        `profile_id` -- e.g. resolve the authenticated User to their
        AppUser(s) and confirm `profile_id` is among them, raising
        ProfileAccessDeniedError otherwise.

        Always allows access for now -- no auth/ownership logic exists
        yet, and `current_user_id` is not read at all in this phase.
        """
        return None

    def validate_entitlement_access(self, *, profile_id: Optional[int], segment: Optional[str]) -> None:
        """
        THE single entitlement/access check for this service. Replaces
        what were previously two separate placeholder hooks
        (validate_trial_access / validate_subscription) with one real
        check, since EntitlementService.has_access() already accounts
        for both an active trial and an active, segment-matching
        subscription in a single decision.

        Reads the entitlement snapshot once (get_current_entitlement)
        purely to classify *why* access is denied for a clearer error
        message, then makes the actual yes/no decision via has_access()
        -- both calls belong to EntitlementService, which is read-only
        and is never modified here.

        Raises SegmentNotSupportedError for an unrecognized segment
        (before EntitlementService.has_access() would otherwise raise a
        raw ValueError for the same reason -- this keeps that failure
        mode identical to what it was before this integration).
        Raises TrialExpiredError or SubscriptionRequiredError -- both
        business errors, never an infrastructure exception -- when a
        recognized segment is denied. Returns None (allows) otherwise.
        """
        if segment not in AI_REPORT_SEGMENTS:
            raise SegmentNotSupportedError(f"Unsupported segment: {segment!r}")

        entitlement = self._entitlement_service.get_current_entitlement(profile_id)

        if self._entitlement_service.has_access(profile_id, segment):
            return

        if entitlement.status == "TRIAL" and not entitlement.trial.is_active:
            raise TrialExpiredError(
                f"Trial for profile_id={profile_id} has expired; "
                f"no active subscription covers '{segment}'."
            )

        raise SubscriptionRequiredError(
            f"No active trial or subscription grants access to '{segment}' "
            f"for profile_id={profile_id}."
        )

    def track_usage(self, *, profile_id: Optional[int], segment: Optional[str], report_type: Optional[str]) -> None:
        """
        FUTURE (Analytics phase): record that this profile requested
        this segment/report_type -- e.g. increment a usage counter or
        emit an analytics event.

        No-op for now.
        """
        return None

    # ------------------------------------------------------------
    # Internal: request validation
    # ------------------------------------------------------------
    def _validate_request(
        self,
        *,
        profile_id: Optional[int],
        segment: Optional[str],
        report_type: Optional[str],
    ) -> None:
        if not isinstance(profile_id, int):
            raise InvalidRequestError("profile_id must be an integer.")
        if not segment:
            raise InvalidRequestError("segment is required.")
        if not report_type:
            raise InvalidRequestError("report_type is required.")

    # ------------------------------------------------------------
    # Internal: translate AI Report Engine exceptions into business
    # exceptions. This is the ONLY place that inspects the engine's
    # exception chain -- the controller never does this itself anymore.
    # ------------------------------------------------------------
    def _translate_generation_error(self, exc: ReportGenerationError) -> PremiumReportError:
        cause = exc.__cause__
        cause_type = type(cause).__name__ if cause is not None else None
        message = str(cause) if cause is not None else str(exc)

        if cause_type == "ContextBuildError":
            if "No AppUser found" in message:
                return ProfileNotFoundError(message)
            if "missing required birth fields" in message:
                return ReportValidationFailedError(message)
            if "must be generated before it can be used" in message:
                return ReportValidationFailedError(message)
            if "does not support report_type" in message:
                return ReportTypeNotSupportedError(message)

        if cause_type == "PromptBuildError" and "does not support report_type" in message:
            return ReportTypeNotSupportedError(message)

        if cause_type == "OutputValidationError":
            return ReportValidationFailedError(message)

        # OpenAICallError, or anything the engine didn't classify.
        return ReportGenerationFailedError("Report generation failed.")

    # ------------------------------------------------------------
    # Internal: response shaping -- never exposes the raw AIReport dict.
    # ------------------------------------------------------------
    def _shape_response(self, cache_row: Dict[str, Any]) -> Dict[str, Any]:
        content_json = cache_row.get("content_json") or {}
        return {
            "profile_id": cache_row.get("profile_id"),
            "segment": cache_row.get("segment"),
            "report_type": cache_row.get("report_type"),
            "language": cache_row.get("language"),
            "content": content_json.get("content"),
            "generated_at": cache_row.get("generated_at"),
            "expires_at": cache_row.get("expires_at"),
        }
