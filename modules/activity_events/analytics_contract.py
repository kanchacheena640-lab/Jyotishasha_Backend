# modules/activity_events/analytics_contract.py

"""
Phase 6B.1 (constants/validation/rate rules) + Phase 6B.3 note (service
moved out, see below) -- the frozen analytics query CONTRACT: constants
and pure validation/rate-calculation helpers that modules/
activity_events/analytics_service.py's real AnalyticsService composes
against.

Nothing in this file touches ActivityEvent, db.session, or SQL of any
kind. Originally (Phase 6B.1) this file also held AnalyticsService
itself as a deliberately-unimplemented stub (every method body `raise
NotImplementedError`) so the metric contract could be frozen and tested
before any repository/service code existed. Phase 6B.3 replaced that
stub with a real implementation, moved to its own file -- see the note
near the bottom of this file for exactly why it moved rather than being
edited in place.

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
    enforced by AnalyticsService (analytics_service.py) never accepting
    an `environment` parameter anywhere on any public method -- there
    is no argument to forget to pass or to accidentally override with.
    PRODUCTION_ENVIRONMENT (this file) is the one unambiguous constant
    that service hard-codes its repository calls' `environment=` against.
  - Revenue/accounting truth is never derived from activity_events --
    see modules/payments/metrics_service.py's own existing boundary
    for the authoritative business-table equivalent; this module
    defines no revenue/amount/currency field anywhere.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from modules.activity_events.analytics_models import AnalyticsLimitation, AnalyticsWindow

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

# The one property value that identifies a payment_* row as belonging
# to the purchased-report journey (modules/payments/payment_models.py::
# PaymentPurpose.REPORT_PURCHASE, confirmed distinct from .SUBSCRIPTION
# and the Ask Now chat-pack purpose) -- verified against the real
# producer during Phase 6B.2, not guessed.
REPORT_PURCHASE_PAYMENT_PURPOSE = "REPORT_PURCHASE"

# entity_type values (Phase 6B.2, verified against the real producers)
# that separate the two report products' report_generation_* rows --
# modules/ai_report_engine/lifecycle_manager.py sets AI_REPORT_ENTITY_
# TYPE; tasks.py AND modules/love/love_premium_task.py (an Order-based
# pipeline despite its "love" name -- confirmed by its own docstring
# and its `from models import Order` import, NOT part of the AI Report
# Engine) both set PURCHASED_REPORT_ENTITY_TYPE.
AI_REPORT_ENTITY_TYPE = "ai_report"
PURCHASED_REPORT_ENTITY_TYPE = "order"

# ---------------------------------------------------------------------
# Phase 6B.3 note: the AnalyticsService surface that used to be
# stubbed HERE (six methods, every body `raise NotImplementedError`)
# has been replaced by a real, DB-backed implementation in
# modules/activity_events/analytics_service.py -- moved rather than
# edited in place, matching this codebase's own established
# modules/payments/metrics_models.py (shape/constants) vs.
# metrics_service.py (business logic + repository composition) split.
# This file no longer defines AnalyticsService at all -- there is
# exactly one implementation of it, not a stub left beside a real one.
# Every constant/helper above (PRODUCTION_ENVIRONMENT, ALLOWED_
# PLATFORMS, validate_platform, compute_rate, DAU_WINDOW/WAU_WINDOW/
# MAU_WINDOW, active_user_window, the three named AnalyticsLimitation
# instances, PURCHASED_REPORT_ENTRY_CTA_ID) is exactly what
# analytics_service.py imports and composes against -- nothing here
# was redesigned, only the now-real service moved out.
# ---------------------------------------------------------------------
