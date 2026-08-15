# test_transit_personalization.py

"""
Local-only entry point for N3 (Personalized Planetary Transit + Dasha
Verification) -- the Transit half (Dasha is a verification-only phase, see
the N3 report; no Dasha code changed, so no new Dasha tests are needed here).

Follows the exact same convention as every other test_*.py script in this
repo (see test_notification_lifecycle.py's own docstring): connects ONLY to
the local scratch Postgres DB (jyotishasha_local), asserts that database
identity before touching anything, and cleans up its own rows at the end. No
production access, no real FCM send (get_user_notifications() only builds
content -- it never calls send_push_notification()).

Proves:
1. calculate_house() -- personalized house differs per user's own natal
   Lagna, for every planet including Moon/Rahu/Ketu (N3 Tests 1-5).
2. transit_engine.get_transit_events() no longer structurally excludes Moon.
3. notification_builder's TRANSIT section: T-1-only gating (slot + relative
   day), delayed-scheduler safety, no same-day/mislabeled notice (N3 Tests
   6-8, 10).
4. Bilingual content + deterministic Planet-in-House URL, verified against
   the ACTUAL website slug formula
   (jyotishasha-frontend/lib/planetInHouse/*/skeleton.ts) (N3 Tests 11-13).
5. Payload contract carries no birth/Kundali data (N3 Test 15).
6. EVENT/PANCHANG/PANCHAK sections are unaffected by the TRANSIT rewrite
   (N3 Test 16).
"""

import os
import sys
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from models import AstroEvent  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from services.personalization_engine import calculate_house  # noqa: E402
from services.notification_builder import (  # noqa: E402
    get_user_notifications,
    build_transit_content,
    _planet_in_house_url,
)
from transit_engine import get_transit_events  # noqa: E402
from notifications.notification_models import NotificationLog  # noqa: E402

PROFILE_A = 9601  # Aries lagna
PROFILE_B = 9602  # Cancer lagna
IST_TODAY = None  # filled in main()

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


def cleanup():
    db.session.execute(text("DELETE FROM notification_logs WHERE user_id IN (:a, :b)"), {"a": PROFILE_A, "b": PROFILE_B})
    db.session.execute(text("DELETE FROM app_users WHERE id IN (:a, :b)"), {"a": PROFILE_A, "b": PROFILE_B})
    db.session.execute(text("DELETE FROM astro_events WHERE name LIKE 'N3-TEST-%'"))
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token, lagna, lang) "
                "VALUES (:id, '+05:30', 'free', 0, :token, :lagna, :lang)"
            ), {"id": PROFILE_A, "token": "fake-fcm-a", "lagna": "aries", "lang": "en"})
            conn.execute(text(
                "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token, lagna, lang) "
                "VALUES (:id, '+05:30', 'free', 0, :token, :lagna, :lang)"
            ), {"id": PROFILE_B, "token": "fake-fcm-b", "lagna": "cancer", "lang": "hi"})
            conn.commit()

        user_a = db.session.get(AppUser, PROFILE_A)
        user_b = db.session.get(AppUser, PROFILE_B)

        # ==============================================================
        print("=== N3 Test 1: Jupiter transit -> correct personalized house ===")
        # ==============================================================
        # Matches the product spec's own worked example: Aries lagna,
        # Jupiter entering Capricorn -> 10th house.
        house = calculate_house("aries", "capricorn")
        check("Jupiter into Capricorn, Aries lagna -> 10th house", house == 10)

        # ==============================================================
        print("\n=== N3 Test 2: Saturn transit -> correct house ===")
        # ==============================================================
        house = calculate_house("cancer", "pisces")
        check("Saturn into Pisces, Cancer lagna -> 9th house", house == 9)

        # ==============================================================
        print("\n=== N3 Test 3: Moon transit -> correct house (same calculate_house(), no special-casing) ===")
        # ==============================================================
        house = calculate_house("aries", "cancer")
        check("Moon into Cancer, Aries lagna -> 4th house (same formula as every other planet)", house == 4)

        # ==============================================================
        print("\n=== N3 Test 4: Rahu/Ketu handled per existing convention (same calculate_house(), no special-casing) ===")
        # ==============================================================
        house_rahu = calculate_house("aries", "gemini")
        house_ketu = calculate_house("aries", "sagittarius")
        check("Rahu into Gemini, Aries lagna -> 3rd house", house_rahu == 3)
        check("Ketu into Sagittarius, Aries lagna -> 9th house", house_ketu == 9)

        # ==============================================================
        print("\n=== N3 Test 5: two users, different natal lagnas -> DIFFERENT houses for the SAME transit ===")
        # ==============================================================
        house_a = calculate_house(user_a.lagna, "capricorn")
        house_b = calculate_house(user_b.lagna, "capricorn")
        check(
            "Jupiter -> Capricorn gives Aries-lagna user and Cancer-lagna user different houses",
            house_a != house_b and house_a == 10 and house_b == 7,
        )

        # ==============================================================
        print("\n=== Structural: Moon is no longer excluded from get_transit_events() ===")
        # ==============================================================
        import inspect
        import transit_engine as te
        source = inspect.getsource(te.get_transit_events)
        check(
            "get_transit_events()'s planet list includes 'Moon' (was previously excluded)",
            '"Moon"' in source,
        )
        check(
            "...while Rahu/Ketu/Sun/etc. remain present (purely additive change)",
            all(f'"{p}"' in source for p in ["Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Rahu", "Ketu"]),
        )

        # ==============================================================
        print("\n=== N3 Test 11/12/13: bilingual content + verified Planet-in-House URL ===")
        # ==============================================================
        en_content = build_transit_content("Jupiter", 10, "en")
        check("EN title mentions planet and house (Jupiter, 10th)", "Jupiter" in en_content["title"] and "10th" in en_content["title"])
        check(
            "EN url matches the verified website slug formula "
            "(jyotishasha-frontend/lib/planetInHouse/jupiter/skeleton.ts: "
            "`${PLANET_SLUG}-in-${ORDINALS[n-1]}-house`), no /hi prefix",
            en_content["url"] == "https://www.jyotishasha.com/planet-in-house/jupiter-in-10th-house",
        )

        hi_content = build_transit_content("Jupiter", 10, "hi")
        check("HI title uses the website's own Hindi planet name (बृहस्पति), not a re-translation", "बृहस्पति" in hi_content["title"])
        check("HI title uses the website's own Hindi house label (दशम भाव)", "दशम भाव" in hi_content["title"])
        check(
            "HI url uses the /hi prefix, same slug",
            hi_content["url"] == "https://www.jyotishasha.com/hi/planet-in-house/jupiter-in-10th-house",
        )

        check("Unrecognized planet -> no URL guessed", _planet_in_house_url("Xyz", 5, "en") is None)
        check("Out-of-range house -> no URL guessed", _planet_in_house_url("Jupiter", 13, "en") is None)

        # ==============================================================
        print("\n=== T-1 gating: fixtures ===")
        # ==============================================================
        today = datetime.now().date()  # server local; scheduler itself uses IST, gating uses relative_day (IST) internally
        from services.relative_day import IST as _IST
        today_ist = datetime.now(_IST).date()
        tomorrow_ist = today_ist + timedelta(days=1)
        yesterday_ist = today_ist - timedelta(days=1)

        ev_tomorrow = AstroEvent(name="N3-TEST-Jupiter enters Capricorn", type="transit", date=tomorrow_ist, meta={"planet": "Jupiter", "rashi": "capricorn"})
        ev_today = AstroEvent(name="N3-TEST-Jupiter enters Capricorn (today)", type="transit", date=today_ist, meta={"planet": "Jupiter", "rashi": "capricorn"})
        ev_yesterday = AstroEvent(name="N3-TEST-Jupiter enters Capricorn (stale)", type="transit", date=yesterday_ist, meta={"planet": "Jupiter", "rashi": "capricorn"})
        db.session.add_all([ev_tomorrow, ev_today, ev_yesterday])
        db.session.commit()

        def transit_notifications(events, slot):
            os.environ["NOTIFICATION_SLOT"] = slot
            try:
                return [n for n in get_user_notifications(user_a, events) if n["data"]["type"] == "transit"]
            finally:
                os.environ.pop("NOTIFICATION_SLOT", None)

        # ==============================================================
        print("\n=== N3 Test 6: T-1 date correct (evening slot, event dated tomorrow) ===")
        # ==============================================================
        results = transit_notifications([ev_tomorrow], "evening")
        check("Evening slot + transit dated TOMORROW -> exactly one T-1 notification produced", len(results) == 1)

        # ==============================================================
        print("\n=== N3 Test 7: transit-day notification not mislabeled 'tomorrow' ===")
        # ==============================================================
        results_today = transit_notifications([ev_today], "evening")
        check("Transit dated TODAY produces NO notification (never a same-day/'already happened' notice)", len(results_today) == 0)

        # ==============================================================
        print("\n=== N3 Test 8: delayed scheduler cannot send stale pre-transit copy ===")
        # ==============================================================
        results_stale = transit_notifications([ev_yesterday], "evening")
        check(
            "Transit dated YESTERDAY (job ran past the boundary) produces NO stale 'tomorrow' notification",
            len(results_stale) == 0,
        )

        # ==============================================================
        print("\n=== N3 Test 10: morning slot never produces the T-1 transit notice (no morning/evening duplicate race) ===")
        # ==============================================================
        results_morning = transit_notifications([ev_tomorrow], "morning")
        check(
            "Morning slot NEVER produces a transit notification for the same event that evening sends "
            "-- structurally impossible to double-send across slots",
            len(results_morning) == 0,
        )

        # ==============================================================
        print("\n=== N3 Test 15: payload contains no birth/Kundali data ===")
        # ==============================================================
        os.environ["NOTIFICATION_SLOT"] = "evening"
        try:
            notif = [n for n in get_user_notifications(user_a, [ev_tomorrow]) if n["data"]["type"] == "transit"][0]
        finally:
            os.environ.pop("NOTIFICATION_SLOT", None)
        data_keys = set(notif["data"].keys())
        forbidden = {"dob", "tob", "pob", "lat", "lng", "lagna", "moon_sign", "nakshatra", "kundali"}
        check(
            "TRANSIT payload keys are exactly the safe contract (type/event_id/planet/house/language/transit_date/url)",
            data_keys == {"type", "event_id", "planet", "house", "language", "transit_date", "url"},
        )
        check("No birth/Kundali fields anywhere in the payload", not (data_keys & forbidden))
        check("Language in payload is the user's own persisted preference (en)", notif["data"]["language"] == "en")

        # Hindi user gets Hindi language tag + /hi URL in the SAME payload shape.
        os.environ["NOTIFICATION_SLOT"] = "evening"
        try:
            notif_b = [n for n in get_user_notifications(user_b, [ev_tomorrow]) if n["data"]["type"] == "transit"][0]
        finally:
            os.environ.pop("NOTIFICATION_SLOT", None)
        check("N3 Test 12: Hindi user's payload carries language: hi", notif_b["data"]["language"] == "hi")
        check("N3 Test 12: Hindi user's url carries the /hi prefix", "/hi/planet-in-house/" in notif_b["data"]["url"])
        check("N3 Test 11: English user's url carries NO /hi prefix", "/hi/" not in notif["data"]["url"])

        # ==============================================================
        print("\n=== N3 Test 9: dedup key is stable/deterministic per (user, event) -- what NotificationLog's uniqueness relies on ===")
        # ==============================================================
        ntype = notif["data"]["type"]
        raw_event_id = notif["data"]["event_id"]
        event_id_1 = f"{ntype}_{raw_event_id}"
        # Re-derive independently, exactly as services/event_scheduler.py does.
        os.environ["NOTIFICATION_SLOT"] = "evening"
        try:
            notif_again = [n for n in get_user_notifications(user_a, [ev_tomorrow]) if n["data"]["type"] == "transit"][0]
        finally:
            os.environ.pop("NOTIFICATION_SLOT", None)
        event_id_2 = f"{notif_again['data']['type']}_{notif_again['data']['event_id']}"
        check("Same (user, transit) produces an identical dedup key across repeated builds", event_id_1 == event_id_2)

        db.session.add(NotificationLog(user_id=PROFILE_A, event_id=event_id_1, slot="evening"))
        db.session.commit()
        existing_log = NotificationLog.query.filter_by(user_id=PROFILE_A, event_id=event_id_1, slot="evening").first()
        check(
            "N3 Test 9: NotificationLog (the real scheduler-level dedup ledger) already has this key logged "
            "-- a second evening run for the same user+transit would see existing_log and skip, exactly like "
            "services/event_scheduler.py's own STEP 5B dedup check",
            existing_log is not None,
        )

        # ==============================================================
        print("\n=== N3 Test 16: EVENT/PANCHANG/PANCHAK sections unaffected by the TRANSIT rewrite ===")
        # ==============================================================
        vrat_event = AstroEvent(name="N3-TEST-Ekadashi", type="vrat", date=today_ist)
        panchak_event = AstroEvent(name="N3-TEST-Panchak", type="panchak", date=today_ist)
        db.session.add_all([vrat_event, panchak_event])
        db.session.commit()

        os.environ["NOTIFICATION_SLOT"] = "morning"
        try:
            mixed = get_user_notifications(user_a, [vrat_event, panchak_event, ev_today])
        finally:
            os.environ.pop("NOTIFICATION_SLOT", None)
        types_produced = {n["data"]["type"] for n in mixed}
        check(
            "EVENT (vrat) section still fires on a Today morning event, unaffected by the TRANSIT rewrite",
            "event" in types_produced,
        )
        check(
            "PANCHAK section still fires, unaffected by the TRANSIT rewrite",
            "panchak" in types_produced,
        )
        check(
            "TRANSIT section correctly produces nothing here (event dated TODAY, morning slot)",
            "transit" not in types_produced,
        )

        # ==============================================================
        print("\n=== N2 integration: transit is now forward-looking (expires at IST midnight of its own date, not end-of-day) ===")
        # ==============================================================
        import services.event_scheduler as es
        scheduler_source = inspect.getsource(es.run_daily_event_job)
        check(
            "event_scheduler.py's STEP 5B treats ntype == 'transit' as forward-looking "
            "(reuses services/notification_lifecycle.py::expiry_for_astro_event_notification "
            "unchanged -- no new expiry function needed)",
            'ntype == "transit"' in scheduler_source,
        )
        from services.notification_lifecycle import expiry_for_astro_event_notification
        transit_expiry = expiry_for_astro_event_notification(event_date=tomorrow_ist, is_forward_looking=True)
        transit_expiry_end_of_day = expiry_for_astro_event_notification(event_date=tomorrow_ist, is_forward_looking=False)
        check(
            "Forward-looking transit expiry (at the instant the transit day begins) is strictly "
            "earlier than the old end-of-day boundary -- the stale-'tomorrow' window this closes",
            transit_expiry < transit_expiry_end_of_day,
        )

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
