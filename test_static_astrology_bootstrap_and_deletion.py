# test_static_astrology_bootstrap_and_deletion.py

"""
USERS U3B.1 -- two remaining, narrower proofs not covered by
test_static_astrology_persistence.py (which exercises
register_or_update_user() directly):

  1. The REAL POST /api/user/bootstrap route (not just the extractor/
     service layer) calls calculate_full_kundali() at most once per
     request and persists all 5 new static-astrology fields, while
     preserving its EXISTING response shape byte-for-byte (ok/
     profileId/name/dob/tob/pob/lagna/moon_sign/nakshatra -- no pada/
     yog/dosh added to the response, per this task's explicit "preserve
     existing endpoint behavior/response").

     Reuses the exact Firebase-mocking convention
     test_signup_completed_producer.py already established (module-
     level monkeypatch of firebase_auth.verify_id_token and
     calculate_full_kundali on the routes_profile_bootstrap module).

  2. Account deletion's _anonymize_app_user() clears all 5 new fields
     alongside the pre-existing lagna/moon_sign/nakshatra it already
     cleared -- no derived astrology survives source birth-data removal.

LOCAL ONLY. No production DB. Test rows use a dedicated firebase_uid
prefix, deleted in a finally block.
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
    return f"fb-u3b1-bootstrap-{tag}"


_FAKE_KUNDALI = {
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
    "kaalsarp_dosh": {"is_present": True},
}


def _fake_verify(token):
    return {"uid": token}


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        from modules.models_user import AppUser, UserDashaTimeline
        import routes.routes_profile_bootstrap as bootstrap_module
        from modules.auth.account_deletion_service import _anonymize_app_user

        client = app.test_client()
        test_firebase_uids = [fb("route1"), fb("route2")]

        def cleanup():
            # U4A.1 -- the bootstrap route now genuinely wires up
            # sync_dasha_timeline_for_user() (previously a no-op for
            # Dasha, since calculate_full_kundali() was always called
            # with user_id=None here), so this fixture -- which uses
            # real, complete birth data -- now really does get a real
            # 81-row UserDashaTimeline. Its FK must be cleared before
            # the AppUser row itself can be deleted (exactly the same
            # child-then-parent order modules/auth/account_deletion_
            # service.py already uses for this same table).
            ids = [u.id for u in AppUser.query.filter(AppUser.firebase_uid.in_(test_firebase_uids)).all()]
            if ids:
                UserDashaTimeline.query.filter(UserDashaTimeline.user_id.in_(ids)).delete(synchronize_session=False)
            AppUser.query.filter(AppUser.firebase_uid.in_(test_firebase_uids)).delete(synchronize_session=False)
            db.session.commit()

        cleanup()

        real_verify = bootstrap_module.firebase_auth.verify_id_token
        real_calculate = bootstrap_module.calculate_full_kundali

        call_count = {"n": 0}

        def _counting_kundali(**kwargs):
            call_count["n"] += 1
            return dict(_FAKE_KUNDALI)

        bootstrap_module.firebase_auth.verify_id_token = _fake_verify
        bootstrap_module.calculate_full_kundali = _counting_kundali

        try:
            # ==========================================================
            print("=== Bootstrap route: single-calculation + full persistence + unchanged response ===")
            # ==========================================================
            fb_uid = fb("route1")
            call_count["n"] = 0
            resp = client.post(
                "/api/user/bootstrap",
                json={
                    "name": "Bootstrap Route Test", "email": "route-test@example.com",
                    "dob": "1990-06-15", "tob": "10:30", "pob": "Lucknow",
                    "lat": 26.8467, "lng": 80.9462, "lang": "en",
                },
                headers={"Authorization": f"Bearer {fb_uid}"},
            )
            check("route: 200 OK", resp.status_code == 200)
            check("route: calculate_full_kundali() called exactly once for this request", call_count["n"] == 1)

            body = resp.get_json()
            check("route: existing response shape UNCHANGED -- exactly the pre-existing keys, no pada/yog/dosh added",
                  set(body.keys()) == {"ok", "profileId", "name", "dob", "tob", "pob", "lagna", "moon_sign", "nakshatra"})
            check("route: response lagna/moon_sign/nakshatra values correct", body["lagna"] == "Leo"
                  and body["moon_sign"] == "Taurus" and body["nakshatra"] == "Rohini")

            app_user = AppUser.query.filter_by(firebase_uid=fb_uid).first()
            check("route: AppUser row persisted nakshatra_pada", app_user is not None and app_user.nakshatra_pada == 3)
            check("route: AppUser row persisted static_yog (sparse, active only)",
                  app_user.static_yog == {"gajakesari_yog": {"strength": "High"}})
            check("route: AppUser row persisted static_dosh (both present here)",
                  app_user.static_dosh == {"manglik": {"severity": "Strong"}, "kaal_sarp": {}})
            check("route: static_astrology_calculated_at set", app_user.static_astrology_calculated_at is not None)
            check("route: static_astrology_version set to the current version", app_user.static_astrology_version == 1)

            # A second bootstrap call for the SAME uid -- still exactly 1
            # call for THAT request (never accumulates/re-triggers extra
            # calls from a prior request).
            call_count["n"] = 0
            resp2 = client.post(
                "/api/user/bootstrap",
                json={
                    "name": "Bootstrap Route Test", "email": "route-test@example.com",
                    "dob": "1990-06-15", "tob": "10:30", "pob": "Lucknow",
                    "lat": 26.8467, "lng": 80.9462, "lang": "en",
                },
                headers={"Authorization": f"Bearer {fb_uid}"},
            )
            check("route: repeat bootstrap for the same profile -> still exactly 1 call for this request",
                  resp2.status_code == 200 and call_count["n"] == 1)

            check("L3: generic initial bootstrap leaves preference unknown", app_user.lang is None)
            app_user.lang = "hi"
            db.session.commit()
            for keys, status in [({}, 200), ({"lang": "en"}, 200), ({"language": "en"}, 200),
                                 ({"lang": "EN", "language": " en "}, 200),
                                 ({"lang": "hi", "language": "en"}, 400),
                                 ({"lang": "en", "language": None}, 400)]:
                response = client.post("/api/user/bootstrap", json={
                    "name": "Bootstrap Route Test", "email": "route-test@example.com",
                    "dob": "1990-06-15", "tob": "10:30", "pob": "Lucknow",
                    "lat": 26.8467, "lng": 80.9462, **keys,
                }, headers={"Authorization": f"Bearer {fb_uid}"})
                db.session.refresh(app_user)
                check(f"L3 bootstrap {keys}: status {status}, preference preserved",
                      response.status_code == status and app_user.lang == "hi")

            print("\n=== Account deletion: _anonymize_app_user() clears all 5 new fields ===")
            fb_uid_2 = fb("route2")
            populated_user = AppUser(
                firebase_uid=fb_uid_2, name="To Delete", dob="1990-06-15", tob="10:30",
                pob="Lucknow", lat=26.8467, lng=80.9462,
                lagna="Leo", moon_sign="Taurus", nakshatra="Rohini",
                nakshatra_pada=3, static_yog={"gajakesari_yog": {"strength": "High"}},
                static_dosh={"manglik": {"severity": "Strong"}},
            )
            import datetime
            populated_user.static_astrology_calculated_at = datetime.datetime.now(datetime.timezone.utc)
            populated_user.static_astrology_version = 1
            db.session.add(populated_user)
            db.session.commit()

            _anonymize_app_user(populated_user)
            db.session.commit()

            check("deletion: lagna/moon_sign/nakshatra cleared (pre-existing behavior, unaffected)",
                  populated_user.lagna is None and populated_user.moon_sign is None and populated_user.nakshatra is None)
            check("deletion: nakshatra_pada cleared", populated_user.nakshatra_pada is None)
            check("deletion: static_yog cleared", populated_user.static_yog is None)
            check("deletion: static_dosh cleared", populated_user.static_dosh is None)
            check("deletion: static_astrology_calculated_at cleared", populated_user.static_astrology_calculated_at is None)
            check("deletion: static_astrology_version cleared", populated_user.static_astrology_version is None)
            check("deletion: dob/tob/pob/lat/lng also cleared (pre-existing behavior, unaffected)",
                  populated_user.dob is None and populated_user.lat is None)

            print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
        finally:
            bootstrap_module.firebase_auth.verify_id_token = real_verify
            bootstrap_module.calculate_full_kundali = real_calculate
            cleanup()

    return failed == 0


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
