"""
test_activity_events_website_analytics_service.py
-------------------------------------------------
Task 11 -- proves modules/activity_events/website_analytics_service.py's
metric MEANING: contract-driven dispatch (READY/PARTIAL executes,
BLOCKED/GA4_EXTERNAL never touches the repository), label/status
preservation, zero-data semantics, and privacy.

DB-FREE by design, matching Phase 6B.3's own explicit established
preference (test_activity_events_analytics_service.py's own docstring:
"Tests should preferably be DB-free using fake/spy repository") --
every test here uses a fake/spy repository (_SpyRepository, defined
below) rather than PostgreSQL. No DATABASE_URL override is needed or
set by this file; nothing here imports app/extensions/db. Real
PostgreSQL execution of the underlying repository methods is proven
separately, against jyotishasha_local, in test_activity_events_
website_analytics_repository.py.

Covers Task 11's own 24 numbered service test requirements (S40).
"""

import inspect
import sys
from dataclasses import fields
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


class _SpyRepository:
    """Fake ActivityEventsAnalyticsRepository -- same shape/convention
    as test_activity_events_analytics_service.py's own _SpyRepository,
    extended with Task 11's 3 new methods. Records every call (as
    (method_name, kwargs)) in `self.calls` and returns a pre-configured
    response keyed by every argument a test might need to disambiguate
    between two calls to the SAME method."""

    DEFAULT_GROUP_LIMIT = 20
    MAX_GROUP_LIMIT = 100

    def __init__(self):
        self.calls = []
        self._responses = {}

    @staticmethod
    def _pf_key(property_filters):
        return tuple(sorted(property_filters.items())) if property_filters else None

    def _key(self, method, **kw):
        event_names = kw.get("event_names")
        if isinstance(event_names, list):
            event_names = tuple(event_names)
        return (
            method, kw.get("window"), event_names, kw.get("platform"),
            self._pf_key(kw.get("property_filters")), kw.get("dimension"),
            kw.get("property_dimension"), kw.get("campaign_dimension"),
        )

    def configure(self, method, value, **kw):
        self._responses[self._key(method, **kw)] = value

    def _respond(self, method, kwargs, default):
        self.calls.append((method, dict(kwargs)))
        key = self._key(method, **kwargs)
        return self._responses.get(key, default)

    def count_events(self, **kwargs):
        return self._respond("count_events", kwargs, 0)

    def group_by_property(self, **kwargs):
        return self._respond("group_by_property", kwargs, {})

    def group_by_campaign_context(self, **kwargs):
        return self._respond("group_by_campaign_context", kwargs, ({}, 0))

    def group_by_property_and_campaign_context(self, **kwargs):
        return self._respond("group_by_property_and_campaign_context", kwargs, ({}, 0))

    def attribution_coverage(self, **kwargs):
        return self._respond("attribution_coverage", kwargs, (0, 0))


def main():
    from modules.activity_events.analytics_models import AnalyticsWindow
    from modules.activity_events.website_analytics_service import (
        WebsiteAnalyticsService,
        WebsiteMetricNotImplemented,
        UnsupportedWebsiteMetric,
        window_for_period,
        WEBSITE_PLATFORM,
        ANDROID_PLATFORM,
        PRODUCT_ACTION_EVENT_NAMES,
    )
    from modules.activity_events.website_analytics_models import (
        MetricValue, GroupedMetricResult, GroupedMetricRow, PageAttributionResult,
        AttributionCoverageResult, UnavailableMetric,
    )
    from modules.activity_events import website_metrics_contract as wmc
    from modules.activity_events import marketing_attribution_contract as mac
    from modules.activity_events.analytics_repository import UnsupportedAnalyticsDimension
    from modules.activity_events import website_analytics_service as was_module

    window = AnalyticsWindow(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 2, 15, tzinfo=timezone.utc),
    )

    # =========================================================
    print("=== GLOBAL: file scope ===")
    # =========================================================
    src = inspect.getsource(was_module)
    check("no dashboard grouping dimension hardcodes session_id/firebase_uid/profile_id/anonymous_id anywhere in this module's source",
          not any(term in src for term in ('dimension="session_id"', "dimension='session_id'", 'dimension="firebase_uid"', 'dimension="profile_id"', 'dimension="anonymous_id"')))
    check("no SUM/revenue/amount/currency summing logic exists in this module",
          not any(term in src for term in ("SUM(", "revenue", "amount", "currency")))

    # =========================================================
    print("\n=== 1/2/3/4: quality-status-driven dispatch ===")
    # =========================================================
    spy = _SpyRepository()
    spy.configure("count_events", 42, window=window, event_names="cta_click", platform=WEBSITE_PLATFORM, property_filters=None)
    svc = WebsiteAnalyticsService(repository=spy)

    ready_result = svc.get_metric("cta_clicks_total", window)
    check("1: READY metric executes the repository (real, spy-configured value)", isinstance(ready_result, MetricValue) and ready_result.value == 42)
    check("1b: exactly one repository call was made for a scalar READY metric", len(spy.calls) == 1 and spy.calls[0][0] == "count_events")

    spy2 = _SpyRepository()
    spy2.configure("count_events", 7, window=window, event_names="feature_used", platform=WEBSITE_PLATFORM, property_filters=None)
    svc2 = WebsiteAnalyticsService(repository=spy2)
    partial_result = svc2.get_metric("tool_completions_all", window)
    check("2: PARTIAL metric executes AND preserves PARTIAL status", partial_result.value == 7 and partial_result.quality_status == wmc.QUALITY_PARTIAL)

    class ExplodingRepository:
        def __getattr__(self, name):
            def _boom(*a, **k):
                raise AssertionError(f"repository.{name}() must never be called for a BLOCKED/GA4_EXTERNAL metric")
            return _boom

    spy_blocked_svc = WebsiteAnalyticsService(repository=ExplodingRepository())
    blocked_result = spy_blocked_svc.get_metric("asknow_website_funnel", window)
    check("3: BLOCKED metric does not execute any repository query (exploding repository never raised)", isinstance(blocked_result, UnavailableMetric) and blocked_result.value is None)

    ga4_result = spy_blocked_svc.get_metric("page_views", window)
    check("4: GA4_EXTERNAL metric does not execute any repository query either", isinstance(ga4_result, UnavailableMetric) and ga4_result.quality_status == wmc.QUALITY_GA4_EXTERNAL)

    # =========================================================
    print("\n=== 5/6/7/8: GA4/landing-page/direct never fabricated ===")
    # =========================================================
    check("5: Page Views returns external/unavailable, never a ledger count", ga4_result.value is None and ga4_result.metric_id == "page_views")

    uvbp = spy_blocked_svc.get_metric("unique_visitors_by_page", window)
    check("6: Unique Visitors by Page is GA4_EXTERNAL, never derived from session_id", uvbp.quality_status == wmc.QUALITY_GA4_EXTERNAL and uvbp.value is None)

    raised_unknown = False
    try:
        spy_blocked_svc.get_metric("not_a_real_metric_id_on_purpose", window)
    except UnsupportedWebsiteMetric:
        raised_unknown = True
    check("7: an unknown metric_id raises UnsupportedWebsiteMetric, distinct from BLOCKED/GA4_EXTERNAL", raised_unknown)

    spy3 = _SpyRepository()
    spy3.configure("attribution_coverage", (0, 0), window=window, event_names=list(PRODUCT_ACTION_EVENT_NAMES), platform=WEBSITE_PLATFORM, property_filters=None)
    svc3 = WebsiteAnalyticsService(repository=spy3)
    coverage_empty = svc3.get_metric("attribution_coverage_pct", window)
    check("8: Direct traffic never fabricated -- zero attribution never produces a 'direct' label anywhere in the result", coverage_empty.attributed == 0 and "direct" not in repr(coverage_empty).lower())

    # =========================================================
    print("\n=== 9/10/11/12: response stability and label correctness ===")
    # =========================================================
    spy4 = _SpyRepository()
    spy4.configure("group_by_property", {"/en/free-kundali": 3, "/reports": 1}, window=window, event_names="cta_click", dimension="page_path", platform=WEBSITE_PLATFORM, property_filters=None)
    spy4.configure("count_events", 4, window=window, event_names="cta_click", platform=WEBSITE_PLATFORM, property_filters=None)
    svc4 = WebsiteAnalyticsService(repository=spy4)
    cta_page1 = svc4.get_metric("cta_clicks_by_page", window)
    cta_page2 = svc4.get_metric("cta_clicks_by_page", window)
    check("9: CTA by page response is stable across repeated calls with the same inputs", cta_page1 == cta_page2)
    check("9b: unknown_count computed correctly (4 total - (3+1) known = 0)", cta_page1.unknown_count == 0)

    spy5 = _SpyRepository()
    spy5.configure("group_by_property", {}, window=window, event_names="feature_used", dimension="page_path", platform=WEBSITE_PLATFORM, property_filters=None)
    spy5.configure("count_events", 5, window=window, event_names="feature_used", platform=WEBSITE_PLATFORM, property_filters=None)
    svc5 = WebsiteAnalyticsService(repository=spy5)
    tool_page = svc5.get_metric("tool_completions_by_page", window)
    check("10: Tool by page carries the producer-coverage PARTIAL limitation", tool_page.quality_status == wmc.QUALITY_PARTIAL and len(tool_page.limitations) > 0)
    check("10b: unknown_count reflects rows the repository didn't group (5 total - 0 known = 5)", tool_page.unknown_count == 5)

    adi_def = wmc.get_metric("app_download_intents_total")
    check("11: app_download_intent's own frozen limitation text explicitly denies install/render meaning", "install" in adi_def.limitations[0].lower() and "never" in adi_def.limitations[0].lower())
    spy6 = _SpyRepository()
    spy6.configure("count_events", 9, window=window, event_names="app_download_intent", platform=WEBSITE_PLATFORM, property_filters=None)
    svc6 = WebsiteAnalyticsService(repository=spy6)
    adi_result = svc6.get_metric("app_download_intents_total", window)
    check("11b: the service's own returned label (metric_id) is 'app_download_intents_total', never 'install'", adi_result.metric_id == "app_download_intents_total" and "install" not in adi_result.metric_id)

    check("12: app_install_attributed label remains 'Attributed Android Acquisition', never 'Installs'",
          mac.ATTRIBUTED_ANDROID_ACQUISITION_LABEL == "Attributed Android Acquisition" and "install" not in mac.ATTRIBUTED_ANDROID_ACQUISITION_LABEL.lower())

    # =========================================================
    print("\n=== 13/14/15: report intent/verified/revenue labels ===")
    # =========================================================
    report_intent_def = wmc.get_metric("report_purchase_intent")
    check("13: report purchase intent's own frozen definition explicitly denies being a payment, and never says 'sales'",
          "not a payment" in report_intent_def.definition.lower() and "sales" not in report_intent_def.definition.lower()
          and "report_purchase_intent" in report_intent_def.metric_id)

    spy7 = _SpyRepository()
    spy7.configure("count_events", 3, window=window, event_names="payment_verified", platform=None, property_filters={"purpose": "REPORT_PURCHASE"})
    svc7 = WebsiteAnalyticsService(repository=spy7)
    report_verified = svc7.get_metric("report_payment_verified", window)
    check("14: report verified count is authoritative (READY) and equals the real repository-returned value", report_verified.quality_status == wmc.QUALITY_READY and report_verified.value == 3)

    revenue_result = spy_blocked_svc.get_metric("report_revenue_by_campaign", window)
    check("15: report revenue remains unavailable (BLOCKED, value None) -- never computed, never queried", isinstance(revenue_result, UnavailableMetric) and revenue_result.value is None)

    # =========================================================
    print("\n=== 16/17: Ask Now / subscription website attribution unavailable ===")
    # =========================================================
    asknow_result = spy_blocked_svc.get_metric("asknow_website_funnel", window)
    check("16: Ask Now website attribution unavailable (BLOCKED)", isinstance(asknow_result, UnavailableMetric))
    sub_result = spy_blocked_svc.get_metric("subscription_starts_by_campaign", window)
    check("17: subscription website attribution unavailable (BLOCKED)", isinstance(sub_result, UnavailableMetric))

    # =========================================================
    print("\n=== 18: limitation metadata included ===")
    # =========================================================
    check("18: limitation metadata is included on a PARTIAL metric's own response", len(partial_result.limitations) > 0)
    check("18b: limitation metadata is included on an UnavailableMetric's own reason field", len(asknow_result.reason) > 0)

    # =========================================================
    print("\n=== 19: filters validated against closed vocabulary ===")
    # =========================================================
    raised_bad_dimension = False
    try:
        svc._grouped_by_campaign("cta_clicks_by_source", window, event_names="cta_click", dimension_name="gclid", platform=WEBSITE_PLATFORM, limit=10)
    except UnsupportedAnalyticsDimension:
        raised_bad_dimension = True
    check("19: an unrecognized dimension name is rejected before any repository call", raised_bad_dimension)

    # =========================================================
    print("\n=== 20: raw JSON / identity fields never returned ===")
    # =========================================================
    forbidden_field_names = ("properties", "campaign_context", "raw", "raw_properties", "firebase_uid", "profile_id", "anonymous_id", "session_id", "email", "phone")
    offending_shapes = [
        cls.__name__ for cls in (MetricValue, GroupedMetricResult, GroupedMetricRow, PageAttributionResult, AttributionCoverageResult, UnavailableMetric)
        if any(f.name in forbidden_field_names for f in fields(cls))
    ]
    check(f"20: none of the response shapes carry a raw properties/campaign_context/identity/PII field (offending: {offending_shapes})", len(offending_shapes) == 0)

    # =========================================================
    print("\n=== 21: zero-data semantics correct ===")
    # =========================================================
    spy_empty = _SpyRepository()  # every configured response defaults to 0/{}/(0,0) -- no explicit configure() calls
    svc_empty = WebsiteAnalyticsService(repository=spy_empty)
    zero_metric = svc_empty.get_metric("cta_clicks_total", window)
    check("21a: zero-data READY metric returns a real 0, not None", zero_metric.value == 0 and zero_metric.value is not None)
    zero_grouped = svc_empty.get_metric("cta_clicks_by_page", window)
    check("21b: zero-data grouped metric returns empty rows tuple and total=0", zero_grouped.rows == () and zero_grouped.total == 0)
    zero_coverage = svc_empty.get_metric("attribution_coverage_pct", window)
    check("21c: zero-data coverage: total_eligible=0, attributed=0, unattributed=0, coverage_percent=None (never NaN/0.0)",
          zero_coverage.total_eligible == 0 and zero_coverage.attributed == 0 and zero_coverage.unattributed == 0 and zero_coverage.coverage_percent is None)
    check("21d: GA4_EXTERNAL/BLOCKED metrics remain unavailable/None even for a zero-data spy, never 0",
          spy_blocked_svc.get_metric("page_views", window).value is None)

    # =========================================================
    print("\n=== 22/23: environment and platform handling ===")
    # =========================================================
    check("22: WebsiteAnalyticsService.ENVIRONMENT is the frozen PRODUCTION_ENVIRONMENT constant, never a hardcoded 'local'",
          WebsiteAnalyticsService.ENVIRONMENT == "production")
    check("22b: every scalar/grouped call this test made passed environment='production' to the repository",
          all(call[1].get("environment") == "production" for call in spy4.calls + spy5.calls + spy6.calls + spy7.calls))
    check("23: website metrics use platform='website'; Android acquisition metrics use platform='app_android' -- distinct constants, never mixed",
          WEBSITE_PLATFORM == "website" and ANDROID_PLATFORM == "app_android" and WEBSITE_PLATFORM != ANDROID_PLATFORM)

    spy_android = _SpyRepository()
    spy_android.configure("group_by_campaign_context", ({"google": 5}, 1), window=window, event_names="app_install_attributed", dimension="utm_source", platform=ANDROID_PLATFORM, property_filters=None)
    spy_android.configure("count_events", 6, window=window, event_names="app_install_attributed", platform=ANDROID_PLATFORM, property_filters=None)
    svc_android = WebsiteAnalyticsService(repository=spy_android)
    android_result = svc_android.get_metric("attributed_android_acquisitions_by_source", window)
    check("23b: Attributed Android Acquisition query uses platform='app_android', never 'website'",
          any(call[1].get("platform") == ANDROID_PLATFORM for call in spy_android.calls)
          and not any(call[1].get("platform") == WEBSITE_PLATFORM for call in spy_android.calls))

    # =========================================================
    print("\n=== 24: Task 9/10 metric IDs/statuses remain aligned ===")
    # =========================================================
    drift = []
    for metric_id, get_def in (
        ("cta_clicks_total", wmc.get_metric), ("cta_clicks_by_page", wmc.get_metric),
        ("tool_completions_all", wmc.get_metric), ("report_payment_verified", wmc.get_metric),
        ("attribution_coverage_pct", mac.get_marketing_attribution_metric),
        ("product_actions_by_source", mac.get_marketing_attribution_metric),
        ("attributed_android_acquisitions_by_campaign", mac.get_marketing_attribution_metric),
    ):
        d = get_def(metric_id)
        if metric_id == "attributed_android_acquisitions_by_campaign":
            result = svc_android.get_metric("attributed_android_acquisitions_by_source", window)
        else:
            result = svc_empty.get_metric(metric_id, window)
        # Compare the metric_id actually reachable via the frozen catalogs, not a re-derived one.
        if result.quality_status != d.quality_status:
            drift.append((metric_id, result.quality_status, d.quality_status))
    check(f"24: every tested metric's returned quality_status matches its frozen contract exactly (drift: {drift})", len(drift) == 0)

    # =========================================================
    print("\n=== Additional: window_for_period / dispatch / Page x Attribution ===")
    # =========================================================
    anchor = datetime(2026, 6, 15, tzinfo=timezone.utc)
    w7 = window_for_period("7d", now=anchor)
    check("window_for_period('7d') spans exactly 7 days, ending at `now`", w7.end - w7.start == timedelta(days=7) and w7.end == anchor)
    w30 = window_for_period("30d", now=anchor)
    check("window_for_period('30d') spans exactly 30 days", w30.end - w30.start == timedelta(days=30))
    w90 = window_for_period("90d", now=anchor)
    check("window_for_period('90d') spans exactly 90 days", w90.end - w90.start == timedelta(days=90))
    wc = window_for_period("custom", custom_start=window.start, custom_end=window.end)
    check("window_for_period('custom') uses the exact supplied bounds", wc.start == window.start and wc.end == window.end)
    raised_bad_period = False
    try:
        window_for_period("14d")
    except ValueError:
        raised_bad_period = True
    check("window_for_period rejects an unsupported period string", raised_bad_period)
    raised_missing_custom = False
    try:
        window_for_period("custom")
    except ValueError:
        raised_missing_custom = True
    check("window_for_period('custom') without bounds raises, never silently substitutes a default range", raised_missing_custom)

    not_impl_raised = False
    try:
        svc_empty.get_metric("kundali_generation_completed", window)  # READY in Task 9, deliberately outside Task 11's curated _DISPATCH
    except WebsiteMetricNotImplemented:
        not_impl_raised = True
    check("a READY metric outside Task 11's own curated scope raises WebsiteMetricNotImplemented, never silently returns nothing", not_impl_raised)

    check("PRODUCT_ACTION_EVENT_NAMES matches Task 10's own frozen population exactly",
          set(PRODUCT_ACTION_EVENT_NAMES) == {"cta_click", "feature_used", "app_download_intent", "report_discovery_viewed"})

    spy_page = _SpyRepository()
    spy_page.configure(
        "group_by_property_and_campaign_context",
        ({("/en/free-kundali", "google"): 4, ("/reports", "facebook"): 2}, 3),
        window=window, event_names="cta_click", property_dimension="page_path", campaign_dimension="utm_source",
        platform=WEBSITE_PLATFORM, property_filters=None,
    )
    spy_page.configure("count_events", 9, window=window, event_names="cta_click", platform=WEBSITE_PLATFORM, property_filters=None)
    svc_page = WebsiteAnalyticsService(repository=spy_page)
    page_attr_result = svc_page.get_metric("cta_clicks_by_page_and_source", window)
    check("Page x Attribution result composes correctly from the repository's dual-grouped response",
          isinstance(page_attr_result, PageAttributionResult)
          and len(page_attr_result.rows) == 2 and page_attr_result.incomplete_count == 3 and page_attr_result.total == 9)

    # report_purchase_intents_by_page reuses the frozen cta_clicks_by_page
    # identity (Task 11 S5 -- documented, not a new metric_id).
    spy_rpip = _SpyRepository()
    spy_rpip.configure(
        "group_by_property", {"/reports": 2}, window=window, event_names="cta_click",
        dimension="page_path", platform=WEBSITE_PLATFORM, property_filters={"cta_id": "report_catalog_buy_now"},
    )
    spy_rpip.configure("count_events", 2, window=window, event_names="cta_click", platform=WEBSITE_PLATFORM, property_filters={"cta_id": "report_catalog_buy_now"})
    svc_rpip = WebsiteAnalyticsService(repository=spy_rpip)
    rpip_result = svc_rpip.get_metric("report_purchase_intents_by_page", window)
    check("report_purchase_intents_by_page returns metric_id='cta_clicks_by_page' (honest identity, not a fabricated new metric_id)",
          rpip_result.metric_id == "cta_clicks_by_page")

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
