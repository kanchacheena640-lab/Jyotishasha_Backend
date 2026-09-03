# modules/activity_events/website_metrics_contract.py

"""
Task 9 -- the FROZEN website analytics metrics contract. Declarative
only: WHAT each metric means, WHICH system owns it, WHICH event/field
produces it, HOW it is counted, WHAT dimensions/filters apply, and its
current measurability status. No SQL, no GA4 Data API call, no new
database table/migration, no new event producer -- this module answers
"what CAN be measured and how" before any query/service/API/dashboard
work begins (Task 10+).

Same architectural role, and the same "shape only, no computation, no
database access" discipline, as modules/activity_events/
analytics_contract.py (Phase 6B.1) and modules/payments/metrics_models.py
-- kept as its OWN, separate module rather than added to
analytics_contract.py because that file's own scope is the cross-
PLATFORM (app+website) Admin analytics API contract (Phase 6B, already
implemented and frozen); THIS module is specifically the WEBSITE
dashboard's own metric catalog, one level up in scope (it references,
but does not modify, Phase 6B's own frozen constants below).

==================================================================
FROZEN SOURCE-OF-TRUTH SPLIT (Task 9 S2)
==================================================================
  GA4/GTM (source="ga4_external"):
    high-volume generic website analytics -- page views, sessions,
    landing pages, traffic acquisition/channel grouping, device/
    browser, new-vs-returning users. NOT reachable from this backend
    today (see GA4_DATA_API_AVAILABLE below) -- these metrics are part
    of the frozen contract as GA4_EXTERNAL, never invented/mocked here.

  First-party PostgreSQL activity_events (source="activity_events"):
    meaningful product/business actions -- feature_used, cta_click,
    app_download_intent, report_discovery_viewed, and (backend-owned)
    payment/report/subscription/Ask Now lifecycle events.
    page_view is registered in the canonical event registry
    (event_schemas.py) but is explicitly `ledger_eligible=False` --
    GA4-owned, PostgreSQL never receives it, and this contract never
    proposes changing that.

  Backend business tables (source="backend_business_table"):
    revenue/order/entitlement truth (Order, ProcessedPayment,
    CurrentEntitlement) -- activity_events' payment_verified/
    subscription_* rows are the LEDGER record of those facts, never a
    substitute source of financial truth themselves (matches
    modules/payments/metrics_service.py's own existing boundary).

==================================================================
GA4 DATA API ACCESS (Task 9 S24, audited not assumed)
==================================================================
Confirmed absent from this backend: no `google-analytics-data`
dependency in requirements.txt, no GA4 property ID, no service-account
credential wired for GA4 specifically (only generic `google-auth`
library internals used by unrelated existing integrations -- Firebase,
Play, pub/sub -- none of them GA4). A later task must add the GA4 Data
API client/credentials/property ID before any GA4_EXTERNAL metric can
actually be queried; until then every GA4_EXTERNAL metric below is a
FROZEN DEFINITION only, never a live value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

# ---------------------------------------------------------------------
# Re-exported, NOT redefined -- this contract must never drift from
# Phase 6B's own already-frozen constants. Importing (not copying) is
# what keeps that guarantee structural rather than a comment.
# ---------------------------------------------------------------------
from modules.activity_events.analytics_contract import (  # noqa: F401
    PRODUCTION_ENVIRONMENT,
    ALLOWED_PLATFORMS,
    PURCHASED_REPORT_ENTRY_CTA_ID,
    REPORT_PURCHASE_PAYMENT_PURPOSE,
    AI_REPORT_ENTITY_TYPE,
    PURCHASED_REPORT_ENTITY_TYPE,
)

GA4_DATA_API_AVAILABLE = False  # audited fact, Task 9 -- see module docstring


# =======================================================================
# Metric SOURCE vocabulary (Task 9 S6/S25)
# =======================================================================
SOURCE_GA4_EXTERNAL = "ga4_external"
SOURCE_ACTIVITY_EVENTS = "activity_events"
SOURCE_BACKEND_BUSINESS_TABLE = "backend_business_table"

METRIC_SOURCES = frozenset({
    SOURCE_GA4_EXTERNAL,
    SOURCE_ACTIVITY_EVENTS,
    SOURCE_BACKEND_BUSINESS_TABLE,
})


# =======================================================================
# Metric QUALITY STATUS vocabulary (Task 9 S23)
# =======================================================================
QUALITY_READY = "READY"                # fully measurable today, as defined
QUALITY_PARTIAL = "PARTIAL"            # measurable with a real, stated gap
QUALITY_BLOCKED = "BLOCKED"            # not currently measurable at all
QUALITY_GA4_EXTERNAL = "GA4_EXTERNAL"  # owned by GA4, not queryable from this backend yet

METRIC_QUALITY_STATUSES = frozenset({
    QUALITY_READY,
    QUALITY_PARTIAL,
    QUALITY_BLOCKED,
    QUALITY_GA4_EXTERNAL,
})


# =======================================================================
# Zero / null / unknown semantics (Task 9 S22) -- frozen dashboard
# meaning, referenced by every metric's own quality_status:
#   MEASURED_ZERO -- the metric IS measurable (source connected, query
#     capability exists) and zero matching events/rows were found for
#     the requested window/filters. A real, meaningful "0".
#   UNAVAILABLE   -- the metric CANNOT currently be measured (source not
#     connected -- e.g. every GA4_EXTERNAL metric today -- or the
#     underlying data genuinely does not exist -- e.g. every BLOCKED
#     metric). MUST NEVER be displayed as "0" -- that would silently
#     misrepresent "no data connected" as "no activity occurred".
#   UNKNOWN_DIMENSION -- the event/row exists and IS counted in totals,
#     but the requested breakdown dimension is absent/uncategorized for
#     it (e.g. a cta_click row with no meaningful screen_name bucket).
#     Counted once in the metric's own total, and once in an explicit
#     "unknown" bucket for that dimension -- never silently dropped,
#     never merged into a real category.
# A future dashboard/API MUST preserve this 3-way distinction --
# collapsing UNAVAILABLE or UNKNOWN_DIMENSION into 0 is a contract
# violation, not a display nuance.
# =======================================================================
ZERO_SEMANTIC_MEASURED_ZERO = "MEASURED_ZERO"
ZERO_SEMANTIC_UNAVAILABLE = "UNAVAILABLE"
ZERO_SEMANTIC_UNKNOWN_DIMENSION = "UNKNOWN_DIMENSION"

ZERO_NULL_UNKNOWN_SEMANTICS = frozenset({
    ZERO_SEMANTIC_MEASURED_ZERO,
    ZERO_SEMANTIC_UNAVAILABLE,
    ZERO_SEMANTIC_UNKNOWN_DIMENSION,
})


# =======================================================================
# Time contract (Task 9 S19)
# =======================================================================
# activity_events: occurred_at (timezone-aware, always) owns EVERY
# metric's own event-period attribution. recorded_at is ingestion/audit
# metadata ONLY -- ledger write time, never a business-event date; no
# metric in this contract is ever windowed by recorded_at.
TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT = "activity_events.occurred_at (UTC, timezone-aware; NOT recorded_at)"
# GA4: that product's own reporting date/time semantics (GA4's own
# timezone-configured property setting) -- this backend does not define
# or override GA4's own time basis.
TIME_BASIS_GA4_REPORTING_TIME = "GA4 property reporting time (GA4-owned, not backend-defined)"

# Storage/query boundary is UTC throughout (matches Phase 6B's own
# AnalyticsWindow contract, which requires timezone-aware bounds and
# performs no timezone conversion). A future dashboard UI MAY present
# IST-labeled periods to end users, but must convert UTC<->IST only at
# the presentation layer -- never store, query, or window activity_events
# in IST. This contract does not, itself, implement that conversion.
STORAGE_TIMEZONE = "UTC"
PRESENTATION_TIMEZONE_RECOMMENDATION = "IST (presentation layer only -- never mixed into storage/query boundaries)"

STANDARD_DASHBOARD_PERIODS: Tuple[str, ...] = ("7d", "30d", "90d", "custom")


# =======================================================================
# Dimension contract (Task 9 S20)
# =======================================================================
DIMENSION_AVAILABLE = "AVAILABLE"
DIMENSION_PARTIAL = "PARTIAL"
DIMENSION_UNAVAILABLE = "UNAVAILABLE"

DIMENSION_STATUSES = frozenset({DIMENSION_AVAILABLE, DIMENSION_PARTIAL, DIMENSION_UNAVAILABLE})


@dataclass(frozen=True)
class DimensionAvailability:
    dimension_id: str
    status: str
    source_field: str
    notes: str


WEBSITE_DIMENSION_CATALOG: Tuple[DimensionAvailability, ...] = (
    DimensionAvailability(
        "pathname_or_page", DIMENSION_AVAILABLE, "activity_events.properties.page_path",
        "Task 9A -- closes the PAGE_ACTION_ATTRIBUTION_GAP for the 4 events that "
        "carry it (cta_click, feature_used, app_download_intent, report_discovery_"
        "viewed): each now attaches page_path (normalized route/pathname), derived "
        "at CALL TIME by lib/pagePath.ts's getCurrentPagePath(), for every existing "
        "website call site. Available for every event PRODUCED after this change; "
        "absent on any row written before it (page_path is optional at the schema "
        "level, so older rows simply lack the key -- never backfilled). "
        "GA4 separately has its own page dimension (GA4_EXTERNAL) for GA4-owned "
        "metrics -- unrelated to and unaffected by this first-party addition.",
    ),
    DimensionAvailability(
        "locale_language", DIMENSION_UNAVAILABLE, "(none)",
        "Not attached to any current website producer's properties/campaign_context.",
    ),
    DimensionAvailability(
        "platform", DIMENSION_AVAILABLE, "activity_events.platform",
        "Server-forced (never client-supplied) on the anonymous endpoint -- 'website' "
        "for every current website-origin row.",
    ),
    DimensionAvailability(
        "source", DIMENSION_PARTIAL, "activity_events.campaign_context.utm_source",
        "Present only when Task 2C's session-scoped first-touch attribution actually "
        "captured a utm_source; absent for direct/no-campaign visits by design.",
    ),
    DimensionAvailability(
        "medium", DIMENSION_PARTIAL, "activity_events.campaign_context.utm_medium",
        "Same first-touch-only availability as source.",
    ),
    DimensionAvailability(
        "campaign", DIMENSION_PARTIAL, "activity_events.campaign_context.utm_campaign",
        "Same first-touch-only availability as source.",
    ),
    DimensionAvailability(
        "feature", DIMENSION_PARTIAL, "activity_events.properties.feature_name",
        "Available on feature_used rows; coverage itself is partial -- only "
        "kundali_generate is currently produced by any website call site "
        "(Panchang/Muhurat/Horoscope/other tools explicitly deferred, Task 2D).",
    ),
    DimensionAvailability(
        "cta_id", DIMENSION_AVAILABLE, "activity_events.properties.cta_id",
        "Present on every cta_click row (frozen schema requirement).",
    ),
    DimensionAvailability(
        "cta_location", DIMENSION_AVAILABLE, "activity_events.properties.cta_location",
        "Present on every app_download_intent row (frozen schema requirement); a "
        "controlled placement label, not a structured pathname -- see PAGE_ACTION_"
        "ATTRIBUTION_GAP.",
    ),
    DimensionAvailability(
        "report_type", DIMENSION_UNAVAILABLE, "activity_events.properties.report_type",
        "Schema-allowed but the current website report_discovery_viewed producer "
        "sends no properties at all (fires once for the whole multi-type catalog "
        "page) -- see WEBSITE_METRIC_CATALOG's report_discovery_views entry.",
    ),
    DimensionAvailability(
        "subscription_plan", DIMENSION_UNAVAILABLE, "activity_events.properties.plan",
        "No live website subscription-discovery producer exists at all (Task 2D "
        "forensic finding: UpgradeButton.tsx/HoroscopeComparison.tsx both orphaned).",
    ),
    DimensionAvailability(
        "entity_type", DIMENSION_AVAILABLE, "activity_events.entity_type",
        "Distinguishes ai_report vs order for report_generation_* rows (backend-"
        "owned events only, not website-producer events).",
    ),
    DimensionAvailability(
        "environment", DIMENSION_AVAILABLE, "activity_events.environment",
        "Structurally fixed to 'production' for every real query (Phase 6B contract) "
        "-- never a caller-supplied filter value.",
    ),
)


# =======================================================================
# Filter contract (Task 9 S21) -- the ONLY filter names a future website
# analytics API may expose. Deliberately a closed, small vocabulary --
# never raw/arbitrary JSON property querying.
# =======================================================================
ALLOWED_WEBSITE_FILTERS: Tuple[str, ...] = (
    "date_range",   # one of STANDARD_DASHBOARD_PERIODS or an explicit start/end
    "platform",     # subset of ALLOWED_PLATFORMS
    "source",       # campaign_context.utm_source, PARTIAL dimension
    "medium",       # campaign_context.utm_medium, PARTIAL dimension
    "campaign",     # campaign_context.utm_campaign, PARTIAL dimension
    "event_name",   # canonical event name, closed vocabulary only
    "feature",      # properties.feature_name, PARTIAL dimension/coverage
    "cta_id",       # properties.cta_id
    "page_path",    # properties.page_path -- Task 9A, AVAILABLE dimension
)


# =======================================================================
# Cross-source join policy (Task 9 S18) -- frozen, referenced by every
# funnel definition below.
# =======================================================================
CROSS_SOURCE_JOIN_POLICY = (
    "AGGREGATE CORRELATION ONLY, NEVER USER-LEVEL ATTRIBUTION. A dashboard MAY "
    "display a GA4_EXTERNAL metric (e.g. Views for a normalized pathname/date range) "
    "alongside an activity_events metric (e.g. Tool Completions for that same "
    "pathname/date range) side by side, IF page-action attribution for the "
    "activity_events side actually exists (see PAGE_ACTION_ATTRIBUTION_GAP -- "
    "today, it mostly does not). A dashboard MUST NEVER claim that a specific GA4 "
    "visitor/session performed a specific activity_events row's action -- no "
    "verified common identifier exists between GA4's own visitor/session model and "
    "activity_events' session_id (an app/process-lifetime id, Phase 6A) or "
    "firebase_uid (present only for authenticated events). Two systems' independently "
    "aggregated counts for the same normalized dimension/window are a coincidence of "
    "presentation, not a join."
)


# =======================================================================
# PAGE-ACTION ATTRIBUTION GAP (Task 9 S8/S26 -- the most important gate)
# =======================================================================
PAGE_ACTION_ATTRIBUTION_GAP = (
    "CONFIRMED, real, verified against the actual current schemas (not assumed): "
    "none of the 5 website-producible events (cta_click, feature_used, "
    "app_download_intent, report_discovery_viewed, subscription_discovery_viewed) "
    "carry a structured pathname/page field. cta_click's own 'screen_name' is the "
    "closest thing to a page label, but it is a manually-chosen, per-call-site "
    "constant (only 'kundali_form' and 'report_catalog' exist today, Task 2D), not "
    "derived from the actual route -- it cannot answer 'which page' for any call "
    "site that doesn't happen to name itself after one. feature_used and "
    "report_discovery_viewed carry NO page-shaped field at all. app_download_intent's "
    "cta_location sometimes encodes page context by NAMING CONVENTION for "
    "AppDownloadCTA's own per-page call sites (e.g. 'daily_panchang_primary_cta'), "
    "but is IDENTICAL ('site_global_sticky_cta') across every page for the globally-"
    "mounted StickyAppDownloadCTA, so it cannot distinguish pages there at all. "
    "Task 2C's own landingPage (session-scoped, captured once, never updated) is "
    "explicitly NOT the action page for any event after the very first page of a "
    "session -- conflating the two would misattribute every subsequent action.\n\n"
    "MINIMAL FUTURE CONTRACT EXTENSION (documented here, NOT implemented in Task 9, "
    "per this task's own explicit instruction -- actual instrumentation requires a "
    "separately authorized corrective subtask): add ONE new, optional, allowlisted "
    "property key -- e.g. `page_path` -- to CAMPAIGN_CONTEXT_ALLOWED_KEYS or a "
    "per-event properties addition, populated from the actual current route "
    "(Next.js usePathname(), normalized to strip locale prefix/query/fragment, "
    "mirroring lib/analyticsAttribution.ts's own normalizeLandingPage() logic) at "
    "the moment each website producer call fires -- NOT the session's landingPage. "
    "Preferred over overloading the existing screen_name/cta_location fields, which "
    "already carry a different, established meaning (a controlled UI label, not a "
    "route) and are inconsistently populated across call sites today.\n\n"
    "TASK 9A RESOLUTION (implemented, not merely proposed, as of this task): exactly "
    "the minimal extension above was built. `page_path` is now an optional, "
    "allowlisted property on cta_click, feature_used, app_download_intent, and "
    "report_discovery_viewed (modules/activity_events/event_schemas.py), validated "
    "by ingestion_validation.validate_page_path() (reject-not-drop on a malformed "
    "value), and attached automatically at CALL TIME by every one of their existing "
    "website producers via lib/websiteEvents.ts's centralized withPagePath() helper "
    "(itself backed by lib/pagePath.ts's getCurrentPagePath(), never landingPage, "
    "never a static/startup-time capture). This closes the gap for the 4 events that "
    "received it -- see PAGE_ACTION_ATTRIBUTION_GAP_STATUS below for exactly what "
    "remains open. subscription_discovery_viewed was deliberately NOT extended: it "
    "has no live website producer to extend (Task 2D finding, unchanged) -- adding "
    "page_path to an event nothing calls would be dead schema, not a real fix."
)

# Task 9A -- the gap's own closure status, kept alongside the historical finding
# above rather than deleting it (the finding remains true of the events it was
# never extended to, and is valuable audit history for the 4 that were fixed).
# NOT a blanket "CLOSED" -- deliberately named to say exactly what closed and what
# did not, so a future reader cannot mistake this for "every page-action question
# is now answerable."
PAGE_ACTION_ATTRIBUTION_GAP_STATUS = "CLOSED_FOR_EXISTING_PRODUCERS"

# What CLOSED_FOR_EXISTING_PRODUCERS means, and its own explicit remaining limits --
# read together with the metric catalog's own per-metric quality_status/limitations
# below, never in place of them.
PAGE_ACTION_ATTRIBUTION_GAP_REMAINING_LIMITATIONS = (
    "subscription_discovery_viewed still carries no page_path -- no live website "
    "producer exists to extend (unchanged Task 2D finding); extending an unused "
    "event's schema would not itself close anything.",
    "Any activity_events row WRITTEN BEFORE this task shipped has no page_path "
    "(the property is optional and was not backfilled) -- page-level breakdowns "
    "are only complete from this task's deploy time forward.",
    "page_path answers 'which page', never 'which tool/CTA is fully instrumented' -- "
    "tool_completions_by_page remains PARTIAL because feature_used itself is only "
    "produced for Free Kundali (Panchang/Muhurat/Horoscope/other calculators remain "
    "uninstrumented, Task 2D), independent of and unaffected by this task.",
    "cta_click's screen_name field remains a coarse, manually-curated UI label, "
    "unaffected by this task -- page_path is a separate, additional dimension, not a "
    "reinterpretation or replacement of screen_name (Task 9A S14's explicit rule).",
)


# =======================================================================
# The metric catalog itself
# =======================================================================
@dataclass(frozen=True)
class WebsiteMetricDefinition:
    metric_id: str
    display_name: str
    source: str
    definition: str
    counting_rule: str
    time_basis: str
    dimensions: Tuple[str, ...]
    quality_status: str
    limitations: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.source not in METRIC_SOURCES:
            raise ValueError(f"{self.metric_id}: unknown source {self.source!r}")
        if self.quality_status not in METRIC_QUALITY_STATUSES:
            raise ValueError(f"{self.metric_id}: unknown quality_status {self.quality_status!r}")


_GA4_TIME = TIME_BASIS_GA4_REPORTING_TIME
_LEDGER_TIME = TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT

WEBSITE_METRIC_CATALOG: Tuple[WebsiteMetricDefinition, ...] = (

    # ---- Overview (Task 9 S5) -- every one of these is GA4's own
    # canonical definition; none is reimplemented with a custom formula. ----
    WebsiteMetricDefinition(
        "page_views", "Page Views", SOURCE_GA4_EXTERNAL,
        "Total count of page-view events across the selected period.",
        "GA4's own canonical page_view event count.", _GA4_TIME,
        ("date_range",), QUALITY_GA4_EXTERNAL,
        ("page_view is frozen ledger-ineligible -- GA4-owned by design, never duplicated into PostgreSQL.",),
    ),
    WebsiteMetricDefinition(
        "users", "Users", SOURCE_GA4_EXTERNAL,
        "Count of distinct users (GA4's own identity model) in the period.",
        "GA4's own canonical Users metric.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "sessions", "Sessions", SOURCE_GA4_EXTERNAL,
        "Count of GA4 sessions in the period.",
        "GA4's own canonical Sessions metric.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "new_users", "New Users", SOURCE_GA4_EXTERNAL,
        "Count of users GA4 classifies as new in the period.",
        "GA4's own canonical New Users metric.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "returning_users", "Returning Users", SOURCE_GA4_EXTERNAL,
        "users - new_users, using GA4's own new-user classification.",
        "Derived from GA4's own Users/New Users, not a custom identity model.", _GA4_TIME,
        ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "engaged_sessions", "Engaged Sessions", SOURCE_GA4_EXTERNAL,
        "GA4's own Engaged Sessions metric.",
        "GA4's own canonical definition (10s+ duration, a conversion event, or 2+ page/screen views).",
        _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "engagement_rate", "Engagement Rate", SOURCE_GA4_EXTERNAL,
        "engaged_sessions / sessions, GA4's own canonical ratio.",
        "GA4's own canonical Engagement Rate.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "avg_engagement_time", "Average Engagement Time", SOURCE_GA4_EXTERNAL,
        "GA4's own Average Engagement Time per user/session.",
        "GA4's own canonical definition.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "most_viewed_pages", "Most Viewed Pages", SOURCE_GA4_EXTERNAL,
        "Pages ranked by page_view COUNT during the selected period -- "
        "NOT the same concept as Top Landing Pages (Task 9 S4, frozen distinction).",
        "GA4 pathname dimension, ranked descending by page_view count.", _GA4_TIME,
        ("date_range", "pathname_or_page"), QUALITY_GA4_EXTERNAL,
        ("Must never be labeled interchangeably with 'Top Landing Pages' -- different ranking basis entirely.",),
    ),
    WebsiteMetricDefinition(
        "top_landing_pages", "Top Landing Pages", SOURCE_GA4_EXTERNAL,
        "The FIRST page of each session, ranked by sessions/entrances during the "
        "selected period -- NOT the same concept as Most Viewed Pages (Task 9 S4, frozen distinction).",
        "GA4 landing-page dimension, ranked descending by session/entrance count.", _GA4_TIME,
        ("date_range", "pathname_or_page"), QUALITY_GA4_EXTERNAL,
        ("Must never be labeled interchangeably with 'Most Viewed Pages' -- different ranking basis entirely.",),
    ),

    # ---- Acquisition (Task 9 S6) ----
    WebsiteMetricDefinition(
        "organic_search_sessions", "Organic Search Sessions", SOURCE_GA4_EXTERNAL,
        "Sessions GA4's own Default Channel Group classifies as Organic Search.",
        "GA4's own channel grouping.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "direct_sessions", "Direct Sessions", SOURCE_GA4_EXTERNAL,
        "Sessions GA4's own Default Channel Group classifies as Direct.",
        "GA4's own channel grouping.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "referral_sessions", "Referral Sessions", SOURCE_GA4_EXTERNAL,
        "Sessions GA4's own Default Channel Group classifies as Referral.",
        "GA4's own channel grouping.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "paid_search_sessions", "Paid Search Sessions", SOURCE_GA4_EXTERNAL,
        "Sessions GA4's own Default Channel Group classifies as Paid Search.",
        "GA4's own channel grouping.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "paid_social_sessions", "Paid Social Sessions", SOURCE_GA4_EXTERNAL,
        "Sessions GA4's own Default Channel Group classifies as Paid Social.",
        "GA4's own channel grouping.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "traffic_source_medium_campaign", "Traffic by Source/Medium/Campaign", SOURCE_GA4_EXTERNAL,
        "GA4's own source/medium/campaign dimensions, session-scoped.",
        "GA4's own canonical acquisition dimensions.", _GA4_TIME,
        ("date_range", "source", "medium", "campaign"), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "first_party_campaign_attribution", "First-Party Campaign Attribution (per event)", SOURCE_ACTIVITY_EVENTS,
        "utm_source/utm_medium/utm_campaign attached to an individual activity_events "
        "row via campaign_context, when Task 2C's first-touch capture succeeded for "
        "that visitor's session.",
        "Count of activity_events rows (any website event) grouped by campaign_context.utm_source/medium/campaign.",
        _LEDGER_TIME, ("date_range", "source", "medium", "campaign", "event_name"), QUALITY_PARTIAL,
        (
            "Session-scoped, first-touch-only (Task 2C) -- NOT equivalent to GA4's own "
            "channel grouping/attribution model; absent entirely for direct/no-campaign visits by design.",
        ),
    ),

    # ---- Page performance table columns (Task 9 S7) ----
    WebsiteMetricDefinition(
        "unique_visitors_by_page", "Unique Visitors by Page", SOURCE_GA4_EXTERNAL,
        "GA4's own Users dimensioned by page.",
        "GA4's own canonical Users-by-page.", _GA4_TIME, ("date_range", "pathname_or_page"), QUALITY_GA4_EXTERNAL,
        ("GA4 owns this metric -- activity_events' session_id is an app/process-lifetime id, "
         "not a persistent visitor identity, and must never be presented as 'unique visitors' (Task 9 S9).",),
    ),
    WebsiteMetricDefinition(
        "organic_entries_by_page", "Organic Entries by Page", SOURCE_GA4_EXTERNAL,
        "Landing-page sessions where the channel is Organic Search.",
        "GA4's own landing-page + channel-group intersection.", _GA4_TIME,
        ("date_range", "pathname_or_page"), QUALITY_GA4_EXTERNAL,
    ),
    WebsiteMetricDefinition(
        "tool_completions_by_page", "Tool Completions by Page", SOURCE_ACTIVITY_EVENTS,
        "feature_used rows grouped by the page the completion happened on.",
        "Count of feature_used rows grouped by properties.page_path.",
        _LEDGER_TIME, ("date_range", "pathname_or_page", "feature"), QUALITY_PARTIAL,
        ("Task 9A closed the PAGE_ACTION_ATTRIBUTION_GAP for this event -- page_path is now "
         "attached at call time. Still PARTIAL, not READY: the underlying tool-COVERAGE gap is "
         "unrelated and unchanged -- only Free Kundali (kundali_generate) produces feature_used "
         "at all (see tool_completions_all); a page breakdown of an incomplete event set is "
         "still an incomplete breakdown.",),
    ),
    WebsiteMetricDefinition(
        "cta_clicks_by_page", "CTA Clicks by Page", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows grouped by the page the click happened on.",
        "Count of cta_click rows grouped by properties.page_path.",
        _LEDGER_TIME, ("date_range", "pathname_or_page", "cta_id"), QUALITY_READY,
        ("Task 9A closed the PAGE_ACTION_ATTRIBUTION_GAP for this event -- page_path is now "
         "attached at call time for both live cta_click call sites (kundali_form_generate, "
         "report_catalog_buy_now). READY because, unlike tool_completions_by_page, cta_clicks_"
         "total/by_cta_id were already READY (every existing CTA is tracked, by design) -- this "
         "is a new dimension on already-complete coverage, not a breakdown of a partial set.",),
    ),
    WebsiteMetricDefinition(
        "app_download_intents_by_page", "App Download Intents by Page", SOURCE_ACTIVITY_EVENTS,
        "app_download_intent rows grouped by the page the click happened on.",
        "Count of app_download_intent rows grouped by properties.page_path.",
        _LEDGER_TIME, ("date_range", "pathname_or_page", "cta_location"), QUALITY_READY,
        ("Task 9A closed the PAGE_ACTION_ATTRIBUTION_GAP for this event -- page_path is now "
         "attached at call time for both AppDownloadCTA (per-page) and StickyAppDownloadCTA "
         "(global) producers. This specifically resolves the sticky-CTA case named in Task 9A's "
         "own objective: a click on the identical 'site_global_sticky_cta' placement is now "
         "distinguishable by the page it was clicked from, via page_path -- cta_location "
         "(placement) and page_path (page) remain two distinct, both-populated dimensions.",),
    ),

    # ---- Tool usage (Task 9 S10) ----
    WebsiteMetricDefinition(
        "kundali_generation_completed", "Free Kundali Generations Completed", SOURCE_ACTIVITY_EVENTS,
        "A successful Free Kundali generation on the website (never fired on failure or render).",
        "Count of feature_used rows where properties.feature_name = 'kundali_generate' and platform = 'website'.",
        _LEDGER_TIME, ("date_range",), QUALITY_READY,
    ),
    WebsiteMetricDefinition(
        "tool_completions_all", "All Tool Completions (website)", SOURCE_ACTIVITY_EVENTS,
        "feature_used rows across every website tool/calculator.",
        "Count of feature_used rows, platform = 'website', grouped by properties.feature_name.",
        _LEDGER_TIME, ("date_range", "feature"), QUALITY_PARTIAL,
        ("KNOWN COVERAGE GAP (Task 2D, carried forward for Task 13's own coverage audit): only "
         "Free Kundali is currently instrumented. Panchang, Muhurat, Horoscope, and other "
         "calculators/tools have NO website feature_used producer yet.",),
    ),

    # ---- CTA (Task 9 S11) ----
    WebsiteMetricDefinition(
        "cta_clicks_total", "CTA Clicks (Total)", SOURCE_ACTIVITY_EVENTS,
        "Every cta_click row from the website.",
        "Count of cta_click rows, platform = 'website'.", _LEDGER_TIME, ("date_range",), QUALITY_READY,
    ),
    WebsiteMetricDefinition(
        "cta_clicks_by_cta_id", "CTA Clicks by CTA ID", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows grouped by their stable cta_id (e.g. 'kundali_form_generate', "
        "'report_catalog_buy_now').",
        "Count of cta_click rows grouped by properties.cta_id.", _LEDGER_TIME,
        ("date_range", "cta_id"), QUALITY_READY,
    ),
    WebsiteMetricDefinition(
        "cta_clicks_by_screen_name", "CTA Clicks by Screen Name", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows grouped by their screen_name label.",
        "Count of cta_click rows grouped by properties.screen_name.", _LEDGER_TIME,
        ("date_range", "cta_id"), QUALITY_PARTIAL,
        ("screen_name is a manually-chosen, per-call-site constant (only 'kundali_form' and "
         "'report_catalog' exist today) -- coverage is limited to the 2 live cta_click producers, "
         "and it is not a structured pathname (see PAGE_ACTION_ATTRIBUTION_GAP).",),
    ),

    # ---- App Download Intent (Task 9 S12) ----
    WebsiteMetricDefinition(
        "app_download_intents_total", "App Download Intents (Total)", SOURCE_ACTIVITY_EVENTS,
        "Every actual click/tap toward the Play Store from AppDownloadCTA or "
        "StickyAppDownloadCTA -- NEVER fired on render/impression.",
        "Count of app_download_intent rows, platform = 'website'.", _LEDGER_TIME,
        ("date_range",), QUALITY_READY,
        ("app_download_intent is an INTENT, never an install -- see app_installs_ga4_first_open "
         "and app_installs_attributed below for the two distinct install-adjacent facts.",),
    ),
    WebsiteMetricDefinition(
        "app_download_intents_by_cta_location", "App Download Intents by CTA Location", SOURCE_ACTIVITY_EVENTS,
        "app_download_intent rows grouped by their controlled placement label.",
        "Count of app_download_intent rows grouped by properties.cta_location.", _LEDGER_TIME,
        ("date_range", "cta_location"), QUALITY_READY,
    ),
    WebsiteMetricDefinition(
        "app_download_intents_by_campaign", "App Download Intents by Campaign", SOURCE_ACTIVITY_EVENTS,
        "app_download_intent rows grouped by first-touch campaign attribution.",
        "Count of app_download_intent rows grouped by campaign_context.utm_source/medium/campaign.",
        _LEDGER_TIME, ("date_range", "source", "medium", "campaign"), QUALITY_PARTIAL,
        ("Same first-touch-only availability as first_party_campaign_attribution above.",),
    ),
    WebsiteMetricDefinition(
        "app_installs_ga4_first_open", "App Installs (GA4/Firebase first_open)", SOURCE_GA4_EXTERNAL,
        "Firebase/GA4's own automatically-collected first_open event -- the "
        "authoritative source for actual install/first-open VOLUME.",
        "GA4/Firebase's own canonical first_open event count.", _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
        ("Explicitly NOT the same fact as app_download_intent (a website click) or "
         "app_installs_attributed (a campaign-attribution fact) -- never conflate the three.",),
    ),
    WebsiteMetricDefinition(
        "app_installs_attributed", "App Installs (Attributed)", SOURCE_ACTIVITY_EVENTS,
        "Google Play install attribution captured by the Android app and later "
        "associated with an authenticated app lifecycle (Task 5A's own frozen "
        "meaning) -- a first-party CAMPAIGN-ATTRIBUTION fact, explicitly NOT a raw "
        "install counter and NOT the same thing as GA4/Firebase first_open.",
        "Count of app_install_attributed rows.", _LEDGER_TIME,
        ("date_range", "source", "medium", "campaign"), QUALITY_PARTIAL,
        (
            "Android only (platform restricted server-side, Task 5A). Requires the install to "
            "reach an authenticated app lifecycle before it can be recorded -- an install that "
            "never signs in is never captured. Must never be presented as 'number of installs' "
            "(Task 5A's own explicit, frozen prohibition) -- app_installs_ga4_first_open is the "
            "authoritative install-volume source.",
        ),
    ),

    # ---- Report metrics (Task 9 S13) ----
    WebsiteMetricDefinition(
        "report_discovery_views", "Report Catalog Discovery Views", SOURCE_ACTIVITY_EVENTS,
        "report_discovery_viewed rows -- fires once per mounted catalog page instance.",
        "Count of report_discovery_viewed rows, platform = 'website'.", _LEDGER_TIME,
        ("date_range",), QUALITY_PARTIAL,
        ("The current website producer sends no report_type property at all (the catalog page "
         "shows every report type at once) -- no per-type breakdown is available from this event.",),
    ),
    WebsiteMetricDefinition(
        "report_purchase_intent", "Report Purchase Intent", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows where cta_id = PURCHASED_REPORT_ENTRY_CTA_ID "
        "('report_catalog_buy_now') -- the catalog-entry moment into the purchase funnel, NOT a payment.",
        "Count of cta_click rows where properties.cta_id = 'report_catalog_buy_now'.",
        _LEDGER_TIME, ("date_range", "pathname_or_page"), QUALITY_READY,
        ("Task 9A -- page_path is now attached at call time (ReportsPageClient.tsx's single "
         "'report_catalog_buy_now' call site), so this metric can now also be broken down by "
         "the page the purchase-intent click occurred on, not just its total count.",),
    ),
    WebsiteMetricDefinition(
        "report_payment_verified", "Report Payment Verified", SOURCE_BACKEND_BUSINESS_TABLE,
        "A backend-verified Razorpay payment for the purchased-report product.",
        "Count of payment_verified rows where properties.purpose = 'REPORT_PURCHASE' "
        "(REPORT_PURCHASE_PAYMENT_PURPOSE). Financial truth remains the backend Order/"
        "ProcessedPayment tables -- this is the ledger record of that fact, not a substitute for it.",
        _LEDGER_TIME, ("date_range",), QUALITY_READY,
        (
            "Frozen purchased-report product semantics: purchase -> generation -> PDF emailed -> "
            "confirmation -> END. report_viewed/report_downloaded are deliberately NOT part of this "
            "contract -- registry compatibility (they exist as canonical events for the AI Report "
            "Engine's in-app flow) does not mean current website producer coverage for this product.",
        ),
    ),
    WebsiteMetricDefinition(
        "report_generation_completed_purchased", "Purchased Report Generation Completed", SOURCE_BACKEND_BUSINESS_TABLE,
        "Backend-confirmed generation completion for an Order-based purchased report.",
        "Count of report_generation_completed rows where entity_type = 'order' "
        "(PURCHASED_REPORT_ENTITY_TYPE).", _LEDGER_TIME, ("date_range",), QUALITY_READY,
    ),

    # ---- Ask Now (Task 9 S14) -- NO website producer exists at all ----
    WebsiteMetricDefinition(
        "asknow_website_funnel", "Ask Now (website funnel)", SOURCE_ACTIVITY_EVENTS,
        "Any website-attributable Ask Now funnel stage (entry/question/answer) on the website surface.",
        "Would count asknow_* rows where platform = 'website', IF a website Ask Now entry point existed.",
        _LEDGER_TIME, ("date_range",), QUALITY_BLOCKED,
        (
            "No website Ask Now entry point/producer exists (confirmed, Task 1/2D audits) -- "
            "asknow_question_submitted/asknow_answer_delivered/asknow_answer_failed are captured "
            "for the APP surface only. The Phase 6B AnalyticsService.get_asknow_metrics() already "
            "serves cross-platform Ask Now metrics for the Admin API -- this entry is specifically "
            "about WEBSITE attribution, which does not exist.",
        ),
    ),

    # ---- Subscription (Task 9 S15) -- NO website producer exists at all ----
    WebsiteMetricDefinition(
        "subscription_discovery_views_website", "Subscription Discovery Views (website)", SOURCE_ACTIVITY_EVENTS,
        "subscription_discovery_viewed rows attributable to the website surface.",
        "Would count subscription_discovery_viewed rows where platform = 'website', IF a live "
        "website discovery surface existed.", _LEDGER_TIME, ("date_range",), QUALITY_BLOCKED,
        (
            "No live website subscription-discovery UI exists (Task 2D forensic finding: "
            "UpgradeButton.tsx and HoroscopeComparison.tsx are both unreferenced/orphaned, "
            "unrendered anywhere). The event exists in the canonical registry and has app-side "
            "(Flutter SubscriptionPage) coverage only.",
        ),
    ),
    WebsiteMetricDefinition(
        "subscription_started_website", "Subscriptions Started (website-attributable)", SOURCE_BACKEND_BUSINESS_TABLE,
        "A verified, backend-confirmed subscription start attributable to a website-originated visit.",
        "Would count subscription_started rows joined to a website-origin session, IF such a "
        "join existed.", _LEDGER_TIME, ("date_range",), QUALITY_BLOCKED,
        (
            "subscription_discovery_viewed (would carry session_id) and the backend subscription "
            "lifecycle events (session_id always NULL) share no correlation key -- "
            "SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION (Phase 6B) already documents this for "
            "the app surface; it applies at least as strongly here, compounded by there being no "
            "live website discovery surface to originate a session from at all.",
        ),
    ),

    # ---- Conversion (Task 9 S16) ----
    WebsiteMetricDefinition(
        "report_purchase_intent_to_payment_correlation", "Report Purchase Intent -> Payment (aggregate)", SOURCE_ACTIVITY_EVENTS,
        "Aggregate-only comparison of report_purchase_intent count against "
        "report_payment_verified count for the same window -- NEVER a user-level conversion rate.",
        "compute_rate(report_payment_verified_count, report_purchase_intent_count) as an "
        "AGGREGATE ratio only.", _LEDGER_TIME, ("date_range",), QUALITY_PARTIAL,
        (
            "See CROSS_SOURCE_JOIN_POLICY -- the website's cta_click (anonymous, session-scoped) "
            "and the backend's payment_verified (authenticated, no shared correlation_id) cannot "
            "be joined at the individual-visit level. Only aggregate, same-window counts are safe.",
        ),
    ),
)


# =======================================================================
# Funnel definitions (Task 9 S17)
# =======================================================================
@dataclass(frozen=True)
class WebsiteFunnelStage:
    stage_name: str
    source: str
    event_or_metric: str
    joinable_to_next_stage: bool
    limitations: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WebsiteFunnel:
    funnel_id: str
    display_name: str
    stages: Tuple[WebsiteFunnelStage, ...]


WEBSITE_FUNNELS: Tuple[WebsiteFunnel, ...] = (
    WebsiteFunnel(
        "free_kundali", "Free Kundali Funnel",
        (
            WebsiteFunnelStage(
                "Landing / Page View", SOURCE_GA4_EXTERNAL, "GA4 page_view (pathname = /free-kundali)",
                joinable_to_next_stage=False,
                limitations=("GA4 session cannot be deterministically joined to the activity_events "
                              "session_id used by the next stage -- see CROSS_SOURCE_JOIN_POLICY.",),
            ),
            WebsiteFunnelStage(
                "Generate CTA", SOURCE_ACTIVITY_EVENTS, "cta_click (cta_id='kundali_form_generate')",
                joinable_to_next_stage=True,
                limitations=(),
            ),
            WebsiteFunnelStage(
                "Kundali Generation Completed", SOURCE_ACTIVITY_EVENTS, "feature_used (feature_name='kundali_generate')",
                joinable_to_next_stage=True, limitations=(),
            ),
            WebsiteFunnelStage(
                "App Download Intent (if present)", SOURCE_ACTIVITY_EVENTS, "app_download_intent",
                joinable_to_next_stage=False,
                limitations=("Not a required/deterministic next step -- a download intent after "
                              "Kundali generation is a plausible but not guaranteed user path.",),
            ),
        ),
    ),
    WebsiteFunnel(
        "paid_report", "Paid Report Funnel",
        (
            WebsiteFunnelStage(
                "Report Discovery", SOURCE_ACTIVITY_EVENTS, "report_discovery_viewed",
                joinable_to_next_stage=True, limitations=(),
            ),
            WebsiteFunnelStage(
                "Purchase Intent", SOURCE_ACTIVITY_EVENTS, "cta_click (cta_id='report_catalog_buy_now')",
                joinable_to_next_stage=False,
                limitations=("The checkout form (ReportCheckout.tsx) is not itself instrumented; "
                              "the gap to the next stage is real and backend-verified only.",),
            ),
            WebsiteFunnelStage(
                "Payment Verified", SOURCE_BACKEND_BUSINESS_TABLE, "payment_verified (purpose='REPORT_PURCHASE')",
                joinable_to_next_stage=True, limitations=(),
            ),
            WebsiteFunnelStage(
                "Report Generation Completed", SOURCE_BACKEND_BUSINESS_TABLE,
                "report_generation_completed (entity_type='order')",
                joinable_to_next_stage=False, limitations=(),
            ),
        ),
    ),
    WebsiteFunnel(
        "subscription", "Subscription Funnel",
        (
            WebsiteFunnelStage(
                "Subscription Discovery", SOURCE_ACTIVITY_EVENTS, "subscription_discovery_viewed",
                joinable_to_next_stage=False,
                limitations=("BLOCKED at the source: no live website discovery surface exists to "
                              "produce this event at all (see subscription_discovery_views_website).",),
            ),
            WebsiteFunnelStage(
                "Pending/Trial (if applicable)", SOURCE_BACKEND_BUSINESS_TABLE,
                "subscription_pending_created / subscription_trial_started",
                joinable_to_next_stage=False, limitations=("No shared correlation key to the discovery stage.",),
            ),
            WebsiteFunnelStage(
                "Subscription Started", SOURCE_BACKEND_BUSINESS_TABLE, "subscription_started",
                joinable_to_next_stage=False, limitations=(),
            ),
        ),
    ),
    WebsiteFunnel(
        "ask_now", "Ask Now Funnel",
        (
            WebsiteFunnelStage(
                "Ask Now Entry", SOURCE_ACTIVITY_EVENTS, "asknow_entry_viewed",
                joinable_to_next_stage=False,
                limitations=("No website Ask Now entry point exists -- this stage is app-only today.",),
            ),
            WebsiteFunnelStage(
                "Question Submitted", SOURCE_BACKEND_BUSINESS_TABLE, "asknow_question_submitted",
                joinable_to_next_stage=True, limitations=(),
            ),
            WebsiteFunnelStage(
                "Answer Delivered", SOURCE_BACKEND_BUSINESS_TABLE, "asknow_answer_delivered",
                joinable_to_next_stage=False,
                limitations=("ASKNOW_ATTEMPT_LINKAGE_LIMITATION (Phase 6B) -- no correlation_id/entity_id "
                              "ties a specific question to its specific answer.",),
            ),
            WebsiteFunnelStage(
                "Purchase (where applicable)", SOURCE_BACKEND_BUSINESS_TABLE,
                "payment_verified (purpose='ASK_NOW_CHAT_PACK')",
                joinable_to_next_stage=False, limitations=(),
            ),
        ),
    ),
)


def get_metric(metric_id: str) -> WebsiteMetricDefinition:
    for metric in WEBSITE_METRIC_CATALOG:
        if metric.metric_id == metric_id:
            return metric
    raise KeyError(f"Unknown website metric_id: {metric_id!r}")
