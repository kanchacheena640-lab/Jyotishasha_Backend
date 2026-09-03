# modules/activity_events/website_analytics_service.py

"""
Task 11 -- the Website Analytics QUERY/SERVICE layer: converts the
frozen contracts from Task 9 (website_metrics_contract.py), Task 9A
(page_path), Task 10 (marketing_attribution_contract.py), and Task 10A
(financial conversion campaign attribution) into executable, tested
PostgreSQL aggregation. NO HTTP/admin endpoints -- that is Task 12.

ARCHITECTURE DECISION (Task 11 S1, recorded here so it is never
silently re-litigated): this service is a NEW, dedicated module rather
than an extension of the existing modules/activity_events/
analytics_service.py, because that file's own response shapes
(OverviewMetrics, EngagementMetrics, AskNowMetrics, ...) are Phase
6B's own cross-platform ADMIN product-analytics contract -- a
completely different shape family from website_metrics_contract.py's/
marketing_attribution_contract.py's metric_id-keyed catalogs this task
must preserve without drift (Task 11 S5). The REPOSITORY layer,
however, IS extended in place (modules/activity_events/
analytics_repository.py gained page_path/cta_location to its property
allowlist and 3 new campaign-attribution query methods) rather than
duplicated -- that file is genuinely generic "query mechanics over
activity_events," already shared across app/website/admin call sites,
not app-or-admin-specific, so a second parallel repository would be
exactly the "duplicate generic abstraction" Task 11 S1 warns against.

Responsibility split (identical discipline to analytics_service.py):
  - ActivityEventsAnalyticsRepository owns SQL mechanics ONLY.
  - WebsiteAnalyticsService (this file) owns metric MEANING: which
    frozen contract entry a metric_id maps to, whether its own
    quality_status permits execution at all, which repository call(s)
    compose into which website_analytics_models.py result shape, and
    the mandatory environment=PRODUCTION_ENVIRONMENT fix on every
    single repository call (same guarantee analytics_service.py
    already freezes -- no public method here accepts an environment
    override).

SOURCE-OF-TRUTH RULE (Task 11 S2/S3, enforced structurally, not by
convention): get_metric() checks the metric's OWN frozen quality_status
BEFORE doing anything else. QUALITY_BLOCKED and QUALITY_GA4_EXTERNAL
metrics return UnavailableMetric immediately -- no repository call is
ever issued for them. There is no code path in this file that can
execute a query for a GA4-owned or BLOCKED metric; this is not merely
documented, it is the only branch that ever calls self._repository.

Only metric_ids Task 11 S4 actually asks for are implemented (a curated
subset of the ~55 combined catalog entries) -- see _DISPATCH at the
bottom of this file for the exact, closed list. Calling get_metric()
with a READY/PARTIAL metric_id outside that list raises NotImplementedError
naming the gap explicitly, rather than silently returning nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from modules.activity_events.analytics_contract import (
    PRODUCTION_ENVIRONMENT,
    compute_rate,
)
from modules.activity_events.analytics_repository import (
    ActivityEventsAnalyticsRepository,
    UnsupportedAnalyticsDimension,
)
from modules.activity_events.website_metrics_contract import (
    QUALITY_BLOCKED,
    QUALITY_GA4_EXTERNAL,
    PURCHASED_REPORT_ENTRY_CTA_ID,
    REPORT_PURCHASE_PAYMENT_PURPOSE,
    STANDARD_DASHBOARD_PERIODS,
    get_metric as get_website_metric,
)
from modules.activity_events.marketing_attribution_contract import (
    get_marketing_attribution_metric,
)
from modules.activity_events.website_analytics_models import (
    AttributionCoverageResult,
    GroupedMetricResult,
    GroupedMetricRow,
    MetricValue,
    PageAttributionResult,
    PageAttributionRow,
    UnavailableMetric,
)


class UnsupportedWebsiteMetric(ValueError):
    """Raised by get_metric() for a metric_id that exists in neither
    frozen catalog at all -- a genuine caller mistake, never silently
    treated as unavailable (that would conflate 'does not exist' with
    'exists but is BLOCKED/GA4_EXTERNAL')."""


class WebsiteMetricNotImplemented(NotImplementedError):
    """Raised for a metric_id whose frozen quality_status DOES permit
    execution (READY/PARTIAL) but which Task 11 has not (yet) wired a
    repository query for -- an honest gap, never silently returned as
    zero or omitted from a response."""


# ---------------------------------------------------------------------
# Frozen event populations (Task 11 S6) -- read directly from the two
# contract catalogs' own `event_population`/`counting_rule` text at
# import time is not practical (those are prose, not machine-readable),
# so the exact canonical event names are reproduced here, verified
# against that prose and against modules/activity_events/event_schemas.py
# at the time of writing -- never guessed.
# ---------------------------------------------------------------------
WEBSITE_PLATFORM = "website"
ANDROID_PLATFORM = "app_android"

# Task 10's own frozen "Product Actions" population
# (marketing_attribution_contract.product_actions_total's own
# event_population text) -- NOT "every activity_events row."
PRODUCT_ACTION_EVENT_NAMES: Tuple[str, ...] = (
    "cta_click", "feature_used", "app_download_intent", "report_discovery_viewed",
)

# Task 11 S9/S13 -- the ONLY external dimension names this service
# accepts for campaign grouping, mapped to their actual campaign_context
# storage key. A CLOSED internal mapping (Task 11 S33) -- never
# interpolates a caller-supplied dimension string into SQL; an
# unrecognized name raises before any repository call.
CAMPAIGN_DIMENSION_MAP: Dict[str, str] = {
    "source": "utm_source",
    "medium": "utm_medium",
    "campaign": "utm_campaign",
}

DEFAULT_GROUP_LIMIT = ActivityEventsAnalyticsRepository.DEFAULT_GROUP_LIMIT
MAX_GROUP_LIMIT = ActivityEventsAnalyticsRepository.MAX_GROUP_LIMIT


def _campaign_field(dimension_name: str) -> str:
    if dimension_name not in CAMPAIGN_DIMENSION_MAP:
        raise UnsupportedAnalyticsDimension(
            f"Unsupported campaign dimension {dimension_name!r}; must be one of "
            f"{sorted(CAMPAIGN_DIMENSION_MAP)}"
        )
    return CAMPAIGN_DIMENSION_MAP[dimension_name]


def _lookup_definition(metric_id: str):
    """Looks metric_id up in website_metrics_contract.py first, then
    marketing_attribution_contract.py -- the two catalogs' metric_id
    vocabularies are confirmed disjoint (Task 11's own audit; also
    guarded by a dedicated regression test). Raises
    UnsupportedWebsiteMetric if found in neither."""
    try:
        return get_website_metric(metric_id)
    except KeyError:
        pass
    try:
        return get_marketing_attribution_metric(metric_id)
    except KeyError:
        pass
    raise UnsupportedWebsiteMetric(
        f"{metric_id!r} is not a known metric_id in either website_metrics_contract.py "
        f"or marketing_attribution_contract.py."
    )


# ---------------------------------------------------------------------
# Time window (Task 11 S7) -- the ONE place "now" is ever read. Every
# repository call below receives an already-constructed AnalyticsWindow
# -- no repository method calls datetime.now() itself.
# ---------------------------------------------------------------------
def window_for_period(
    period: str,
    *,
    custom_start: Optional[datetime] = None,
    custom_end: Optional[datetime] = None,
    now: Optional[datetime] = None,
):
    """Builds an AnalyticsWindow for one of STANDARD_DASHBOARD_PERIODS
    ("7d"/"30d"/"90d"/"custom"). For "custom", both custom_start and
    custom_end are required (timezone-aware -- AnalyticsWindow's own
    constructor enforces this). For a standard period, the window ends
    at `now` (defaults to datetime.now(timezone.utc) -- injectable so
    tests never depend on the real wall clock) and starts exactly N
    days earlier -- UTC storage/query boundary throughout (Task 11 S7);
    no IST conversion happens here or anywhere in this file (day-bucket/
    trend semantics are explicitly OUT of this task's scope -- see
    module docstring and Task 11 S8: no existing timezone-safe day-
    bucketing convention was found to extend safely, so Task 11 stays
    aggregate-only, one total per window, never a daily trend array)."""
    from modules.activity_events.analytics_models import AnalyticsWindow

    if period not in STANDARD_DASHBOARD_PERIODS:
        raise ValueError(
            f"Unknown period {period!r}; must be one of {STANDARD_DASHBOARD_PERIODS}"
        )
    if period == "custom":
        if custom_start is None or custom_end is None:
            raise ValueError("period='custom' requires both custom_start and custom_end")
        return AnalyticsWindow(start=custom_start, end=custom_end)

    days = {"7d": 7, "30d": 30, "90d": 90}[period]
    end = now if now is not None else datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return AnalyticsWindow(start=start, end=end)


class WebsiteAnalyticsService:
    """Real, DB-backed (via ActivityEventsAnalyticsRepository) website
    analytics composition layer. See module docstring for the
    repository/service responsibility split and the source-of-truth
    rule this class enforces structurally in get_metric()."""

    ENVIRONMENT = PRODUCTION_ENVIRONMENT

    def __init__(self, repository: Optional[ActivityEventsAnalyticsRepository] = None) -> None:
        self._repository = repository if repository is not None else ActivityEventsAnalyticsRepository()

    # -------------------------------------------------------------
    # The one, contract-driven entry point.
    # -------------------------------------------------------------
    def get_metric(self, metric_id: str, window, **kwargs):
        """Dispatches to this task's own curated implementation first
        (_DISPATCH -- this also covers the handful of Task 11-only
        aliases, like report_purchase_intents_by_page, that scope an
        already-frozen READY metric rather than mint a new metric_id --
        see that alias's own handler docstring). If metric_id is not in
        _DISPATCH, looks up its frozen definition: BLOCKED/GA4_EXTERNAL
        returns UnavailableMetric immediately (NO repository call is
        EVER issued for those two statuses -- this is the one and only
        branch of this method that can reach self._repository, and it
        is never reached for them). A READY/PARTIAL metric_id outside
        _DISPATCH raises WebsiteMetricNotImplemented -- an honest gap,
        never a silent nothing. An unrecognized metric_id raises
        UnsupportedWebsiteMetric."""
        handler_name = _DISPATCH.get(metric_id)
        if handler_name is not None:
            return getattr(self, handler_name)(window, **kwargs)

        definition = _lookup_definition(metric_id)  # raises UnsupportedWebsiteMetric if truly unknown

        if definition.quality_status in (QUALITY_BLOCKED, QUALITY_GA4_EXTERNAL):
            reason = "; ".join(definition.limitations) if definition.limitations else definition.definition
            return UnavailableMetric(
                metric_id=definition.metric_id,
                quality_status=definition.quality_status,
                value=None,
                reason=reason,
            )

        raise WebsiteMetricNotImplemented(
            f"{metric_id!r} is {definition.quality_status} in its frozen contract "
            f"but Task 11 has not implemented a repository query for it yet."
        )

    # =================================================================
    # Scalar counts
    # =================================================================
    def cta_clicks_total(self, window) -> MetricValue:
        return self._simple_count("cta_clicks_total", window, event_names="cta_click", platform=WEBSITE_PLATFORM)

    def tool_completions_all(self, window) -> MetricValue:
        return self._simple_count("tool_completions_all", window, event_names="feature_used", platform=WEBSITE_PLATFORM)

    def app_download_intents_total(self, window) -> MetricValue:
        return self._simple_count("app_download_intents_total", window, event_names="app_download_intent", platform=WEBSITE_PLATFORM)

    def report_discovery_views(self, window) -> MetricValue:
        return self._simple_count("report_discovery_views", window, event_names="report_discovery_viewed", platform=WEBSITE_PLATFORM)

    def report_purchase_intent(self, window) -> MetricValue:
        return self._simple_count(
            "report_purchase_intent", window, event_names="cta_click", platform=WEBSITE_PLATFORM,
            property_filters={"cta_id": PURCHASED_REPORT_ENTRY_CTA_ID},
        )

    def report_payment_verified(self, window) -> MetricValue:
        # Deliberately NO platform filter -- payment_verified is a
        # backend-authoritative event (platform="backend_internal",
        # modules/payments/payment_service.py's own emission), never a
        # website-platform row. Task 11 S20's own "authoritative
        # payment_verified, REPORT PURCHASE population only" discriminator.
        return self._simple_count(
            "report_payment_verified", window, event_names="payment_verified",
            property_filters={"purpose": REPORT_PURCHASE_PAYMENT_PURPOSE},
        )

    def product_actions_total(self, window) -> MetricValue:
        return self._simple_count(
            "product_actions_total", window,
            event_names=list(PRODUCT_ACTION_EVENT_NAMES), platform=WEBSITE_PLATFORM,
        )

    def product_actions_attributed(self, window) -> MetricValue:
        definition = get_marketing_attribution_metric("product_actions_attributed")
        _total, attributed = self._repository.attribution_coverage(
            window=window, environment=self.ENVIRONMENT,
            event_names=list(PRODUCT_ACTION_EVENT_NAMES), platform=WEBSITE_PLATFORM,
        )
        return MetricValue(definition.metric_id, definition.quality_status, attributed, definition.limitations)

    def product_actions_unattributed(self, window) -> MetricValue:
        definition = get_marketing_attribution_metric("product_actions_unattributed")
        total, attributed = self._repository.attribution_coverage(
            window=window, environment=self.ENVIRONMENT,
            event_names=list(PRODUCT_ACTION_EVENT_NAMES), platform=WEBSITE_PLATFORM,
        )
        return MetricValue(definition.metric_id, definition.quality_status, total - attributed, definition.limitations)

    def _simple_count(self, metric_id, window, *, event_names, platform=None, property_filters=None) -> MetricValue:
        definition = _lookup_definition(metric_id)
        value = self._repository.count_events(
            window=window, environment=self.ENVIRONMENT,
            event_names=event_names, platform=platform, property_filters=property_filters,
        )
        return MetricValue(definition.metric_id, definition.quality_status, value, definition.limitations)

    # =================================================================
    # Attribution coverage (Task 10 S10/S11/S12)
    # =================================================================
    def attribution_coverage_pct(self, window) -> AttributionCoverageResult:
        definition = get_marketing_attribution_metric("attribution_coverage_pct")
        total, attributed = self._repository.attribution_coverage(
            window=window, environment=self.ENVIRONMENT,
            event_names=list(PRODUCT_ACTION_EVENT_NAMES), platform=WEBSITE_PLATFORM,
        )
        unattributed = total - attributed
        rate = compute_rate(attributed, total)
        coverage_percent = rate * 100 if rate is not None else None
        return AttributionCoverageResult(
            metric_id=definition.metric_id, quality_status=definition.quality_status,
            total_eligible=total, attributed=attributed, unattributed=unattributed,
            coverage_percent=coverage_percent, limitations=definition.limitations,
        )

    # =================================================================
    # Single-dimension grouped: properties.page_path (with an explicit
    # unknown_count -- Task 9A/Task 11 S14, never silently dropped).
    # =================================================================
    def cta_clicks_by_page(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_page("cta_clicks_by_page", window, event_names="cta_click", limit=limit)

    def tool_completions_by_page(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_page("tool_completions_by_page", window, event_names="feature_used", limit=limit)

    def app_download_intents_by_page(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_page("app_download_intents_by_page", window, event_names="app_download_intent", limit=limit)

    def report_purchase_intents_by_page(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        # Task 11 S5 note (recorded, not silently resolved): neither
        # website_metrics_contract.py nor marketing_attribution_contract.py
        # freezes a metric_id literally named "report_purchase_intents_by_page"
        # (only the dual "..._by_page_and_source" and the plain
        # "cta_clicks_by_page" exist). cta_clicks_by_page's own frozen
        # `dimensions` tuple already includes cta_id -- so this is a
        # contract-consistent SCOPING of that exact, already-READY
        # metric (grouped by page_path, filtered to cta_id=
        # PURCHASED_REPORT_ENTRY_CTA_ID), not a new metric_id. The
        # returned metric_id is therefore honestly "cta_clicks_by_page",
        # never a fabricated new identity.
        return self._grouped_by_page(
            "cta_clicks_by_page", window, event_names="cta_click", limit=limit,
            property_filters={"cta_id": PURCHASED_REPORT_ENTRY_CTA_ID},
        )

    def cta_clicks_by_cta_id(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_property("cta_clicks_by_cta_id", window, event_names="cta_click", dimension="cta_id", limit=limit)

    def _grouped_by_page(self, metric_id, window, *, event_names, limit, property_filters=None) -> GroupedMetricResult:
        return self._grouped_by_property(metric_id, window, event_names=event_names, dimension="page_path", limit=limit, property_filters=property_filters)

    def _grouped_by_property(self, metric_id, window, *, event_names, dimension, limit, property_filters=None) -> GroupedMetricResult:
        definition = _lookup_definition(metric_id)
        safe_limit = max(1, min(limit, MAX_GROUP_LIMIT))
        total = self._repository.count_events(
            window=window, environment=self.ENVIRONMENT, event_names=event_names,
            platform=WEBSITE_PLATFORM, property_filters=property_filters,
        )
        groups_dict = self._repository.group_by_property(
            window=window, environment=self.ENVIRONMENT, event_names=event_names,
            dimension=dimension, platform=WEBSITE_PLATFORM, property_filters=property_filters,
        )
        # group_by_property() is unlimited and ordered by dimension
        # value ASC only (its own, older, still-valid convention) --
        # this service layer applies Task 11's OWN deterministic
        # ordering (count DESC, dimension ASC) and limit on top,
        # without needing a second repository method (page/cta_id
        # cardinality is low enough for this small site to sort safely
        # in Python -- typically dozens, never remotely close to
        # PostgreSQL-side-sort territory).
        ordered = sorted(groups_dict.items(), key=lambda kv: (-kv[1], kv[0]))[:safe_limit]
        rows = tuple(GroupedMetricRow(dimension_value=k, count=v) for k, v in ordered)
        known_sum = sum(groups_dict.values())
        unknown_count = total - known_sum
        return GroupedMetricResult(
            metric_id=definition.metric_id, quality_status=definition.quality_status,
            dimension=dimension, rows=rows, unknown_count=unknown_count, total=total,
            limitations=definition.limitations,
        )

    # =================================================================
    # Single-dimension grouped: campaign_context (source/medium/campaign)
    # =================================================================
    def product_actions_by_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("product_actions_by_source", window, event_names=list(PRODUCT_ACTION_EVENT_NAMES), dimension_name="source", platform=WEBSITE_PLATFORM, limit=limit)

    def product_actions_by_medium(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("product_actions_by_medium", window, event_names=list(PRODUCT_ACTION_EVENT_NAMES), dimension_name="medium", platform=WEBSITE_PLATFORM, limit=limit)

    def product_actions_by_campaign(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("product_actions_by_campaign", window, event_names=list(PRODUCT_ACTION_EVENT_NAMES), dimension_name="campaign", platform=WEBSITE_PLATFORM, limit=limit)

    def cta_clicks_by_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("cta_clicks_by_source", window, event_names="cta_click", dimension_name="source", platform=WEBSITE_PLATFORM, limit=limit)

    def cta_clicks_by_medium(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("cta_clicks_by_medium", window, event_names="cta_click", dimension_name="medium", platform=WEBSITE_PLATFORM, limit=limit)

    def cta_clicks_by_campaign(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("cta_clicks_by_campaign", window, event_names="cta_click", dimension_name="campaign", platform=WEBSITE_PLATFORM, limit=limit)

    def tool_completions_by_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("tool_completions_by_source", window, event_names="feature_used", dimension_name="source", platform=WEBSITE_PLATFORM, limit=limit)

    def app_download_intents_by_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("app_download_intents_by_source", window, event_names="app_download_intent", dimension_name="source", platform=WEBSITE_PLATFORM, limit=limit)

    def app_download_intents_by_medium(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("app_download_intents_by_medium", window, event_names="app_download_intent", dimension_name="medium", platform=WEBSITE_PLATFORM, limit=limit)

    def app_download_intents_by_campaign(self, window, dimension: str = "campaign", limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        # Task 9's own single metric_id whose frozen `dimensions` tuple
        # spans all three of source/medium/campaign -- the only metric
        # in this file where one metric_id supports a caller-chosen
        # campaign dimension (defaults to "campaign", matching the
        # metric's own name).
        return self._grouped_by_campaign("app_download_intents_by_campaign", window, event_names="app_download_intent", dimension_name=dimension, platform=WEBSITE_PLATFORM, limit=limit)

    def report_purchase_intents_by_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign(
            "report_purchase_intents_by_source", window, event_names="cta_click", dimension_name="source",
            platform=WEBSITE_PLATFORM, limit=limit, property_filters={"cta_id": PURCHASED_REPORT_ENTRY_CTA_ID},
        )

    def report_purchase_intents_by_campaign(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign(
            "report_purchase_intents_by_campaign", window, event_names="cta_click", dimension_name="campaign",
            platform=WEBSITE_PLATFORM, limit=limit, property_filters={"cta_id": PURCHASED_REPORT_ENTRY_CTA_ID},
        )

    def report_payment_verified_by_campaign(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        # No platform filter -- see report_payment_verified()'s own note.
        return self._grouped_by_campaign(
            "report_payment_verified_by_campaign", window, event_names="payment_verified", dimension_name="campaign",
            platform=None, limit=limit, property_filters={"purpose": REPORT_PURCHASE_PAYMENT_PURPOSE},
        )

    def attributed_android_acquisitions_by_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("attributed_android_acquisitions_by_source", window, event_names="app_install_attributed", dimension_name="source", platform=ANDROID_PLATFORM, limit=limit)

    def attributed_android_acquisitions_by_medium(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("attributed_android_acquisitions_by_medium", window, event_names="app_install_attributed", dimension_name="medium", platform=ANDROID_PLATFORM, limit=limit)

    def attributed_android_acquisitions_by_campaign(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> GroupedMetricResult:
        return self._grouped_by_campaign("attributed_android_acquisitions_by_campaign", window, event_names="app_install_attributed", dimension_name="campaign", platform=ANDROID_PLATFORM, limit=limit)

    def _grouped_by_campaign(self, metric_id, window, *, event_names, dimension_name, platform, limit, property_filters=None) -> GroupedMetricResult:
        definition = _lookup_definition(metric_id)
        campaign_field = _campaign_field(dimension_name)
        safe_limit = max(1, min(limit, MAX_GROUP_LIMIT))

        groups_dict, unattributed_count = self._repository.group_by_campaign_context(
            window=window, environment=self.ENVIRONMENT, event_names=event_names,
            dimension=campaign_field, platform=platform, property_filters=property_filters,
            limit=safe_limit,
        )
        total = self._repository.count_events(
            window=window, environment=self.ENVIRONMENT, event_names=event_names,
            platform=platform, property_filters=property_filters,
        )
        rows = tuple(GroupedMetricRow(dimension_value=value, count=count) for value, count in groups_dict.items())
        return GroupedMetricResult(
            metric_id=definition.metric_id, quality_status=definition.quality_status,
            dimension=dimension_name, rows=rows, unknown_count=unattributed_count, total=total,
            limitations=definition.limitations,
        )

    # =================================================================
    # Page x Attribution (Task 10 S9, Task 11 S4/S14)
    # =================================================================
    def cta_clicks_by_page_and_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> PageAttributionResult:
        return self._page_attribution("cta_clicks_by_page_and_source", window, event_names="cta_click", limit=limit)

    def tool_completions_by_page_and_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> PageAttributionResult:
        return self._page_attribution("tool_completions_by_page_and_source", window, event_names="feature_used", limit=limit)

    def app_download_intents_by_page_and_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> PageAttributionResult:
        return self._page_attribution("app_download_intents_by_page_and_source", window, event_names="app_download_intent", limit=limit)

    def report_purchase_intents_by_page_and_source(self, window, limit: int = DEFAULT_GROUP_LIMIT) -> PageAttributionResult:
        return self._page_attribution(
            "report_purchase_intents_by_page_and_source", window, event_names="cta_click", limit=limit,
            property_filters={"cta_id": PURCHASED_REPORT_ENTRY_CTA_ID},
        )

    def _page_attribution(self, metric_id, window, *, event_names, limit, property_filters=None) -> PageAttributionResult:
        definition = get_marketing_attribution_metric(metric_id)
        safe_limit = max(1, min(limit, MAX_GROUP_LIMIT))
        campaign_field = _campaign_field("source")  # every frozen ..._by_page_and_source metric is source-only

        groups_dict, incomplete_count = self._repository.group_by_property_and_campaign_context(
            window=window, environment=self.ENVIRONMENT, event_names=event_names,
            property_dimension="page_path", campaign_dimension=campaign_field,
            platform=WEBSITE_PLATFORM, property_filters=property_filters, limit=safe_limit,
        )
        total = self._repository.count_events(
            window=window, environment=self.ENVIRONMENT, event_names=event_names,
            platform=WEBSITE_PLATFORM, property_filters=property_filters,
        )
        rows = tuple(
            PageAttributionRow(page_path=page, dimension_value=value, count=count)
            for (page, value), count in groups_dict.items()
        )
        return PageAttributionResult(
            metric_id=definition.metric_id, quality_status=definition.quality_status,
            property_dimension="page_path", campaign_dimension="source",
            rows=rows, incomplete_count=incomplete_count, total=total,
            limitations=definition.limitations,
        )


# ---------------------------------------------------------------------
# Closed dispatch table (Task 11 S4/S5) -- the ONLY metric_ids this
# task implements a repository query for. A READY/PARTIAL metric_id
# from either frozen catalog that is NOT listed here (e.g. Task 9's own
# cta_clicks_by_screen_name, first_party_campaign_attribution,
# kundali_generation_completed, report_generation_completed_purchased,
# report_purchase_intent_to_payment_correlation; Task 10's own
# website_to_app_campaign_funnel_indicator) is deliberately out of this
# task's curated scope, per Task 11 S4's own explicit list -- calling
# get_metric() for one of those raises WebsiteMetricNotImplemented, not
# a silent gap.
# ---------------------------------------------------------------------
_DISPATCH: Dict[str, str] = {
    "cta_clicks_total": "cta_clicks_total",
    "cta_clicks_by_cta_id": "cta_clicks_by_cta_id",
    "cta_clicks_by_page": "cta_clicks_by_page",
    "cta_clicks_by_source": "cta_clicks_by_source",
    "cta_clicks_by_medium": "cta_clicks_by_medium",
    "cta_clicks_by_campaign": "cta_clicks_by_campaign",
    "cta_clicks_by_page_and_source": "cta_clicks_by_page_and_source",

    "tool_completions_all": "tool_completions_all",
    "tool_completions_by_page": "tool_completions_by_page",
    "tool_completions_by_source": "tool_completions_by_source",
    "tool_completions_by_page_and_source": "tool_completions_by_page_and_source",

    "app_download_intents_total": "app_download_intents_total",
    "app_download_intents_by_page": "app_download_intents_by_page",
    "app_download_intents_by_source": "app_download_intents_by_source",
    "app_download_intents_by_medium": "app_download_intents_by_medium",
    "app_download_intents_by_campaign": "app_download_intents_by_campaign",
    "app_download_intents_by_page_and_source": "app_download_intents_by_page_and_source",

    "report_discovery_views": "report_discovery_views",
    "report_purchase_intent": "report_purchase_intent",
    "report_purchase_intents_by_page": "report_purchase_intents_by_page",
    "report_purchase_intents_by_source": "report_purchase_intents_by_source",
    "report_purchase_intents_by_campaign": "report_purchase_intents_by_campaign",
    "report_purchase_intents_by_page_and_source": "report_purchase_intents_by_page_and_source",
    "report_payment_verified": "report_payment_verified",
    "report_payment_verified_by_campaign": "report_payment_verified_by_campaign",

    "product_actions_total": "product_actions_total",
    "product_actions_attributed": "product_actions_attributed",
    "product_actions_unattributed": "product_actions_unattributed",
    "product_actions_by_source": "product_actions_by_source",
    "product_actions_by_medium": "product_actions_by_medium",
    "product_actions_by_campaign": "product_actions_by_campaign",
    "attribution_coverage_pct": "attribution_coverage_pct",

    "attributed_android_acquisitions_by_source": "attributed_android_acquisitions_by_source",
    "attributed_android_acquisitions_by_medium": "attributed_android_acquisitions_by_medium",
    "attributed_android_acquisitions_by_campaign": "attributed_android_acquisitions_by_campaign",
}
