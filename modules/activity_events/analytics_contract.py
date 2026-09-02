# modules/activity_events/analytics_contract.py

"""
Phase 6B.1 -- the frozen analytics query/service CONTRACT: constants,
pure validation/rate-calculation helpers, and the (deliberately
not-yet-implemented) service surface a future modules/activity_events/
analytics_service.py (Phase 6B.2/6B.3) must satisfy.

Nothing in this file touches ActivityEvent, db.session, or SQL of any
kind -- that is explicitly out of scope for Phase 6B.1 (see this
phase's own task brief, "Implementation boundary"). This file exists so
6B.2's real implementation has an already-agreed contract to satisfy
rather than inventing metric semantics while also writing SQL.

Frozen Phase 6A architectural principles this file encodes:
  - PostgreSQL activity_events is the durable first-party ledger;
    GA4/Firebase remains complementary, never authoritative here.
  - firebase_uid, NOT profile_id, is the canonical unique-user key
    (profile_id may be legitimately NULL before AppUser/profile
    creation -- see login_completed's own frozen semantic, Phase 5D.3).
  - occurred_at drives every metric/window; recorded_at is ingestion
    metadata only.
  - session_id is an app/process session (Flutter's
    AnalyticsSessionContext -- one id per process lifetime), never a
    30-minute web-analytics session.
  - Every production analytics query MUST be structurally fixed to
    environment="production" -- never a caller-supplied value. This is
    enforced here by simply never accepting an `environment` parameter
    anywhere on AnalyticsService -- there is no argument to forget to
    pass or to accidentally override with. PRODUCTION_ENVIRONMENT is
    also exposed as AnalyticsService.ENVIRONMENT precisely so 6B.2's
    real subclass has one, unambiguous constant to hard-code its own
    WHERE clause against, rather than re-deriving or importing a
    string literal from elsewhere.
  - Revenue/accounting truth is never derived from activity_events --
    see modules/payments/metrics_service.py's own existing boundary
    for the authoritative business-table equivalent; this module
    defines no revenue/amount/currency field anywhere.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from modules.activity_events.analytics_models import (
    AnalyticsLimitation,
    AnalyticsWindow,
    AskNowMetrics,
    EngagementMetrics,
    NotificationMetrics,
    OverviewMetrics,
    ReportMetrics,
    SubscriptionMetrics,
)

# ---------------------------------------------------------------------
# Environment -- structurally fixed, never a request parameter.
# ---------------------------------------------------------------------
PRODUCTION_ENVIRONMENT = "production"


# ---------------------------------------------------------------------
# Platform filter -- closed vocabulary, matches
# modules/models_activity_events.py's own column comment exactly. No
# new platform value may be introduced here without a schema-level
# design-freeze pass, same rule CLIENT_INGESTIBLE_EVENTS already
# follows for event ownership.
# ---------------------------------------------------------------------
ALLOWED_PLATFORMS = frozenset({"app_android", "app_ios", "website", "backend_internal"})


class InvalidPlatformFilter(ValueError):
    """Raised for any platform value outside ALLOWED_PLATFORMS -- never
    silently ignored or passed through to a query."""


def validate_platform(platform: Optional[str]) -> Optional[str]:
    """None means "no platform filter" and is always valid. Any other
    value must be one of the four real ledger platform values."""
    if platform is None:
        return None
    if platform not in ALLOWED_PLATFORMS:
        raise InvalidPlatformFilter(
            f"Unknown platform: {platform!r}; must be one of {sorted(ALLOWED_PLATFORMS)}"
        )
    return platform


# ---------------------------------------------------------------------
# Rate calculation -- ONE consistent rule for every ratio metric in
# this contract (notification open_rate, Ask Now delivery/failure
# rate, report verification/completion rate). denominator <= 0 -> None,
# NEVER 0.0: a real 0.0 means "the denominator existed and nobody
# converted"; None means "this rate cannot be computed at all" -- the
# two are not the same fact and must never be conflated (Phase 6A
# section 21).
# ---------------------------------------------------------------------
def compute_rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return numerator / denominator


# ---------------------------------------------------------------------
# DAU / WAU / MAU -- anchor = the window's own `end`. Each is a
# trailing window ending at that same anchor, per Phase 6A section 12's
# recommended (and here, frozen) convention.
# ---------------------------------------------------------------------
DAU_WINDOW = timedelta(days=1)
WAU_WINDOW = timedelta(days=7)
MAU_WINDOW = timedelta(days=30)


def active_user_window(anchor_window: AnalyticsWindow, span: timedelta) -> AnalyticsWindow:
    """Derives the trailing [end-span, end) window used for one of
    DAU/WAU/MAU, anchored at `anchor_window.end` -- the SAME end point
    the caller's own overview window already uses, so DAU/WAU/MAU are
    always "as of the end of the requested overview window," never a
    second, independently-chosen anchor."""
    return AnalyticsWindow(start=anchor_window.end - span, end=anchor_window.end)


# ---------------------------------------------------------------------
# Named, reusable limitations -- frozen wording for the specific gaps
# Phase 6A already identified as real (not hypothetical), so 6B.2 does
# not have to reinvent the explanation and cannot quietly drop it.
# ---------------------------------------------------------------------
CTA_CTR_LIMITATION = AnalyticsLimitation(
    metric="engagement.ctr",
    reason=(
        "No impression event exists anywhere in the canonical activity_events "
        "registry -- click-through rate has no denominator and must never be "
        "approximated as 0."
    ),
)

ASKNOW_ATTEMPT_LINKAGE_LIMITATION = AnalyticsLimitation(
    metric="asknow.attempt_linkage",
    reason=(
        "asknow_question_submitted/asknow_answer_delivered/asknow_answer_failed "
        "share no correlation_id or entity_id -- only aggregate stage counts and "
        "rates are computable, never an exact question-to-answer pairing."
    ),
)

SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION = AnalyticsLimitation(
    metric="subscription.placement_attribution",
    reason=(
        "subscription_discovery_viewed (Flutter, carries session_id) and the "
        "subscription lifecycle events (backend-owned, session_id always NULL) "
        "share no correlation key -- placement-to-conversion is aggregate-only, "
        "never an exact per-visit attribution."
    ),
)

# The one CTA id that identifies the purchased-report journey's entry
# point (Order-based, Razorpay) -- confirmed against the real Flutter
# producer (report_catalog_page.dart). Deliberately not treated as a
# report_discovery_viewed equivalent -- see PurchasedReportMetrics'
# own docstring.
PURCHASED_REPORT_ENTRY_CTA_ID = "report_catalog_buy_now"


# ---------------------------------------------------------------------
# The service surface itself -- signatures/types frozen now; every
# method body is intentionally unimplemented (NotImplementedError) so
# that NOTHING can accidentally call a real query that doesn't exist
# yet and get back silent zeros/fake data. Phase 6B.2/6B.3 replaces
# this class's method BODIES only -- the signatures below (including
# the deliberate absence of an `environment` parameter anywhere) are
# the frozen part of this contract.
#
# Every method takes exactly (window: AnalyticsWindow, platform:
# Optional[str] = None) -- no `environment` parameter exists on this
# class at all, on any method, so a caller has no argument through
# which to override the production-only filter. The real 6B.2
# implementation MUST hard-code environment=AnalyticsService.
# ENVIRONMENT (== PRODUCTION_ENVIRONMENT) in every query it builds.
# ---------------------------------------------------------------------
class AnalyticsService:
    """Not yet DB-backed (Phase 6B.1). See module docstring."""

    ENVIRONMENT = PRODUCTION_ENVIRONMENT

    def get_overview(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> OverviewMetrics:
        validate_platform(platform)
        raise NotImplementedError("modules.activity_events.analytics_service (Phase 6B.2)")

    def get_engagement(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> EngagementMetrics:
        validate_platform(platform)
        raise NotImplementedError("modules.activity_events.analytics_service (Phase 6B.2)")

    def get_asknow_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> AskNowMetrics:
        validate_platform(platform)
        raise NotImplementedError("modules.activity_events.analytics_service (Phase 6B.2)")

    def get_report_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> ReportMetrics:
        validate_platform(platform)
        raise NotImplementedError("modules.activity_events.analytics_service (Phase 6B.2)")

    def get_subscription_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> SubscriptionMetrics:
        validate_platform(platform)
        raise NotImplementedError("modules.activity_events.analytics_service (Phase 6B.2)")

    def get_notification_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> NotificationMetrics:
        validate_platform(platform)
        raise NotImplementedError("modules.activity_events.analytics_service (Phase 6B.2)")
