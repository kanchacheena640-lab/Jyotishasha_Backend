"""
test_routes_website_analytics.py
-------------------------------------------------
Task 12 -- proves routes/routes_website_analytics.py: blueprint
registration, admin auth reuse, period/custom-range parsing and
validation, metric dispatch (READY/PARTIAL/GA4_EXTERNAL/BLOCKED),
dimension/limit validation, unknown-metric/not-implemented handling,
controlled internal-failure responses, batch behavior, and privacy --
WITHOUT depending on real event aggregation for most cases (a fake
WebsiteAnalyticsService is substituted for routes_website_analytics._service,
restored in a finally block, matching test_routes_analytics.py's own
established pattern exactly). One real, DB-backed smoke path proves
genuine end-to-end wiring against jyotishasha_local, and one dedicated
section proves a GA4_EXTERNAL/BLOCKED metric executes NO repository
query even through the REAL service.

LOCAL ONLY -- DATABASE_URL is overridden to jyotishasha_local before
`app` is ever imported, and the smoke test independently re-verifies
current_database() before issuing any request.
"""

import os
import sys
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


ADMIN_UID = 969301
NON_ADMIN_UID = 969302


class _FakeWebsiteAnalyticsService:
    """Records every get_metric() call as (metric_id, window, kwargs)
    and returns a pre-configured canned result -- no repository, no DB.
    Configured per metric_id via `responses`. A metric_id with no
    configured response raises AssertionError (a test bug, not a
    legitimate 'unknown metric' -- that specific behavior is proven
    separately using the REAL service, whose UnsupportedWebsiteMetric
    this fake does not attempt to reproduce)."""

    def __init__(self):
        self.calls = []
        self.responses = {}
        self.raise_for = {}

    def get_metric(self, metric_id, window, **kwargs):
        self.calls.append((metric_id, window, dict(kwargs)))
        if metric_id in self.raise_for:
            raise self.raise_for[metric_id]
        if metric_id not in self.responses:
            raise AssertionError(f"_FakeWebsiteAnalyticsService: no response configured for {metric_id!r}")
        return self.responses[metric_id]


def main():
    from app import app as flask_app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token

    import routes.routes_website_analytics as routes_module
    from modules.activity_events.website_analytics_models import (
        MetricValue, GroupedMetricResult, GroupedMetricRow, PageAttributionResult,
        PageAttributionRow, AttributionCoverageResult, UnavailableMetric,
    )
    from modules.activity_events.website_analytics_service import (
        WebsiteAnalyticsService, UnsupportedWebsiteMetric, WebsiteMetricNotImplemented,
    )
    from modules.activity_events.analytics_repository import UnsupportedAnalyticsDimension

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

    SINGLE = "/admin/api/website-analytics/metrics/cta_clicks_total"
    BATCH = "/admin/api/website-analytics/metrics/batch"

    real_service = routes_module._service

    # ==================================================================
    print("=== ROUTE REGISTRATION ===")
    # ==================================================================
    registered = {r.rule for r in flask_app.url_map.iter_rules()}
    check("website analytics blueprint registered", "routes_website_analytics" in flask_app.blueprints)
    check("single-metric route exists", "/admin/api/website-analytics/metrics/<metric_id>" in registered)
    check("batch route exists", BATCH in registered)
    check("existing application routes remain intact (e.g. /api/activity-events still registered)",
          "/api/activity-events" in registered)
    check("old routes_analytics blueprint (Task 9-era) is untouched and still registered separately",
          "routes_analytics" in flask_app.blueprints and "/admin/api/analytics/overview" in registered)

    # ==================================================================
    print("\n=== AUTH ===")
    # ==================================================================
    resp = client.get(SINGLE, query_string={"period": "7d"})
    check("1: no auth -> 401", resp.status_code == 401)

    # A structurally garbage bearer value is rejected by Flask-JWT-
    # Extended's own, pre-existing, unmodified default handling as 422
    # (not 401) -- this is admin_required's/@jwt_required()'s own
    # inherited behavior, reused unchanged here (Task 12 explicitly
    # forbids weakening or re-implementing admin auth), not something
    # this route introduces. Either way the request is REJECTED, no
    # analytics data is exposed -- confirmed directly.
    resp = client.get(SINGLE, query_string={"period": "7d"}, headers={"Authorization": "Bearer not-a-real-token"})
    check("2: structurally malformed bearer token -> 422 (Flask-JWT-Extended's own unmodified default), never 200", resp.status_code == 422)
    check("2b: no analytics data present in a malformed-auth response", "data" not in (resp.get_json() or {}))

    # A well-formed but INVALID token (wrong signing key -> signature
    # verification fails, the genuine "invalid auth" case) -> 422 as
    # well, from the exact same unmodified Flask-JWT-Extended decode
    # path -- also confirmed, not assumed.
    from flask_jwt_extended import JWTManager
    import jwt as pyjwt
    with flask_app.app_context():
        wrong_key_token = pyjwt.encode({"sub": str(ADMIN_UID), "type": "access"}, "a-completely-wrong-signing-key", algorithm="HS256")
    resp = client.get(SINGLE, query_string={"period": "7d"}, headers={"Authorization": f"Bearer {wrong_key_token}"})
    check("2c: well-formed token with an invalid signature is rejected, never 200", resp.status_code in (401, 422))

    os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)
    resp = client.get(SINGLE, query_string={"period": "7d"}, headers=auth_headers(NON_ADMIN_UID))
    check("3: authenticated but NON-admin -> 403", resp.status_code == 403)

    admin_headers = auth_headers(ADMIN_UID)
    resp = client.get(SINGLE, query_string={"period": "7d"}, headers=admin_headers)
    check("4: valid admin auth -> not 401/403 (route reachable)", resp.status_code not in (401, 403))

    resp = client.post(BATCH, json={"period": "7d", "metrics": [{"metric_id": "cta_clicks_total"}]})
    check("5: batch route also requires auth -> 401", resp.status_code == 401)

    # ==================================================================
    print("\n=== PERIOD PARSING (fake service substituted) ===")
    # ==================================================================
    fake = _FakeWebsiteAnalyticsService()
    fake.responses["cta_clicks_total"] = MetricValue("cta_clicks_total", "READY", 42, ())
    routes_module._service = fake
    try:
        for period in ("today", "yesterday", "7d", "28d"):
            resp = client.get(SINGLE, query_string={"period": period}, headers=admin_headers)
            check(f"6: period={period} accepted -> 200", resp.status_code == 200)
            body = resp.get_json()
            check(f"6b: period={period} echoed correctly in response envelope", body["period"] == period)
            start = datetime.fromisoformat(body["start"])
            end = datetime.fromisoformat(body["end"])
            check(f"6c: period={period} start < end (half-open, non-empty window)", start < end)

        resp = client.get(SINGLE, headers=admin_headers)  # no period at all
        check("7: missing period defaults to 7d", resp.status_code == 200 and resp.get_json()["period"] == "7d")

        resp = client.get(SINGLE, query_string={"period": "14d"}, headers=admin_headers)
        check("8: unsupported period string -> 400", resp.status_code == 400 and resp.get_json()["error"] == "invalid_period")

        # --- custom range ---
        valid_start = "2026-01-01T00:00:00+00:00"
        valid_end = "2026-01-08T00:00:00+00:00"
        resp = client.get(SINGLE, query_string={"period": "custom", "start": valid_start, "end": valid_end}, headers=admin_headers)
        check("9: valid custom range accepted -> 200", resp.status_code == 200)

        resp = client.get(SINGLE, query_string={"period": "custom", "end": valid_end}, headers=admin_headers)
        check("10: custom missing start -> 400", resp.status_code == 400)

        resp = client.get(SINGLE, query_string={"period": "custom", "start": valid_start}, headers=admin_headers)
        check("11: custom missing end -> 400", resp.status_code == 400)

        resp = client.get(SINGLE, query_string={"period": "custom", "start": "not-a-date", "end": valid_end}, headers=admin_headers)
        check("12: custom malformed start -> 400", resp.status_code == 400)

        resp = client.get(SINGLE, query_string={"period": "custom", "start": valid_end, "end": valid_start}, headers=admin_headers)
        check("13: custom reversed range (start > end) -> 400", resp.status_code == 400)

        resp = client.get(SINGLE, query_string={"period": "custom", "start": valid_start, "end": valid_start}, headers=admin_headers)
        check("13b: custom start == end -> 400", resp.status_code == 400)

        far_future_end = "2030-01-01T00:00:00+00:00"
        resp = client.get(SINGLE, query_string={"period": "custom", "start": "2020-01-01T00:00:00+00:00", "end": far_future_end}, headers=admin_headers)
        check("14: custom range exceeding the maximum -> 400", resp.status_code == 400)

        resp = client.get(SINGLE, query_string={"period": "custom", "start": "2026-01-01T00:00:00Z", "end": "2026-01-08T00:00:00Z"}, headers=admin_headers)
        check("15: 'Z'-suffixed UTC timestamps accepted for custom", resp.status_code == 200)

        # ==================================================================
        print("\n=== METRIC DISPATCH ===")
        # ==================================================================
        fake.calls.clear()
        resp = client.get(SINGLE, query_string={"period": "7d"}, headers=admin_headers)
        check("16: exactly one get_metric() call for a single-metric request", resp.status_code == 200 and len(fake.calls) == 1)
        metric_id, window, kwargs = fake.calls[0]
        check("17: correct metric_id dispatched", metric_id == "cta_clicks_total")
        check("18: a real AnalyticsWindow object was passed", hasattr(window, "start") and hasattr(window, "end"))

        # ==================================================================
        print("\n=== READY / PARTIAL / GA4_EXTERNAL / BLOCKED ===")
        # ==================================================================
        fake.responses["tool_completions_all"] = MetricValue("tool_completions_all", "PARTIAL", 7, ("some limitation",))
        resp = client.get("/admin/api/website-analytics/metrics/tool_completions_all", query_string={"period": "7d"}, headers=admin_headers)
        body = resp.get_json()
        check("19: PARTIAL metric returns status=PARTIAL with real data and limitations", resp.status_code == 200 and body["status"] == "PARTIAL" and body["data"]["value"] == 7 and len(body["limitations"]) == 1)

        fake.responses["page_views"] = UnavailableMetric("page_views", "GA4_EXTERNAL", None, "GA4-owned, not connected.")
        resp = client.get("/admin/api/website-analytics/metrics/page_views", query_string={"period": "7d"}, headers=admin_headers)
        body = resp.get_json()
        check("20: GA4_EXTERNAL metric returns status=GA4_EXTERNAL, data=null, and a reason", resp.status_code == 200 and body["status"] == "GA4_EXTERNAL" and body["data"] is None and body["reason"])

        fake.responses["asknow_website_funnel"] = UnavailableMetric("asknow_website_funnel", "BLOCKED", None, "No website producer.")
        resp = client.get("/admin/api/website-analytics/metrics/asknow_website_funnel", query_string={"period": "7d"}, headers=admin_headers)
        body = resp.get_json()
        check("21: BLOCKED metric returns status=BLOCKED, data=null, and a reason", resp.status_code == 200 and body["status"] == "BLOCKED" and body["data"] is None and body["reason"])

        # ==================================================================
        print("\n=== ZERO-DATA SEMANTICS ===")
        # ==================================================================
        fake.responses["cta_clicks_total"] = MetricValue("cta_clicks_total", "READY", 0, ())
        resp = client.get(SINGLE, query_string={"period": "7d"}, headers=admin_headers)
        body = resp.get_json()
        check("22: a real zero-data READY metric serializes data.value=0 (numeric, not null)", body["data"]["value"] == 0 and body["data"]["value"] is not None)
        check("23: zero-data READY (status=READY, data.value=0) is structurally distinguishable from unavailable (status=GA4_EXTERNAL/BLOCKED, data=null)",
              body["status"] == "READY" and body["data"] is not None)

        # ==================================================================
        print("\n=== CAMPAIGN DIMENSION ===")
        # ==================================================================
        fake.responses["cta_clicks_by_source"] = GroupedMetricResult(
            "cta_clicks_by_source", "READY", "source",
            (GroupedMetricRow("google", 5), GroupedMetricRow("facebook", 3)), 1, 9, (),
        )
        resp = client.get("/admin/api/website-analytics/metrics/cta_clicks_by_source", query_string={"period": "7d", "dimension": "source"}, headers=admin_headers)
        body = resp.get_json()
        check("24: dimension parameter forwarded and reflected in the response", resp.status_code == 200 and body["data"]["dimension"] == "source")
        check("24b: grouped rows serialize correctly, plus unknown_count/total", len(body["data"]["rows"]) == 2 and body["data"]["unknown_count"] == 1 and body["data"]["total"] == 9)

        fake.raise_for["cta_clicks_by_source"] = UnsupportedAnalyticsDimension("bad dimension")
        resp = client.get("/admin/api/website-analytics/metrics/cta_clicks_by_source", query_string={"period": "7d", "dimension": "gclid"}, headers=admin_headers)
        check("25: unsupported campaign dimension -> 400, controlled error shape", resp.status_code == 400 and resp.get_json()["error"] == "unsupported_dimension")
        del fake.raise_for["cta_clicks_by_source"]

        # unexpected TypeError path (a dimension passed to a metric whose
        # own handler signature doesn't accept it)
        fake.raise_for["cta_clicks_total"] = TypeError("cta_clicks_total() got an unexpected keyword argument 'dimension'")
        resp = client.get(SINGLE, query_string={"period": "7d", "dimension": "source"}, headers=admin_headers)
        check("25b: a parameter unsupported by a specific metric's own handler -> controlled 400, never a raw 500", resp.status_code == 400 and resp.get_json()["error"] == "unsupported_parameter")
        del fake.raise_for["cta_clicks_total"]
        fake.responses["cta_clicks_total"] = MetricValue("cta_clicks_total", "READY", 0, ())

        # ==================================================================
        print("\n=== LIMIT VALIDATION ===")
        # ==================================================================
        fake.calls.clear()
        resp = client.get("/admin/api/website-analytics/metrics/cta_clicks_by_source", query_string={"period": "7d", "limit": "10"}, headers=admin_headers)
        check("26: valid numeric limit accepted -> 200", resp.status_code == 200)
        _, _, kwargs = fake.calls[-1]
        check("26b: limit forwarded exactly", kwargs.get("limit") == 10)

        resp = client.get("/admin/api/website-analytics/metrics/cta_clicks_by_source", query_string={"period": "7d", "limit": "not-a-number"}, headers=admin_headers)
        check("27: non-numeric limit -> 400", resp.status_code == 400 and resp.get_json()["error"] == "invalid_limit")

        resp = client.get("/admin/api/website-analytics/metrics/cta_clicks_by_source", query_string={"period": "7d", "limit": "99999"}, headers=admin_headers)
        check("28: an out-of-range limit is CLAMPED (200, not rejected) -- matches Task 11's own established clamping convention", resp.status_code == 200)
        _, _, kwargs2 = fake.calls[-1]
        check("28b: clamped to MAX_GROUP_LIMIT (100)", kwargs2.get("limit") == 100)

        resp = client.get("/admin/api/website-analytics/metrics/cta_clicks_by_source", query_string={"period": "7d", "limit": "-5"}, headers=admin_headers)
        check("28c: a limit below 1 is clamped up to 1, not rejected", resp.status_code == 200)
        _, _, kwargs3 = fake.calls[-1]
        check("28d: clamped to 1", kwargs3.get("limit") == 1)

        # ==================================================================
        print("\n=== SERVICE FAILURE ===")
        # ==================================================================
        fake.raise_for["cta_clicks_total"] = RuntimeError("simulated unexpected repository failure")
        resp = client.get(SINGLE, query_string={"period": "7d"}, headers=admin_headers)
        body = resp.get_json()
        check("29: unexpected service/repository exception -> controlled 500 JSON", resp.status_code == 500)
        check("29b: no stack trace / exception message / SQL text leaked in the response body", "simulated unexpected repository failure" not in str(body) and "Traceback" not in str(body))
        del fake.raise_for["cta_clicks_total"]
        fake.responses["cta_clicks_total"] = MetricValue("cta_clicks_total", "READY", 0, ())

        # ==================================================================
        print("\n=== PRIVACY ===")
        # ==================================================================
        resp = client.get(SINGLE, query_string={"period": "7d"}, headers=admin_headers)
        body_text = str(resp.get_json())
        forbidden = ("firebase_uid", "profile_id", "anonymous_id", "session_id", "properties", "campaign_context", "@", "razorpay", "token")
        check("30: no PII/identity/raw-JSON substring anywhere in a serialized response", not any(f in body_text.lower() for f in forbidden))

        # ==================================================================
        print("\n=== BATCH ENDPOINT ===")
        # ==================================================================
        fake.responses["cta_clicks_by_page"] = GroupedMetricResult("cta_clicks_by_page", "READY", "page_path", (), 0, 0, ())
        resp = client.post(BATCH, json={"period": "7d", "metrics": [{"metric_id": "cta_clicks_total"}, {"metric_id": "cta_clicks_by_page"}]}, headers=admin_headers)
        body = resp.get_json()
        check("31: batch with 2 valid metrics -> 200, 2 results, same shared period", resp.status_code == 200 and len(body["results"]) == 2 and body["period"] == "7d")

        resp = client.post(BATCH, json={"period": "7d", "metrics": []}, headers=admin_headers)
        check("32: empty metrics list -> 400", resp.status_code == 400)

        resp = client.post(BATCH, json={"period": "7d", "metrics": [{"metric_id": f"m{i}"} for i in range(25)]}, headers=admin_headers)
        check("33: batch exceeding MAX_BATCH_METRICS -> 400 batch_too_large", resp.status_code == 400 and resp.get_json()["error"] == "batch_too_large")

        fake.raise_for["not_a_real_metric_in_fake"] = UnsupportedWebsiteMetric("unknown")
        resp = client.post(BATCH, json={"period": "7d", "metrics": [{"metric_id": "cta_clicks_total"}, {"metric_id": "not_a_real_metric_in_fake"}]}, headers=admin_headers)
        body = resp.get_json()
        check("34: one invalid metric in a batch does not fail the whole batch (still 200)", resp.status_code == 200 and len(body["results"]) == 2)
        check("34b: the invalid entry carries its own explicit error, the valid one still succeeds",
              any(r.get("error") == "unknown_metric" for r in body["results"])
              and any(r.get("metric_id") == "cta_clicks_total" and r.get("data") is not None for r in body["results"]))
        del fake.raise_for["not_a_real_metric_in_fake"]

        resp = client.post(BATCH, json={"period": "7d", "metrics": [{"not_metric_id": "oops"}]}, headers=admin_headers)
        body = resp.get_json()
        check("35: a malformed batch entry (no metric_id) gets its own explicit error, not a 500", resp.status_code == 200 and body["results"][0]["error"] == "invalid_metric_entry")

    finally:
        routes_module._service = real_service

    # ==================================================================
    print("\n=== UNKNOWN METRIC / NOT IMPLEMENTED (real service, no DB rows needed) ===")
    # ==================================================================
    resp = client.get("/admin/api/website-analytics/metrics/totally_not_a_real_metric_id", query_string={"period": "7d"}, headers=admin_headers)
    check("36: unknown metric_id -> 404, controlled error shape", resp.status_code == 404 and resp.get_json()["error"] == "unknown_metric")

    resp = client.get("/admin/api/website-analytics/metrics/kundali_generation_completed", query_string={"period": "7d"}, headers=admin_headers)
    check("37: a READY metric outside Task 11's curated scope -> 501 not_implemented, never silently 200", resp.status_code == 501 and resp.get_json()["error"] == "not_implemented")

    # ==================================================================
    print("\n=== PROOF: unavailable metrics execute NO analytics query (real service) ===")
    # ==================================================================
    class ExplodingRepository:
        def __getattr__(self, name):
            def _boom(*a, **k):
                raise AssertionError(f"repository.{name}() must never be called for a BLOCKED/GA4_EXTERNAL metric")
            return _boom

    routes_module._service = WebsiteAnalyticsService(repository=ExplodingRepository())
    try:
        resp = client.get("/admin/api/website-analytics/metrics/page_views", query_string={"period": "7d"}, headers=admin_headers)
        check("38: GA4_EXTERNAL metric via the REAL service (exploding repository) -> 200, no exception raised", resp.status_code == 200 and resp.get_json()["status"] == "GA4_EXTERNAL")

        resp = client.get("/admin/api/website-analytics/metrics/asknow_website_funnel", query_string={"period": "7d"}, headers=admin_headers)
        check("39: BLOCKED metric via the REAL service (exploding repository) -> 200, no exception raised", resp.status_code == 200 and resp.get_json()["status"] == "BLOCKED")
    finally:
        routes_module._service = real_service

    # ==================================================================
    print("\n=== SECURITY / BOUNDARY ===")
    # ==================================================================
    import inspect
    src = open(routes_module.__file__, encoding="utf-8").read()
    import_lines = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
    check("40: routes_website_analytics.py never imports the ActivityEvent model directly", not any("models_activity_events" in l for l in import_lines))
    check("41: route source never touches db.session directly (no import of extensions/db)", not any(("extensions" in l or "import db" in l) for l in import_lines))
    check("42: no raw SQL/query/export/events endpoint exists under this prefix",
          not any(r.rule.startswith("/admin/api/website-analytics/") and r.rule not in
                  ("/admin/api/website-analytics/metrics/<metric_id>", "/admin/api/website-analytics/metrics/batch")
                  for r in flask_app.url_map.iter_rules()))

    app_src = open("app.py", encoding="utf-8").read()
    check("43: app.py registers the website analytics blueprint exactly once",
          app_src.count("app.register_blueprint(routes_website_analytics)") == 1)

    # ==================================================================
    print("\n=== SMOKE TEST -- real WebsiteAnalyticsService, real jyotishasha_local ===")
    # ==================================================================
    routes_module._service = WebsiteAnalyticsService()
    resp = client.get(
        "/admin/api/website-analytics/metrics/cta_clicks_total",
        query_string={"period": "custom", "start": "2099-01-01T00:00:00+00:00", "end": "2099-01-02T00:00:00+00:00"},
        headers=admin_headers,
    )
    check("SMOKE: real WebsiteAnalyticsService end-to-end via the route -> 200", resp.status_code == 200)
    body = resp.get_json()
    check("SMOKE: an empty far-future window yields a real 0, not an error", body["status"] == "READY" and body["data"]["value"] == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
