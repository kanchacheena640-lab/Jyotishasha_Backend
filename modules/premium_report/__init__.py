# modules/premium_report/__init__.py

"""
Premium Report business layer (Phase 7).

Public surface:
    PremiumReportService -- the only business layer between the API and
                             the AI Report Engine
    PremiumReportError    -- base business exception; the controller
                             catches only this
    (plus every specific PremiumReportError subclass, for callers that
     want to handle one deliberately)
"""

from modules.premium_report.exceptions import (
    InvalidRequestError,
    PremiumReportError,
    ProfileAccessDeniedError,
    ProfileNotFoundError,
    ReportGenerationFailedError,
    ReportTypeNotSupportedError,
    ReportValidationFailedError,
    SegmentNotSupportedError,
    SubscriptionRequiredError,
    TrialExpiredError,
)
from modules.premium_report.premium_report_service import PremiumReportService

__all__ = [
    "PremiumReportService",
    "PremiumReportError",
    "InvalidRequestError",
    "ProfileAccessDeniedError",
    "TrialExpiredError",
    "SubscriptionRequiredError",
    "SegmentNotSupportedError",
    "ProfileNotFoundError",
    "ReportTypeNotSupportedError",
    "ReportValidationFailedError",
    "ReportGenerationFailedError",
]
