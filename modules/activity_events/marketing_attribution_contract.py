# modules/activity_events/marketing_attribution_contract.py

"""
Task 10 -- the FROZEN marketing attribution metrics contract. Declarative
only, following the exact architectural pattern Task 9 established in
website_metrics_contract.py (which this module imports its source/
quality-status vocabulary from, rather than redefining it -- Task 10 S26
"do not create a competing status vocabulary"): WHAT each attribution
metric means, WHICH system/field produces it, HOW it is counted, and its
CURRENT measurability -- before any query/API/dashboard work begins.
No SQL, no GA4 Data API, no new event producer, no gclid/fbclid
persistence.

==================================================================
FROZEN VOCABULARY (Task 10 S2) -- five distinct concepts, never used
interchangeably by any future dashboard/API code this contract governs:
==================================================================
  TRAFFIC ACQUISITION       -- how a website SESSION arrived (GA4-owned:
                                Organic Search/Direct/Referral/Paid
                                Search/Paid Social, sessions/users).
  CAMPAIGN ATTRIBUTION       -- captured source/medium/campaign context
                                associated with a first-party website
                                EVENT (activity_events.campaign_context;
                                Task 2C, session-scoped, first-touch).
  LANDING PAGE               -- the first page of the session (Task 2C's
                                own `landingPage`) -- NEVER transmitted
                                to the backend (see S3 finding below).
  ACTION PAGE                -- properties.page_path (Task 9A): the page
                                a specific product action occurred on.
  CONVERSION ATTRIBUTION      -- linking an acquisition/campaign to an
                                actual COMMERCIAL conversion (payment_
                                verified, subscription_started, etc.) --
                                see FINANCIAL_CONVERSION_ATTRIBUTION_GAP.

TRAFFIC ACQUISITION != CAMPAIGN ATTRIBUTION: the former counts SESSIONS
by GA4's own channel model; the latter counts EVENTS (product actions)
that happen to carry a first-party campaign_context. "How many recorded
product actions carried source X" is never the same question as "how
many sessions came from channel X" -- different systems, different
denominators, different population (Task 10 S7, frozen).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from modules.activity_events.analytics_models import AnalyticsLimitation
from modules.activity_events.website_metrics_contract import (
    SOURCE_GA4_EXTERNAL,
    SOURCE_ACTIVITY_EVENTS,
    SOURCE_BACKEND_BUSINESS_TABLE,
    METRIC_SOURCES,
    QUALITY_READY,
    QUALITY_PARTIAL,
    QUALITY_BLOCKED,
    QUALITY_GA4_EXTERNAL,
    METRIC_QUALITY_STATUSES,
    ZERO_SEMANTIC_MEASURED_ZERO,
    ZERO_SEMANTIC_UNAVAILABLE,
    ZERO_SEMANTIC_UNKNOWN_DIMENSION,
    TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT,
    TIME_BASIS_GA4_REPORTING_TIME,
    STANDARD_DASHBOARD_PERIODS,
    CROSS_SOURCE_JOIN_POLICY,
    DIMENSION_AVAILABLE,
    DIMENSION_PARTIAL,
    DIMENSION_UNAVAILABLE,
    DIMENSION_STATUSES,
)

# =======================================================================
# Attribution concept vocabulary (Task 10 S2) -- machine-readable, so a
# test can assert the 5 concepts are distinct and named exactly once.
# =======================================================================
CONCEPT_TRAFFIC_ACQUISITION = "traffic_acquisition"
CONCEPT_CAMPAIGN_ATTRIBUTION = "campaign_attribution"
CONCEPT_LANDING_PAGE = "landing_page"
CONCEPT_ACTION_PAGE = "action_page"
CONCEPT_CONVERSION_ATTRIBUTION = "conversion_attribution"

ATTRIBUTION_CONCEPTS = frozenset({
    CONCEPT_TRAFFIC_ACQUISITION,
    CONCEPT_CAMPAIGN_ATTRIBUTION,
    CONCEPT_LANDING_PAGE,
    CONCEPT_ACTION_PAGE,
    CONCEPT_CONVERSION_ATTRIBUTION,
})


# =======================================================================
# Task 2C attribution contract (Task 10 S3) -- audited, not re-derived.
# Kept here as frozen facts a marketing-attribution metric can cite;
# Task 2C's own source (lib/analyticsAttribution.ts) remains authoritative
# and is NOT modified by this task.
# =======================================================================
TASK_2C_ATTRIBUTION_CONTRACT = (
    "Captured ONCE per analytics session (browser tab lifetime), on first "
    "mount of WebsiteAnalyticsInit, via getOrCreateAttribution() -- read-once-"
    "then-persist: if a valid attribution object already exists in "
    "sessionStorage, it is returned UNCHANGED and the current URL/referrer/"
    "pathname are never re-consulted. Persisted under sessionStorage key "
    "'jyotishasha:analytics:attribution'. Captured fields: utmSource, "
    "utmMedium, utmCampaign (from the FIRST page's query string only), "
    "referrer (origin+path of the incoming HTTP referrer, first page only), "
    "landingPage (pathname of the first page only), and a locally-computed "
    "classification (direct/referral/campaign). SPA navigation after the "
    "first page NEVER updates any of these -- even if a later page in the "
    "same session carries new UTM parameters, they are ignored (first-touch "
    "wins, permanently, for the session's lifetime). A new browser tab or a "
    "new browsing session gets an entirely fresh capture (sessionStorage is "
    "tab-scoped, not shared across tabs or persisted across browser "
    "restarts). If sessionStorage is unavailable (blocked, disabled, "
    "private-mode quota, or any other access failure), getOrCreateAttribution() "
    "returns null and NO campaign_context is ever sent for that visit -- "
    "this is silently absent attribution, not a fabricated 'direct' label."
)

# The single most consequential audit finding of Task 10: verified by
# direct inspection of lib/analyticsAttribution.ts's own
# buildCampaignContextFromAttribution() -- it builds EXACTLY
# {utm_source?, utm_medium?, utm_campaign?, referrer?} and explicitly,
# by its own docstring, NEVER includes landingPage or classification (the
# backend's campaign_context envelope does not accept either key at all).
# Two direct consequences, both frozen below:
#   1. LANDING PAGE is a Task 2C browser-local-only concept -- it NEVER
#      reaches activity_events. "Product Actions by Landing Page" is
#      therefore BLOCKED at the source, not merely low-coverage.
#   2. The direct/referral/campaign CLASSIFICATION itself is also
#      browser-local-only and never reaches the backend -- the backend
#      only ever sees the raw utm_source/utm_medium/utm_campaign/referrer
#      values (or none of them). It has NO stored signal that ever
#      explicitly means "this was a direct visit" -- see
#      DIRECT_TRAFFIC_LIMITATION below.
LANDING_PAGE_NEVER_TRANSMITTED = True
CLASSIFICATION_NEVER_TRANSMITTED = True

CLASSIFICATION_NEVER_TRANSMITTED_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.classification",
    reason=(
        "lib/analyticsAttribution.ts computes a direct/referral/campaign "
        "classification locally (classifySourceMedium()) but "
        "buildCampaignContextFromAttribution() never includes it in the "
        "campaign_context sent to the backend -- verified by direct source "
        "read, Task 10. The backend therefore cannot reconstruct this "
        "classification from stored data; it can only see whether utm_* "
        "fields and/or referrer are present or absent on a given event."
    ),
)

LANDING_PAGE_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.landing_page",
    reason=(
        "landingPage is captured and persisted in the BROWSER's own "
        "sessionStorage (lib/analyticsAttribution.ts) but is never included "
        "in the campaign_context payload sent to the backend -- the backend's "
        "CAMPAIGN_CONTEXT_ALLOWED_KEYS does not even accept a landing_page "
        "key. No activity_events row, past or future (under the current "
        "contract), carries the session's landing page. 'Product Actions by "
        "Landing Page' is BLOCKED at the source, not a coverage gap."
    ),
)


# =======================================================================
# campaign_context field semantics (Task 10 S4) -- audited against
# modules/activity_events/event_schemas.py's own frozen
# CAMPAIGN_CONTEXT_ALLOWED_KEYS = {utm_source, utm_medium, utm_campaign,
# referrer, medium}.
# =======================================================================
@dataclass(frozen=True)
class CampaignContextFieldSemantics:
    field_name: str
    meaning: str
    currently_populated: bool
    notes: str


CAMPAIGN_CONTEXT_FIELD_CONTRACT: Tuple[CampaignContextFieldSemantics, ...] = (
    CampaignContextFieldSemantics(
        "utm_source", "The raw utm_source query-parameter value from the FIRST page of the session.",
        True,
        "Case-sensitive, trimmed, bounded at 256 chars (lib/analyticsAttribution.ts "
        "normalizeUtmValue()) -- never lowercased/canonicalized. See UTM_CASE_SENSITIVE.",
    ),
    CampaignContextFieldSemantics(
        "utm_medium", "The raw utm_medium query-parameter value from the FIRST page of the session.",
        True,
        "Same normalization (trim + 256-char bound) as utm_source. This is the field "
        "actually populated for 'medium' -- see the separate, unused 'medium' key below.",
    ),
    CampaignContextFieldSemantics(
        "utm_campaign", "The raw utm_campaign query-parameter value from the FIRST page of the session.",
        True,
        "Same normalization as utm_source.",
    ),
    CampaignContextFieldSemantics(
        "referrer", "Origin + path ONLY of the incoming HTTP referrer, captured on the FIRST page of the session.",
        True,
        "Never query/fragment/credentials -- see REFERRER_CONTRACT. Presence alone does "
        "NOT mean 'referral traffic' in a classified sense (see CLASSIFICATION_NEVER_"
        "TRANSMITTED_LIMITATION) -- it is the raw value only.",
    ),
    CampaignContextFieldSemantics(
        "medium", "Schema-allowed since Phase 2, intended (per event_schemas.py's own docstring) "
        "for a future channel/medium CLASSIFICATION distinct from the raw utm_medium value.",
        False,
        "AUDITED, CONFIRMED UNUSED: no current frontend producer ever sends a bare "
        "'medium' key -- lib/analyticsAttribution.ts's own docstring states explicitly "
        "'this task does not send a medium value at all -- no classification-to-medium "
        "mapping is invented here.' Do not confuse this always-empty key with the "
        "always-populated utm_medium key above; a future dashboard querying "
        "campaign_context.medium will find it always absent today.",
    ),
)

# activity_events.source (the envelope column) vs campaign_context.
# utm_source (a properties-adjacent JSONB field) -- two structurally and
# semantically DIFFERENT fields that happen to share the word "source."
# Frozen distinction, referenced by the dimension contract below.
ENVELOPE_SOURCE_VS_UTM_SOURCE = (
    "activity_events.source (envelope column, VARCHAR(64)) means 'which screen/service "
    "fired this event' -- a producer-context label, always caller-supplied or None, "
    "structurally unrelated to marketing traffic. campaign_context.utm_source is the "
    "ONLY marketing-traffic-source field. Never conflate the two: a future dashboard/ "
    "API must never read activity_events.source expecting a UTM value, and must never "
    "write a utm_source value into the source column. (event_schemas.py's own docstring "
    "separately documents a THIRD, unrelated collision: Ask Now's own required "
    "properties.source business value, meaning free|pack -- a third, independent use of "
    "the word 'source'. All three are distinct fields; none substitutes for another.)"
)


# =======================================================================
# Source classification (Task 10 S6) -- what the FRONTEND computes
# locally (never transmitted, see above) vs what the BACKEND can actually
# observe from stored data.
# =======================================================================
# The 3 values Task 2C's own classifySourceMedium() computes -- for
# documentation of the LOCAL-ONLY concept only; the backend never
# receives any of these labels (CLASSIFICATION_NEVER_TRANSMITTED).
FRONTEND_LOCAL_CLASSIFICATION_VALUES: Tuple[str, ...] = ("direct", "referral", "campaign")

# Explicitly NOT supportable from first-party stored data today -- GA4's
# own richer channel grouping owns these (Task 9 S7, Task 10 S7,
# reaffirmed). A future first-party classification engine, if ever built,
# is a distinct, separately-authorized task -- not implied by this list's
# mere existence here.
CHANNEL_GROUPING_VALUES_GA4_ONLY: Tuple[str, ...] = ("organic_search", "paid_search", "paid_social")


# =======================================================================
# Direct traffic (Task 10 S21) -- BLOCKED for first-party data, evidence-
# based (not assumed): see CLASSIFICATION_NEVER_TRANSMITTED_LIMITATION.
# =======================================================================
DIRECT_TRAFFIC_FIRST_PARTY_STATUS = QUALITY_BLOCKED

DIRECT_TRAFFIC_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.direct_traffic",
    reason=(
        "The backend has NO stored signal that ever explicitly means 'direct' -- "
        "classification is computed client-side only and never transmitted (see "
        "CLASSIFICATION_NEVER_TRANSMITTED_LIMITATION). An activity_events row with no "
        "campaign_context could be a genuinely direct visit, an old pre-Task-2C row, a "
        "session where sessionStorage was unavailable, or a producer call made before "
        "attribution capture ran -- these are indistinguishable in stored data. Per this "
        "task's own rule (label Direct ONLY where the stored contract explicitly "
        "indicates it), and since it never does, first-party Direct Traffic is BLOCKED, "
        "full stop, unless a future task explicitly transmits the classification. GA4's "
        "own Direct channel (GA4_EXTERNAL) is real, complete, and entirely unaffected."
    ),
)


# =======================================================================
# UTM normalization / casing (Task 10 S22) -- documented, not fixed.
# =======================================================================
UTM_CASE_SENSITIVE = True
UTM_TRIMMED = True
UTM_MAX_LENGTH = 256

UTM_CASING_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.utm_casing",
    reason=(
        "utm_source/utm_medium/utm_campaign are stored exactly as received after only "
        "trim + 256-char bound (lib/analyticsAttribution.ts normalizeUtmValue(); the "
        "backend's sanitize_campaign_context() applies no further normalization "
        "either). 'Google' and 'google', or 'Facebook' and 'facebook', are DISTINCT "
        "stored values today, not merged. A future dashboard grouping by source should "
        "canonicalize case at QUERY time, or accept this fragmentation -- this is a "
        "recommendation for a future task; Task 10 does not mutate Task 2C's stored "
        "semantics or historic rows."
    ),
)


# =======================================================================
# Referrer contract (Task 10 S20)
# =======================================================================
REFERRER_CONTRACT = (
    "Stores origin + path ONLY -- query string, fragment, and any userinfo/credentials "
    "are always stripped, independently, on BOTH sides: lib/analyticsAttribution.ts's "
    "normalizeReferrer() (frontend capture, Task 2C) and modules/activity_events."
    "anonymous_ingestion_service._normalize_referrer() (backend defense-in-depth, "
    "anonymous endpoint only -- Task 2B). External hosts ARE allowed and are the "
    "field's whole purpose (capturing an external referring site); non-http(s) schemes "
    "are rejected outright by both normalizers. Length bounded at 256 characters on "
    "both sides. This is not an arbitrary-URL store -- it is bounded, scheme-checked, "
    "and query/fragment-stripped by construction, not by a denylist alone."
)


# =======================================================================
# Paid channel click-ID readiness (Task 10 S23) -- distinct from UTM
# campaign readiness.
# =======================================================================
GCLID_CAPTURED = False
FBCLID_CAPTURED = False
FBC_CAPTURED = False
FBP_CAPTURED = False

UTM_CAMPAIGN_ATTRIBUTION_READY = True          # for browser-originated events only
AD_PLATFORM_CLICK_LEVEL_ATTRIBUTION_READY = False

PAID_CHANNEL_READINESS_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.paid_channel_click_id",
    reason=(
        "Confirmed absent (Task 6/7, re-verified by grep for this task -- zero matches "
        "anywhere in this backend for gclid/fbclid/_fbc/_fbp): no Google Ads click ID, "
        "no Meta click ID, and no Meta browser/click cookie value is ever captured or "
        "stored. Task 10's UTM-based marketing metrics (source/medium/campaign) ARE "
        "usable today. Google Ads / Meta CLICK-LEVEL conversion attribution (matching a "
        "specific ad click to a specific later conversion via their own platform APIs) "
        "is NOT ready and is out of this task's scope entirely (no credentials, no "
        "Conversions API, no Google Ads offline-conversion upload exist)."
    ),
)


# =======================================================================
# App Download Intent campaign meaning (Task 10 S12)
# =======================================================================
APP_DOWNLOAD_INTENT_CAMPAIGN_MEANING = (
    "app_download_intent + campaign_context together mean EXACTLY: a website visitor, "
    "under a captured first-touch campaign context (if any), clicked an in-page CTA "
    "expressing intent to open/download the app. This does NOT prove: the visitor "
    "reached the Play Store listing, an install occurred, GA4/Firebase recorded a "
    "first_open, a signup happened, or any purchase occurred. Each of those is a "
    "separate, independently-measured fact -- install/first_open volume is GA4/"
    "Firebase's own domain entirely (GA4_EXTERNAL), not derivable from this event."
)


# =======================================================================
# Attributed Android Acquisition (Task 10 S13) -- audited against
# jyotishasha_appF's InstallAttributionProducer.buildCampaignContext()
# (Flutter, READ-ONLY per this task's own instruction).
# =======================================================================
ATTRIBUTED_ANDROID_ACQUISITION_LABEL = "Attributed Android Acquisition"  # NEVER "Installs"

ATTRIBUTED_ANDROID_ACQUISITION_FIELDS: Tuple[str, ...] = ("utm_source", "utm_medium", "utm_campaign")

ATTRIBUTED_ANDROID_ACQUISITION_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.attributed_android_acquisition",
    reason=(
        "app_install_attributed's campaign_context carries EXACTLY utm_source/"
        "utm_medium/utm_campaign (confirmed by direct read of jyotishasha_appF's "
        "InstallAttributionProducer.buildCampaignContext() -- no referrer, no "
        "cta_location, no medium, no session_id). This is Google Play install "
        "ATTRIBUTION captured by the app and associated with an authenticated app "
        "lifecycle (Task 5A's own frozen meaning) -- NEVER a raw install counter and "
        "NEVER GA4/Firebase first_open. GA4/Firebase first_open remains the "
        "authoritative install/first-open VOLUME source (GA4_EXTERNAL); this metric "
        "answers a campaign-ATTRIBUTION question, not a volume question."
    ),
)


# =======================================================================
# Website -> app cross-surface joinability (Task 10 S14)
# =======================================================================
WEBSITE_TO_APP_DETERMINISTIC_JOIN_POSSIBLE = False

WEBSITE_TO_APP_JOIN_POLICY = (
    "AGGREGATE CAMPAIGN-LEVEL COMPARISON ONLY, NEVER USER/SESSION-LEVEL. Task 5 "
    "deliberately never transmits the website's own session_id through the Play "
    "Store referrer chain (lib/playStoreAttribution.ts's own explicit prohibition, "
    "re-verified for this task) -- there is no shared identifier between a specific "
    "app_download_intent row and a specific app_install_attributed row. A dashboard "
    "MAY show 'Website App Download Intents by Campaign' beside 'Attributed Android "
    "Acquisitions by Campaign' for the SAME utm_campaign string, as an aggregate "
    "funnel INDICATOR -- both sides happen to reuse the same developer-authored "
    "campaign name constants, so a shared string is a coincidence of convention, not "
    "a verified or guaranteed join key (also subject to UTM_CASING_LIMITATION). It "
    "must NEVER be presented as 'N website visitors installed the app' -- that "
    "specific, user-level claim is not supportable by any data this system collects. "
    "This is a narrower, campaign-attribution-specific instance of the general "
    "CROSS_SOURCE_JOIN_POLICY frozen in Task 9, re-affirmed here."
)


# =======================================================================
# FINANCIAL CONVERSION ATTRIBUTION GAP (Task 10 S15 -- critical)
# =======================================================================
FINANCIAL_CONVERSION_ATTRIBUTION_GAP_CONFIRMED = True

FINANCIAL_CONVERSION_ATTRIBUTION_GAP = (
    "CONFIRMED via direct source audit, not assumed: grepped every backend-"
    "authoritative conversion producer for 'campaign_context' -- zero matches in "
    "modules/payments/payment_service.py (payment_initiated/payment_verified/"
    "payment_failed), modules/entitlement/entitlement_write_service.py "
    "(subscription_started and the rest of the subscription lifecycle), modules/"
    "ai_report_engine/lifecycle_manager.py (report_generation_started/completed/"
    "failed), and modules/services/chat_pack_service.py (Ask Now purchase). None of "
    "these ever pass campaign_context to record_event() -- confirmed by reading "
    "modules/activity_events/service.py's own record_event() signature (campaign_"
    "context defaults to None, stored NULL unless a caller explicitly supplies it) "
    "and finding no such caller among any backend-internal conversion producer. This "
    "is ARCHITECTURAL, not incidental: these events fire from payment webhooks and "
    "backend business logic, which has no browser session/UTM context available to "
    "it at write time -- campaign_context only ever flows from a browser-originated "
    "ingestion request (anonymous or authenticated), never from a backend-internal "
    "call site. CONSEQUENCE: revenue cannot currently be attributed to a marketing "
    "campaign for report purchases, subscription starts, or Ask Now purchases. No "
    "campaign ROAS, CPA, or 'revenue by campaign' metric is possible for ANY vertical "
    "today."
)

# Per-vertical breakdown, explicitly requested (Task 10 S15) -- all three
# TRUE (gap confirmed) as of this audit.
REPORT_PURCHASE_CAMPAIGN_ATTRIBUTION_GAP = True
ASKNOW_PURCHASE_CAMPAIGN_ATTRIBUTION_GAP = True
SUBSCRIPTION_START_CAMPAIGN_ATTRIBUTION_GAP = True


# =======================================================================
# Intent vs verified conversion (Task 10 S16) -- reaffirms Task 9's own
# frozen distinctions, restated here as a structured, testable tuple.
# =======================================================================
@dataclass(frozen=True)
class IntentVsConversionPair:
    intent_metric: str
    conversion_fact: str
    note: str


INTENT_VS_CONVERSION_PAIRS: Tuple[IntentVsConversionPair, ...] = (
    IntentVsConversionPair("report_purchase_intent", "report_payment_verified",
                            "A cta_click is never a payment."),
    IntentVsConversionPair("subscription_discovery_viewed", "subscription_started",
                            "Viewing a paywall/discovery surface is never a started subscription."),
    IntentVsConversionPair("app_download_intent", "app_install_attributed / GA4 first_open",
                            "A click toward the store is never an install."),
    IntentVsConversionPair("cta_click", "any verified backend conversion",
                            "A CTA click alone is never, by itself, a conversion."),
)


# =======================================================================
# Report / Ask Now / Subscription attribution verdicts (Task 10 S17-19)
# =======================================================================
REPORT_DISCOVERY_CAMPAIGN_ATTRIBUTION_STATUS = QUALITY_PARTIAL     # website event, has campaign_context, first-touch coverage only
REPORT_PURCHASE_INTENT_CAMPAIGN_ATTRIBUTION_STATUS = QUALITY_PARTIAL  # same -- cta_click, website event
REPORT_PAYMENT_VERIFIED_CAMPAIGN_ATTRIBUTION_STATUS = QUALITY_BLOCKED   # financial gap
REPORT_GENERATION_CAMPAIGN_ATTRIBUTION_STATUS = QUALITY_BLOCKED          # financial gap

REPORT_ATTRIBUTION_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.report_purchase_intent",
    reason=(
        "report_discovery_viewed and the report_catalog_buy_now cta_click are both "
        "browser-originated website events and DO carry campaign_context when Task 2C "
        "captured one -- PARTIAL, not READY, purely due to normal first-touch coverage "
        "limits (a direct/no-campaign visit has none). payment_verified and "
        "report_generation_completed are backend-authoritative and carry NO campaign "
        "attribution at all (FINANCIAL_CONVERSION_ATTRIBUTION_GAP). Report purchase "
        "INTENT must never be called 'report sales' -- sales/revenue requires the "
        "verified-payment side, which has no campaign attribution today."
    ),
)

ASKNOW_WEBSITE_ATTRIBUTION_STATUS = QUALITY_BLOCKED
ASKNOW_WEBSITE_ATTRIBUTION_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.asknow_website",
    reason=(
        "Preserved from Task 9's own finding, re-verified for this task (no code "
        "change found): the website has NO Ask Now producer/surface at all -- "
        "ANONYMOUS_WEBSITE_EVENTS (modules/activity_events/anonymous_ingestion_"
        "policy.py) contains no asknow_* event. Backend/app Ask Now commercial events "
        "exist but must never be presented as WEBSITE campaign attribution -- there is "
        "no website-origin Ask Now event to attribute in the first place."
    ),
)

SUBSCRIPTION_WEBSITE_ATTRIBUTION_STATUS = QUALITY_BLOCKED
SUBSCRIPTION_WEBSITE_ATTRIBUTION_LIMITATION = AnalyticsLimitation(
    metric="marketing_attribution.subscription_website",
    reason=(
        "Preserved from Task 9's own finding, re-verified for this task (no code "
        "change found -- components/UpgradeButton.tsx and HoroscopeComparison.tsx "
        "remain unreferenced/unrendered anywhere): no live website subscription-"
        "discovery surface exists to originate a campaign-attributed website event "
        "from. A future campaign->subscription relationship is not invented here."
    ),
)


# =======================================================================
# Attribution coverage (Task 10 S10/S11) -- the exact, frozen formula.
# =======================================================================
USABLE_ATTRIBUTION_FIELDS = frozenset({"utm_source", "utm_medium", "utm_campaign"})

ATTRIBUTION_STATUS_ATTRIBUTED = "ATTRIBUTED"
ATTRIBUTION_STATUS_UNATTRIBUTED = "UNATTRIBUTED"
ATTRIBUTION_STATUS_UNKNOWN = "UNKNOWN"

ATTRIBUTION_STATUSES = frozenset({
    ATTRIBUTION_STATUS_ATTRIBUTED,
    ATTRIBUTION_STATUS_UNATTRIBUTED,
    ATTRIBUTION_STATUS_UNKNOWN,
})


def is_usable_campaign_attribution(campaign_context: Optional[dict]) -> bool:
    """Pure. True iff campaign_context carries at least one non-empty
    value among utm_source/utm_medium/utm_campaign. A bare referrer with
    no UTM value does NOT count (Task 10 S11: 'do not count page_path
    alone as campaign attribution' -- the same reasoning applies to a
    bare referrer: reconstructing a meaningful classification from it
    alone would require redoing classifySourceMedium()'s same-origin
    check server-side, which nothing currently does -- see
    CLASSIFICATION_NEVER_TRANSMITTED_LIMITATION). Never raises."""
    if not campaign_context:
        return False
    return any(campaign_context.get(field) for field in USABLE_ATTRIBUTION_FIELDS)


def classify_attribution(campaign_context: Optional[dict]) -> str:
    """Pure. Returns one of ATTRIBUTION_STATUS_ATTRIBUTED /
    ATTRIBUTION_STATUS_UNATTRIBUTED for a single event's campaign_context.
    Never returns ATTRIBUTION_STATUS_UNKNOWN itself -- UNKNOWN is reserved
    for a DIMENSION being requested but uncategorized on an otherwise-
    attributed row (e.g. grouping by campaign when only utm_source was
    sent), not for this event-level attributed/unattributed check."""
    return ATTRIBUTION_STATUS_ATTRIBUTED if is_usable_campaign_attribution(campaign_context) else ATTRIBUTION_STATUS_UNATTRIBUTED


ATTRIBUTION_COVERAGE_DEFINITION = (
    "Attribution Coverage % = "
    "(count of eligible events where is_usable_campaign_attribution(campaign_context) "
    "is True) / (count of ALL eligible events in the same metric population -- "
    "ATTRIBUTED and UNATTRIBUTED alike) x 100. The denominator is EVERY eligible "
    "event, never narrowed to only those carrying campaign_context (that would make "
    "coverage trivially 100% and hide the real gap). 'Usable attribution' means "
    "campaign_context contains at least one non-empty value among utm_source/"
    "utm_medium/utm_campaign -- see is_usable_campaign_attribution(). Unattributed "
    "events are NEVER dropped from any total; they remain a legitimate, counted "
    "bucket in every metric that reports a total alongside a by-source/medium/"
    "campaign breakdown."
)


# =======================================================================
# Zero / null / unknown / unattributed semantics (Task 10 S30) -- reuses
# Task 9's own frozen vocabulary; unattributed is an ADDITIONAL,
# attribution-specific bucket, not a replacement for it.
# =======================================================================
UNATTRIBUTED_IS_LEGITIMATE_BUCKET = True
UNATTRIBUTED_NEVER_DROPPED_FROM_TOTALS = True


# =======================================================================
# Time contract (Task 10 S29) -- unchanged from Task 9, re-imported not
# redefined (TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT, TIME_BASIS_GA4_
# REPORTING_TIME, STANDARD_DASHBOARD_PERIODS above).
# =======================================================================


# =======================================================================
# Dimension contract (Task 10 S27)
# =======================================================================
@dataclass(frozen=True)
class DimensionAvailability:
    dimension_id: str
    status: str
    source_field: str
    notes: str


MARKETING_ATTRIBUTION_DIMENSION_CATALOG: Tuple[DimensionAvailability, ...] = (
    DimensionAvailability(
        "source", DIMENSION_PARTIAL, "activity_events.campaign_context.utm_source",
        "First-touch-per-session only (Task 2C); absent for direct/no-campaign visits "
        "by design, and absent for every row whose sessionStorage capture failed.",
    ),
    DimensionAvailability(
        "medium", DIMENSION_PARTIAL, "activity_events.campaign_context.utm_medium",
        "Same first-touch-only availability as source. NOT the schema's separate, "
        "always-empty bare 'medium' key (see CAMPAIGN_CONTEXT_FIELD_CONTRACT) -- that "
        "one is UNAVAILABLE (schema-allowed, never populated).",
    ),
    DimensionAvailability(
        "campaign", DIMENSION_PARTIAL, "activity_events.campaign_context.utm_campaign",
        "Same first-touch-only availability as source.",
    ),
    DimensionAvailability(
        "referrer", DIMENSION_PARTIAL, "activity_events.campaign_context.referrer",
        "Origin+path only (REFERRER_CONTRACT); first-touch-only; raw value, not a "
        "classified 'referral' label (see CLASSIFICATION_NEVER_TRANSMITTED_LIMITATION).",
    ),
    DimensionAvailability(
        "landing_page", DIMENSION_UNAVAILABLE, "(none -- never transmitted)",
        "See LANDING_PAGE_LIMITATION -- captured locally by Task 2C, never sent to the "
        "backend. No activity_events row carries it under the current contract.",
    ),
    DimensionAvailability(
        "page_path", DIMENSION_AVAILABLE, "activity_events.properties.page_path",
        "Task 9A -- call-time action page, on cta_click/feature_used/app_download_"
        "intent/report_discovery_viewed. Absent on rows written before Task 9A shipped.",
    ),
    DimensionAvailability(
        "cta_id", DIMENSION_AVAILABLE, "activity_events.properties.cta_id",
        "Present on every cta_click row (frozen schema requirement).",
    ),
    DimensionAvailability(
        "cta_location", DIMENSION_AVAILABLE, "activity_events.properties.cta_location",
        "Present on every app_download_intent row (frozen schema requirement).",
    ),
    DimensionAvailability(
        "feature_name", DIMENSION_PARTIAL, "activity_events.properties.feature_name",
        "Available on feature_used rows; coverage itself is partial -- only "
        "kundali_generate is currently produced by any website call site.",
    ),
    DimensionAvailability(
        "report_type", DIMENSION_UNAVAILABLE, "activity_events.properties.report_type",
        "Schema-allowed but report_discovery_viewed's current website producer sends "
        "no properties at all (Task 9 finding, unchanged).",
    ),
    DimensionAvailability(
        "platform", DIMENSION_AVAILABLE, "activity_events.platform",
        "Server-forced 'website' for every anonymous-endpoint row.",
    ),
    DimensionAvailability(
        "environment", DIMENSION_AVAILABLE, "activity_events.environment",
        "Structurally fixed to 'production' for every real query -- never caller-supplied.",
    ),
)

# Within-row combination of page_path and campaign_context (Page x
# Attribution metrics, Task 10 S9) is a DETERMINISTIC, same-row join by
# construction -- both live as columns/JSONB-keys on the SAME
# activity_events row. This is explicitly NOT the class of join
# CROSS_SOURCE_JOIN_POLICY restricts (that policy governs crossing GA4
# and first-party as two SEPARATE systems/rows); no additional
# uncertainty is introduced beyond each dimension's own already-stated
# coverage (page_path's own availability x campaign_context's own
# first-touch coverage).
PAGE_TIMES_ATTRIBUTION_JOIN_IS_WITHIN_ROW = True


# =======================================================================
# Filter contract (Task 10 S28) -- closed vocabulary. Deliberately
# excludes `referrer` as a filter (free-form external host+path values,
# borderline-identifying at high cardinality) and excludes `landing_page`
# (unavailable -- see above); no raw JSON-path filter of any kind.
# =======================================================================
ALLOWED_MARKETING_ATTRIBUTION_FILTERS: Tuple[str, ...] = (
    "date_range",
    "source",
    "medium",
    "campaign",
    "page_path",
    "event_name",
    "cta_id",
    "feature_name",
    "platform",
)


# =======================================================================
# The metric catalog itself (Task 10 S5/S9/S24)
# =======================================================================
@dataclass(frozen=True)
class MarketingAttributionMetricDefinition:
    metric_id: str
    display_name: str
    source: str
    definition: str
    event_population: str
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


_LEDGER_TIME = TIME_BASIS_ACTIVITY_EVENTS_OCCURRED_AT
_GA4_TIME = TIME_BASIS_GA4_REPORTING_TIME

MARKETING_ATTRIBUTION_METRIC_CATALOG: Tuple[MarketingAttributionMetricDefinition, ...] = (

    # ---- Attribution coverage (Task 10 S10/S11) ----
    MarketingAttributionMetricDefinition(
        "product_actions_total", "Total Product Actions", SOURCE_ACTIVITY_EVENTS,
        "Every website-origin, ledger-eligible activity_events row in the period -- the "
        "denominator for attribution coverage.",
        "cta_click, feature_used, app_download_intent, report_discovery_viewed rows, platform='website'.",
        "COUNT(*) over the event population above, regardless of campaign_context presence.",
        _LEDGER_TIME, ("date_range", "event_name"), QUALITY_READY,
    ),
    MarketingAttributionMetricDefinition(
        "product_actions_attributed", "Attributed Product Actions", SOURCE_ACTIVITY_EVENTS,
        "Subset of product_actions_total where is_usable_campaign_attribution() is True.",
        "Same population as product_actions_total.",
        "COUNT(*) WHERE campaign_context contains a non-empty utm_source, utm_medium, or utm_campaign.",
        _LEDGER_TIME, ("date_range", "event_name"), QUALITY_PARTIAL,
        ("First-touch-per-session coverage only (Task 2C) -- never claims a session's true acquisition channel, only that a first-party campaign_context happened to be captured and attached.",),
    ),
    MarketingAttributionMetricDefinition(
        "product_actions_unattributed", "Unattributed Product Actions", SOURCE_ACTIVITY_EVENTS,
        "product_actions_total minus product_actions_attributed -- a legitimate, always-reported bucket, never dropped.",
        "Same population as product_actions_total.",
        "COUNT(*) WHERE is_usable_campaign_attribution() is False.",
        _LEDGER_TIME, ("date_range", "event_name"), QUALITY_READY,
        ("Does NOT mean 'direct' -- see DIRECT_TRAFFIC_LIMITATION. Means only 'no usable campaign_context was persisted for this row'.",),
    ),
    MarketingAttributionMetricDefinition(
        "attribution_coverage_pct", "Attribution Coverage %", SOURCE_ACTIVITY_EVENTS,
        "product_actions_attributed / product_actions_total x 100 -- see ATTRIBUTION_COVERAGE_DEFINITION.",
        "Same population as product_actions_total.",
        "compute_rate(product_actions_attributed, product_actions_total) x 100; denominator=0 -> unavailable, never 0%.",
        _LEDGER_TIME, ("date_range", "event_name"), QUALITY_PARTIAL,
        ("Inherits product_actions_attributed's own PARTIAL coverage limitation.",),
    ),

    # ---- Product Actions by source/medium/campaign (Task 10 S5) ----
    MarketingAttributionMetricDefinition(
        "product_actions_by_source", "Product Actions by Source", SOURCE_ACTIVITY_EVENTS,
        "Attributed product actions grouped by campaign_context.utm_source.",
        "cta_click, feature_used, app_download_intent, report_discovery_viewed rows, platform='website'.",
        "COUNT(*) GROUP BY campaign_context.utm_source, restricted to attributed rows only.",
        _LEDGER_TIME, ("date_range", "source", "event_name"), QUALITY_PARTIAL,
        ("Answers 'how many recorded product actions carried source X', never 'how many sessions came from channel X' -- GA4 Sessions by Source is the distinct, GA4_EXTERNAL answer to that question (Task 10 S7).",),
    ),
    MarketingAttributionMetricDefinition(
        "product_actions_by_medium", "Product Actions by Medium", SOURCE_ACTIVITY_EVENTS,
        "Attributed product actions grouped by campaign_context.utm_medium.",
        "Same population as product_actions_by_source.",
        "COUNT(*) GROUP BY campaign_context.utm_medium, restricted to attributed rows only.",
        _LEDGER_TIME, ("date_range", "medium", "event_name"), QUALITY_PARTIAL,
    ),
    MarketingAttributionMetricDefinition(
        "product_actions_by_campaign", "Product Actions by Campaign", SOURCE_ACTIVITY_EVENTS,
        "Attributed product actions grouped by campaign_context.utm_campaign.",
        "Same population as product_actions_by_source.",
        "COUNT(*) GROUP BY campaign_context.utm_campaign, restricted to attributed rows only.",
        _LEDGER_TIME, ("date_range", "campaign", "event_name"), QUALITY_PARTIAL,
        ("Subject to UTM_CASING_LIMITATION -- 'Hero' and 'hero' group separately today.",),
    ),

    # ---- CTA attribution ----
    MarketingAttributionMetricDefinition(
        "cta_clicks_by_source", "CTA Clicks by Source", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows grouped by campaign_context.utm_source.",
        "cta_click rows, platform='website'.",
        "COUNT(*) GROUP BY campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "source", "cta_id"), QUALITY_READY,
        ("READY because cta_click's own total coverage is already complete (both live call sites tracked, Task 9) -- only the SOURCE breakdown is bounded by attribution coverage, documented separately via attribution_coverage_pct.",),
    ),
    MarketingAttributionMetricDefinition(
        "cta_clicks_by_medium", "CTA Clicks by Medium", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows grouped by campaign_context.utm_medium.",
        "cta_click rows, platform='website'.",
        "COUNT(*) GROUP BY campaign_context.utm_medium, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "medium", "cta_id"), QUALITY_READY,
    ),
    MarketingAttributionMetricDefinition(
        "cta_clicks_by_campaign", "CTA Clicks by Campaign", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows grouped by campaign_context.utm_campaign.",
        "cta_click rows, platform='website'.",
        "COUNT(*) GROUP BY campaign_context.utm_campaign, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "campaign", "cta_id"), QUALITY_READY,
    ),

    # ---- Tool attribution ----
    MarketingAttributionMetricDefinition(
        "tool_completions_by_source", "Tool Completions by Source", SOURCE_ACTIVITY_EVENTS,
        "feature_used rows grouped by campaign_context.utm_source.",
        "feature_used rows, platform='website'.",
        "COUNT(*) GROUP BY campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "source", "feature_name"), QUALITY_PARTIAL,
        ("PARTIAL for the same reason as tool_completions_all (Task 9): only Free Kundali (kundali_generate) is currently produced -- unrelated to and unchanged by attribution coverage itself.",),
    ),

    # ---- App Download Intent attribution ----
    MarketingAttributionMetricDefinition(
        "app_download_intents_by_source", "App Download Intents by Source", SOURCE_ACTIVITY_EVENTS,
        "app_download_intent rows grouped by campaign_context.utm_source. See APP_DOWNLOAD_INTENT_CAMPAIGN_MEANING for the exact, limited claim this metric supports.",
        "app_download_intent rows, platform='website'.",
        "COUNT(*) GROUP BY campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "source", "cta_location"), QUALITY_READY,
    ),
    MarketingAttributionMetricDefinition(
        "app_download_intents_by_medium", "App Download Intents by Medium", SOURCE_ACTIVITY_EVENTS,
        "app_download_intent rows grouped by campaign_context.utm_medium.",
        "app_download_intent rows, platform='website'.",
        "COUNT(*) GROUP BY campaign_context.utm_medium, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "medium", "cta_location"), QUALITY_READY,
    ),

    # ---- Report purchase-intent attribution ----
    MarketingAttributionMetricDefinition(
        "report_purchase_intents_by_source", "Report Purchase Intents by Source", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows where cta_id='report_catalog_buy_now', grouped by campaign_context.utm_source. NEVER 'report sales' -- see REPORT_ATTRIBUTION_LIMITATION.",
        "cta_click rows where properties.cta_id='report_catalog_buy_now'.",
        "COUNT(*) GROUP BY campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "source"), QUALITY_PARTIAL,
        ("PARTIAL: attribution coverage bound, not a coverage-of-CTA-instrumentation gap.",),
    ),
    MarketingAttributionMetricDefinition(
        "report_purchase_intents_by_campaign", "Report Purchase Intents by Campaign", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows where cta_id='report_catalog_buy_now', grouped by campaign_context.utm_campaign.",
        "cta_click rows where properties.cta_id='report_catalog_buy_now'.",
        "COUNT(*) GROUP BY campaign_context.utm_campaign, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "campaign"), QUALITY_PARTIAL,
    ),

    # ---- Page x attribution (Task 10 S9) ----
    MarketingAttributionMetricDefinition(
        "cta_clicks_by_page_and_source", "CTA Clicks by Page + Source", SOURCE_ACTIVITY_EVENTS,
        "cta_click rows grouped by BOTH properties.page_path and campaign_context.utm_source (within-row combination, see PAGE_TIMES_ATTRIBUTION_JOIN_IS_WITHIN_ROW).",
        "cta_click rows, platform='website'.",
        "COUNT(*) GROUP BY properties.page_path, campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "page_path", "source", "cta_id"), QUALITY_PARTIAL,
        ("Bounded by attribution_coverage_pct AND by page_path only existing on rows written after Task 9A shipped.",),
    ),
    MarketingAttributionMetricDefinition(
        "tool_completions_by_page_and_source", "Tool Completions by Page + Source", SOURCE_ACTIVITY_EVENTS,
        "feature_used rows grouped by BOTH properties.page_path and campaign_context.utm_source.",
        "feature_used rows, platform='website'.",
        "COUNT(*) GROUP BY properties.page_path, campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "page_path", "source", "feature_name"), QUALITY_PARTIAL,
        ("Compounds tool_completions_by_source's own tool-coverage PARTIAL status with the page_path/attribution coverage bounds.",),
    ),
    MarketingAttributionMetricDefinition(
        "app_download_intents_by_page_and_source", "App Download Intents by Page + Source", SOURCE_ACTIVITY_EVENTS,
        "app_download_intent rows grouped by BOTH properties.page_path and campaign_context.utm_source.",
        "app_download_intent rows, platform='website'.",
        "COUNT(*) GROUP BY properties.page_path, campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "page_path", "source", "cta_location"), QUALITY_PARTIAL,
        ("page_path coverage itself is READY (Task 9A) for this event -- PARTIAL here is solely the attribution-coverage bound, not a page_path gap.",),
    ),
    MarketingAttributionMetricDefinition(
        "report_purchase_intents_by_page_and_source", "Report Purchase Intents by Page + Source", SOURCE_ACTIVITY_EVENTS,
        "report_catalog_buy_now cta_click rows grouped by BOTH properties.page_path and campaign_context.utm_source.",
        "cta_click rows where properties.cta_id='report_catalog_buy_now'.",
        "COUNT(*) GROUP BY properties.page_path, campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "page_path", "source"), QUALITY_PARTIAL,
    ),

    # ---- GA4-owned acquisition, for contrast (Task 10 S7) ----
    MarketingAttributionMetricDefinition(
        "ga4_sessions_by_source", "GA4 Sessions by Source", SOURCE_GA4_EXTERNAL,
        "GA4's own Sessions metric, dimensioned by its own Source/Medium channel model. The traffic-acquisition answer 'how many sessions came from channel X' -- distinct from and never substitutable by product_actions_by_source.",
        "GA4 property, all sessions.",
        "GA4's own canonical Sessions-by-Source-dimension count.",
        _GA4_TIME, ("date_range",), QUALITY_GA4_EXTERNAL,
    ),

    # ---- Attributed Android Acquisition (Task 10 S13) ----
    MarketingAttributionMetricDefinition(
        "attributed_android_acquisitions_by_source", "Attributed Android Acquisitions by Source", SOURCE_ACTIVITY_EVENTS,
        "app_install_attributed rows grouped by campaign_context.utm_source. Label is 'Attributed Android Acquisition' -- NEVER 'Installs'. See ATTRIBUTED_ANDROID_ACQUISITION_LIMITATION.",
        "app_install_attributed rows, platform='app_android'.",
        "COUNT(*) GROUP BY campaign_context.utm_source, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "source"), QUALITY_PARTIAL,
        ("Requires the install to reach an authenticated app lifecycle before capture (Task 5A) -- an install that never signs in is never counted here. GA4/Firebase first_open remains the install-VOLUME authority.",),
    ),
    MarketingAttributionMetricDefinition(
        "attributed_android_acquisitions_by_medium", "Attributed Android Acquisitions by Medium", SOURCE_ACTIVITY_EVENTS,
        "app_install_attributed rows grouped by campaign_context.utm_medium.",
        "app_install_attributed rows, platform='app_android'.",
        "COUNT(*) GROUP BY campaign_context.utm_medium, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "medium"), QUALITY_PARTIAL,
    ),
    MarketingAttributionMetricDefinition(
        "attributed_android_acquisitions_by_campaign", "Attributed Android Acquisitions by Campaign", SOURCE_ACTIVITY_EVENTS,
        "app_install_attributed rows grouped by campaign_context.utm_campaign.",
        "app_install_attributed rows, platform='app_android'.",
        "COUNT(*) GROUP BY campaign_context.utm_campaign, restricted to attributed rows.",
        _LEDGER_TIME, ("date_range", "campaign"), QUALITY_PARTIAL,
    ),
    MarketingAttributionMetricDefinition(
        "website_to_app_campaign_funnel_indicator", "Website App Download Intents vs Attributed Android Acquisitions, by Campaign", SOURCE_ACTIVITY_EVENTS,
        "Aggregate, same-utm_campaign-string juxtaposition of app_download_intents_by_source's campaign breakdown against attributed_android_acquisitions_by_campaign. See WEBSITE_TO_APP_JOIN_POLICY.",
        "app_download_intent rows (platform='website') and app_install_attributed rows (platform='app_android'), same campaign string, same date range.",
        "Two independent COUNT(*) GROUP BY campaign_context.utm_campaign queries, presented side by side -- never joined at the row level.",
        _LEDGER_TIME, ("date_range", "campaign"), QUALITY_PARTIAL,
        ("NOT a deterministic user-level join -- WEBSITE_TO_APP_DETERMINISTIC_JOIN_POSSIBLE is False. An aggregate funnel INDICATOR only.",),
    ),

    # ---- Financial conversion attribution status (Task 10 S15) ----
    MarketingAttributionMetricDefinition(
        "report_revenue_by_campaign", "Report Revenue by Campaign", SOURCE_BACKEND_BUSINESS_TABLE,
        "Would attribute verified report-purchase revenue to a marketing campaign, IF payment_verified carried campaign_context.",
        "payment_verified rows where properties.purpose='REPORT_PURCHASE'.",
        "Would be SUM(amount) GROUP BY campaign_context.utm_campaign -- not computable today.",
        _LEDGER_TIME, ("date_range", "campaign"), QUALITY_BLOCKED,
        ("FINANCIAL_CONVERSION_ATTRIBUTION_GAP -- payment_verified never carries campaign_context. No ROAS/CPA/revenue-by-campaign metric exists as READY anywhere in this catalog.",),
    ),
    MarketingAttributionMetricDefinition(
        "subscription_starts_by_campaign", "Subscription Starts by Campaign", SOURCE_BACKEND_BUSINESS_TABLE,
        "Would attribute subscription starts to a marketing campaign, IF subscription_started carried campaign_context.",
        "subscription_started rows.",
        "Would be COUNT(*) GROUP BY campaign_context.utm_campaign -- not computable today.",
        _LEDGER_TIME, ("date_range", "campaign"), QUALITY_BLOCKED,
        ("FINANCIAL_CONVERSION_ATTRIBUTION_GAP -- subscription_started never carries campaign_context.",),
    ),
    MarketingAttributionMetricDefinition(
        "asknow_revenue_by_campaign", "Ask Now Revenue by Campaign", SOURCE_BACKEND_BUSINESS_TABLE,
        "Would attribute Ask Now purchase revenue to a marketing campaign, IF the Ask Now payment path carried campaign_context (and IF a website Ask Now producer existed at all).",
        "payment_verified rows where properties.purpose indicates an Ask Now chat-pack purchase.",
        "Would be SUM(amount) GROUP BY campaign_context.utm_campaign -- not computable today.",
        _LEDGER_TIME, ("date_range", "campaign"), QUALITY_BLOCKED,
        ("Doubly blocked: FINANCIAL_CONVERSION_ATTRIBUTION_GAP (no campaign_context on the payment) AND ASKNOW_WEBSITE_ATTRIBUTION_LIMITATION (no website Ask Now producer exists to originate a campaign-attributed entry point).",),
    ),
)


def get_marketing_attribution_metric(metric_id: str) -> MarketingAttributionMetricDefinition:
    for metric in MARKETING_ATTRIBUTION_METRIC_CATALOG:
        if metric.metric_id == metric_id:
            return metric
    raise KeyError(f"Unknown marketing attribution metric_id: {metric_id!r}")
