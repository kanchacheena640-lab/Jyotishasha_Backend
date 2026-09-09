# test_static_astrology_persistence.py

"""
USERS U3B.1 -- schema/model, single-calculation, staleness, and
snapshot-consistency tests for the static astrology persistence
foundation.

Covers:
  18. Schema/model: AppUser exposes all 5 new fields, the local
      migration applied cleanly, existing rows are unaffected/NULL.
  20. Calculation count: register_or_update_user() calls
      calculate_full_kundali() at most once per actual birth-detail
      change, and zero times otherwise. A lighter companion test proves
      the same for the real POST /api/user/bootstrap route (reusing
      the exact Firebase-mocking convention
      test_signup_completed_producer.py already established).
  21. Staleness: each of dob/tob/pob/lat/lng individually triggers
      recalculation/invalidation; name/phone/fcm_token-only updates and
      an identical-birth-data resubmission do NOT.
  22. Snapshot consistency: after a successful recalculation, every one
      of lagna/moon_sign/nakshatra/nakshatra_pada/static_yog/
      static_dosh/calculated_at/version originates from the SAME
      mocked Kundali result -- no stale old value survives.

LOCAL ONLY. No production DB. All test AppUser rows use a dedicated,
obviously-test-only firebase_uid prefix and are deleted in a finally
block.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def fb(tag):
    return f"fb-u3b1-{tag}"


_KUNDALI_A = {
    "lagna_sign": "Leo", "rashi": "Taurus",
    "planets": [
        {"name": "Sun", "sign": "Aries", "house": 1, "nakshatra": "Ashwini", "pada": 1},
        {"name": "Moon", "sign": "Taurus", "house": 2, "nakshatra": "Rohini", "pada": 3},
    ],
    "budh_aditya_yog": {"id": "budh_aditya_yog", "is_active": False, "strength": "None"},
    "chandra_mangal_yog": {"id": "chandra_mangal_yog", "is_active": False, "strength": "None"},
    "adhi_rajyog": {"id": "adhi_rajyog", "is_active": False, "strength": "None"},
    "dhan_yog": {"id": "dhan_yog", "is_active": False, "strength": "None"},
    "dharma_karmadhipati_rajyog": {"id": "dharma_karmadhipati_rajyog", "is_active": False, "strength": "None"},
    "gajakesari_yog": {"id": "gajakesari_yog", "is_active": True, "strength": "High"},
    "kuber_rajyog": {"id": "kuber_rajyog", "is_active": False, "strength": "None"},
    "lakshmi_yog": {"id": "lakshmi_yog", "is_active": False, "strength": "None"},
    "neechbhang_rajyog": {"id": "neechbhang_rajyog", "is_active": False, "strength": "None"},
    "panch_mahapurush_yog": {"id": "panch_mahapurush_rajyog", "is_active": False, "sub_yogs": []},
    "parashari_rajyog": {"id": "parashari_rajyog", "is_active": False, "strength": "None"},
    "rajya_sambandh_rajyog": {"id": "rajya_sambandh_rajyog", "is_active": False, "strength": "None"},
    "shubh_kartari_yog": {"id": "shubh_kartari_yog", "is_active": False, "strength": "None"},
    "vipreet_rajyog": {"id": "vipreet_rajyog", "is_active": False, "strength": "None"},
    "manglik_dosh": {"status": {"strength": "Strong"}},
    "kaalsarp_dosh": {"is_present": False},
}

# A DIFFERENT chart -- used to prove snapshot consistency (§22): a
# recalculation must replace EVERY field with THIS chart's own values,
# with zero leftover from _KUNDALI_A.
_KUNDALI_B = {
    "lagna_sign": "Scorpio", "rashi": "Gemini",
    "planets": [
        {"name": "Sun", "sign": "Cancer", "house": 1, "nakshatra": "Pushya", "pada": 2},
        {"name": "Moon", "sign": "Gemini", "house": 8, "nakshatra": "Mrigashira", "pada": 4},
    ],
    "budh_aditya_yog": {"id": "budh_aditya_yog", "is_active": False, "strength": "None"},
    "chandra_mangal_yog": {"id": "chandra_mangal_yog", "is_active": False, "strength": "None"},
    "adhi_rajyog": {"id": "adhi_rajyog", "is_active": False, "strength": "None"},
    "dhan_yog": {"id": "dhan_yog", "is_active": False, "strength": "None"},
    "dharma_karmadhipati_rajyog": {"id": "dharma_karmadhipati_rajyog", "is_active": False, "strength": "None"},
    "gajakesari_yog": {"id": "gajakesari_yog", "is_active": False, "strength": "None"},
    "kuber_rajyog": {"id": "kuber_rajyog", "is_active": False, "strength": "None"},
    "lakshmi_yog": {"id": "lakshmi_yog", "is_active": False, "strength": "None"},
    "neechbhang_rajyog": {"id": "neechbhang_rajyog", "is_active": False, "strength": "None"},
    "panch_mahapurush_yog": {"id": "panch_mahapurush_rajyog", "is_active": False, "sub_yogs": []},
    "parashari_rajyog": {"id": "parashari_rajyog", "is_active": False, "strength": "None"},
    "rajya_sambandh_rajyog": {"id": "rajya_sambandh_rajyog", "is_active": False, "strength": "None"},
    "shubh_kartari_yog": {"id": "shubh_kartari_yog", "is_active": False, "strength": "None"},
    "vipreet_rajyog": {"id": "vipreet_rajyog", "is_active": True, "strength": "Moderate"},
    "manglik_dosh": {"status": {"strength": "None"}},
    "kaalsarp_dosh": {"is_present": True},
}


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text, inspect as sa_inspect

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        from modules.models_user import AppUser, UserDashaTimeline
        import modules.user_service as user_service_module
        import full_kundali_api

        all_test_firebase_uids = [fb(f"t{i}") for i in range(1, 20)]

        def cleanup():
            # U4A.1 -- register_or_update_user() now also resyncs a real
            # UserDashaTimeline (only calculate_full_kundali() itself is
            # mocked by this test; get_moon_longitude_lahiri()/
            # calculate_vimshottari_dasha() are not, so these fixtures'
            # valid dob/tob really do generate real 81-row timelines).
            # Delete children before the parent AppUser row, same order
            # account_deletion_service.py already uses.
            ids = [u.id for u in AppUser.query.filter(AppUser.firebase_uid.in_(all_test_firebase_uids)).all()]
            if ids:
                UserDashaTimeline.query.filter(UserDashaTimeline.user_id.in_(ids)).delete(synchronize_session=False)
            AppUser.query.filter(AppUser.firebase_uid.in_(all_test_firebase_uids)).delete(synchronize_session=False)
            db.session.commit()

        cleanup()

        try:
            # ==========================================================
            print("=== 18: schema/model ===")
            # ==========================================================
            new_columns = {"nakshatra_pada", "static_yog", "static_dosh",
                            "static_astrology_calculated_at", "static_astrology_version"}
            model_columns = {c.name for c in AppUser.__table__.columns}
            check("18a: AppUser model exposes all 5 new fields", new_columns.issubset(model_columns))

            db_columns = {
                row[0] for row in db.session.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='app_users'"
                )).fetchall()
            }
            check("18b: local DB schema has all 5 new columns (migration applied)", new_columns.issubset(db_columns))

            alembic_version = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            # N6 -- the Bell items table + user_notifications.dismissed_at
            # migration (c4d8f21a9e05) is the verified current head,
            # chained onto N5's campaign-scheduling migration
            # (8c2f7b91d4e6), itself chained onto N4's execution/delivery/
            # attempt/idempotency migration (5a1e9d2f4c73), N3's
            # campaign-drafts migration (c71a83b4e209) and U6's Saved
            # Audience migration (9f2a5c7e1b83). This literal is expected
            # to move again the next time a reviewed migration is
            # actually applied locally -- that is this check's whole
            # point, not a reason to remove it.
            check("18b: alembic_version reflects the current head", alembic_version == "c4d8f21a9e05")

            fresh_user = AppUser(firebase_uid=fb("t1"))
            db.session.add(fresh_user)
            db.session.commit()
            check("18c/18d: a freshly created AppUser (no astrology assigned) reads NULL for all 5 new fields",
                  fresh_user.nakshatra_pada is None and fresh_user.static_yog is None
                  and fresh_user.static_dosh is None and fresh_user.static_astrology_calculated_at is None
                  and fresh_user.static_astrology_version is None)
            check("18: existing, unrelated fields remain valid (name/lagna still readable, untouched)",
                  fresh_user.name is None and fresh_user.lagna is None)

            other_columns_untouched = {"id", "name", "email", "phone", "dob", "tob", "pob", "lat", "lng",
                                        "lagna", "moon_sign", "nakshatra", "tz", "lang", "subscription",
                                        "asknow_tokens", "fcm_token", "firebase_uid", "created_at"}
            check("18e: no pre-existing column was removed/renamed",
                  other_columns_untouched.issubset(model_columns) and other_columns_untouched.issubset(db_columns))

            # ==========================================================
            print("\n=== 20/21: calculation count + staleness -- register_or_update_user() ===")
            # ==========================================================
            call_count = {"n": 0}
            real_calculate = full_kundali_api.calculate_full_kundali

            def _counting_kundali_a(**kwargs):
                call_count["n"] += 1
                return dict(_KUNDALI_A)

            def _counting_kundali_b(**kwargs):
                call_count["n"] += 1
                return dict(_KUNDALI_B)

            full_kundali_api.calculate_full_kundali = _counting_kundali_a

            # First-ever registration WITH complete birth data -- exactly 1 call.
            call_count["n"] = 0
            u_full = user_service_module.register_or_update_user({
                "firebase_uid": fb("t2"), "name": "Test Full", "dob": "1990-06-15",
                "tob": "10:30", "pob": "Lucknow", "lat": 26.8467, "lng": 80.9462,
            })
            check("20: register_or_update_user() with complete NEW birth data -> exactly 1 calculate_full_kundali() call",
                  call_count["n"] == 1)
            check("21: DOB/TOB/POB/lat/lng all recorded, static astrology populated from the mocked chart",
                  u_full.dob == "1990-06-15" and u_full.lagna == "Leo" and u_full.moon_sign == "Taurus"
                  and u_full.nakshatra == "Rohini" and u_full.nakshatra_pada == 3
                  and u_full.static_yog == {"gajakesari_yog": {"strength": "High"}}
                  and u_full.static_dosh == {"manglik": {"severity": "Strong"}}
                  and u_full.static_astrology_calculated_at is not None
                  and u_full.static_astrology_version == 1)

            # Identical birth data resubmitted -- 0 calls.
            call_count["n"] = 0
            user_service_module.register_or_update_user({
                "firebase_uid": fb("t2"), "name": "Test Full", "dob": "1990-06-15",
                "tob": "10:30", "pob": "Lucknow", "lat": 26.8467, "lng": 80.9462,
            })
            check("21: resubmitting IDENTICAL birth data -> 0 calculate_full_kundali() calls",
                  call_count["n"] == 0)

            # name-only update -- 0 calls.
            call_count["n"] = 0
            user_service_module.register_or_update_user({"firebase_uid": fb("t2"), "name": "Renamed Only"})
            check("21: name-only update -> 0 calculate_full_kundali() calls", call_count["n"] == 0)

            # phone-only update -- 0 calls.
            call_count["n"] = 0
            user_service_module.register_or_update_user({"firebase_uid": fb("t2"), "phone": "+919999999999"})
            check("21: phone-only update -> 0 calculate_full_kundali() calls", call_count["n"] == 0)

            # fcm_token-only update -- 0 calls.
            call_count["n"] = 0
            user_service_module.register_or_update_user({"firebase_uid": fb("t2"), "fcm_token": "tok-abc"})
            check("21: fcm_token-only update -> 0 calculate_full_kundali() calls", call_count["n"] == 0)

            # ---- individual field changes, one at a time, each its own fresh profile ----
            for field, value, tag in [
                ("dob", "1991-01-01", "t3"), ("tob", "23:59", "t4"),
                ("pob", "Delhi", "t5"), ("lat", 28.7041, "t6"), ("lng", 77.1025, "t7"),
            ]:
                base = {
                    "firebase_uid": fb(tag), "dob": "1990-06-15", "tob": "10:30",
                    "pob": "Lucknow", "lat": 26.8467, "lng": 80.9462,
                }
                call_count["n"] = 0
                user_service_module.register_or_update_user(base)
                check(f"21-setup ({field}): initial complete registration -> 1 call", call_count["n"] == 1)

                call_count["n"] = 0
                changed = dict(base)
                changed[field] = value
                u_changed = user_service_module.register_or_update_user(changed)
                check(f"21 ({field}): changing ONLY {field} -> exactly 1 recalculation call", call_count["n"] == 1)
                check(f"21 ({field}): static astrology actually refreshed (still matches the mocked chart)",
                      u_changed.static_astrology_calculated_at is not None
                      and u_changed.lagna == "Leo")

            # ---- incomplete birth data -> invalidation, 0 calculation calls ----
            call_count["n"] = 0
            u_incomplete = user_service_module.register_or_update_user({
                "firebase_uid": fb("t8"), "dob": "1990-06-15", "tob": "10:30",
                "pob": "", "lat": 26.8467, "lng": 80.9462,  # pob deliberately blank
            })
            check("14: incomplete birth data (blank pob) -> 0 calculate_full_kundali() calls (never guesses)",
                  call_count["n"] == 0)
            check("14: incomplete birth data -> ALL static astrology fields explicitly NULL, never fabricated",
                  u_incomplete.lagna is None and u_incomplete.moon_sign is None and u_incomplete.nakshatra is None
                  and u_incomplete.nakshatra_pada is None and u_incomplete.static_yog is None
                  and u_incomplete.static_dosh is None and u_incomplete.static_astrology_calculated_at is None
                  and u_incomplete.static_astrology_version is None)

            # Complete -> then made incomplete -> must INVALIDATE previously-good astrology.
            call_count["n"] = 0
            u_t9 = user_service_module.register_or_update_user({
                "firebase_uid": fb("t9"), "dob": "1990-06-15", "tob": "10:30",
                "pob": "Lucknow", "lat": 26.8467, "lng": 80.9462,
            })
            check("14-setup: complete registration populates astrology", u_t9.lagna == "Leo")
            call_count["n"] = 0
            u_t9_broken = user_service_module.register_or_update_user({
                "firebase_uid": fb("t9"), "lat": None,  # lat cleared -> now incomplete
            })
            check("14: birth data becomes incomplete -> 0 new calculate_full_kundali() calls",
                  call_count["n"] == 0)
            check("14: previously-good astrology is fully INVALIDATED, never left stale on now-incomplete data",
                  u_t9_broken.lagna is None and u_t9_broken.static_yog is None
                  and u_t9_broken.static_astrology_calculated_at is None)

            # ==========================================================
            print("\n=== 22: snapshot consistency -- no stale old value survives a recalculation ===")
            # ==========================================================
            full_kundali_api.calculate_full_kundali = _counting_kundali_a
            call_count["n"] = 0
            u_snap = user_service_module.register_or_update_user({
                "firebase_uid": fb("t10"), "dob": "1990-06-15", "tob": "10:30",
                "pob": "Lucknow", "lat": 26.8467, "lng": 80.9462,
            })
            check("22-setup: initial snapshot matches chart A", u_snap.lagna == "Leo" and u_snap.moon_sign == "Taurus"
                  and u_snap.static_yog == {"gajakesari_yog": {"strength": "High"}})

            # Switch the mocked engine to chart B and change ONE birth field.
            full_kundali_api.calculate_full_kundali = _counting_kundali_b
            call_count["n"] = 0
            u_snap_2 = user_service_module.register_or_update_user({
                "firebase_uid": fb("t10"), "dob": "1990-06-16",  # actual change
            })
            check("22: exactly 1 call for the switched-chart recalculation", call_count["n"] == 1)
            check("22: lagna now matches chart B, not stale chart A", u_snap_2.lagna == "Scorpio")
            check("22: moon_sign now matches chart B", u_snap_2.moon_sign == "Gemini")
            check("22: nakshatra now matches chart B", u_snap_2.nakshatra == "Mrigashira")
            check("22: nakshatra_pada now matches chart B", u_snap_2.nakshatra_pada == 4)
            check("22: static_yog now matches chart B (vipreet active, gajakesari GONE)",
                  u_snap_2.static_yog == {"vipreet_rajyog": {"strength": "Moderate"}})
            check("22: static_dosh now matches chart B (kaal_sarp present, manglik GONE)",
                  u_snap_2.static_dosh == {"kaal_sarp": {}})
            check("22: static_astrology_version still the current version", u_snap_2.static_astrology_version == 1)
            check("22: no leftover chart-A value survives anywhere in the snapshot",
                  "gajakesari_yog" not in u_snap_2.static_yog and "manglik" not in u_snap_2.static_dosh)

            full_kundali_api.calculate_full_kundali = real_calculate

            print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
        finally:
            full_kundali_api.calculate_full_kundali = real_calculate
            cleanup()

    return failed == 0


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
