"""
test_activity_events_analytics_service.py
-------------------------------------------------
Phase 6B.3 -- proves modules/activity_events/analytics_service.py's
real AnalyticsService: metric semantics, repository composition, the
mandatory environment="production" fix, platform validation, rate
rules, report-product separation, and the frozen limitation contract.

DB-FREE by design -- every test here uses a fake/spy repository
(_SpyRepository, defined below) rather than PostgreSQL, matching this
phase's own explicit preference ("Tests should preferably be DB-free
using fake/spy repository"). No DATABASE_URL override is needed or set
by this file; nothing here imports app/extensions/db.
"""

import inspect
import sys
from dataclasses import fields
from datetime import datetime, timezone

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
    """Fake ActivityEventsAnalyticsRepository. Records every call (as
    (method_name, kwargs)) in `self.calls` and returns a pre-configured
    response keyed by (method, window, event_names, entity_type,
    property_filters, dimension) -- everything a test cares about
    disambiguating between two calls to the SAME method. `window` is
    included in the key (AnalyticsWindow is a frozen, hashable
    dataclass) specifically so DAU/WAU/MAU -- three calls to
    count_distinct_users with identical event_names but three
    different windows -- can be given three different canned answers,
    proving the service actually derived three different windows
    rather than accidentally reusing one."""

    def __init__(self):
        self.calls = []
        self._responses = {}

    @staticmethod
    def _key(method, window=None, event_names=None, entity_type=None,
              property_filters=None, dimension=None):
        if isinstance(event_names, list):
            event_names = tuple(event_names)
        pf = tuple(sorted(property_filters.items())) if property_filters else None
        return (method, window, event_names, entity_type, pf, dimension)

    def configure(self, method, value, *, window=None, event_names=None,
                  entity_type=None, property_filters=None, dimension=None):
        self._responses[self._key(method, window, event_names, entity_type, property_filters, dimension)] = value

    def _respond(self, method, kwargs, default):
        self.calls.append((method, dict(kwargs)))
        key = self._key(
            method, kwargs.get("window"), kwargs.get("event_names"),
            kwargs.get("entity_type"), kwargs.get("property_filters"), kwargs.get("dimension"),
        )
        return self._responses.get(key, default)

    def count_events(self, **kwargs):
        return self._respond("count_events", kwargs, 0)

    def count_distinct_users(self, **kwargs):
        return self._respond("count_distinct_users", kwargs, 0)

    def count_distinct_sessions(self, **kwargs):
        return self._respond("count_distinct_sessions", kwargs, 0)

    def group_by_property(self, **kwargs):
        return self._respond("group_by_property", kwargs, {})

    def group_by_notification_context(self, **kwargs):
        return self._respond("group_by_notification_context", kwargs, {})


def main():
    from modules.activity_events import analytics_service as svc
    from modules.activity_events import analytics_contract as contract
    from modules.activity_events.analytics_models import (
        AnalyticsWindow, OverviewMetrics, EngagementMetrics, AskNowMetrics,
        ReportMetrics, SubscriptionMetrics, NotificationMetrics,
    )

    # Deliberately NOT a 1/7/30-day span -- active_user_window() derives
    # DAU/WAU/MAU windows as [window.end - N days, window.end), and if
    # the overview window itself happened to also span exactly N days,
    # it would come out EQUAL (by value) to that derived window,
    # colliding in the spy's window-keyed response table. A 45-day
    # span can never coincide with any of 1/7/30.
    window = AnalyticsWindow(
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 2, 15, tzinfo=timezone.utc),
    )

    # ==========================================================
    print("=== GLOBAL: file scope -- no SQL/DB imports in the service ===")
    # ==========================================================
    src = inspect.getsource(svc)
    import_lines = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
    check("47: analytics_service.py imports no sqlalchemy/extensions/ActivityEvent model",
          not any(("sqlalchemy" in l or "extensions" in l or "models_activity_events" in l) for l in import_lines))
    check("47b: analytics_service.py never calls db.session/.query()/func.count()/select() as real code",
          not any(pattern in src for pattern in (".query(", "func.count(", "db.session.", "select(")))
    check("48: no revenue/amount/currency SUMMING logic exists (no SUM/amount/revenue/currency token in source)",
          not any(term in src for term in ("SUM(", "revenue", "amount", "currency")))

    # ==========================================================
    print("\n=== OVERVIEW ===")
    # ==========================================================
    dau_window = contract.active_user_window(window, contract.DAU_WINDOW)
    wau_window = contract.active_user_window(window, contract.WAU_WINDOW)
    mau_window = contract.active_user_window(window, contract.MAU_WINDOW)

    spy = _SpyRepository()
    spy.configure("count_events", 100, window=window)                              # total_events
    spy.configure("count_distinct_users", 50, window=window)                       # unique_users
    spy.configure("count_distinct_sessions", 30, window=window)                    # app_sessions
    spy.configure("count_events", 5, window=window, event_names="signup_completed")
    spy.configure("count_events", 20, window=window, event_names="login_completed")
    spy.configure("count_distinct_users", 7, window=dau_window)
    spy.configure("count_distinct_users", 25, window=wau_window)
    spy.configure("count_distinct_users", 60, window=mau_window)

    service = svc.AnalyticsService(repository=spy)
    overview = service.get_overview(window)

    check("49: get_overview returns the frozen OverviewMetrics type", isinstance(overview, OverviewMetrics))
    check("1: total_events composed from count_events(event_names=None)", overview.total_events == 100)
    check("2: unique_users uses the repository's distinct-user query", overview.unique_users == 50)
    check("3: app_sessions uses the repository's distinct-session query", overview.app_sessions == 30)
    check("4: new_signups uses event_names='signup_completed'", overview.new_signups == 5)
    check("5: interactive_logins uses event_names='login_completed'", overview.interactive_logins == 20)
    check("6: DAU uses the trailing 1-day window ending at window.end", overview.dau == 7)
    check("7: WAU uses the trailing 7-day window ending at window.end", overview.wau == 25)
    check("8: MAU uses the trailing 30-day window ending at window.end", overview.mau == 60)
    check("9/46: every overview repository call used environment='production'",
          all(kwargs.get("environment") == "production" for _, kwargs in spy.calls))
    check("_: get_overview issued exactly 8 repository calls (total/unique/sessions/signups/logins/dau/wau/mau)",
          len(spy.calls) == 8)

    # platform forwarding
    spy2 = _SpyRepository()
    service2 = svc.AnalyticsService(repository=spy2)
    service2.get_overview(window, platform="app_android")
    check("10: optional platform is forwarded to every repository call",
          all(kwargs.get("platform") == "app_android" for _, kwargs in spy2.calls) and len(spy2.calls) > 0)

    # ==========================================================
    print("\n=== VALIDATION ===")
    # ==========================================================
    raised = False
    try:
        service.get_overview(window, platform="not_a_real_platform")
    except contract.InvalidPlatformFilter:
        raised = True
    check("11: invalid platform rejected", raised)

    spy3 = _SpyRepository()
    service3 = svc.AnalyticsService(repository=spy3)
    raised = False
    try:
        service3.get_overview(window, platform="bogus")
    except contract.InvalidPlatformFilter:
        raised = True
    check("12: invalid platform causes ZERO repository calls (validated before any composition)",
          raised and spy3.calls == [])

    all_methods = [
        svc.AnalyticsService.get_overview, svc.AnalyticsService.get_engagement,
        svc.AnalyticsService.get_asknow_metrics, svc.AnalyticsService.get_report_metrics,
        svc.AnalyticsService.get_subscription_metrics, svc.AnalyticsService.get_notification_metrics,
    ]
    for method in all_methods:
        sig = inspect.signature(method)
        check(f"13: {method.__name__}() has no 'environment' parameter -- caller cannot override it",
              "environment" not in sig.parameters)
    check("13b: AnalyticsService.ENVIRONMENT is fixed to 'production'",
          svc.AnalyticsService.ENVIRONMENT == "production" == contract.PRODUCTION_ENVIRONMENT)

    # ==========================================================
    print("\n=== ENGAGEMENT ===")
    # ==========================================================
    spy = _SpyRepository()
    spy.configure("count_events", 40, window=window, event_names="cta_click")
    spy.configure("count_distinct_users", 15, window=window, event_names="cta_click")
    spy.configure("group_by_property", {"cta_a": 20, "cta_b": 20}, window=window,
                  event_names="cta_click", dimension="cta_id")
    spy.configure("group_by_property", {"home": 25, "explore": 15}, window=window,
                  event_names="cta_click", dimension="screen_name")
    spy.configure("count_events", 90, window=window, event_names="feature_used")
    spy.configure("count_distinct_users", 33, window=window, event_names="feature_used")
    spy.configure("group_by_property", {"kundali_generate": 90}, window=window,
                  event_names="feature_used", dimension="feature_name")

    engagement = svc.AnalyticsService(repository=spy).get_engagement(window)
    check("49b: get_engagement returns the frozen EngagementMetrics type", isinstance(engagement, EngagementMetrics))
    check("14: CTA total uses event_names='cta_click'", engagement.cta_clicks_total == 40)
    check("15: CTA unique users uses event_names='cta_click'", engagement.cta_unique_users == 15)
    check("16: cta_id grouping composed correctly", engagement.cta_clicks_by_cta_id == {"cta_a": 20, "cta_b": 20})
    check("17: screen_name grouping composed correctly", engagement.cta_clicks_by_screen_name == {"home": 25, "explore": 15})
    check("18: feature total uses event_names='feature_used'", engagement.feature_usage_total == 90)
    check("19: feature unique users uses event_names='feature_used'", engagement.feature_unique_users == 33)
    check("20: feature_name grouping composed correctly", engagement.feature_usage_by_feature_name == {"kundali_generate": 90})
    check("21: EngagementMetrics has no ctr field -- CTA CTR is never fabricated",
          not any("ctr" in f.name.lower() for f in fields(EngagementMetrics)))

    # ==========================================================
    print("\n=== ASK NOW ===")
    # ==========================================================
    spy = _SpyRepository()
    spy.configure("count_events", 200, window=window, event_names="asknow_entry_viewed")
    spy.configure("count_events", 10, window=window, event_names="asknow_question_submitted")
    spy.configure("count_events", 0, window=window, event_names="asknow_answer_delivered")
    spy.configure("count_events", 0, window=window, event_names="asknow_answer_failed")
    asknow = svc.AnalyticsService(repository=spy).get_asknow_metrics(window)
    check("49c: get_asknow_metrics returns the frozen AskNowMetrics type", isinstance(asknow, AskNowMetrics))
    check("22: all four stages use their own canonical event_name", asknow.entry_views == 200 and asknow.questions_submitted == 10)
    check("22b: delivered/failed also independently queried", asknow.answers_delivered == 0 and asknow.answers_failed == 0)
    # 23/24/25 -- the IMPORTANT rate test (task section 22): a real zero
    # numerator with a positive denominator is 0.0, NOT None.
    check("23: delivery_rate with submitted=10, delivered=0 -> 0.0 (a REAL zero, not unavailable)",
          asknow.delivery_rate == 0.0)
    check("24: failure_rate with submitted=10, failed=0 -> 0.0", asknow.failure_rate == 0.0)

    spy_zero = _SpyRepository()
    spy_zero.configure("count_events", 0, window=window, event_names="asknow_question_submitted")
    asknow_zero = svc.AnalyticsService(repository=spy_zero).get_asknow_metrics(window)
    check("25: submitted=0 -> BOTH rates are None (unavailable), never 0.0",
          asknow_zero.delivery_rate is None and asknow_zero.failure_rate is None)
    check("26: ASKNOW_ATTEMPT_LINKAGE_LIMITATION is preserved on every result",
          contract.ASKNOW_ATTEMPT_LINKAGE_LIMITATION in asknow.limitations
          and contract.ASKNOW_ATTEMPT_LINKAGE_LIMITATION in asknow_zero.limitations)

    # ==========================================================
    print("\n=== REPORTS -- AI Report Engine vs. purchased report ===")
    # ==========================================================
    spy = _SpyRepository()
    # A. AI Report Engine
    spy.configure("count_events", 300, window=window, event_names="report_discovery_viewed")
    spy.configure("group_by_property", {"love": 150, "career": 150}, window=window,
                  event_names="report_discovery_viewed", dimension="report_type")
    spy.configure("count_events", 80, window=window, event_names="report_generation_started", entity_type="ai_report")
    spy.configure("count_events", 70, window=window, event_names="report_generation_completed", entity_type="ai_report")
    spy.configure("count_events", 10, window=window, event_names="report_generation_failed", entity_type="ai_report")
    # B. Purchased report
    spy.configure("count_events", 25, window=window, event_names="cta_click",
                  property_filters={"cta_id": "report_catalog_buy_now"})
    spy.configure("count_events", 20, window=window, event_names="payment_initiated",
                  property_filters={"purpose": "REPORT_PURCHASE"})
    spy.configure("count_events", 18, window=window, event_names="payment_verified",
                  property_filters={"purpose": "REPORT_PURCHASE"})
    spy.configure("count_events", 2, window=window, event_names="payment_failed",
                  property_filters={"purpose": "REPORT_PURCHASE"})
    spy.configure("count_events", 18, window=window, event_names="report_generation_started", entity_type="order")
    spy.configure("count_events", 17, window=window, event_names="report_generation_completed", entity_type="order")
    spy.configure("count_events", 1, window=window, event_names="report_generation_failed", entity_type="order")

    report = svc.AnalyticsService(repository=spy).get_report_metrics(window)
    check("49d: get_report_metrics returns the frozen ReportMetrics type", isinstance(report, ReportMetrics))

    check("27: AI discovery uses report_discovery_viewed", report.ai_report_engine.discovery_views == 300)
    check("28: AI generation is filtered entity_type='ai_report'",
          report.ai_report_engine.generation_started == 80
          and report.ai_report_engine.generation_completed == 70
          and report.ai_report_engine.generation_failed == 10)

    check("29: purchased entry uses cta_click + property_filters={'cta_id': 'report_catalog_buy_now'}",
          report.purchased_report.purchase_entry_clicks == 25)
    check("30: purchased payment is filtered purpose='REPORT_PURCHASE'",
          report.purchased_report.payment_initiated == 20
          and report.purchased_report.payment_verified == 18
          and report.purchased_report.payment_failed == 2)
    check("31: purchased generation is filtered entity_type='order'",
          report.purchased_report.generation_started == 18
          and report.purchased_report.generation_completed == 17
          and report.purchased_report.generation_failed == 1)

    check("32: AI and purchased generation counts do NOT cross-contaminate "
          "(ai=80/70/10 vs purchased=18/17/1, entirely distinct numbers)",
          report.ai_report_engine.generation_started != report.purchased_report.generation_started
          and report.ai_report_engine.generation_completed != report.purchased_report.generation_completed)
    check("33: PurchasedReportMetrics field is 'purchase_entry_clicks', never a 'discovery' field",
          not any("discovery" in f.name for f in fields(type(report.purchased_report))))

    # Verify the EXACT recorded repository calls carry the exact expected kwargs.
    def _find_call(calls, method, **match):
        for name, kwargs in calls:
            if name != method:
                continue
            if all(kwargs.get(k) == v for k, v in match.items()):
                return kwargs
        return None

    check("Report separation (exact kwargs): AI generation call used entity_type='ai_report'",
          _find_call(spy.calls, "count_events", event_names="report_generation_started", entity_type="ai_report") is not None)
    check("Report separation (exact kwargs): purchased generation call used entity_type='order'",
          _find_call(spy.calls, "count_events", event_names="report_generation_completed", entity_type="order") is not None)
    check("Report separation (exact kwargs): purchased payment call used property_filters={'purpose': 'REPORT_PURCHASE'}",
          _find_call(spy.calls, "count_events", event_names="payment_verified",
                     property_filters={"purpose": "REPORT_PURCHASE"}) is not None)
    check("Report separation (exact kwargs): purchased CTA call used property_filters={'cta_id': 'report_catalog_buy_now'}",
          _find_call(spy.calls, "count_events", event_names="cta_click",
                     property_filters={"cta_id": "report_catalog_buy_now"}) is not None)
    check("Rate: purchased verification_rate == verified/initiated", report.purchased_report.verification_rate == 18 / 20)
    check("Rate: AI completion_rate == completed/started", report.ai_report_engine.completion_rate == 70 / 80)

    # ==========================================================
    print("\n=== SUBSCRIPTIONS ===")
    # ==========================================================
    spy = _SpyRepository()
    spy.configure("count_events", 500, window=window, event_names="subscription_discovery_viewed")
    spy.configure("group_by_property", {"account": 300, "explore": 200}, window=window,
                  event_names="subscription_discovery_viewed", dimension="placement")
    for name, value in (
        ("subscription_trial_started", 40), ("subscription_trial_expired", 5),
        ("subscription_started", 30), ("subscription_renewed", 20),
        ("subscription_grace_entered", 3), ("subscription_expired", 2),
        ("subscription_cancelled", 4), ("subscription_refunded", 1),
    ):
        spy.configure("count_events", value, window=window, event_names=name)

    subscription = svc.AnalyticsService(repository=spy).get_subscription_metrics(window)
    check("49e: get_subscription_metrics returns the frozen SubscriptionMetrics type", isinstance(subscription, SubscriptionMetrics))
    check("34: discovery uses subscription_discovery_viewed", subscription.discovery_views == 500)
    check("35: placement grouping composed correctly", subscription.discovery_by_placement == {"account": 300, "explore": 200})
    check("36: lifecycle events mapped to their own exact canonical names",
          subscription.trial_started == 40 and subscription.trial_expired == 5
          and subscription.subscription_started == 30 and subscription.subscription_renewed == 20
          and subscription.subscription_grace_entered == 3 and subscription.subscription_expired == 2
          and subscription.subscription_cancelled == 4 and subscription.subscription_refunded == 1)
    check("37: subscription_pending_created was never queried at all",
          not any(kwargs.get("event_names") == "subscription_pending_created" for _, kwargs in spy.calls))
    check("37b: SubscriptionMetrics has no subscription_pending_created field",
          "subscription_pending_created" not in {f.name for f in fields(SubscriptionMetrics)})
    check("38: SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION is preserved on the result",
          contract.SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION in subscription.limitations)

    # ==========================================================
    print("\n=== NOTIFICATIONS ===")
    # ==========================================================
    spy = _SpyRepository()
    spy.configure("count_events", 1000, window=window, event_names="notification_created")
    spy.configure("count_events", 950, window=window, event_names="notification_sent")
    spy.configure("count_events", 0, window=window, event_names="notification_opened")
    spy.configure("count_distinct_users", 0, window=window, event_names="notification_opened")

    notification = svc.AnalyticsService(repository=spy).get_notification_metrics(window)
    check("49f: get_notification_metrics returns the frozen NotificationMetrics type", isinstance(notification, NotificationMetrics))
    check("39: created count correct", notification.created == 1000)
    check("40: sent count correct", notification.sent == 950)
    check("41: opened count correct", notification.opened == 0)
    check("42: unique opened users correct", notification.unique_users_opened == 0)
    # The IMPORTANT rate test's notification half (task section 22):
    # sent=10, opened=0 -> 0.0 (a real zero -- reuse a fresh spy).
    spy_rate = _SpyRepository()
    spy_rate.configure("count_events", 10, window=window, event_names="notification_sent")
    spy_rate.configure("count_events", 0, window=window, event_names="notification_opened")
    n_rate = svc.AnalyticsService(repository=spy_rate).get_notification_metrics(window)
    check("43: open_rate = opened/sent (sent=10, opened=0 -> a REAL 0.0)", n_rate.open_rate == 0.0)

    spy_zero_sent = _SpyRepository()
    spy_zero_sent.configure("count_events", 0, window=window, event_names="notification_sent")
    spy_zero_sent.configure("count_events", 100, window=window, event_names="notification_created")
    n_zero = svc.AnalyticsService(repository=spy_zero_sent).get_notification_metrics(window)
    check("44: sent=0 -> open_rate is None (never 0.0), even with a nonzero opened/created", n_zero.open_rate is None)
    check("45: created (100, nonzero) is NEVER used as the open_rate denominator -- "
          "sent=0 still yields None, proving created was not silently substituted",
          n_zero.open_rate is None and n_zero.created == 100)

    # ==========================================================
    print("\n=== GLOBAL: environment on every call, across every method ===")
    # ==========================================================
    spy = _SpyRepository()
    service = svc.AnalyticsService(repository=spy)
    service.get_overview(window)
    service.get_engagement(window)
    service.get_asknow_metrics(window)
    service.get_report_metrics(window)
    service.get_subscription_metrics(window)
    service.get_notification_metrics(window)

    check("46: every repository call, across all six methods, used environment='production'",
          len(spy.calls) > 0 and all(kwargs.get("environment") == "production" for _, kwargs in spy.calls))
    check("50: all six frozen public methods are implemented (no NotImplementedError anywhere above)", True)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
