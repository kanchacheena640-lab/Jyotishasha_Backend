"""
test_routes_analytics.py
-------------------------------------------------
Phase 6B.4 -- proves routes/routes_analytics.py: blueprint
registration, admin auth reuse, start/end/platform parsing and
validation, correct AnalyticsService method dispatch, and frozen-DTO
JSON serialization -- WITHOUT depending on real event aggregation for
most cases (a fake AnalyticsService is substituted for
routes_analytics._service, restored in a finally block). Exactly one
real, DB-backed smoke path proves genuine end-to-end wiring against
jyotishasha_local, per this phase's own "at least one safe
integration/smoke path" guidance.

LOCAL ONLY -- DATABASE_URL is overridden to jyotishasha_local before
`app` is ever imported (Flask-SQLAlchemy initializes against it at
import time), and the smoke test independently re-verifies
current_database() before issuing any request.
"""

import inspect
import os
import sys
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

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


# Dedicated, obviously-test-only ids -- distinct from every other test
# file's own fixture range in this repo.
ADMIN_UID = 969201
NON_ADMIN_UID = 969202

VALID_START = "2026-01-01T00:00:00+00:00"
VALID_END = "2026-01-31T00:00:00+00:00"


class _FakeAnalyticsService:
    """Records every call as (method_name, window, platform) and
    returns a hand-built frozen DTO instance -- no repository, no DB,
    no real aggregation. Proves routing/parsing/dispatch/serialization
    in complete isolation from Phase 6B.2/6B.3's own already-tested
    metric composition. Each method still calls the REAL
    validate_platform() first, exactly like the real AnalyticsService
    does -- otherwise this fake would silently bypass the one
    behavior (InvalidPlatformFilter -> the route's own 400 translation)
    that must be proven, not skipped."""

    def __init__(self, models):
        self.calls = []
        self._m = models
        from modules.activity_events.analytics_contract import validate_platform
        self._validate_platform = validate_platform

    def get_overview(self, window, platform=None):
        self._validate_platform(platform)
        self.calls.append(("get_overview", window, platform))
        return self._m.OverviewMetrics(
            total_events=100, unique_users=40, app_sessions=30,
            new_signups=5, interactive_logins=20, dau=6, wau=25, mau=60,
        )

    def get_engagement(self, window, platform=None):
        self._validate_platform(platform)
        self.calls.append(("get_engagement", window, platform))
        return self._m.EngagementMetrics(
            cta_clicks_total=10, cta_unique_users=5,
            cta_clicks_by_cta_id={"cta_a": 6, "cta_b": 4},
            cta_clicks_by_screen_name={"home": 10},
            feature_usage_total=20, feature_unique_users=8,
            feature_usage_by_feature_name={"kundali_generate": 20},
        )

    def get_asknow_metrics(self, window, platform=None):
        self._validate_platform(platform)
        self.calls.append(("get_asknow_metrics", window, platform))
        from modules.activity_events.analytics_contract import ASKNOW_ATTEMPT_LINKAGE_LIMITATION
        return self._m.AskNowMetrics(
            entry_views=50, questions_submitted=10, answers_delivered=8, answers_failed=2,
            delivery_rate=0.8, failure_rate=0.2, limitations=[ASKNOW_ATTEMPT_LINKAGE_LIMITATION],
        )

    def get_report_metrics(self, window, platform=None):
        self._validate_platform(platform)
        self.calls.append(("get_report_metrics", window, platform))
        return self._m.ReportMetrics(
            ai_report_engine=self._m.AiReportEngineMetrics(
                discovery_views=5, discovery_by_report_type={"love": 5},
                generation_started=3, generation_completed=2, generation_failed=1,
                completion_rate=2 / 3,
            ),
            purchased_report=self._m.PurchasedReportMetrics(
                purchase_entry_clicks=4, payment_initiated=3, payment_verified=2, payment_failed=1,
                generation_started=2, generation_completed=1, generation_failed=1,
                verification_rate=2 / 3, completion_rate=0.5,
            ),
        )

    def get_subscription_metrics(self, window, platform=None):
        self._validate_platform(platform)
        self.calls.append(("get_subscription_metrics", window, platform))
        from modules.activity_events.analytics_contract import SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION
        return self._m.SubscriptionMetrics(
            discovery_views=10, discovery_by_placement={"account": 10},
            trial_started=1, trial_expired=0, subscription_started=1, subscription_renewed=0,
            subscription_grace_entered=0, subscription_expired=0, subscription_cancelled=0,
            subscription_refunded=0, limitations=[SUBSCRIPTION_PLACEMENT_ATTRIBUTION_LIMITATION],
        )

    def get_notification_metrics(self, window, platform=None):
        self._validate_platform(platform)
        self.calls.append(("get_notification_metrics", window, platform))
        return self._m.NotificationMetrics(
            created=10, sent=8, opened=0, unique_users_opened=0, open_rate=None,
        )


def main():
    from app import app as flask_app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token

    import routes.routes_analytics as routes_analytics_module
    from modules.activity_events import analytics_models as models
    from modules.activity_events.analytics_service import AnalyticsService

    with flask_app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

    client = flask_app.test_client()

    def auth_headers(user_id):
        with flask_app.app_context():
            token = create_access_token(identity=str(user_id))
        return {"Authorization": f"Bearer {token}"}

    ENDPOINTS = {
        "overview": "/admin/api/analytics/overview",
        "engagement": "/admin/api/analytics/engagement",
        "asknow": "/admin/api/analytics/asknow",
        "reports": "/admin/api/analytics/reports",
        "subscriptions": "/admin/api/analytics/subscriptions",
        "notifications": "/admin/api/analytics/notifications",
    }
    METHOD_NAMES = {
        "overview": "get_overview", "engagement": "get_engagement", "asknow": "get_asknow_metrics",
        "reports": "get_report_metrics", "subscriptions": "get_subscription_metrics",
        "notifications": "get_notification_metrics",
    }

    def valid_qs(**extra):
        qs = {"start": VALID_START, "end": VALID_END}
        qs.update(extra)
        return qs

    # ==================================================================
    print("=== ROUTE REGISTRATION ===")
    # ==================================================================
    registered = {r.rule for r in flask_app.url_map.iter_rules()}
    check("1: analytics blueprint registered (routes_analytics in app.py)",
          "routes_analytics" in flask_app.blueprints)
    for name, path in ENDPOINTS.items():
        check(f"2: {name} endpoint exists at {path}", path in registered)
    check("48: existing application routes remain intact (e.g. /api/activity-events still registered)",
          "/api/activity-events" in registered)

    # ==================================================================
    print("\n=== AUTH ===")
    # ==================================================================
    for name, path in ENDPOINTS.items():
        resp = client.get(path, query_string=valid_qs())
        check(f"3-8: unauthenticated {name} rejected (401)", resp.status_code == 401)

    os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)
    resp = client.get(ENDPOINTS["overview"], query_string=valid_qs(), headers=auth_headers(NON_ADMIN_UID))
    check("9: authenticated but NON-admin caller -> 403", resp.status_code == 403)

    admin_headers = auth_headers(ADMIN_UID)

    # ==================================================================
    print("\n=== WINDOW VALIDATION (fake service substituted) ===")
    # ==================================================================
    fake = _FakeAnalyticsService(models)
    real_service = routes_analytics_module._service
    routes_analytics_module._service = fake
    try:
        resp = client.get(ENDPOINTS["overview"], query_string={"end": VALID_END}, headers=admin_headers)
        check("10: missing start -> 400", resp.status_code == 400)
        check("10b: 400 body has a stable JSON error shape",
              resp.get_json().get("error") == "invalid_analytics_window")

        resp = client.get(ENDPOINTS["overview"], query_string={"start": VALID_START}, headers=admin_headers)
        check("11: missing end -> 400", resp.status_code == 400)

        resp = client.get(ENDPOINTS["overview"], query_string={"start": "not-a-date", "end": VALID_END}, headers=admin_headers)
        check("12: malformed start -> 400", resp.status_code == 400)

        resp = client.get(ENDPOINTS["overview"], query_string={"start": VALID_START, "end": "not-a-date"}, headers=admin_headers)
        check("13: malformed end -> 400", resp.status_code == 400)

        resp = client.get(ENDPOINTS["overview"], query_string={"start": "2026-01-01T00:00:00", "end": VALID_END}, headers=admin_headers)
        check("14: naive start (no timezone) -> 400", resp.status_code == 400)

        resp = client.get(ENDPOINTS["overview"], query_string={"start": VALID_START, "end": "2026-01-31T00:00:00"}, headers=admin_headers)
        check("15: naive end (no timezone) -> 400", resp.status_code == 400)

        resp = client.get(ENDPOINTS["overview"], query_string={"start": VALID_START, "end": VALID_START}, headers=admin_headers)
        check("16: start == end -> 400", resp.status_code == 400)

        resp = client.get(ENDPOINTS["overview"], query_string={"start": VALID_END, "end": VALID_START}, headers=admin_headers)
        check("17: start > end -> 400", resp.status_code == 400)

        resp = client.get(ENDPOINTS["overview"], query_string=valid_qs(), headers=admin_headers)
        check("18: valid timezone-aware window accepted -> 200", resp.status_code == 200)

        resp = client.get(
            ENDPOINTS["overview"],
            query_string={"start": "2026-01-01T00:00:00+05:30", "end": "2026-01-31T00:00:00+05:30"},
            headers=admin_headers,
        )
        check("19: non-UTC (+05:30, IST) offset accepted", resp.status_code == 200)

        resp = client.get(
            ENDPOINTS["overview"],
            query_string={"start": "2026-01-01T00:00:00Z", "end": "2026-01-31T00:00:00Z"},
            headers=admin_headers,
        )
        check("19b: 'Z'-suffixed UTC timestamp accepted", resp.status_code == 200)

        # ==================================================================
        print("\n=== PLATFORM VALIDATION ===")
        # ==================================================================
        resp = client.get(ENDPOINTS["overview"], query_string=valid_qs(), headers=admin_headers)
        check("20: platform omitted -> accepted", resp.status_code == 200)

        for value in ("app_android", "app_ios", "website", "backend_internal"):
            resp = client.get(ENDPOINTS["overview"], query_string=valid_qs(platform=value), headers=admin_headers)
            check(f"21-24: platform='{value}' accepted", resp.status_code == 200)

        resp = client.get(ENDPOINTS["overview"], query_string=valid_qs(platform="not_a_real_platform"), headers=admin_headers)
        check("25: invalid platform -> 400", resp.status_code == 400)
        check("25b: invalid platform body has a stable JSON error shape",
              resp.get_json().get("error") == "invalid_platform")

        # ==================================================================
        print("\n=== DISPATCH ===")
        # ==================================================================
        for name, path in ENDPOINTS.items():
            fake.calls.clear()
            resp = client.get(path, query_string=valid_qs(platform="app_android"), headers=admin_headers)
            check(f"26-31: {name} calls {METHOD_NAMES[name]}() exactly once", resp.status_code == 200 and len(fake.calls) == 1)
            method_name, window, platform = fake.calls[0]
            check(f"_: {name} dispatched to the correct service method", method_name == METHOD_NAMES[name])
            check("32: parsed AnalyticsWindow passed correctly",
                  isinstance(window, models.AnalyticsWindow)
                  and window.start == datetime.fromisoformat(VALID_START)
                  and window.end == datetime.fromisoformat(VALID_END))
            check("33: platform passed correctly", platform == "app_android")

        # ==================================================================
        print("\n=== SERIALIZATION ===")
        # ==================================================================
        resp = client.get(ENDPOINTS["overview"], query_string=valid_qs(), headers=admin_headers)
        body = resp.get_json()
        check("34: OverviewMetrics serializes correctly under 'data'",
              body["data"]["total_events"] == 100 and body["data"]["dau"] == 6)

        resp = client.get(ENDPOINTS["engagement"], query_string=valid_qs(), headers=admin_headers)
        body = resp.get_json()
        check("35: EngagementMetrics nested breakdown dicts serialize as JSON objects",
              body["data"]["cta_clicks_by_cta_id"] == {"cta_a": 6, "cta_b": 4}
              and isinstance(body["data"]["cta_clicks_by_cta_id"], dict))

        resp = client.get(ENDPOINTS["asknow"], query_string=valid_qs(), headers=admin_headers)
        body = resp.get_json()
        limitations = body["data"]["limitations"]
        check("36: AskNow limitation serializes as structured JSON ({metric, reason}), not repr()",
              isinstance(limitations, list) and len(limitations) == 1
              and set(limitations[0].keys()) == {"metric", "reason"}
              and limitations[0]["metric"] == "asknow.attempt_linkage")

        resp = client.get(ENDPOINTS["reports"], query_string=valid_qs(), headers=admin_headers)
        body = resp.get_json()
        check("37/28: ReportMetrics keeps two separate nested JSON sections, not flattened",
              "ai_report_engine" in body["data"] and "purchased_report" in body["data"]
              and body["data"]["ai_report_engine"]["discovery_views"] == 5
              and body["data"]["purchased_report"]["purchase_entry_clicks"] == 4
              and "discovery_views" not in body["data"]["purchased_report"])

        resp = client.get(ENDPOINTS["subscriptions"], query_string=valid_qs(), headers=admin_headers)
        body = resp.get_json()
        check("38: Subscription limitation serializes correctly",
              body["data"]["limitations"][0]["metric"] == "subscription.placement_attribution")

        resp = client.get(ENDPOINTS["notifications"], query_string=valid_qs(), headers=admin_headers)
        body = resp.get_json()
        check("39: notification open_rate None becomes JSON null", body["data"]["open_rate"] is None)

        # 40 -- a real 0.0 rate (not the fake's None) survives asdict() as
        # numeric 0.0, proven directly against the dataclass (no need for
        # a second route round trip -- this is exactly what jsonify()
        # would serialize the dict asdict() already produced into).
        zero_rate_dto = models.NotificationMetrics(created=5, sent=5, opened=0, unique_users_opened=0, open_rate=0.0)
        zero_rate_json = asdict(zero_rate_dto)
        check("40: a real 0.0 rate remains numeric 0.0 in the serialized dict (not omitted, not stringified)",
              zero_rate_json["open_rate"] == 0.0 and zero_rate_json["open_rate"] is not None
              and isinstance(zero_rate_json["open_rate"], float))

    finally:
        routes_analytics_module._service = real_service

    # ==================================================================
    print("\n=== SECURITY / BOUNDARY ===")
    # ==================================================================
    src = open(routes_analytics_module.__file__, encoding="utf-8").read()
    import_lines = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]

    route_handlers = [
        routes_analytics_module.analytics_overview, routes_analytics_module.analytics_engagement,
        routes_analytics_module.analytics_asknow, routes_analytics_module.analytics_reports,
        routes_analytics_module.analytics_subscriptions, routes_analytics_module.analytics_notifications,
    ]
    check("41: no route view function accepts an 'environment' parameter (all take zero args -- Flask calls them bare)",
          all("environment" not in inspect.signature(h).parameters for h in route_handlers))

    # 42 -- the real behavioral proof: ?environment=local must have
    # ZERO effect. Re-substitute the fake service to inspect what the
    # route actually forwards.
    fake2 = _FakeAnalyticsService(models)
    routes_analytics_module._service = fake2
    try:
        resp = client.get(
            ENDPOINTS["overview"],
            query_string={"start": VALID_START, "end": VALID_END, "environment": "local"},
            headers=admin_headers,
        )
        check("42: ?environment=local is silently ignored -- request still succeeds normally", resp.status_code == 200)
        _, _, forwarded_platform = fake2.calls[0]
        check("42b: 'environment' was never forwarded to the service as any recognized argument "
              "(only window/platform reach get_overview)", forwarded_platform is None)
    finally:
        routes_analytics_module._service = real_service

    # 43/44 -- checked against IMPORT lines only, not the whole file
    # (this module's own docstring prose explains, in English, that it
    # does NOT query ActivityEvent/db.session -- a whole-file substring
    # search would false-positive on that very sentence; the real
    # structural proof is that the model/db symbols are never imported
    # at all, so there is nothing to query even if someone tried).
    check("43: routes_analytics.py never imports the ActivityEvent model (nothing to query)",
          not any("models_activity_events" in l for l in import_lines))
    check("44: route source never touches db.session for analytics (no import of extensions/db)",
          not any(("extensions" in l or "import db" in l) for l in import_lines))
    # 45/46 -- the real, non-prose-confusable proof: the ACTUAL
    # registered URL map contains exactly the 6 frozen endpoints and
    # nothing else under this prefix (subsumes any source-text search
    # for a stray /query, /funnel, /sql, /events/raw, /export route).
    analytics_routes = {r.rule for r in flask_app.url_map.iter_rules() if r.rule.startswith("/admin/api/analytics/")}
    check("45/46: exactly the 6 frozen metric-domain endpoints exist under /admin/api/analytics/ -- "
          "no raw-event, export, query, or funnel endpoint was added",
          analytics_routes == set(ENDPOINTS.values()))
    check("29: routes_analytics.py imports no business-table model (Order/Subscription/User/AppUser/AIReport)",
          not any(("import Order" in l or "import User" in l or "import AppUser" in l
                    or "import AIReport" in l or "models_premium_subscription" in l) for l in import_lines))

    # ==================================================================
    print("\n=== APP REGISTRATION ===")
    # ==================================================================
    app_src = open(flask_app.root_path + "/app.py", encoding="utf-8").read() if hasattr(flask_app, "root_path") else open("app.py", encoding="utf-8").read()
    check("47: app.py registers the analytics blueprint exactly once",
          app_src.count("app.register_blueprint(routes_analytics)") == 1)

    # ==================================================================
    print("\n=== SMOKE TEST -- real AnalyticsService, real jyotishasha_local, no fixtures needed ===")
    # ==================================================================
    # A window guaranteed to contain no real activity_events rows in
    # this dev DB (far future) -- proves the REAL service/repository
    # chain executes end-to-end through the route without erroring,
    # returning well-formed (all-zero) metrics rather than skipping
    # this path entirely.
    routes_analytics_module._service = AnalyticsService()
    resp = client.get(
        ENDPOINTS["overview"],
        query_string={"start": "2099-01-01T00:00:00+00:00", "end": "2099-01-02T00:00:00+00:00"},
        headers=admin_headers,
    )
    check("SMOKE: real AnalyticsService end-to-end via the route returns 200", resp.status_code == 200)
    body = resp.get_json()
    check("SMOKE: an empty far-future window yields all-zero counts, not an error",
          body["data"]["total_events"] == 0 and body["data"]["unique_users"] == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
