# modules/premium_report/exceptions.py

"""
Business exception hierarchy for the Premium Report Service.

Every exception the controller ever needs to handle is one of these --
the controller catches only the base `PremiumReportError` and reads its
`status_code`/`error_code`/`public_message`, so it never inspects
exception text or reaches into `.__cause__` chains itself (that
translation now happens once, inside PremiumReportService, not in the
controller).
"""


class PremiumReportError(Exception):
    status_code = 500
    error_code = "internal_error"

    def __init__(self, message: str = None):
        self.public_message = message or "An unexpected error occurred."
        super().__init__(self.public_message)


class InvalidRequestError(PremiumReportError):
    """Missing/malformed request parameters."""
    status_code = 400
    error_code = "invalid_request"


class ProfileAccessDeniedError(PremiumReportError):
    """FUTURE: the current authenticated user does not own profile_id.
    Not raised anywhere yet -- see validate_profile_access()."""
    status_code = 403
    error_code = "profile_access_denied"


class TrialExpiredError(PremiumReportError):
    """The profile's trial window has ended and no active subscription
    covers the requested segment -- see
    PremiumReportService.validate_entitlement_access()."""
    status_code = 402
    error_code = "trial_expired"


class SubscriptionRequiredError(PremiumReportError):
    """No active trial or subscription grants access to the requested
    segment -- see PremiumReportService.validate_entitlement_access()."""
    status_code = 402
    error_code = "subscription_required"


class SegmentNotSupportedError(PremiumReportError):
    """The requested segment has no registered generator (translated
    from the AI Report Engine's UnknownSegmentError)."""
    status_code = 400
    error_code = "unknown_segment"


class ProfileNotFoundError(PremiumReportError):
    """No profile exists for the given profile_id (translated from the
    engine's ContextBuildError)."""
    status_code = 404
    error_code = "profile_not_found"


class ReportTypeNotSupportedError(PremiumReportError):
    """The requested report_type isn't supported by this segment's
    generator (translated from ContextBuildError/PromptBuildError)."""
    status_code = 400
    error_code = "unknown_report_type"


class ReportValidationFailedError(PremiumReportError):
    """The profile's data was incomplete, an upstream report dependency
    was missing, or the AI output failed validation (translated from
    ContextBuildError/OutputValidationError)."""
    status_code = 422
    error_code = "validation_failure"


class ReportGenerationFailedError(PremiumReportError):
    """The AI call itself failed, or failed for an unclassified reason
    (translated from OpenAICallError or any other generation failure)."""
    status_code = 502
    error_code = "generation_failure"
