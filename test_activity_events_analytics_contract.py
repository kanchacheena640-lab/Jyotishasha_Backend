"""
test_activity_events_analytics_contract.py
-------------------------------------------------
Phase 6B.1 -- proves the frozen analytics query/service CONTRACT
(modules/activity_events/analytics_models.py + analytics_contract.py)
BEFORE any real PostgreSQL aggregation exists. No SQL, no
ActivityEvent.query, no Flask app, no database of any kind is touched
by this file -- every symbol under test is pure Python (dataclasses +
plain functions), so this suite needs no DATABASE_URL override and
none is set. If a future change to these two files ever requires a
database, that itself would be a contract violation this file is
designed to catch as an import-time or collection-time failure, not
silently pass.

Covers the 20 minimum contract invariants from the Phase 6B.1 task
brief, plus a handful of additional structural checks the contract
design introduced (DAU/WAU/MAU anchor rule, the stub service's
validate-before-NotImplementedError ordering, subscription_pending_
created's deliberate absence).
"""

import inspect
import sys
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


def main():
    from dataclasses import fields, is_dataclass

    from modules.activity_events import analytics_contract as contract
    from modules.activity_events import analytics_models as models

    def all_field_names():
        """Every field name across every metric/limitation dataclass in
        analytics_models.py -- used for whole-contract structural
        guards (no revenue field anywhere, no profile_id-keyed field
        anywhere, no fake-linkage field anywhere)."""
        names = []
        for attr_name in dir(models):
            obj = getattr(models, attr_name)
            if isinstance(obj, type) and is_dataclass(obj):
                names.extend(f.name for f in fields(obj))
        return names

    all_names = all_field_names()

    # =====================================================================
    # 1/2/3/4 -- AnalyticsWindow validation (timezone-aware, start < end)
    # =====================================================================
    print("=== AnalyticsWindow validation ===")
    utc_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    utc_end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    window = models.AnalyticsWindow(start=utc_start, end=utc_end)
    check("1: timezone-aware start/end accepted", window.start == utc_start and window.end == utc_end)

    naive_start = datetime(2026, 1, 1)
    raised = False
    try:
        models.AnalyticsWindow(start=naive_start, end=utc_end)
    except models.InvalidAnalyticsWindow:
        raised = True
    check("2: naive start rejected", raised)

    naive_end = datetime(2026, 1, 2)
    raised = False
    try:
        models.AnalyticsWindow(start=utc_start, end=naive_end)
    except models.InvalidAnalyticsWindow:
        raised = True
    check("2b: naive end rejected (asymmetric case)", raised)

    raised = False
    try:
        models.AnalyticsWindow(start=utc_start, end=utc_start)
    except models.InvalidAnalyticsWindow:
        raised = True
    check("3: equal start/end rejected", raised)

    raised = False
    try:
        models.AnalyticsWindow(start=utc_end, end=utc_start)
    except models.InvalidAnalyticsWindow:
        raised = True
    check("4: reversed window (start > end) rejected", raised)

    # =====================================================================
    # 5/6 -- platform filter
    # =====================================================================
    print("\n=== Platform filter ===")
    check("5: valid platform accepted", contract.validate_platform("app_android") == "app_android")
    check("5b: None platform (no filter) accepted", contract.validate_platform(None) is None)
    for value in contract.ALLOWED_PLATFORMS:
        check(f"5c: '{value}' is an accepted platform", contract.validate_platform(value) == value)

    raised = False
    try:
        contract.validate_platform("totally_not_a_real_platform")
    except contract.InvalidPlatformFilter:
        raised = True
    check("6: invalid platform rejected", raised)

    # =====================================================================
    # 7 -- canonical unique-user key is firebase_uid, never profile_id
    # =====================================================================
    print("\n=== Unique-user identity ===")
    overview_fields = {f.name for f in fields(models.OverviewMetrics)}
    check("7: OverviewMetrics has 'unique_users' (firebase_uid-based), not 'unique_profiles'",
          "unique_users" in overview_fields and "unique_profiles" not in overview_fields)
    check("7b: no metric dataclass anywhere exposes a profile_id-keyed field",
          not any("profile_id" in name for name in all_names))

    # =====================================================================
    # 8 -- app session semantics are explicit, never a bare "sessions"
    # =====================================================================
    print("\n=== Session semantics ===")
    check("8: OverviewMetrics field is 'app_sessions', not bare 'sessions'",
          "app_sessions" in overview_fields and "sessions" not in overview_fields)
    check("8b: AnalyticsWindow/OverviewMetrics docstrings document the app-session (not 30-minute) semantic",
          "process" in (models.OverviewMetrics.__doc__ or "").lower()
          and "30-minute" in (models.OverviewMetrics.__doc__ or "").lower())

    # =====================================================================
    # 9 -- environment is structurally fixed, never a request parameter
    # =====================================================================
    print("\n=== Environment contract ===")
    service_methods = [
        contract.AnalyticsService.get_overview,
        contract.AnalyticsService.get_engagement,
        contract.AnalyticsService.get_asknow_metrics,
        contract.AnalyticsService.get_report_metrics,
        contract.AnalyticsService.get_subscription_metrics,
        contract.AnalyticsService.get_notification_metrics,
    ]
    for method in service_methods:
        sig = inspect.signature(method)
        check(f"9: {method.__name__}() has no 'environment' parameter",
              "environment" not in sig.parameters)
        check(f"9b: {method.__name__}() accepts exactly (self, window, platform=None)",
              list(sig.parameters) == ["self", "window", "platform"]
              and sig.parameters["platform"].default is None)
    check("9c: AnalyticsService.ENVIRONMENT is fixed to 'production'",
          contract.AnalyticsService.ENVIRONMENT == "production" == contract.PRODUCTION_ENVIRONMENT)

    # =====================================================================
    # 10/26 -- rate calculation: zero (or negative) denominator -> None
    # =====================================================================
    print("\n=== Rate calculation rule ===")
    check("10: denominator == 0 -> None (never 0.0)", contract.compute_rate(0, 0) is None)
    check("10b: denominator == 0 with nonzero numerator -> still None", contract.compute_rate(7, 0) is None)
    check("10c: negative denominator (defensive) -> None", contract.compute_rate(3, -1) is None)
    check("10d: real zero conversion (denominator > 0, numerator == 0) -> 0.0, not None",
          contract.compute_rate(0, 10) == 0.0)
    check("10e: normal rate computes correctly", contract.compute_rate(3, 12) == 0.25)
    check("20: None (unavailable) and 0.0 (real zero) are distinguishable, not conflated",
          contract.compute_rate(0, 0) is not contract.compute_rate(0, 10)
          and contract.compute_rate(0, 0) is None
          and contract.compute_rate(0, 10) == 0.0)

    # =====================================================================
    # 11 -- no CTA CTR field anywhere; explicit limitation exists instead
    # =====================================================================
    print("\n=== CTA CTR unavailable ===")
    engagement_fields = {f.name for f in fields(models.EngagementMetrics)}
    check("11: EngagementMetrics has no field containing 'ctr'",
          not any("ctr" in name.lower() for name in engagement_fields))
    check("11b: CTA_CTR_LIMITATION is defined with a non-empty reason",
          contract.CTA_CTR_LIMITATION.metric == "engagement.ctr"
          and len(contract.CTA_CTR_LIMITATION.reason) > 0)

    # =====================================================================
    # 12 -- Ask Now: no exact attempt-linkage field, limitation documented
    # =====================================================================
    print("\n=== Ask Now attempt linkage unavailable ===")
    asknow_fields = {f.name for f in fields(models.AskNowMetrics)}
    check("12: AskNowMetrics has no exact question<->answer pairing field",
          not any(term in name.lower() for name in asknow_fields for term in ("pair", "linkage", "attempt_id")))
    check("12b: ASKNOW_ATTEMPT_LINKAGE_LIMITATION is defined",
          contract.ASKNOW_ATTEMPT_LINKAGE_LIMITATION.metric == "asknow.attempt_linkage"
          and len(contract.ASKNOW_ATTEMPT_LINKAGE_LIMITATION.reason) > 0)
    check("12c: AskNowMetrics carries only aggregate stage counts + rates",
          asknow_fields == {"entry_views", "questions_submitted", "answers_delivered",
                             "answers_failed", "delivery_rate", "failure_rate", "limitations"})

    # =====================================================================
    # 13/14 -- report products structurally separate
    # =====================================================================
    print("\n=== Report product separation ===")
    report_fields = {f.name: f.type for f in fields(models.ReportMetrics)}
    check("13: ReportMetrics has exactly two sections: ai_report_engine, purchased_report",
          set(report_fields.keys()) == {"ai_report_engine", "purchased_report"})

    ai_fields = {f.name for f in fields(models.AiReportEngineMetrics)}
    check("13b: AiReportEngineMetrics has no payment-stage field (subscription-gated, not paid per-item)",
          not any("payment" in name for name in ai_fields))

    purchased_fields = {f.name for f in fields(models.PurchasedReportMetrics)}
    check("14: PurchasedReportMetrics' entry field is 'purchase_entry_clicks', never 'discovery_views'",
          "purchase_entry_clicks" in purchased_fields and "discovery_views" not in purchased_fields)
    check("14b: PURCHASED_REPORT_ENTRY_CTA_ID matches the real Flutter-emitted cta_id",
          contract.PURCHASED_REPORT_ENTRY_CTA_ID == "report_catalog_buy_now")

    # =====================================================================
    # 15 -- subscription: no exact per-visit attribution field/claim
    # =====================================================================
    print("\n=== Subscription attribution unavailable ===")
    subscription_fields = {f.name for f in fields(models.SubscriptionMetrics)}
    check("15: SubscriptionMetrics has no exact per-visit attribution field",
          not any(term in name.lower() for name in subscription_fields for term in ("per_visit", "exact_attribution")))
    check("15b: SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION is defined",
          contract.SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION.metric == "subscription.placement_attribution"
          and len(contract.SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION.reason) > 0)
    check("21: SubscriptionMetrics has no subscription_pending_created field (business flow not implemented)",
          "subscription_pending_created" not in subscription_fields
          and not any("pending_created" in name for name in subscription_fields))

    # =====================================================================
    # 16/17 -- notification open_rate: denominator is 'sent', never 'created'
    # =====================================================================
    print("\n=== Notification open rate ===")
    notification_fields = {f.name for f in fields(models.NotificationMetrics)}
    check("16: NotificationMetrics has both 'sent' and 'open_rate' fields",
          {"sent", "open_rate", "created"} <= notification_fields)
    check("16b: open_rate is documented as opened/sent, not opened/created",
          "sent" in (models.NotificationMetrics.__doc__ or "")
          and "never" in (models.NotificationMetrics.__doc__ or "").lower())
    # Behavioral proof using the shared rate rule: sent=0 -> open_rate None.
    zero_sent_rate = contract.compute_rate(numerator=0, denominator=0)
    check("17: sent == 0 -> open_rate is None, not 0.0", zero_sent_rate is None)
    real_rate = contract.compute_rate(numerator=4, denominator=8)
    check("17b: sent > 0 with real opens -> a real float rate", real_rate == 0.5)

    # =====================================================================
    # 18 -- revenue excluded from every activity-event analytics shape
    # =====================================================================
    print("\n=== Revenue/business-truth boundary ===")
    forbidden_terms = ("revenue", "amount", "currency", "paise", "rupee", "price")
    offending = [name for name in all_names if any(term in name.lower() for term in forbidden_terms)]
    check(f"18: no revenue/amount/currency field anywhere in analytics_models.py (found: {offending})",
          len(offending) == 0)

    # =====================================================================
    # 19 -- no naive login/signup conversion ratio exposed
    # =====================================================================
    print("\n=== Auth metric contract ===")
    check("19: OverviewMetrics carries only raw new_signups/interactive_logins counts, no conversion field",
          {"new_signups", "interactive_logins"} <= overview_fields
          and not any("conversion" in name.lower() for name in overview_fields))

    # =====================================================================
    # DAU/WAU/MAU anchor rule (Phase 6A section 12, frozen)
    # =====================================================================
    print("\n=== DAU/WAU/MAU anchor rule ===")
    overview_window = models.AnalyticsWindow(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )
    dau_window = contract.active_user_window(overview_window, contract.DAU_WINDOW)
    check("DAU window ends at the SAME anchor as the overview window", dau_window.end == overview_window.end)
    check("DAU window spans exactly 1 day", dau_window.end - dau_window.start == timedelta(days=1))

    wau_window = contract.active_user_window(overview_window, contract.WAU_WINDOW)
    check("WAU window spans exactly 7 days, same anchor", wau_window.end == overview_window.end
          and wau_window.end - wau_window.start == timedelta(days=7))

    mau_window = contract.active_user_window(overview_window, contract.MAU_WINDOW)
    check("MAU window spans exactly 30 days, same anchor", mau_window.end == overview_window.end
          and mau_window.end - mau_window.start == timedelta(days=30))

    # =====================================================================
    # Stub service: validates before ever reaching NotImplementedError,
    # and NEVER silently returns fake data.
    # =====================================================================
    print("\n=== AnalyticsService stub behavior ===")
    service = contract.AnalyticsService()

    raised_type = None
    try:
        service.get_overview(overview_window, platform="not_a_real_platform")
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, classified below
        raised_type = type(exc)
    check("invalid platform raises InvalidPlatformFilter BEFORE NotImplementedError",
          raised_type is contract.InvalidPlatformFilter)

    for method_name in ("get_overview", "get_engagement", "get_asknow_metrics",
                         "get_report_metrics", "get_subscription_metrics",
                         "get_notification_metrics"):
        raised = False
        try:
            getattr(service, method_name)(overview_window)
        except NotImplementedError:
            raised = True
        check(f"{method_name}() raises NotImplementedError -- never returns silent fake data",
              raised)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
