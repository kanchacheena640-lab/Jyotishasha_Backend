# modules/activity_events/analytics_models.py

"""
Phase 6B.1 -- pure data shapes for the future Admin analytics query
layer. Same role as modules/payments/metrics_models.py: shape only, no
computation, no database access. See modules/activity_events/
analytics_contract.py for the validation rules, constants, and the
(deliberately not-yet-implemented) service surface these shapes feed.

Every dataclass here is a RESULT shape a future modules/activity_events/
analytics_service.py (Phase 6B.2/6B.3) will populate from real
PostgreSQL aggregation -- nothing in this file queries ActivityEvent.

Frozen Phase 6A decisions this file structurally encodes (see that
phase's own audit report for the full reasoning, not repeated here):

  - AnalyticsWindow self-validates on construction (timezone-aware,
    start < end) -- so an invalid window can never silently reach a
    metric method; the check lives with the shape itself, not merely a
    helper someone could forget to call.
  - No metric dataclass below carries a naive ratio field that could
    mislead (e.g. no `signup_conversion` on OverviewMetrics, no exact
    per-attempt/per-visit linkage field on AskNowMetrics/
    SubscriptionMetrics, no `ctr` on EngagementMetrics, no revenue
    field anywhere). Where a rate IS legitimately computable, it is
    Optional[float] and MUST be None (never 0.0) when its denominator
    is zero -- see analytics_contract.compute_rate().
  - ReportMetrics has exactly two, separately-named sections --
    ai_report_engine and purchased_report -- never merged into one
    funnel (Phase 6A section 18/M: these are two different products).
  - PurchasedReportMetrics' entry signal is named purchase_entry_
    clicks, never discovery_views -- it is a cta_click on a specific
    CTA id, not the report_discovery_viewed event.
  - SubscriptionMetrics has no subscription_pending_created field --
    that business flow is not implemented (Phase 4/6A finding); a
    dashboard must never display a metric for data that cannot exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


class InvalidAnalyticsWindow(ValueError):
    """Raised by AnalyticsWindow's own construction -- a naive
    datetime, start == end, or start > end is a caller bug, not a
    condition to silently reinterpret (Phase 6A section 8)."""


@dataclass(frozen=True)
class AnalyticsWindow:
    """A validated [start, end) query window. Both bounds MUST be
    timezone-aware (activity_events.occurred_at is `DateTime(timezone=
    True)` -- see modules/models_activity_events.py); comparing a naive
    datetime against it would silently do the wrong thing in Python
    rather than raise, which is exactly what this constructor exists to
    prevent. `occurred_at` is the field every Phase 6 metric is defined
    against -- `recorded_at` is server-generated ingestion metadata
    only (Phase 6A section I), never a user-facing filter basis."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.start.tzinfo.utcoffset(self.start) is None:
            raise InvalidAnalyticsWindow("start must be timezone-aware")
        if self.end.tzinfo is None or self.end.tzinfo.utcoffset(self.end) is None:
            raise InvalidAnalyticsWindow("end must be timezone-aware")
        if self.start >= self.end:
            raise InvalidAnalyticsWindow(
                f"start ({self.start.isoformat()}) must be strictly before "
                f"end ({self.end.isoformat()})"
            )


@dataclass
class AnalyticsLimitation:
    """Explains, for one metric, exactly why it is absent/None rather
    than a number -- same idiom as modules/payments/metrics_models.py's
    MetricsLimitation, kept as a separate, activity_events-scoped type
    (not imported from modules.payments) so this module stays readable
    on its own, matching this codebase's existing convention of NOT
    cross-importing sibling metrics domains (see modules/activity_events/
    ingestion_policy.py's own docstring for the identical reasoning
    applied to a different pair of modules)."""

    metric: str
    reason: str


# ---------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------
@dataclass
class OverviewMetrics:
    """total_events: row count in the window (production environment
    only -- see analytics_contract.py). unique_users: COUNT(DISTINCT
    firebase_uid) among non-null firebase_uid rows -- firebase_uid, NOT
    profile_id, is the canonical unique-user key (Phase 6A section F:
    profile_id may be legitimately NULL before AppUser/profile
    creation). app_sessions: COUNT(DISTINCT session_id) among non-null
    session_id rows -- an app/process session (Flutter's
    AnalyticsSessionContext, one id per process lifetime), explicitly
    NOT a 30-minute web-analytics session; the field is named
    `app_sessions`, never bare `sessions`, so no caller can confuse the
    two. new_signups: raw signup_completed count. interactive_logins:
    raw login_completed count. Deliberately NO ratio field between
    new_signups and interactive_logins -- a returning user legitimately
    produces login_completed with no signup_completed, so a naive
    global conversion percentage would be misleading (Phase 6A section
    K); a real first-login-cohort conversion, if ever built, is its own
    explicit query, not a division of these two counts."""

    total_events: int
    unique_users: int
    app_sessions: int
    new_signups: int
    interactive_logins: int
    dau: int
    wau: int
    mau: int


# ---------------------------------------------------------------------
# Engagement -- cta_click + feature_used
# ---------------------------------------------------------------------
@dataclass
class EngagementMetrics:
    """No CTR/ctr field anywhere on this shape -- no impression event
    exists in the canonical registry (Phase 6A section P), so a
    click-through rate cannot be computed and must never be
    approximated as 0. feature_usage_by_feature_name only ever contains
    the feature_name values a producer actually emits (currently 7,
    Phase 5 finding) -- a feature absent from this dict means
    "not instrumented," never "used zero times"; the service/API layer
    must not conflate the two."""

    cta_clicks_total: int
    cta_unique_users: int
    cta_clicks_by_cta_id: Dict[str, int]
    cta_clicks_by_screen_name: Dict[str, int]
    feature_usage_total: int
    feature_unique_users: int
    feature_usage_by_feature_name: Dict[str, int]


# ---------------------------------------------------------------------
# Ask Now
# ---------------------------------------------------------------------
@dataclass
class AskNowMetrics:
    """Aggregate stage counts only. delivery_rate/failure_rate are
    answers_delivered/answers_failed divided by questions_submitted --
    None (never 0.0) when questions_submitted is 0 (analytics_contract.
    compute_rate()). No question-to-answer PAIR field exists here and
    none should ever be added under this contract: asknow_question_
    submitted/asknow_answer_delivered/asknow_answer_failed share no
    correlation_id/entity_id (Phase 6A section L) -- exact per-attempt
    linkage is not reconstructable from current data, only aggregate
    counts and rates are trustworthy. `limitations` carries that fact
    explicitly (see analytics_contract.ASKNOW_ATTEMPT_LINKAGE_
    LIMITATION) rather than leaving it undocumented."""

    entry_views: int
    questions_submitted: int
    answers_delivered: int
    answers_failed: int
    delivery_rate: Optional[float]
    failure_rate: Optional[float]
    limitations: List[AnalyticsLimitation] = field(default_factory=list)


# ---------------------------------------------------------------------
# Reports -- TWO separate products, never merged (Phase 6A section 18/M)
# ---------------------------------------------------------------------
@dataclass
class AiReportEngineMetrics:
    """The subscription-gated AI Report Engine (love/career/finance/
    health/family, browsed from explore_page.dart). No payment stage
    belongs in this section -- access is via subscription, not a
    per-report purchase."""

    discovery_views: int
    discovery_by_report_type: Dict[str, int]
    generation_started: int
    generation_completed: int
    generation_failed: int
    completion_rate: Optional[float]  # generation_completed / generation_started


@dataclass
class PurchasedReportMetrics:
    """The separate, Order-based one-off purchased-report journey.
    `purchase_entry_clicks` is a cta_click count for the ONE cta_id
    that identifies this journey's entry point (analytics_contract.
    PURCHASED_REPORT_ENTRY_CTA_ID) -- deliberately NOT named
    `discovery_views`: this product has no report_discovery_viewed
    signal of its own (Phase 6A section 18), and calling a generic CTA
    click "discovery" would misrepresent what was actually measured."""

    purchase_entry_clicks: int
    payment_initiated: int
    payment_verified: int
    payment_failed: int
    generation_started: int
    generation_completed: int
    generation_failed: int
    verification_rate: Optional[float]  # payment_verified / payment_initiated
    completion_rate: Optional[float]    # generation_completed / generation_started


@dataclass
class ReportMetrics:
    """Exactly two named sections, never one merged funnel. See
    AiReportEngineMetrics/PurchasedReportMetrics for why."""

    ai_report_engine: AiReportEngineMetrics
    purchased_report: PurchasedReportMetrics


# ---------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------
@dataclass
class SubscriptionMetrics:
    """No subscription_pending_created field: that business flow is not
    implemented anywhere in the current backend (Phase 4/6A finding,
    re-verified) -- a dashboard must never display a metric for data
    that structurally cannot exist yet. discovery_by_placement uses the
    same 6-value closed vocabulary Phase 5C froze (account, explore,
    alerts_dashboard, premium_locked_content, premium_report_reader,
    direct_route). `limitations` documents that placement-to-conversion
    is aggregate-only: subscription_discovery_viewed (Flutter, carries
    session_id) and the subscription lifecycle events (backend,
    session_id=None) share no correlation key, so an exact per-visit
    attribution is not reconstructable (Phase 6A section N)."""

    discovery_views: int
    discovery_by_placement: Dict[str, int]
    trial_started: int
    trial_expired: int
    subscription_started: int
    subscription_renewed: int
    subscription_grace_entered: int
    subscription_expired: int
    subscription_cancelled: int
    subscription_refunded: int
    limitations: List[AnalyticsLimitation] = field(default_factory=list)


# ---------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------
@dataclass
class NotificationMetrics:
    """open_rate = opened / sent -- sent, NEVER created, is the
    denominator (Phase 6A section O: notification_created must not be
    treated as delivered). None (never 0.0) when sent is 0."""

    created: int
    sent: int
    opened: int
    unique_users_opened: int
    open_rate: Optional[float]
