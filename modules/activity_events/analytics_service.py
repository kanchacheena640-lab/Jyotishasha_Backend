# modules/activity_events/analytics_service.py

"""
Phase 6B.3 -- the real AnalyticsService: metric semantics + funnel/
report-product composition over modules/activity_events/
analytics_repository.py's pure query primitives, producing the frozen
modules/activity_events/analytics_models.py result shapes.

Responsibility split (Phase 6A/6B.2, preserved exactly):
  - ActivityEventsAnalyticsRepository (analytics_repository.py) owns
    SQL mechanics ONLY -- count/distinct-count/group/filter. It knows
    nothing about "DAU," "Ask Now delivery rate," or "the purchased
    report journey."
  - AnalyticsService (this file) owns metric MEANING: which repository
    calls compose into which frozen DTO field, rate calculation
    (analytics_contract.compute_rate), DAU/WAU/MAU window derivation
    (analytics_contract.active_user_window), attaching the frozen
    AnalyticsLimitation instances, and -- critically -- the mandatory
    environment="production" fix on every single repository call. This
    file contains NO SQLAlchemy, no db.session, no ActivityEvent
    reference of any kind; every fact it reports comes from calling
    self._repository's own methods.

This class used to be a stub living in analytics_contract.py (Phase
6B.1, every method body `raise NotImplementedError`) -- moved here
rather than edited in place once real, matching this codebase's own
established modules/payments/metrics_models.py (shape/constants) vs.
metrics_service.py (business logic) split. See analytics_contract.py's
own note near its AnalyticsService-removal point for the full
reasoning.

No public method accepts an `environment` parameter -- there is
structurally no argument through which a caller could override the
production-only filter (same guarantee the Phase 6B.1 stub already
froze; this real implementation upholds it, never weakens it).
`ENVIRONMENT = PRODUCTION_ENVIRONMENT` is the one constant every
repository call below hard-codes its own `environment=` argument
against.
"""

from __future__ import annotations

from typing import Optional

from modules.activity_events.analytics_contract import (
    AI_REPORT_ENTITY_TYPE,
    ASKNOW_ATTEMPT_LINKAGE_LIMITATION,
    DAU_WINDOW,
    MAU_WINDOW,
    PRODUCTION_ENVIRONMENT,
    PURCHASED_REPORT_ENTITY_TYPE,
    PURCHASED_REPORT_ENTRY_CTA_ID,
    REPORT_PURCHASE_PAYMENT_PURPOSE,
    SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION,
    WAU_WINDOW,
    active_user_window,
    compute_rate,
    validate_platform,
)
from modules.activity_events.analytics_models import (
    AiReportEngineMetrics,
    AnalyticsWindow,
    AskNowMetrics,
    EngagementMetrics,
    NotificationMetrics,
    OverviewMetrics,
    PurchasedReportMetrics,
    ReportMetrics,
    SubscriptionMetrics,
)
from modules.activity_events.analytics_repository import ActivityEventsAnalyticsRepository


class AnalyticsService:
    """Real, DB-backed (via ActivityEventsAnalyticsRepository) analytics
    composition layer. See module docstring for the repository/service
    responsibility split this class preserves."""

    ENVIRONMENT = PRODUCTION_ENVIRONMENT

    def __init__(self, repository: Optional[ActivityEventsAnalyticsRepository] = None) -> None:
        # Constructor injection -- a test supplies a fake/spy
        # repository here; production code gets the real one for free.
        self._repository = repository if repository is not None else ActivityEventsAnalyticsRepository()

    # -------------------------------------------------------------
    # Overview
    # -------------------------------------------------------------
    def get_overview(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> OverviewMetrics:
        validate_platform(platform)
        common = dict(window=window, environment=self.ENVIRONMENT, platform=platform)

        total_events = self._repository.count_events(**common)
        unique_users = self._repository.count_distinct_users(**common)
        app_sessions = self._repository.count_distinct_sessions(**common)
        new_signups = self._repository.count_events(event_names="signup_completed", **common)
        interactive_logins = self._repository.count_events(event_names="login_completed", **common)

        # DAU/WAU/MAU -- each its own trailing window anchored at THIS
        # request's window.end (analytics_contract.active_user_window),
        # never a second, independently-chosen anchor.
        dau = self._repository.count_distinct_users(
            window=active_user_window(window, DAU_WINDOW), environment=self.ENVIRONMENT, platform=platform,
        )
        wau = self._repository.count_distinct_users(
            window=active_user_window(window, WAU_WINDOW), environment=self.ENVIRONMENT, platform=platform,
        )
        mau = self._repository.count_distinct_users(
            window=active_user_window(window, MAU_WINDOW), environment=self.ENVIRONMENT, platform=platform,
        )

        return OverviewMetrics(
            total_events=total_events,
            unique_users=unique_users,
            app_sessions=app_sessions,
            new_signups=new_signups,
            interactive_logins=interactive_logins,
            dau=dau, wau=wau, mau=mau,
        )

    # -------------------------------------------------------------
    # Engagement -- cta_click + feature_used. No CTR field exists on
    # EngagementMetrics at all (Phase 6A/6B.1) -- there is nothing to
    # populate or omit; the frozen DTO's own shape already is the
    # "unavailable" signal, so no AnalyticsLimitation is attached here.
    # -------------------------------------------------------------
    def get_engagement(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> EngagementMetrics:
        validate_platform(platform)
        common = dict(window=window, environment=self.ENVIRONMENT, platform=platform)

        cta_clicks_total = self._repository.count_events(event_names="cta_click", **common)
        cta_unique_users = self._repository.count_distinct_users(event_names="cta_click", **common)
        cta_clicks_by_cta_id = self._repository.group_by_property(
            event_names="cta_click", dimension="cta_id", **common,
        )
        cta_clicks_by_screen_name = self._repository.group_by_property(
            event_names="cta_click", dimension="screen_name", **common,
        )

        feature_usage_total = self._repository.count_events(event_names="feature_used", **common)
        feature_unique_users = self._repository.count_distinct_users(event_names="feature_used", **common)
        feature_usage_by_feature_name = self._repository.group_by_property(
            event_names="feature_used", dimension="feature_name", **common,
        )

        return EngagementMetrics(
            cta_clicks_total=cta_clicks_total,
            cta_unique_users=cta_unique_users,
            cta_clicks_by_cta_id=cta_clicks_by_cta_id,
            cta_clicks_by_screen_name=cta_clicks_by_screen_name,
            feature_usage_total=feature_usage_total,
            feature_unique_users=feature_unique_users,
            feature_usage_by_feature_name=feature_usage_by_feature_name,
        )

    # -------------------------------------------------------------
    # Ask Now -- aggregate stage counts + rates only. No question-to-
    # answer pairing is ever attempted (Phase 6A: no shared correlation
    # key exists) -- ASKNOW_ATTEMPT_LINKAGE_LIMITATION documents this
    # on every result.
    # -------------------------------------------------------------
    def get_asknow_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> AskNowMetrics:
        validate_platform(platform)
        common = dict(window=window, environment=self.ENVIRONMENT, platform=platform)

        entry_views = self._repository.count_events(event_names="asknow_entry_viewed", **common)
        questions_submitted = self._repository.count_events(event_names="asknow_question_submitted", **common)
        answers_delivered = self._repository.count_events(event_names="asknow_answer_delivered", **common)
        answers_failed = self._repository.count_events(event_names="asknow_answer_failed", **common)

        return AskNowMetrics(
            entry_views=entry_views,
            questions_submitted=questions_submitted,
            answers_delivered=answers_delivered,
            answers_failed=answers_failed,
            delivery_rate=compute_rate(answers_delivered, questions_submitted),
            failure_rate=compute_rate(answers_failed, questions_submitted),
            limitations=[ASKNOW_ATTEMPT_LINKAGE_LIMITATION],
        )

    # -------------------------------------------------------------
    # Reports -- TWO independent sections, never merged (Phase 6A/6B.1/
    # 6B.2's frozen "AI Report Engine vs. purchased report" split).
    # entity_type/purpose/cta_id filters below are the exact, verified-
    # against-real-producers facts Phase 6B.2 established -- nothing
    # here is guessed.
    # -------------------------------------------------------------
    def get_report_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> ReportMetrics:
        validate_platform(platform)
        common = dict(window=window, environment=self.ENVIRONMENT, platform=platform)

        # A. AI Report Engine -- subscription-gated, no payment stage.
        ai_discovery_views = self._repository.count_events(
            event_names="report_discovery_viewed", **common,
        )
        ai_discovery_by_report_type = self._repository.group_by_property(
            event_names="report_discovery_viewed", dimension="report_type", **common,
        )
        ai_generation_started = self._repository.count_events(
            event_names="report_generation_started", entity_type=AI_REPORT_ENTITY_TYPE, **common,
        )
        ai_generation_completed = self._repository.count_events(
            event_names="report_generation_completed", entity_type=AI_REPORT_ENTITY_TYPE, **common,
        )
        ai_generation_failed = self._repository.count_events(
            event_names="report_generation_failed", entity_type=AI_REPORT_ENTITY_TYPE, **common,
        )

        ai_report_engine = AiReportEngineMetrics(
            discovery_views=ai_discovery_views,
            discovery_by_report_type=ai_discovery_by_report_type,
            generation_started=ai_generation_started,
            generation_completed=ai_generation_completed,
            generation_failed=ai_generation_failed,
            completion_rate=compute_rate(ai_generation_completed, ai_generation_started),
        )

        # B. Purchased report -- Order-based, one-off Razorpay purchase.
        # Entry signal is a cta_click on the ONE known CTA id, never
        # labeled "discovery" (this product has no report_discovery_
        # viewed of its own).
        purchase_entry_clicks = self._repository.count_events(
            event_names="cta_click",
            property_filters={"cta_id": PURCHASED_REPORT_ENTRY_CTA_ID},
            **common,
        )
        payment_initiated = self._repository.count_events(
            event_names="payment_initiated",
            property_filters={"purpose": REPORT_PURCHASE_PAYMENT_PURPOSE},
            **common,
        )
        payment_verified = self._repository.count_events(
            event_names="payment_verified",
            property_filters={"purpose": REPORT_PURCHASE_PAYMENT_PURPOSE},
            **common,
        )
        payment_failed = self._repository.count_events(
            event_names="payment_failed",
            property_filters={"purpose": REPORT_PURCHASE_PAYMENT_PURPOSE},
            **common,
        )
        purchased_generation_started = self._repository.count_events(
            event_names="report_generation_started", entity_type=PURCHASED_REPORT_ENTITY_TYPE, **common,
        )
        purchased_generation_completed = self._repository.count_events(
            event_names="report_generation_completed", entity_type=PURCHASED_REPORT_ENTITY_TYPE, **common,
        )
        purchased_generation_failed = self._repository.count_events(
            event_names="report_generation_failed", entity_type=PURCHASED_REPORT_ENTITY_TYPE, **common,
        )

        purchased_report = PurchasedReportMetrics(
            purchase_entry_clicks=purchase_entry_clicks,
            payment_initiated=payment_initiated,
            payment_verified=payment_verified,
            payment_failed=payment_failed,
            generation_started=purchased_generation_started,
            generation_completed=purchased_generation_completed,
            generation_failed=purchased_generation_failed,
            verification_rate=compute_rate(payment_verified, payment_initiated),
            completion_rate=compute_rate(purchased_generation_completed, purchased_generation_started),
        )

        return ReportMetrics(ai_report_engine=ai_report_engine, purchased_report=purchased_report)

    # -------------------------------------------------------------
    # Subscriptions
    # -------------------------------------------------------------
    def get_subscription_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> SubscriptionMetrics:
        validate_platform(platform)
        common = dict(window=window, environment=self.ENVIRONMENT, platform=platform)

        discovery_views = self._repository.count_events(
            event_names="subscription_discovery_viewed", **common,
        )
        discovery_by_placement = self._repository.group_by_property(
            event_names="subscription_discovery_viewed", dimension="placement", **common,
        )

        # subscription_pending_created is deliberately never queried --
        # that business flow is not implemented (Phase 4/6A finding).
        return SubscriptionMetrics(
            discovery_views=discovery_views,
            discovery_by_placement=discovery_by_placement,
            trial_started=self._repository.count_events(event_names="subscription_trial_started", **common),
            trial_expired=self._repository.count_events(event_names="subscription_trial_expired", **common),
            subscription_started=self._repository.count_events(event_names="subscription_started", **common),
            subscription_renewed=self._repository.count_events(event_names="subscription_renewed", **common),
            subscription_grace_entered=self._repository.count_events(event_names="subscription_grace_entered", **common),
            subscription_expired=self._repository.count_events(event_names="subscription_expired", **common),
            subscription_cancelled=self._repository.count_events(event_names="subscription_cancelled", **common),
            subscription_refunded=self._repository.count_events(event_names="subscription_refunded", **common),
            limitations=[SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION],
        )

    # -------------------------------------------------------------
    # Notifications -- open_rate denominator is `sent`, NEVER `created`
    # (Phase 6A: created must not be treated as delivered).
    # -------------------------------------------------------------
    def get_notification_metrics(
        self, window: AnalyticsWindow, platform: Optional[str] = None,
    ) -> NotificationMetrics:
        validate_platform(platform)
        common = dict(window=window, environment=self.ENVIRONMENT, platform=platform)

        created = self._repository.count_events(event_names="notification_created", **common)
        sent = self._repository.count_events(event_names="notification_sent", **common)
        opened = self._repository.count_events(event_names="notification_opened", **common)
        unique_users_opened = self._repository.count_distinct_users(event_names="notification_opened", **common)

        return NotificationMetrics(
            created=created,
            sent=sent,
            opened=opened,
            unique_users_opened=unique_users_opened,
            open_rate=compute_rate(opened, sent),
        )
