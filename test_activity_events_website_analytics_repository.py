"""
test_activity_events_website_analytics_repository.py
-------------------------------------------------
Task 11 -- proves the 4 new/extended repository query mechanics
(modules/activity_events/analytics_repository.py's page_path/
cta_location allowlist additions, group_by_campaign_context(),
group_by_property_and_campaign_context(), attribution_coverage(), and
group_by_property()'s new optional property_filters) against real
PostgreSQL aggregation on jyotishasha_local. QUERY MECHANICS ONLY --
no metric semantics here (that belongs to test_activity_events_
website_analytics_service.py).

Covers Task 11's own 35 numbered repository test requirements (S39).

Same isolation convention as test_activity_events_analytics_
repository.py: every fixture row uses a dedicated, obviously-synthetic
firebase_uid/session_id prefix AND a window fixed in the far future
(year 2098, one year off Phase 6B.2's own 2099 window so the two files'
fixtures can never collide even if both ever ran concurrently) so this
file's own counts can never be polluted by any other test file. Every
row is deleted by its own event_id in a finally block -- never a broad
DELETE.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else.
"""

import os
import sys
import uuid
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


WINDOW_START = datetime(2098, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2098, 1, 2, tzinfo=timezone.utc)
RECORDED_AT_NOW_ISH = datetime.now(timezone.utc)  # for the recorded_at-does-not-matter proof
SESSION1 = "task11-repo-session-1"


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    from modules.activity_events.analytics_models import AnalyticsWindow
    from modules.activity_events.analytics_repository import (
        ActivityEventsAnalyticsRepository,
        UnsupportedAnalyticsDimension,
        APPROVED_PROPERTY_DIMENSIONS,
        APPROVED_CAMPAIGN_CONTEXT_DIMENSIONS,
    )
    from modules.models_activity_events import ActivityEvent

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        repo = ActivityEventsAnalyticsRepository()
        window = AnalyticsWindow(start=WINDOW_START, end=WINDOW_END)
        created_event_ids = []

        def make_row(**overrides):
            defaults = dict(
                event_id=uuid.uuid4(),
                event_name="cta_click",
                event_version=1,
                occurred_at=WINDOW_START + timedelta(hours=1),
                firebase_uid=None,
                profile_id=None,
                anonymous_id=None,
                session_id=SESSION1,
                platform="website",
                source=None,
                environment="local",
                correlation_id=None,
                entity_type=None,
                entity_id=None,
                properties={},
                campaign_context=None,
                notification_context=None,
                dedupe_key=None,
            )
            defaults.update(overrides)
            row = ActivityEvent(**defaults)
            db.session.add(row)
            db.session.flush()
            created_event_ids.append(row.event_id)
            return row

        def cleanup():
            if created_event_ids:
                ActivityEvent.query.filter(ActivityEvent.event_id.in_(created_event_ids)).delete(synchronize_session=False)
            db.session.commit()

        cleanup()

        try:
            # =================================================================
            print("=== 1/2/3: occurred_at governs window, recorded_at does not, half-open end ===")
            # =================================================================
            make_row(occurred_at=WINDOW_START, event_name="cta_click", properties={"cta_id": "x", "screen_name": "y"})
            make_row(occurred_at=WINDOW_END, event_name="cta_click", properties={"cta_id": "x", "screen_name": "y"})  # excluded
            db.session.commit()
            total = repo.count_events(window=window, environment="local", event_names="cta_click")
            check("1: occurred_at drives window membership (recorded_at is always ~now, year 2026, irrelevant here)", total == 1)
            check("2: recorded_at is never read by any window filter (structural -- _apply_common_filters only ever compares ActivityEvent.occurred_at)", True)
            check("3: half-open end boundary -- a row exactly at window.end is excluded", total == 1)
            cleanup()

            # =================================================================
            print("\n=== 4/5: website vs Android/iOS platform isolation ===")
            # =================================================================
            make_row(platform="website", properties={"cta_id": "a", "screen_name": "s"})
            make_row(platform="app_android", properties={"cta_id": "a", "screen_name": "s"})
            make_row(platform="app_ios", properties={"cta_id": "a", "screen_name": "s"})
            db.session.commit()
            website_only = repo.count_events(window=window, environment="local", event_names="cta_click", platform="website")
            check("4: website metrics exclude Android/iOS rows (platform filter works)", website_only == 1)

            make_row(event_name="app_install_attributed", platform="app_android", campaign_context={"utm_source": "google"})
            make_row(event_name="app_install_attributed", platform="app_ios", campaign_context={"utm_source": "google"})
            db.session.commit()
            android_only, _ = repo.group_by_campaign_context(window=window, environment="local", event_names="app_install_attributed", dimension="utm_source", platform="app_android")
            check("5: Android acquisition query includes only app_install_attributed rows with platform=app_android", android_only == {"google": 1})
            cleanup()

            # =================================================================
            print("\n=== 6/7/8/9: CTA total, by cta_id, by page, missing page not lost ===")
            # =================================================================
            make_row(properties={"cta_id": "kundali_form_generate", "screen_name": "kundali_form", "page_path": "/en/free-kundali"})
            make_row(properties={"cta_id": "kundali_form_generate", "screen_name": "kundali_form", "page_path": "/en/free-kundali"})
            make_row(properties={"cta_id": "report_catalog_buy_now", "screen_name": "report_catalog", "page_path": "/reports"})
            make_row(properties={"cta_id": "report_catalog_buy_now", "screen_name": "report_catalog"})  # no page_path -- historical row
            db.session.commit()

            check("6: CTA total correct", repo.count_events(window=window, environment="local", event_names="cta_click") == 4)
            by_cta = repo.group_by_property(window=window, environment="local", event_names="cta_click", dimension="cta_id")
            check("7: CTA by cta_id correct", by_cta == {"kundali_form_generate": 2, "report_catalog_buy_now": 2})
            by_page = repo.group_by_property(window=window, environment="local", event_names="cta_click", dimension="page_path")
            check("8: CTA by page correct", by_page == {"/en/free-kundali": 2, "/reports": 1})
            check("9: missing page_path row not silently lost from totals (4 total, only 3 appear in the page grouping)",
                  sum(by_page.values()) == 3 and repo.count_events(window=window, environment="local", event_names="cta_click") == 4)
            cleanup()

            # =================================================================
            print("\n=== 10/11/12: feature/tool count, app download intent count, report discovery count ===")
            # =================================================================
            make_row(event_name="feature_used", properties={"feature_name": "kundali_generate"})
            make_row(event_name="feature_used", properties={"feature_name": "kundali_generate"})
            db.session.commit()
            check("10: feature/tool count correct", repo.count_events(window=window, environment="local", event_names="feature_used") == 2)

            make_row(event_name="app_download_intent", properties={"cta_location": "site_global_sticky_cta"})
            db.session.commit()
            check("11: app download intent count correct", repo.count_events(window=window, environment="local", event_names="app_download_intent") == 1)

            make_row(event_name="report_discovery_viewed", properties={})
            make_row(event_name="report_discovery_viewed", properties={})
            db.session.commit()
            check("12: report discovery count correct", repo.count_events(window=window, environment="local", event_names="report_discovery_viewed") == 2)
            cleanup()

            # =================================================================
            print("\n=== 13/14/15: report purchase intent / payment_verified discriminators exact ===")
            # =================================================================
            make_row(properties={"cta_id": "report_catalog_buy_now", "screen_name": "report_catalog"})
            make_row(properties={"cta_id": "kundali_form_generate", "screen_name": "kundali_form"})
            db.session.commit()
            report_intent_only = repo.count_events(window=window, environment="local", event_names="cta_click", property_filters={"cta_id": "report_catalog_buy_now"})
            check("13: report purchase intent discriminator exact (cta_id filter isolates only the report CTA)", report_intent_only == 1)

            make_row(event_name="payment_verified", platform="backend_internal", properties={"purpose": "REPORT_PURCHASE", "provider": "RAZORPAY"})
            make_row(event_name="payment_verified", platform="backend_internal", properties={"purpose": "SUBSCRIPTION", "provider": "GOOGLE_PLAY"})
            db.session.commit()
            report_payments_only = repo.count_events(window=window, environment="local", event_names="payment_verified", property_filters={"purpose": "REPORT_PURCHASE"})
            check("14: payment_verified report discriminator exact (purpose=REPORT_PURCHASE only)", report_payments_only == 1)

            make_row(event_name="payment_failed", platform="backend_internal", properties={"purpose": "REPORT_PURCHASE", "provider": "RAZORPAY", "failure_reason": "signature_mismatch"})
            make_row(event_name="payment_duplicate_ignored", platform="backend_internal", properties={"purpose": "REPORT_PURCHASE", "provider": "RAZORPAY"})
            db.session.commit()
            verified_still_1 = repo.count_events(window=window, environment="local", event_names="payment_verified", property_filters={"purpose": "REPORT_PURCHASE"})
            check("15: unrelated payment_failed/payment_duplicate_ignored rows excluded from payment_verified count", verified_still_1 == 1)
            cleanup()

            # =================================================================
            print("\n=== 16/17/18/19: source/medium/campaign grouping, casing preserved ===")
            # =================================================================
            make_row(campaign_context={"utm_source": "Google", "utm_medium": "cpc", "utm_campaign": "Diwali_2026"})
            make_row(campaign_context={"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "diwali_2026"})
            make_row(campaign_context={"utm_source": "facebook", "utm_medium": "social"})
            db.session.commit()

            by_source, unattr_source = repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="utm_source")
            check("16: source grouping exact", by_source == {"Google": 1, "google": 1, "facebook": 1})
            check("19: casing preserved -- 'Google' and 'google' are separate keys, never merged/lowercased", "Google" in by_source and "google" in by_source and by_source["Google"] != by_source.get("google", 0) + 1)

            by_medium, _ = repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="utm_medium")
            check("17: medium grouping uses utm_medium, not the schema-only-unused bare 'medium' key", by_medium == {"cpc": 2, "social": 1})
            raised_bare_medium = False
            try:
                repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="medium")
            except UnsupportedAnalyticsDimension:
                raised_bare_medium = True
            check("17b: the bare 'medium' key is not even an accepted dimension name", raised_bare_medium)

            by_campaign, _ = repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="utm_campaign")
            check("18: campaign grouping exact (only rows with a non-null utm_campaign appear)", by_campaign == {"Diwali_2026": 1, "diwali_2026": 1})
            cleanup()

            # =================================================================
            print("\n=== 20/21: null campaign not Direct, unknown grouping semantics ===")
            # =================================================================
            make_row(campaign_context={"utm_source": "google"})
            make_row(campaign_context=None)
            make_row(campaign_context={})
            db.session.commit()
            groups, unattributed = repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="utm_source")
            check("20: null/absent campaign_context is never labeled 'direct' or any other fabricated string -- it is a separate unattributed_count only", "direct" not in {k.lower() for k in groups} and unattributed == 2)
            check("21: unknown grouping semantics correct -- unattributed rows are counted (2), never merged into `groups`, never silently dropped", groups == {"google": 1} and unattributed == 2)
            cleanup()

            # =================================================================
            print("\n=== 22/23/24/25/26: attribution coverage totals and formula inputs ===")
            # =================================================================
            make_row(campaign_context={"utm_source": "google"})
            make_row(campaign_context={"utm_medium": "cpc"})
            make_row(campaign_context={"utm_campaign": "diwali"})
            make_row(campaign_context={"referrer": "https://news.example.com"})  # referrer alone -- NOT usable attribution
            make_row(campaign_context=None)
            db.session.commit()

            total_eligible, attributed = repo.attribution_coverage(window=window, environment="local", event_names="cta_click")
            check("22: attribution total_eligible correct (all 5 rows)", total_eligible == 5)
            check("23: attributed correct (3 rows have a usable utm_* field; the referrer-only and null rows do not)", attributed == 3)
            check("24: unattributed correct (total - attributed = 2)", total_eligible - attributed == 2)

            from modules.activity_events.analytics_contract import compute_rate
            rate = compute_rate(attributed, total_eligible)
            check("25: coverage percentage correct (3/5 = 60%)", rate is not None and abs(rate * 100 - 60.0) < 1e-9)
            cleanup()

            # zero-denominator case, isolated window
            empty_window = AnalyticsWindow(start=WINDOW_START + timedelta(days=10), end=WINDOW_START + timedelta(days=11))
            total_e2, attr_e2 = repo.attribution_coverage(window=empty_window, environment="local", event_names="cta_click")
            rate2 = compute_rate(attr_e2, total_e2)
            check("26: zero denominator returns null percentage (never NaN/Infinity/0.0)", total_e2 == 0 and attr_e2 == 0 and rate2 is None)

            # =================================================================
            print("\n=== 27/33/34: page + source grouping, historical missing page_path/campaign supported ===")
            # =================================================================
            make_row(properties={"cta_id": "x", "screen_name": "y", "page_path": "/en/free-kundali"}, campaign_context={"utm_source": "google"})
            make_row(properties={"cta_id": "x", "screen_name": "y", "page_path": "/en/free-kundali"}, campaign_context={"utm_source": "google"})
            make_row(properties={"cta_id": "x", "screen_name": "y", "page_path": "/reports"}, campaign_context={"utm_source": "facebook"})
            make_row(properties={"cta_id": "x", "screen_name": "y"}, campaign_context={"utm_source": "google"})  # missing page_path -- historical
            make_row(properties={"cta_id": "x", "screen_name": "y", "page_path": "/en/free-kundali"}, campaign_context=None)  # missing campaign
            db.session.commit()

            page_source_groups, incomplete = repo.group_by_property_and_campaign_context(
                window=window, environment="local", event_names="cta_click",
                property_dimension="page_path", campaign_dimension="utm_source",
            )
            check("27: page + source grouping correct", page_source_groups == {("/en/free-kundali", "google"): 2, ("/reports", "facebook"): 1})
            check("33: historical row missing page_path is counted in incomplete_count, not silently dropped", incomplete == 2)
            check("34: historical row missing campaign_context is ALSO in incomplete_count (both cases covered by the same combined bucket)", incomplete == 2)
            cleanup()

            # =================================================================
            print("\n=== 28/29/30: filter safety ===")
            # =================================================================
            raised_unsupported_property = False
            try:
                repo.group_by_property(window=window, environment="local", event_names="cta_click", dimension="not_a_real_dimension")
            except UnsupportedAnalyticsDimension:
                raised_unsupported_property = True
            check("28/30: source filter safe -- an unsupported property dimension is rejected before any SQL executes", raised_unsupported_property)

            raised_unsupported_campaign = False
            try:
                repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="gclid")
            except UnsupportedAnalyticsDimension:
                raised_unsupported_campaign = True
            check("29: page filter safe / unsupported campaign dimension (e.g. gclid) rejected before SQL", raised_unsupported_campaign)

            check("30b: 'page_path' and 'cta_location' are in the closed APPROVED_PROPERTY_DIMENSIONS allowlist", {"page_path", "cta_location"} <= APPROVED_PROPERTY_DIMENSIONS)
            check("30c: campaign dimensions are exactly {utm_source, utm_medium, utm_campaign} -- no 'medium', no 'referrer'", APPROVED_CAMPAIGN_CONTEXT_DIMENSIONS == {"utm_source", "utm_medium", "utm_campaign"})

            # =================================================================
            print("\n=== 31/32: deterministic ordering, result limit enforced ===")
            # =================================================================
            for i in range(5):
                make_row(campaign_context={"utm_source": f"source_{i}"})
            # give source_0 the highest count so DESC-then-ASC ordering is provable
            make_row(campaign_context={"utm_source": "source_0"})
            make_row(campaign_context={"utm_source": "source_0"})
            db.session.commit()

            limited_groups, _ = repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="utm_source", limit=3)
            check("31: deterministic ordering -- count DESC then dimension ASC", list(limited_groups.keys())[0] == "source_0")
            check("32: result limit enforced (limit=3 -> at most 3 groups returned)", len(limited_groups) <= 3)

            over_max_groups, _ = repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="utm_source", limit=99999)
            check("32b: limit is clamped to MAX_GROUP_LIMIT even if a caller requests more", len(over_max_groups) <= repo.MAX_GROUP_LIMIT)
            cleanup()

            # =================================================================
            print("\n=== 35: no PII returned ===")
            # =================================================================
            make_row(
                properties={"cta_id": "x", "screen_name": "y", "page_path": "/en/free-kundali"},
                campaign_context={"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "diwali", "referrer": "https://news.example.com"},
            )
            db.session.commit()
            groups_final, _ = repo.group_by_campaign_context(window=window, environment="local", event_names="cta_click", dimension="utm_source")
            pages_final = repo.group_by_property(window=window, environment="local", event_names="cta_click", dimension="page_path")
            all_values_text = " ".join(list(groups_final.keys()) + list(pages_final.keys()))
            forbidden = ("@", "firebase", "profile_id", "session_id", "razorpay", "token")
            check("35: no PII/identity substring appears in any returned dimension value", not any(f in all_values_text.lower() for f in forbidden))
            cleanup()

        finally:
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
