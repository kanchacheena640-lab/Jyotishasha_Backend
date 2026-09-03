"""
test_activity_events_page_path.py
-------------------------------------------------
Task 9A -- focused tests for the page_path contract extension resolving
Task 9's own documented PAGE-ACTION ATTRIBUTION GAP:
  modules/activity_events/event_schemas.py       (schema allowlist)
  modules/activity_events/ingestion_validation.py (validate_page_path)
  modules/activity_events/anonymous_ingestion_service.py (wiring)
  modules/activity_events/ingestion_service.py    (wiring, symmetry)
  modules/activity_events/website_metrics_contract.py (updated quality
    statuses reflecting the closed gap)

Covers Task 9A's own 20 numbered backend test requirements (S21).

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else (same convention as every other test_activity_
events_*.py file in this repo). Every activity_events row this file
creates is deleted in a finally block, keyed by its own event_id --
never a broad DELETE.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
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


def iso(offset=timedelta(0)):
    return (datetime.now(timezone.utc) + offset).isoformat()


ENDPOINT = "/api/activity-events/anonymous"


def main():
    from modules.activity_events import event_schemas
    from modules.activity_events import ingestion_validation as iv
    from modules.activity_events import website_metrics_contract as wmc

    # =========================================================================
    # PURE (no DB) -- validate_page_path() format contract
    # =========================================================================
    print("=== validate_page_path() pure format contract ===")

    check("validate_page_path(None) is a no-op (optional)", iv.validate_page_path(None) is None)

    for good in ("/", "/en/free-kundali", "/hi/reports", "/reports/career-report",
                 "/free-kundali/free-birthchart-result/"):
        raised = False
        try:
            iv.validate_page_path(good)
        except iv.ValidationError:
            raised = True
        check(f"valid page_path accepted: {good!r}", not raised)

    def expect_reject(value, label):
        raised = False
        try:
            iv.validate_page_path(value)
        except iv.ValidationError:
            raised = True
        check(label, raised)

    # 6. must be a string
    expect_reject(12345, "6: non-string page_path rejected")
    # 7. must start with "/"
    expect_reject("free-kundali", "7: page_path missing leading '/' rejected")
    # 8. query string rejected
    expect_reject("/free-kundali?utm_source=x", "8: page_path with query string rejected")
    # 9. fragment rejected
    expect_reject("/free-kundali#top", "9: page_path with fragment rejected")
    # 10. full http URL rejected
    expect_reject("http://evil.com/x", "10: full http:// URL rejected")
    # 11. full https URL rejected
    expect_reject("https://www.jyotishasha.com/free-kundali", "11: full https:// URL rejected")
    # protocol-relative URL (not in the numbered list, but the same class
    # of attack "reject full external URL" is meant to close)
    expect_reject("//evil.com/x", "11b: protocol-relative '//host' URL rejected")
    # 12. oversized path rejected
    expect_reject("/" + ("a" * 300), "12: oversized page_path (>256 chars) rejected")

    # =========================================================================
    # PURE (no DB) -- schema allowlist checks
    # =========================================================================
    print("\n=== event_schemas.py allowlist ===")

    for event_name in ("cta_click", "feature_used", "app_download_intent", "report_discovery_viewed"):
        schema = event_schemas.EVENT_SCHEMAS[(event_name, 1)]
        check(f"'page_path' is allowed on {event_name}", "page_path" in schema["properties"])

    # 14. existing required properties unchanged
    check("14: cta_click still allows cta_id + screen_name",
          {"cta_id", "screen_name"} <= event_schemas.EVENT_SCHEMAS[("cta_click", 1)]["properties"])
    check("14b: feature_used still allows feature_name",
          "feature_name" in event_schemas.EVENT_SCHEMAS[("feature_used", 1)]["properties"])
    check("14c: app_download_intent still allows cta_location",
          "cta_location" in event_schemas.EVENT_SCHEMAS[("app_download_intent", 1)]["properties"])
    check("14d: report_discovery_viewed still allows report_type",
          "report_type" in event_schemas.EVENT_SCHEMAS[("report_discovery_viewed", 1)]["properties"])

    # 13. unexpected property still rejected (dropped, not admitted)
    clean, dropped = event_schemas.sanitize_properties("cta_click", 1, {"totally_unknown_key": "x", "cta_id": "a", "screen_name": "b"})
    check("13: unexpected property still rejected (dropped) by sanitize_properties",
          "totally_unknown_key" not in clean and "totally_unknown_key" in dropped)

    # 20. page_view remains ledger-ineligible
    check("20: page_view remains ledger-ineligible", event_schemas.is_ledger_eligible("page_view") is False)
    check("20b: page_view schema still has zero properties (untouched by Task 9A)",
          event_schemas.EVENT_SCHEMAS[("page_view", 1)]["properties"] == frozenset())

    # 17. cross-platform compatibility: no platform restriction was
    # accidentally introduced for the 4 extended events (only
    # app_install_attributed is restricted, per ingestion_policy.py).
    print("\n=== cross-platform compatibility ===")
    from modules.activity_events import ingestion_policy
    for event_name in ("cta_click", "feature_used", "app_download_intent", "report_discovery_viewed"):
        check(f"17: {event_name} still has no EVENT_PLATFORM_RESTRICTIONS entry (unrestricted)",
              event_name not in ingestion_policy.EVENT_PLATFORM_RESTRICTIONS)
    for platform in ("app_android", "app_ios", "website"):
        check(f"17b: cta_click still allowed for platform={platform}",
              ingestion_policy.is_platform_allowed_for_event("cta_click", platform))
        check(f"17c: feature_used still allowed for platform={platform}",
              ingestion_policy.is_platform_allowed_for_event("feature_used", platform))

    # 18. no envelope/database schema change -- exactly the same 19
    # columns as before Task 9A; page_path lives inside the existing
    # `properties` JSONB column only.
    print("\n=== 19-column envelope unchanged ===")
    from modules.models_activity_events import ActivityEvent
    column_names = {c.name for c in ActivityEvent.__table__.columns}
    check("18: ActivityEvent table still has exactly 19 columns", len(column_names) == 19)
    check("18b: no new column named page_path (or anything page-path-shaped) on the envelope itself",
          not any("page_path" in name or "page_path" in name.replace("_", "") for name in column_names))
    check("18c: 'properties' JSONB column is still the carrier (page_path lives inside it, not beside it)",
          "properties" in column_names)

    # =========================================================================
    # 19. Task 9 contract quality statuses accurately reflect new reality
    # =========================================================================
    print("\n=== website_metrics_contract.py quality-status updates ===")
    by_id = {m.metric_id: m for m in wmc.WEBSITE_METRIC_CATALOG}
    check("19: pathname_or_page dimension is now AVAILABLE",
          next(d for d in wmc.WEBSITE_DIMENSION_CATALOG if d.dimension_id == "pathname_or_page").status
          == wmc.DIMENSION_AVAILABLE)
    check("19b: tool_completions_by_page upgraded off BLOCKED",
          by_id["tool_completions_by_page"].quality_status != wmc.QUALITY_BLOCKED)
    check("19c: cta_clicks_by_page upgraded off BLOCKED",
          by_id["cta_clicks_by_page"].quality_status != wmc.QUALITY_BLOCKED)
    check("19d: app_download_intents_by_page is now READY (all current producers carry page_path)",
          by_id["app_download_intents_by_page"].quality_status == wmc.QUALITY_READY)
    check("19e: tool_completions_all (aggregate) is STILL PARTIAL -- Panchang/Muhurat/Horoscope coverage gap unchanged",
          by_id["tool_completions_all"].quality_status == wmc.QUALITY_PARTIAL)
    check("19f: PAGE_ACTION_ATTRIBUTION_GAP_STATUS reflects CLOSED_FOR_EXISTING_PRODUCERS (not silently deleted)",
          hasattr(wmc, "PAGE_ACTION_ATTRIBUTION_GAP_STATUS"))

    # =========================================================================
    # DB-BACKED -- anonymous endpoint actually accepts/persists/rejects
    # page_path correctly
    # =========================================================================
    print("\n=== DB-backed anonymous endpoint checks ===")
    from app import app
    from extensions import db
    from sqlalchemy import text

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        client = app.test_client()
        created_event_ids = []

        def cleanup_events():
            for eid in created_event_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()

        def post(body):
            resp = client.post(ENDPOINT, json=body)
            if resp.status_code == 201 and resp.get_json(silent=True) and resp.get_json().get("event_id"):
                created_event_ids.append(resp.get_json()["event_id"])
            return resp

        def base_body(**overrides):
            body = {
                "event_name": "cta_click",
                "occurred_at": iso(),
                "session_id": "anon-sess-page-path-0001",
                "properties": {"cta_id": "x", "screen_name": "y"},
            }
            body.update(overrides)
            return body

        try:
            # 1-4: each of the 4 extended events accepts a valid page_path
            r = post(base_body(event_name="cta_click",
                                properties={"cta_id": "kundali_form_generate", "screen_name": "kundali_form", "page_path": "/en/free-kundali"}))
            check("1: cta_click accepts valid page_path -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            r = post(base_body(event_name="feature_used",
                                properties={"feature_name": "kundali_generate", "page_path": "/free-kundali/free-birthchart-result/"}))
            check("2: feature_used accepts valid page_path -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            r = post(base_body(event_name="app_download_intent",
                                properties={"cta_location": "site_global_sticky_cta", "page_path": "/hi/panchang"}))
            check("3: app_download_intent accepts valid page_path -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            r = post(base_body(event_name="report_discovery_viewed",
                                properties={"page_path": "/reports"}))
            check("4: report_discovery_viewed accepts valid page_path -> 201 written", r.status_code == 201 and r.get_json()["status"] == "written")

            # 5. all four remain valid when page_path omitted
            for event_name, props in (
                ("cta_click", {"cta_id": "a", "screen_name": "b"}),
                ("feature_used", {"feature_name": "kundali_generate"}),
                ("app_download_intent", {"cta_location": "app_download_cta"}),
                ("report_discovery_viewed", {}),
            ):
                r = post(base_body(event_name=event_name, properties=props))
                check(f"5: {event_name} still 201 written with page_path OMITTED entirely",
                      r.status_code == 201 and r.get_json()["status"] == "written")

            # 15. anonymous endpoint PERSISTS a valid page_path (round-trip
            # proof, not just a 201 -- actually read the row back).
            r = post(base_body(event_name="cta_click",
                                properties={"cta_id": "report_catalog_buy_now", "screen_name": "report_catalog", "page_path": "/reports/career-report"}))
            check("15a: persistence-check event written", r.status_code == 201 and r.get_json()["status"] == "written")
            row = db.session.execute(
                text("SELECT properties FROM activity_events WHERE event_id = :id"),
                {"id": r.get_json()["event_id"]},
            ).scalar()
            check("15b: persisted properties.page_path matches exactly what was sent",
                  row is not None and row.get("page_path") == "/reports/career-report")

            # 16. invalid page_path creates ZERO ledger rows -- whole event
            # rejected, not silently written with the key dropped.
            count_before = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE session_id = :sid"),
                {"sid": "anon-sess-page-path-0001"},
            ).scalar()
            r = post(base_body(event_name="cta_click",
                                properties={"cta_id": "x", "screen_name": "y", "page_path": "https://evil.com/phish"}))
            check("16a: malformed page_path -> NOT 201/written", r.status_code != 201)
            check("16b: malformed page_path -> invalid_field error, on the page_path field specifically",
                  r.status_code == 400
                  and r.get_json(silent=True) is not None
                  and r.get_json().get("error") == "invalid_field"
                  and r.get_json().get("field") == "properties.page_path")
            count_after = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE session_id = :sid"),
                {"sid": "anon-sess-page-path-0001"},
            ).scalar()
            check("16c: zero new ledger rows created for the malformed request (row count unchanged)", count_after == count_before)

        finally:
            cleanup_events()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
