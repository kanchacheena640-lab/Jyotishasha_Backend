"""
test_alerts_sunrise_boundary.py
-----------------------------------
Local-only entry point for the Phase 3 sunrise-to-sunrise alert-day
boundary (modules/alerts/sunrise_boundary.py) and its wiring into
PlanningWindowEngine.plan()'s optional `day_anchors` parameter
(modules/alerts/planning_window_engine.py) and
ProfileDetectionService.evaluate_profile()
(modules/alerts/profile_detection_service.py).

This script uses REAL calculate_sunrise_sunset() calls (the existing,
unmodified production sunrise infrastructure) with REAL coordinates --
no astronomy is mocked, only the surrounding Rule Engine (via a fake
planning engine, as in test_alerts_profile_detection.py) where a
lifecycle scenario needs deterministic events. It does not touch Flask
routes, Celery, or OpenAI. DATABASE_URL is pointed at the LOCAL scratch
Postgres DB ONLY, exactly like every other test_alerts_*.py script in
this repository.
"""

import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from services.sun_calc import calculate_sunrise_sunset  # noqa: E402
from full_kundali_api import calculate_full_kundali  # noqa: E402

from modules.alerts.sunrise_boundary import (  # noqa: E402
    resolve_current_alert_day_start, resolve_alert_day_sequence, SunriseResolutionError,
)
from modules.alerts.planning_window_engine import PlanningWindowEngine  # noqa: E402
from modules.alerts.event_registry import get_default_registry  # noqa: E402
from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402
from modules.alerts.profile_detection_service import (  # noqa: E402
    ProfileDetectionService, DetectionRunFailedError,
)
from modules.alerts.planning_models import PlannedMicroEvent  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
DELHI = (28.6139, 77.2090)
TOKYO = (35.6762, 139.6503)   # far-east coordinate, real sunrise well before Delhi's
LOS_ANGELES = (34.0522, -118.2437)  # negative longitude, western hemisphere
TEST_PROFILE = 9201

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
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": TEST_PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
        db.session.commit()

        lat, lon = DELHI
        today = date.today()
        today_sunrise, today_sunset = calculate_sunrise_sunset(today, lat, lon)
        print(f"Real Delhi sunrise today ({today}): {today_sunrise}")

        # ------------------------------------------------------------
        print("\n=== Test 1: immediately before sunrise ===")
        # ------------------------------------------------------------
        just_before = today_sunrise - timedelta(minutes=1)
        anchor = resolve_current_alert_day_start(lat, lon, now=just_before)
        yesterday_sunrise, _ = calculate_sunrise_sunset(today - timedelta(days=1), lat, lon)
        check("anchor is YESTERDAY's sunrise, not today's", anchor == yesterday_sunrise)

        # ------------------------------------------------------------
        print("\n=== Test 2: exactly at sunrise ===")
        # ------------------------------------------------------------
        anchor_at = resolve_current_alert_day_start(lat, lon, now=today_sunrise)
        check("anchor is TODAY's sunrise when now == sunrise exactly (on/after rule)", anchor_at == today_sunrise)

        # ------------------------------------------------------------
        print("\n=== Test 3: immediately after sunrise ===")
        # ------------------------------------------------------------
        just_after = today_sunrise + timedelta(minutes=1)
        anchor_after = resolve_current_alert_day_start(lat, lon, now=just_after)
        check("anchor is TODAY's sunrise", anchor_after == today_sunrise)

        # ------------------------------------------------------------
        print("\n=== Test 4: different lat/lng profiles get different sunrise anchors ===")
        # ------------------------------------------------------------
        delhi_anchor = resolve_current_alert_day_start(*DELHI, now=datetime.now(IST))
        tokyo_anchor = resolve_current_alert_day_start(*TOKYO, now=datetime.now(IST))
        la_anchor = resolve_current_alert_day_start(*LOS_ANGELES, now=datetime.now(IST))
        check("Delhi and Tokyo sunrise anchors differ (no hardcoded single location)", delhi_anchor != tokyo_anchor)
        check("Delhi and Los Angeles sunrise anchors differ", delhi_anchor != la_anchor)

        # ------------------------------------------------------------
        print("\n=== Test 5: sunrise crossing calendar dates (sequence spans midnight boundary correctly) ===")
        # ------------------------------------------------------------
        seq = resolve_alert_day_sequence(lat, lon, count=4, now=just_before)
        check("4 anchors returned", len(seq) == 4)
        check("anchors strictly increasing", all(seq[i] < seq[i + 1] for i in range(len(seq) - 1)))
        check("first anchor is yesterday's sunrise (per Test 1)", seq[0] == yesterday_sunrise)
        check("second anchor is today's sunrise", seq[1] == today_sunrise)
        check("consecutive anchors are ~1 day apart (real sunrise drift, not fixed 24h)", all(
            timedelta(hours=23) < (seq[i + 1] - seq[i]) < timedelta(hours=25) for i in range(len(seq) - 1)
        ))

        # ------------------------------------------------------------
        print("\n=== Test 6: month/year boundary ===")
        # ------------------------------------------------------------
        new_year_eve = datetime(2026, 12, 31, 12, 0, tzinfo=IST)  # midday, well after sunrise
        ny_seq = resolve_alert_day_sequence(lat, lon, count=3, now=new_year_eve)
        check("sequence correctly rolls Dec 31 -> Jan 1 -> Jan 2", [d.date() for d in ny_seq] == [date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 2)])

        # ------------------------------------------------------------
        print("\n=== Test 7: sunrise calculation failure fails safely ===")
        # ------------------------------------------------------------
        raised_invalid_lat = False
        try:
            resolve_current_alert_day_start(lat=999.0, lon=lon)  # out-of-range latitude
        except SunriseResolutionError:
            raised_invalid_lat = True
        check("out-of-range latitude raises SunriseResolutionError", raised_invalid_lat)

        # ------------------------------------------------------------
        print("\n=== Test 8: missing/invalid coordinates fails safely ===")
        # ------------------------------------------------------------
        for bad_lat, bad_lon, label in [
            (None, lon, "lat=None"),
            (lat, None, "lon=None"),
            ("not-a-number", lon, "lat as string"),
        ]:
            raised = False
            try:
                resolve_current_alert_day_start(lat=bad_lat, lon=bad_lon)
            except SunriseResolutionError:
                raised = True
            check(f"invalid coordinates ({label}) raise SunriseResolutionError", raised)

        # ------------------------------------------------------------
        print("\n=== Test 9: repeated evaluation within the same sunrise-to-sunrise window is stable ===")
        # ------------------------------------------------------------
        anchor_1 = resolve_current_alert_day_start(lat, lon, now=today_sunrise + timedelta(hours=1))
        anchor_2 = resolve_current_alert_day_start(lat, lon, now=today_sunrise + timedelta(hours=5))
        check("same alert-day anchor for two evaluations within the same window", anchor_1 == anchor_2)

        # ------------------------------------------------------------
        print("\n=== Test 10: evaluation after the next sunrise advances the window ===")
        # ------------------------------------------------------------
        tomorrow_sunrise, _ = calculate_sunrise_sunset(today + timedelta(days=1), lat, lon)
        anchor_next_day = resolve_current_alert_day_start(lat, lon, now=tomorrow_sunrise + timedelta(minutes=1))
        check("anchor advances to the NEXT sunrise once it passes", anchor_next_day == tomorrow_sunrise)
        check("advanced anchor differs from the original day's anchor", anchor_next_day != today_sunrise)

        # ------------------------------------------------------------
        print("\n=== Test 11: PlanningWindowEngine.plan() backward compatibility (no day_anchors) ===")
        # ------------------------------------------------------------
        real_kundali = calculate_full_kundali(
            name="Ravi", dob="1985-03-31", tob="19:45", lat=26.8467, lon=80.9462,
            user_id=None, language="en",
        )
        engine = PlanningWindowEngine()
        planned_old_style = engine.plan(real_kundali)  # no day_anchors -- must still work exactly as before
        check("plan() with no day_anchors still returns a list (old callers unaffected)", isinstance(planned_old_style, list))
        check("plan() with no day_anchors returns at least the Stable Phase fallback", len(planned_old_style) >= 1)

        # ------------------------------------------------------------
        print("\n=== Test 12: PlanningWindowEngine.plan() with explicit sunrise day_anchors ===")
        # ------------------------------------------------------------
        sunrise_anchors = resolve_alert_day_sequence(26.8467, 80.9462, count=engine.window_days)
        planned_sunrise = engine.plan(real_kundali, day_anchors=sunrise_anchors)
        check("plan() with sunrise day_anchors returns a list", isinstance(planned_sunrise, list))
        check("plan() rejects a mismatched-length day_anchors list", _raises_value_error(engine, real_kundali, sunrise_anchors[:2]))

        # ------------------------------------------------------------
        print("\n=== Test 13: end-to-end -- ProfileDetectionService now uses sunrise anchors ===")
        # ------------------------------------------------------------
        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, name, dob, tob, pob, lat, lng) "
                "VALUES (:id, 'IST', 'free', 0, 'Ravi', '1985-03-31', '19:45', 'Lucknow', 26.8467, 80.9462)"
            ), {"id": TEST_PROFILE})
            conn.commit()

        repo = AlertPersistenceRepository()
        service = ProfileDetectionService(repository=repo)  # REAL PlanningWindowEngine, REAL sunrise resolver
        result = service.evaluate_profile(TEST_PROFILE)
        check("end-to-end evaluate_profile() succeeds using sunrise-anchored days", result.events_detected >= 1)

        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": TEST_PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
        db.session.commit()

        # ------------------------------------------------------------
        print("\n=== Test 14: end-to-end -- invalid coordinates fail safely, no persistence touched ===")
        # ------------------------------------------------------------
        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, name, dob, tob, pob, lat, lng) "
                "VALUES (:id, 'IST', 'free', 0, 'Bad', '1985-03-31', '19:45', 'Nowhere', 999.0, 999.0)"
            ), {"id": TEST_PROFILE})
            conn.commit()

        raised_sunrise_error = False
        try:
            service.evaluate_profile(TEST_PROFILE)
        except SunriseResolutionError:
            raised_sunrise_error = True
        check("invalid coordinates raise SunriseResolutionError, not silently defaulting", raised_sunrise_error)
        check("zero rows persisted for the invalid-coordinate profile", AlertPersistenceRepository().fetch_history_for_profile(profile_id=TEST_PROFILE) == [])

        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": TEST_PROFILE})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": TEST_PROFILE})
        db.session.commit()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


def _raises_value_error(engine, kundali, bad_anchors):
    try:
        engine.plan(kundali, day_anchors=bad_anchors)
        return False
    except ValueError:
        return True


if __name__ == "__main__":
    main()
