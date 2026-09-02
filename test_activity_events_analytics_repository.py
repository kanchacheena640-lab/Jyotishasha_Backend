"""
test_activity_events_analytics_repository.py
-------------------------------------------------
Phase 6B.2 -- proves modules/activity_events/analytics_repository.py's
real PostgreSQL aggregation against jyotishasha_local. Repository is
QUERY MECHANICS ONLY (see that module's own docstring) -- this file
proves the mechanics, not metric semantics (no DAU/funnel/rate
assertions here; that belongs to Phase 6B.3's service-layer tests).

Every fixture row uses a dedicated, obviously-synthetic firebase_uid/
session_id prefix AND a window fixed in the far future (year 2099) so
this file's own row counts can never be polluted by leftover fixtures
from any other test file (which all use `datetime.now()`-ish
occurred_at values, i.e. the 2020s) -- no other test file could ever
plausibly insert a row inside a 2099 window. This also gives a clean,
free proof that occurred_at (not recorded_at, which is always
~"now" == the 2020s regardless of what occurred_at is set to) governs
window membership -- see the dedicated section below.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. Every row this file creates is deleted by its
own event_id in a finally block -- never a broad DELETE.
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


# A window no other test file could plausibly ever touch.
WINDOW_START = datetime(2099, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2099, 1, 2, tzinfo=timezone.utc)
FB1 = "phase6b2-fb-1"
FB2 = "phase6b2-fb-2"
SESSION1 = "phase6b2-session-1"
SESSION2 = "phase6b2-session-2"


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    from modules.activity_events.analytics_models import AnalyticsWindow
    from modules.activity_events.analytics_repository import (
        ActivityEventsAnalyticsRepository,
        UnsupportedAnalyticsDimension,
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
                firebase_uid=FB1,
                profile_id=None,
                anonymous_id=None,
                session_id=SESSION1,
                platform="app_android",
                source="flutter_app",
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
                ActivityEvent.query.filter(
                    ActivityEvent.event_id.in_(created_event_ids)
                ).delete(synchronize_session=False)
            db.session.commit()

        cleanup()  # defensive pre-run cleanup, same convention as sibling files

        try:
            # ==================================================================
            print("=== 1/2/3: total count, start included, end excluded ===")
            # ==================================================================
            make_row(occurred_at=WINDOW_START)  # exactly on start -- must count
            make_row(occurred_at=WINDOW_START + timedelta(hours=12))
            make_row(occurred_at=WINDOW_END)  # exactly on end -- must NOT count
            db.session.commit()

            total = repo.count_events(window=window, environment="local", event_names="cta_click")
            check("1: total count == 2 (only rows strictly inside [start, end))", total == 2)

            start_row_count = repo.count_events(
                window=AnalyticsWindow(start=WINDOW_START, end=WINDOW_START + timedelta(seconds=1)),
                environment="local", event_names="cta_click",
            )
            check("2: start boundary is included (a row exactly at window.start counts)", start_row_count == 1)

            end_row_count = repo.count_events(
                window=AnalyticsWindow(start=WINDOW_END - timedelta(seconds=1), end=WINDOW_END),
                environment="local", event_names="cta_click",
            )
            check("3: end boundary is excluded (a row exactly at window.end does NOT count)", end_row_count == 0)

            # ==================================================================
            print("\n=== 4/30: environment filtering is mandatory and effective ===")
            # ==================================================================
            raised = False
            try:
                repo.count_events(window=window, event_names="cta_click")  # environment omitted
            except TypeError:
                raised = True
            check("4: calling count_events() without environment -> TypeError (no default exists)", raised)

            # A synthetic "production"-tagged row inserted into the LOCAL DB
            # solely to prove filtering -- explicitly permitted by this
            # phase's own task brief, cleaned up by event_id like every
            # other fixture row here. Zero possibility of touching the real
            # production database (DATABASE_URL is jyotishasha_local).
            make_row(event_name="feature_used", environment="production", properties={"feature_name": "phase6b2_prod_probe"})
            db.session.commit()

            local_only = repo.count_events(window=window, environment="local", event_names="feature_used")
            prod_only = repo.count_events(window=window, environment="production", event_names="feature_used")
            check("30: environment='local' does NOT see the production-tagged row", local_only == 0)
            check("30b: environment='production' sees ONLY the production-tagged row", prod_only == 1)

            # ==================================================================
            print("\n=== 5/6: platform filter ===")
            # ==================================================================
            make_row(event_name="feature_used", platform="app_ios", properties={"feature_name": "phase6b2_ios"})
            make_row(event_name="feature_used", platform="app_android", properties={"feature_name": "phase6b2_android"})
            db.session.commit()

            ios_count = repo.count_events(window=window, environment="local", event_names="feature_used", platform="app_ios")
            check("5: platform filter restricts to exactly the matching platform", ios_count == 1)

            all_platforms = repo.count_events(window=window, environment="local", event_names="feature_used")
            check("6: platform=None does not restrict (both platforms counted)", all_platforms == 2)

            # ==================================================================
            print("\n=== 7/8: event_name filter (single + multiple) ===")
            # ==================================================================
            make_row(event_name="asknow_entry_viewed", properties={})
            db.session.commit()

            single = repo.count_events(window=window, environment="local", event_names="asknow_entry_viewed")
            check("7: single event_name filter matches only that event", single == 1)

            multi = repo.count_events(window=window, environment="local", event_names=["cta_click", "feature_used"])
            all_events = repo.count_events(window=window, environment="local")
            check("8: multiple event_names filter matches exactly the union (2 cta_click + 2 feature_used)", multi == 4)
            check("8b: the union plus the excluded third type (asknow_entry_viewed) accounts for every local row",
                  multi + single == all_events)

            # ==================================================================
            print("\n=== 9/10/11/12: distinct firebase_uid users ===")
            # ==================================================================
            fb_probe_event = "login_completed"
            make_row(event_name=fb_probe_event, firebase_uid=FB1, properties={"method": "google"})
            make_row(event_name=fb_probe_event, firebase_uid=FB1, properties={"method": "google"})  # dup FB1
            make_row(event_name=fb_probe_event, firebase_uid=FB2, properties={"method": "google"})
            make_row(event_name=fb_probe_event, firebase_uid=None, profile_id=None, properties={"method": "google"})
            make_row(event_name=fb_probe_event, firebase_uid=None, profile_id=999999, properties={"method": "google"})
            db.session.commit()

            distinct_users = repo.count_distinct_users(window=window, environment="local", event_names=fb_probe_event)
            check("9/12: distinct firebase_uid count == 2 (FB1 counted once despite duplicate rows)", distinct_users == 2)
            check("10: NULL firebase_uid rows excluded (not counted as a 3rd/4th/5th user)", distinct_users == 2)
            check("11: profile_id does NOT substitute for a missing firebase_uid "
                  "(the profile_id=999999/firebase_uid=None row still doesn't count)", distinct_users == 2)

            # ==================================================================
            print("\n=== 13/14/15: distinct session_id ===")
            # ==================================================================
            make_row(event_name="cta_click", session_id=SESSION1)  # dup SESSION1 (also from row #1 above)
            make_row(event_name="cta_click", session_id=SESSION2)
            make_row(event_name="cta_click", session_id=None)
            db.session.commit()

            distinct_sessions = repo.count_distinct_sessions(window=window, environment="local", event_names="cta_click")
            check("13/15: distinct session_id count reflects unique sessions only (duplicates counted once)",
                  distinct_sessions == 2)
            check("14: NULL session_id excluded", distinct_sessions == 2)

            # ==================================================================
            print("\n=== 16/17/18: property grouping ===")
            # ==================================================================
            make_row(event_name="cta_click", properties={"cta_id": "phase6b2_cta_a", "screen_name": "home"})
            make_row(event_name="cta_click", properties={"cta_id": "phase6b2_cta_a", "screen_name": "home"})
            make_row(event_name="cta_click", properties={"cta_id": "phase6b2_cta_b", "screen_name": "explore"})
            make_row(event_name="cta_click", properties={"screen_name": "no_cta_id_here"})  # missing cta_id
            db.session.commit()

            by_cta = repo.group_by_property(
                window=window, environment="local", event_names="cta_click", dimension="cta_id",
            )
            check("16: property grouping produces correct per-value counts",
                  by_cta.get("phase6b2_cta_a") == 2 and by_cta.get("phase6b2_cta_b") == 1)
            check("17: a row missing the grouped property is excluded, not folded into a fake bucket",
                  "unknown" not in by_cta and sum(by_cta.values()) == 3)

            raised = False
            try:
                repo.group_by_property(window=window, environment="local", event_names="cta_click", dimension="not_a_real_dimension")
            except UnsupportedAnalyticsDimension:
                raised = True
            check("18: invalid property dimension rejected", raised)

            # ==================================================================
            print("\n=== 19/20: property-value filter ===")
            # ==================================================================
            purchase_count = repo.count_events(
                window=window, environment="local", event_names="cta_click",
                property_filters={"cta_id": "phase6b2_cta_a"},
            )
            check("19: property-value filter matches exactly the rows with that value", purchase_count == 2)

            raised = False
            try:
                repo.count_events(window=window, environment="local", event_names="cta_click",
                                   property_filters={"not_a_real_key": "x"})
            except UnsupportedAnalyticsDimension:
                raised = True
            check("20: invalid property filter key rejected", raised)

            # ==================================================================
            print("\n=== 21/22/23: notification context ===")
            # ==================================================================
            make_row(event_name="notification_opened", firebase_uid=FB1, properties={},
                     notification_context={"notification_id": "phase6b2-notif-1", "slot": "morning"})
            make_row(event_name="notification_opened", firebase_uid=FB1, properties={},
                     notification_context={"notification_id": "phase6b2-notif-2", "slot": "morning"})
            make_row(event_name="notification_opened", firebase_uid=FB2, properties={},
                     notification_context={"notification_id": "phase6b2-notif-3", "slot": "evening"})
            make_row(event_name="notification_opened", firebase_uid=FB2, properties={},
                     notification_context=None)  # no context at all
            db.session.commit()

            by_slot = repo.group_by_notification_context(
                window=window, environment="local", event_names="notification_opened", dimension="slot",
            )
            check("21: notification-context grouping works", by_slot.get("morning") == 2 and by_slot.get("evening") == 1)
            check("21b: a row with no notification_context is excluded from grouping", sum(by_slot.values()) == 3)

            raised = False
            try:
                repo.group_by_notification_context(window=window, environment="local", event_names="notification_opened", dimension="bogus")
            except UnsupportedAnalyticsDimension:
                raised = True
            check("22: invalid notification dimension rejected", raised)

            opened_users = repo.count_distinct_users(window=window, environment="local", event_names="notification_opened")
            check("23: unique opened users can be counted", opened_users == 2)

            # ==================================================================
            print("\n=== 24: Ask Now aggregate counts ===")
            # ==================================================================
            make_row(event_name="asknow_question_submitted", properties={"source": "free", "category": "career"})
            make_row(event_name="asknow_answer_delivered", properties={"source": "free", "category": "career"})
            make_row(event_name="asknow_answer_failed", properties={"source": "pack", "failure_reason": "timeout"})
            db.session.commit()

            submitted = repo.count_events(window=window, environment="local", event_names="asknow_question_submitted")
            delivered = repo.count_events(window=window, environment="local", event_names="asknow_answer_delivered")
            # Deliberately NOT named `failed` -- that name is the module-
            # global check() failure counter; shadowing it here (main() has
            # no `global failed`) would make Python treat it as local to
            # main() for the rest of the function, silently corrupting the
            # final passed/failed report below.
            answers_failed_count = repo.count_events(window=window, environment="local", event_names="asknow_answer_failed")
            check("24: Ask Now aggregate stage counts are all independently queryable",
                  submitted == 1 and delivered == 1 and answers_failed_count == 1)

            # ==================================================================
            print("\n=== 25: subscription discovery grouping by placement ===")
            # ==================================================================
            make_row(event_name="subscription_discovery_viewed", properties={"placement": "account"})
            make_row(event_name="subscription_discovery_viewed", properties={"placement": "account"})
            make_row(event_name="subscription_discovery_viewed", properties={"placement": "explore"})
            db.session.commit()

            by_placement = repo.group_by_property(
                window=window, environment="local", event_names="subscription_discovery_viewed", dimension="placement",
            )
            check("25: subscription discovery grouping by placement works",
                  by_placement.get("account") == 2 and by_placement.get("explore") == 1)

            # ==================================================================
            print("\n=== 26/27: payment counts + purchased-report CTA isolation ===")
            # ==================================================================
            make_row(event_name="payment_verified", properties={"purpose": "REPORT_PURCHASE", "provider": "razorpay"})
            make_row(event_name="payment_verified", properties={"purpose": "SUBSCRIPTION", "provider": "google_play"})
            db.session.commit()

            report_payments = repo.count_events(
                window=window, environment="local", event_names="payment_verified",
                property_filters={"purpose": "REPORT_PURCHASE"},
            )
            check("26: payment counts filterable by purpose without any revenue/amount aggregation", report_payments == 1)
            check("26b: repository exposes no revenue/amount summing method",
                  not any("revenue" in name.lower() or "amount" in name.lower() or "sum" in name.lower()
                          for name in dir(ActivityEventsAnalyticsRepository) if not name.startswith("_")))

            make_row(event_name="cta_click", properties={"cta_id": "report_catalog_buy_now", "screen_name": "report_catalog"})
            make_row(event_name="cta_click", properties={"cta_id": "some_other_cta", "screen_name": "report_catalog"})
            db.session.commit()

            purchase_entry = repo.count_events(
                window=window, environment="local", event_names="cta_click",
                property_filters={"cta_id": "report_catalog_buy_now"},
            )
            check("27: purchased-report CTA (report_catalog_buy_now) isolated by exact cta_id", purchase_entry == 1)

            # ==================================================================
            print("\n=== Report product separation via entity_type (ai_report vs order) ===")
            # ==================================================================
            make_row(event_name="report_generation_completed", entity_type="ai_report", entity_id="1",
                     properties={"report_type": "love"})
            make_row(event_name="report_generation_completed", entity_type="order", entity_id="1",
                     properties={})
            db.session.commit()

            ai_gen = repo.count_events(window=window, environment="local",
                                        event_names="report_generation_completed", entity_type="ai_report")
            order_gen = repo.count_events(window=window, environment="local",
                                           event_names="report_generation_completed", entity_type="order")
            check("13-P (report split): entity_type='ai_report' isolates AI Report Engine generation rows", ai_gen == 1)
            check("13-P (report split): entity_type='order' isolates purchased-report generation rows", order_gen == 1)

            raised = False
            try:
                repo.count_events(window=window, environment="local", entity_type="not_a_real_entity_type")
            except UnsupportedAnalyticsDimension:
                raised = True
            check("entity_type filter also rejects an unapproved value", raised)

            # ==================================================================
            print("\n=== 28: no repository query mutates activity_events ===")
            # ==================================================================
            before_count = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            # Exercise every public method once more, read-only.
            repo.count_events(window=window, environment="local")
            repo.count_distinct_users(window=window, environment="local")
            repo.count_distinct_sessions(window=window, environment="local")
            repo.group_by_property(window=window, environment="local", event_names="cta_click", dimension="cta_id")
            repo.group_by_notification_context(window=window, environment="local", event_names="notification_opened", dimension="slot")
            after_count = db.session.execute(text("SELECT COUNT(*) FROM activity_events")).scalar()
            check("28: running every repository method does not change the table's row count", before_count == after_count)
            check("28b: repository class defines no add/insert/update/delete/mutate method",
                  not any(name in ("add", "insert", "update", "delete", "mutate", "commit", "write")
                          for name in dir(ActivityEventsAnalyticsRepository) if not name.startswith("_")))

            # ==================================================================
            print("\n=== 29: occurred_at (never recorded_at) governs window membership ===")
            # ==================================================================
            # This row's occurred_at is INSIDE the 2099 test window; its
            # recorded_at is server-generated "now" -- i.e. the 2020s,
            # nowhere near 2099. It is still returned: proves the query
            # uses occurred_at, not recorded_at (which would exclude it).
            far_future_row = make_row(event_name="feature_used", occurred_at=WINDOW_START + timedelta(hours=2),
                                       properties={"feature_name": "phase6b2_occurred_at_probe"})
            db.session.commit()
            check("29: recorded_at was server-generated to 'now' (far outside the 2099 window), not 2099",
                  far_future_row.recorded_at.year < 2099)
            found = repo.count_events(window=window, environment="local", event_names="feature_used",
                                       property_filters={"feature_name": "phase6b2_occurred_at_probe"})
            check("29b: the row IS returned for the 2099 window despite recorded_at being in the 2020s "
                  "-- proves occurred_at, not recorded_at, governs membership", found == 1)

            # Inverse case: occurred_at OUTSIDE the window (year 2015),
            # recorded_at still "now" (2020s) -- must be excluded.
            old_window = AnalyticsWindow(start=datetime(2015, 1, 1, tzinfo=timezone.utc), end=datetime(2015, 1, 2, tzinfo=timezone.utc))
            old_row = make_row(event_name="feature_used", occurred_at=datetime(2010, 6, 1, tzinfo=timezone.utc),
                                properties={"feature_name": "phase6b2_old_occurred_at_probe"})
            db.session.commit()
            check("29c: recorded_at for the old-occurred_at row is still 'now' (2020s), not 2010",
                  old_row.recorded_at.year > 2015)
            old_found = repo.count_events(window=old_window, environment="local", event_names="feature_used",
                                           property_filters={"feature_name": "phase6b2_old_occurred_at_probe"})
            check("29d: a row with occurred_at outside the queried window is excluded, "
                  "even though recorded_at (now) would fall in many other windows", old_found == 0)

            # ==================================================================
            print("\n=== 31: output determinism / clean mapping types ===")
            # ==================================================================
            check("31: group_by_property returns a plain dict", isinstance(by_cta, dict))
            check("31b: dict keys are plain str, values are plain int",
                  all(isinstance(k, str) and isinstance(v, int) for k, v in by_cta.items()))
            # Two back-to-back calls of the SAME query at the SAME point in
            # time (not a stale snapshot from earlier in this file, where
            # fewer cta_click rows existed) -- proves determinism of one
            # query against itself, not equality across a changed dataset.
            call_a = repo.group_by_property(
                window=window, environment="local", event_names="cta_click", dimension="cta_id",
            )
            call_b = repo.group_by_property(
                window=window, environment="local", event_names="cta_click", dimension="cta_id",
            )
            check("31c: calling the same grouped query twice in a row returns identical content", call_a == call_b)

        finally:
            cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
