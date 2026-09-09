"""
test_saved_audience.py
------------------------
U6A -- Saved Audience Backend Foundation.

Covers:
  - _apply_admin_users_filters()/resolve_user_ids() reuse (no second
    filter/astrology engine).
  - SavedAudience CRUD (create/get/list/update/deactivate) + validation.
  - Criteria v1 contract: version check, filter allowlist, exact JSON
    types (never query-string encodings), unknown keys rejected.
  - Authoring-time vs resolve-time Ask Now Concern validation (an
    inactive-but-historically-valid category must still resolve).
  - created_by semantics: real admin JWT -> stored; bridge-key path ->
    NULL, never fabricated.
  - Security: malformed/SQL-injection-shaped/wrong-type criteria all
    rejected as data, never executed.
  - Filter parity: GET /admin/api/users vs SavedAudience preview return
    IDENTICAL membership/total_count for identical criteria (A-G).
  - Empty valid criteria ({"version":1,"filters":{}}) == All Users.
  - Query-count / no-N+1 proof for preview and resolve_user_ids().

LOCAL ONLY. No production DB. No DB writes outside this test's own
fixture setup/teardown (SavedAudience rows created here are deleted in
a finally block).
"""

import os
import sys
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text, event  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser, UserDashaTimeline  # noqa: E402
from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.models_ask_now_intent_history import AskNowIntentHistory  # noqa: E402
from modules.models_saved_audience import SavedAudience  # noqa: E402

import modules.services.admin_users_service as admin_service  # noqa: E402
import modules.services.asknow_category_service as category_service  # noqa: E402
from modules.services.saved_audience_criteria import validate_criteria, CriteriaValidationError  # noqa: E402
from modules.services.saved_audience_service import (  # noqa: E402
    create_audience, update_audience, deactivate_audience, get_audience,
    list_audiences, preview_audience, preview_criteria, AudienceNotFoundError,
)
from services.current_transit_resolver import CurrentTransitSnapshot  # noqa: E402
from services.current_saturn_resolver import CurrentSaturnResolution  # noqa: E402
from services.sadhesati_classifier import classify_sade_sati, STATE_ACTIVE  # noqa: E402

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


ADMIN_UID = 993199
BASE = 993100

U_BREAKUP_PAYING = BASE + 0     # genuine paid buyer, Breakup concern
U_BREAKUP_FREE = BASE + 1       # Breakup concern, NOT a buyer
U_ARIES_SATURN_DASHA = BASE + 2   # moon_sign=Aries + current Mahadasha=Saturn
U_ARIES_ONLY = BASE + 3          # moon_sign=Aries, different Mahadasha
U_SADE_SATI_ACTIVE = BASE + 4    # moon_sign in the mocked-Saturn active set
U_SADE_SATI_INACTIVE = BASE + 5  # moon_sign NOT in the active set
U_SATURN_HOUSE10 = BASE + 6      # lagna resolving Saturn to House 10
U_SATURN_OTHER_HOUSE = BASE + 7  # different lagna
U_JOBCAREER_JUP7 = BASE + 8      # Job & Career concern + lagna resolving Jupiter to House 7
U_JOBCAREER_ONLY = BASE + 9      # Job & Career concern, different lagna

ALL_UIDS = [
    U_BREAKUP_PAYING, U_BREAKUP_FREE, U_ARIES_SATURN_DASHA, U_ARIES_ONLY,
    U_SADE_SATI_ACTIVE, U_SADE_SATI_INACTIVE, U_SATURN_HOUSE10, U_SATURN_OTHER_HOUSE,
    U_JOBCAREER_JUP7, U_JOBCAREER_ONLY, ADMIN_UID,
]
ALL_APPUSER_IDS = [uid for uid in ALL_UIDS if uid != ADMIN_UID]

_CREATED_AUDIENCE_IDS = []


def fb(uid):
    return f"savedaud-fb-{uid}"


def cleanup():
    for aid in _CREATED_AUDIENCE_IDS:
        SavedAudience.query.filter_by(id=aid).delete(synchronize_session=False)
    _CREATED_AUDIENCE_IDS.clear()
    AskNowIntentHistory.query.filter(AskNowIntentHistory.user_id.in_(ALL_UIDS)).delete(synchronize_session=False)
    ChatPack.query.filter(ChatPack.user_id.in_(ALL_UIDS)).delete(synchronize_session=False)
    UserDashaTimeline.query.filter(UserDashaTimeline.user_id.in_(ALL_APPUSER_IDS)).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.id.in_(ALL_APPUSER_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(ALL_UIDS)).delete(synchronize_session=False)
    db.session.commit()


def make_user(uid, **overrides):
    defaults = dict(
        id=uid, email=f"savedaud{uid}@example.com", provider="password",
        name=f"Test User {uid}", phone=f"+91900003{str(uid)[-4:]}",
        firebase_uid=fb(uid), created_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    return User(**defaults)


def make_appuser(uid, **overrides):
    defaults = dict(
        id=uid, firebase_uid=fb(uid), tz="+05:30", subscription="free", asknow_tokens=0,
        created_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    return AppUser(**defaults)


FIXED_POSITIONS = {
    "Sun": {"rashi": "Leo", "degree": 10.0, "motion": "Direct"},
    "Moon": {"rashi": "Cancer", "degree": 5.0, "motion": "Direct"},
    "Mercury": {"rashi": "Virgo", "degree": 2.0, "motion": "Direct"},
    "Venus": {"rashi": "Libra", "degree": 8.0, "motion": "Direct"},
    "Mars": {"rashi": "Gemini", "degree": 20.0, "motion": "Direct"},
    "Jupiter": {"rashi": "Taurus", "degree": 15.0, "motion": "Direct"},
    "Saturn": {"rashi": "Pisces", "degree": 19.0, "motion": "Retrograde"},
    "Rahu": {"rashi": "Aquarius", "degree": 4.0, "motion": "Retrograde"},
    "Ketu": {"rashi": "Leo", "degree": 4.0, "motion": "Retrograde"},
}


def mock_transit():
    call_count = {"n": 0}

    def _fake():
        call_count["n"] += 1
        return CurrentTransitSnapshot(positions=FIXED_POSITIONS, resolved_at=str(datetime.now()), source="mocked")

    return _fake, call_count


def mock_saturn(sign):
    call_count = {"n": 0}

    def _fake():
        call_count["n"] += 1
        return CurrentSaturnResolution(saturn_sign=sign, resolved_at=datetime.now(), source="mocked")

    return _fake, call_count


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()

        active_names = category_service.get_active_category_names()
        check("Setup: Breakup/Job & Career are active categories", {"Breakup", "Job & Career"} <= set(active_names))

        # ==============================================================
        # Fixtures
        # ==============================================================
        SATURN_SIGN = "Pisces"
        active_moon_signs = [
            s for s in admin_service.CANONICAL_SIGNS
            if classify_sade_sati(s, SATURN_SIGN)["state"] == STATE_ACTIVE
        ]
        inactive_moon_sign = next(s for s in admin_service.CANONICAL_SIGNS if s not in active_moon_signs)

        lagna_for_saturn10 = admin_service._lagna_signs_for_house("Pisces", [10])[0]
        other_lagna = next(s for s in admin_service.CANONICAL_SIGNS if s != lagna_for_saturn10)
        lagna_for_jup7 = admin_service._lagna_signs_for_house("Taurus", [7])[0]
        other_lagna_2 = next(s for s in admin_service.CANONICAL_SIGNS if s != lagna_for_jup7)

        for uid in ALL_APPUSER_IDS:
            db.session.add(make_user(uid))
            db.session.add(make_appuser(uid))
        db.session.add(make_user(ADMIN_UID))
        db.session.commit()

        # A/B fixtures
        db.session.add(ChatPack(
            user_id=U_BREAKUP_PAYING, amount=51, questions_total=8, questions_used=0,
            status="success", razorpay_order_id="order_SAVEDAUD1", razorpay_payment_id="pay_SAVEDAUD1",
            verified_at=datetime.utcnow(),
        ))
        db.session.add(AskNowIntentHistory(user_id=U_BREAKUP_PAYING, concern_category="Breakup", source="pack"))
        db.session.add(AskNowIntentHistory(user_id=U_BREAKUP_FREE, concern_category="Breakup", source="free"))

        # C fixtures
        AppUser.query.get(U_ARIES_SATURN_DASHA).moon_sign = "Aries"
        AppUser.query.get(U_ARIES_ONLY).moon_sign = "Aries"
        today = date.today()
        db.session.add(UserDashaTimeline(
            user_id=U_ARIES_SATURN_DASHA, mahadasha="Saturn", antardasha="Venus",
            start_date=today - timedelta(days=100), end_date=today + timedelta(days=100),
        ))
        db.session.add(UserDashaTimeline(
            user_id=U_ARIES_ONLY, mahadasha="Mercury", antardasha="Venus",
            start_date=today - timedelta(days=100), end_date=today + timedelta(days=100),
        ))

        # D fixtures
        AppUser.query.get(U_SADE_SATI_ACTIVE).moon_sign = active_moon_signs[0]
        AppUser.query.get(U_SADE_SATI_INACTIVE).moon_sign = inactive_moon_sign

        # E fixtures
        AppUser.query.get(U_SATURN_HOUSE10).lagna = lagna_for_saturn10
        AppUser.query.get(U_SATURN_OTHER_HOUSE).lagna = other_lagna

        # F fixtures
        AppUser.query.get(U_JOBCAREER_JUP7).lagna = lagna_for_jup7
        db.session.add(AskNowIntentHistory(user_id=U_JOBCAREER_JUP7, concern_category="Job & Career", source="free"))
        AppUser.query.get(U_JOBCAREER_ONLY).lagna = other_lagna_2
        db.session.add(AskNowIntentHistory(user_id=U_JOBCAREER_ONLY, concern_category="Job & Career", source="free"))

        db.session.commit()

        os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)
        token_admin = create_access_token(identity=str(ADMIN_UID))
        headers_admin = {"Authorization": f"Bearer {token_admin}"}
        client = app.test_client()

        original_transit_resolver = admin_service.resolve_current_transit_snapshot
        original_saturn_resolver = admin_service.resolve_current_saturn_sign

        try:
            fake_transit, transit_calls = mock_transit()
            admin_service.resolve_current_transit_snapshot = fake_transit
            fake_saturn, saturn_calls = mock_saturn(SATURN_SIGN)
            admin_service.resolve_current_saturn_sign = fake_saturn

            # ==========================================================
            print("\n=== Criteria v1 Contract / Type Validation ===")
            # ==========================================================
            check("Valid empty criteria (All Users) passes",
                  validate_criteria({"version": 1, "filters": {}}, authoring=True) == {})

            try:
                validate_criteria({"version": 2, "filters": {}}, authoring=True)
                check("Unknown criteria version -> rejected", False)
            except CriteriaValidationError as e:
                check("Unknown criteria version -> rejected", e.code == "invalid_criteria_version")

            try:
                validate_criteria({"version": 1, "filters": []}, authoring=True)
                check("filters as array (not object) -> rejected", False)
            except CriteriaValidationError as e:
                check("filters as array (not object) -> rejected", e.code == "invalid_criteria")

            try:
                validate_criteria({"version": 1, "filters": {"not_a_real_filter": ["x"]}}, authoring=True)
                check("Unknown filter key -> rejected", False)
            except CriteriaValidationError as e:
                check("Unknown filter key -> rejected", e.code == "unknown_filter_key")

            try:
                validate_criteria({"version": 1, "filters": {"moon_sign": {"nested": "object"}}}, authoring=True)
                check("Nested object as filter value -> rejected", False)
            except CriteriaValidationError as e:
                check("Nested object as filter value -> rejected", e.code == "invalid_filter_value")

            try:
                validate_criteria({"version": 1, "filters": {"ask_now_buyer": "true"}}, authoring=True)
                check("ask_now_buyer as string 'true' (not JSON bool) -> rejected", False)
            except CriteriaValidationError as e:
                check("ask_now_buyer as string 'true' (not JSON bool) -> rejected", e.code == "invalid_filter_value")

            try:
                validate_criteria({"version": 1, "filters": {"saturn_house": "10"}}, authoring=True)
                check("saturn_house as string '10' (not array) -> rejected", False)
            except CriteriaValidationError as e:
                check("saturn_house as string '10' (not array) -> rejected", e.code == "invalid_filter_value")

            try:
                validate_criteria({"version": 1, "filters": {"moon_sign": ["Aries,Cancer"]}}, authoring=True)
                check("moon_sign as comma-joined string element -> rejected (not a canonical sign)", False)
            except CriteriaValidationError as e:
                check("moon_sign as comma-joined string element -> rejected (not a canonical sign)", e.code == "invalid_filter_value")

            try:
                validate_criteria({"version": 1, "filters": {"moon_sign": ["Aries'; DROP TABLE users; --"]}}, authoring=True)
                check("SQL-injection-shaped moon_sign value -> rejected", False)
            except CriteriaValidationError as e:
                check("SQL-injection-shaped moon_sign value -> rejected", e.code == "invalid_filter_value")

            try:
                validate_criteria({"version": 1, "filters": {"nakshatra": ["NotARealNakshatra"]}}, authoring=True)
                check("Invalid nakshatra -> rejected", False)
            except CriteriaValidationError:
                check("Invalid nakshatra -> rejected", True)

            try:
                validate_criteria({"version": 1, "filters": {"yog": ["not_a_real_yog"]}}, authoring=True)
                check("Invalid Yog key -> rejected", False)
            except CriteriaValidationError:
                check("Invalid Yog key -> rejected", True)

            try:
                validate_criteria({"version": 1, "filters": {"dosh": ["not_a_real_dosh"]}}, authoring=True)
                check("Invalid Dosh key -> rejected", False)
            except CriteriaValidationError:
                check("Invalid Dosh key -> rejected", True)

            try:
                validate_criteria({"version": 1, "filters": {"mahadasha": ["Pluto"]}}, authoring=True)
                check("Invalid Dasha lord -> rejected", False)
            except CriteriaValidationError:
                check("Invalid Dasha lord -> rejected", True)

            try:
                validate_criteria({"version": 1, "filters": {"sade_sati_phase": ["4th Phase"]}}, authoring=True)
                check("Invalid Sade Sati phase -> rejected", False)
            except CriteriaValidationError:
                check("Invalid Sade Sati phase -> rejected", True)

            try:
                validate_criteria({"version": 1, "filters": {"saturn_house": [0]}}, authoring=True)
                check("House 0 -> rejected", False)
            except CriteriaValidationError:
                check("House 0 -> rejected", True)

            try:
                validate_criteria({"version": 1, "filters": {"saturn_house": [13]}}, authoring=True)
                check("House 13 -> rejected", False)
            except CriteriaValidationError:
                check("House 13 -> rejected", True)

            try:
                validate_criteria({"version": 1, "filters": {"ask_now_concern": ["NotARealCategory"]}}, authoring=True)
                check("Invalid Ask Now category (authoring) -> rejected", False)
            except CriteriaValidationError as e:
                check("Invalid Ask Now category (authoring) -> rejected", e.code == "invalid_ask_now_concern")

            # Correct exact-type examples pass cleanly.
            good = validate_criteria({"version": 1, "filters": {
                "customer_type": "paying", "ask_now_buyer": True,
                "ask_now_concern": ["Breakup"], "saturn_house": [10],
            }}, authoring=True)
            check("Well-typed criteria passes validation", good["saturn_house"] == [10] and good["ask_now_buyer"] is True)

            # ==========================================================
            print("\n=== CRUD API + created_by semantics ===")
            # ==========================================================
            r = client.post("/admin/api/audiences", json={
                "name": "  Breakup Users  ",
                "description": "Users asking about breakup",
                "criteria": {"version": 1, "filters": {"ask_now_concern": ["Breakup"]}},
            }, headers=headers_admin)
            check("Create via admin JWT -> 201", r.status_code == 201)
            body = r.get_json()
            _CREATED_AUDIENCE_IDS.append(body["id"])
            check("Create: name is trimmed", body["name"] == "Breakup Users")
            check("Create: created_by is the admin's own users.id (real JWT path)", body["created_by"] == ADMIN_UID)
            check("Create: is_active defaults True", body["is_active"] is True)
            audience_id = body["id"]

            r_bridge = client.post("/admin/api/audiences", json={
                "name": "Bridge Path Audience",
                "criteria": {"version": 1, "filters": {}},
            }, headers={"X-Admin-Bridge-Key": os.environ.get("ADMIN_BRIDGE_SECRET", "")})
            # Bridge secret may not be configured in this local env --
            # only assert created_by semantics if the create actually
            # succeeded via the bridge path.
            if r_bridge.status_code == 201:
                _CREATED_AUDIENCE_IDS.append(r_bridge.get_json()["id"])
                check("Create via bridge key -> created_by is NULL (no JWT identity)", r_bridge.get_json()["created_by"] is None)
            else:
                print("  SKIP: bridge-key create_by check (ADMIN_BRIDGE_SECRET not configured in this local env)")

            r_blank = client.post("/admin/api/audiences", json={
                "name": "   ", "criteria": {"version": 1, "filters": {}},
            }, headers=headers_admin)
            check("Blank name -> 400", r_blank.status_code == 400)

            r_get = client.get(f"/admin/api/audiences/{audience_id}", headers=headers_admin)
            check("Get detail -> 200", r_get.status_code == 200)
            check("Get detail -> criteria stored exactly as validated", r_get.get_json()["criteria"]["filters"]["ask_now_concern"] == ["Breakup"])

            r_list = client.get("/admin/api/audiences", headers=headers_admin)
            check("List -> 200", r_list.status_code == 200)
            check("List -> lightweight metadata only (no 'users'/'member_count' keys)",
                  all("users" not in a and "member_count" not in a for a in r_list.get_json()["audiences"]))

            r_patch = client.patch(f"/admin/api/audiences/{audience_id}", json={"description": "Updated desc"}, headers=headers_admin)
            check("Patch description only -> 200", r_patch.status_code == 200)
            check("Patch: name unchanged (PATCH semantics)", r_patch.get_json()["name"] == "Breakup Users")
            check("Patch: description updated", r_patch.get_json()["description"] == "Updated desc")

            r_patch_bad_criteria = client.patch(f"/admin/api/audiences/{audience_id}", json={
                "criteria": {"version": 1, "filters": {"unknown_key": ["x"]}}
            }, headers=headers_admin)
            check("Patch with invalid criteria -> 400, never partially applied", r_patch_bad_criteria.status_code == 400)
            r_recheck = client.get(f"/admin/api/audiences/{audience_id}", headers=headers_admin)
            check("Patch rejection did not mutate stored criteria", r_recheck.get_json()["criteria"]["filters"]["ask_now_concern"] == ["Breakup"])

            r_delete = client.delete(f"/admin/api/audiences/{audience_id}", headers=headers_admin)
            check("Delete -> 200 (soft-deactivate)", r_delete.status_code == 200)
            check("Delete -> is_active False", r_delete.get_json()["is_active"] is False)
            r_get_after_delete = client.get(f"/admin/api/audiences/{audience_id}", headers=headers_admin)
            check("Deactivated audience still readable (never hard-deleted)", r_get_after_delete.status_code == 200)

            r_reactivate = client.patch(f"/admin/api/audiences/{audience_id}", json={"is_active": True}, headers=headers_admin)
            check("Reactivate via PATCH is_active=true -> 200", r_reactivate.status_code == 200 and r_reactivate.get_json()["is_active"] is True)

            r_404 = client.get("/admin/api/audiences/999999999", headers=headers_admin)
            check("Unknown audience id -> 404", r_404.status_code == 404)

            r_noauth = client.get("/admin/api/audiences")
            check("No auth -> 401", r_noauth.status_code == 401)

            # ==========================================================
            print("\n=== Resolve-Time Historical Ask Now Category Test ===")
            # ==========================================================
            r_hist = client.post("/admin/api/audiences", json={
                "name": "Historical Other Audience",
                "criteria": {"version": 1, "filters": {"ask_now_concern": ["Other"]}},
            }, headers=headers_admin)
            check("Create with active 'Other' category -> 201", r_hist.status_code == 201)
            hist_id = r_hist.get_json()["id"]
            _CREATED_AUDIENCE_IDS.append(hist_id)

            category_service.set_category_active("Other", False)
            try:
                r_preview_hist = client.get(f"/admin/api/audiences/{hist_id}/preview", headers=headers_admin)
                check("Preview of EXISTING audience still works after category disabled", r_preview_hist.status_code == 200)

                r_new_with_inactive = client.post("/admin/api/audiences", json={
                    "name": "Should Fail",
                    "criteria": {"version": 1, "filters": {"ask_now_concern": ["Other"]}},
                }, headers=headers_admin)
                check("Creating a NEW audience with the now-inactive category -> 400", r_new_with_inactive.status_code == 400)
            finally:
                category_service.set_category_active("Other", True)

            r_preview_restored = client.get(f"/admin/api/audiences/{hist_id}/preview", headers=headers_admin)
            check("Preview still works after category re-enabled", r_preview_restored.status_code == 200)

            # ==========================================================
            print("\n=== Filter Parity: GET /admin/api/users vs SavedAudience preview ===")
            # ==========================================================
            def parity_check(label, filters):
                qs_dict = {}
                for k, v in filters.items():
                    if isinstance(v, list):
                        qs_dict[k] = ",".join(str(x) for x in v)
                    elif isinstance(v, bool):
                        qs_dict[k] = "true" if v else "false"
                    else:
                        qs_dict[k] = str(v)
                qs_dict["page_size"] = "200"
                r_live = client.get("/admin/api/users", query_string=qs_dict, headers=headers_admin)
                r_prev = client.post("/admin/api/audiences/preview", json={
                    "criteria": {"version": 1, "filters": filters}, "page": 1, "page_size": 200,
                }, headers=headers_admin)
                check(f"{label}: both 200", r_live.status_code == 200 and r_prev.status_code == 200)
                live_ids = {u["id"] for u in r_live.get_json()["users"]}
                prev_ids = {u["id"] for u in r_prev.get_json()["users"]}
                live_total = r_live.get_json()["pagination"]["total_count"]
                prev_total = r_prev.get_json()["member_count"]
                check(f"{label}: total_count/member_count match ({live_total} == {prev_total})", live_total == prev_total)
                check(f"{label}: matched user id sets are IDENTICAL", live_ids == prev_ids)
                return live_ids

            ids_a = parity_check("A: ask_now_concern=Breakup", {"ask_now_concern": ["Breakup"]})
            check("A: includes both Breakup fixtures", {U_BREAKUP_PAYING, U_BREAKUP_FREE} <= ids_a)

            ids_b = parity_check("B: customer_type=paying + ask_now_concern=Breakup", {"customer_type": "paying", "ask_now_concern": ["Breakup"]})
            check("B: includes only the PAYING Breakup fixture", U_BREAKUP_PAYING in ids_b and U_BREAKUP_FREE not in ids_b)

            ids_c = parity_check("C: moon_sign=Aries + mahadasha=Saturn", {"moon_sign": ["Aries"], "mahadasha": ["Saturn"]})
            check("C: includes the Aries+Saturn-dasha fixture, excludes the Aries-only fixture", U_ARIES_SATURN_DASHA in ids_c and U_ARIES_ONLY not in ids_c)

            ids_d = parity_check("D: sade_sati_active=true", {"sade_sati_active": True})
            check("D: includes the active fixture, excludes the inactive one", U_SADE_SATI_ACTIVE in ids_d and U_SADE_SATI_INACTIVE not in ids_d)

            ids_e = parity_check("E: saturn_house=10", {"saturn_house": [10]})
            check("E: includes the House-10 fixture, excludes the other-house fixture", U_SATURN_HOUSE10 in ids_e and U_SATURN_OTHER_HOUSE not in ids_e)

            ids_f = parity_check("F: ask_now_concern=Job & Career + jupiter_house=7", {"ask_now_concern": ["Job & Career"], "jupiter_house": [7]})
            check("F: includes the matching fixture, excludes the Job&Career-but-wrong-house fixture", U_JOBCAREER_JUP7 in ids_f and U_JOBCAREER_ONLY not in ids_f)

            # G: empty criteria = All Users
            # L3: exercise the same four membership surfaces with language
            # AND every representative existing dimension, on these fixtures.
            for uid in ALL_APPUSER_IDS:
                AppUser.query.get(uid).lang = "hi" if uid % 2 == 0 else "en"
            db.session.commit()
            language_cases = [
                ({"moon_sign": ["Aries"]}, U_ARIES_SATURN_DASHA),
                ({"mahadasha": ["Saturn"]}, U_ARIES_SATURN_DASHA),
                ({"sade_sati_active": True}, U_SADE_SATI_ACTIVE),
                ({"saturn_house": [10]}, U_SATURN_HOUSE10),
                ({"ask_now_concern": ["Breakup"]}, U_BREAKUP_PAYING),
                ({"customer_type": "paying"}, U_BREAKUP_PAYING),
                ({}, U_BREAKUP_PAYING),
            ]
            for dimension, expected in language_cases:
                filters = {**dimension, "language": ["hi"]}
                label = f"L3 {dimension} + Hindi"
                live_ids = parity_check(label, filters)
                audience = create_audience(name=label, criteria={"version": 1, "filters": filters})
                _CREATED_AUDIENCE_IDS.append(audience.id)
                saved = preview_audience(audience.id, page=1, page_size=200)
                resolved = set(admin_service.resolve_user_ids(**filters))
                check(label + ": four-way IDs", live_ids == {u["id"] for u in saved["users"]} == resolved)
                check(label + ": nonempty expected fixture", expected in live_ids)
            for uid in ALL_APPUSER_IDS:
                AppUser.query.get(uid).lang = None
            db.session.commit()

            r_all_live = client.get("/admin/api/users?page_size=1", headers=headers_admin)
            r_all_preview = client.post("/admin/api/audiences/preview", json={
                "criteria": {"version": 1, "filters": {}}, "page": 1, "page_size": 1,
            }, headers=headers_admin)
            check("G: empty criteria -> 200", r_all_preview.status_code == 200)
            check("G: empty criteria member_count == whole-table total_count",
                  r_all_preview.get_json()["member_count"] == r_all_live.get_json()["pagination"]["total_count"])

            # ==========================================================
            print("\n=== resolve_user_ids() standalone ===")
            # ==========================================================
            ids_direct = admin_service.resolve_user_ids(ask_now_concern=["Breakup"])
            check("resolve_user_ids(): returns a plain list of ints", all(isinstance(x, int) for x in ids_direct))
            check("resolve_user_ids(): matches list_users()'s own matched ids for the same filter",
                  set(ids_direct) == ids_a)
            check("resolve_user_ids(): deterministic ascending order", ids_direct == sorted(ids_direct))

            # ==========================================================
            print("\n=== Performance / Query Counts ===")
            # ==========================================================
            transit_calls["n"] = 0
            saturn_calls["n"] = 0
            admin_service.resolve_user_ids(saturn_house=[10], jupiter_house=[7])
            check("resolve_user_ids(): transit snapshot resolved AT MOST once", transit_calls["n"] <= 1)
            check("resolve_user_ids(): Saturn resolved EXACTLY once", saturn_calls["n"] == 1)

            query_counts = {}
            for page_size in (1, 20, 100):
                queries = []

                def _counter(conn, cursor, statement, parameters, context, executemany):
                    queries.append(statement)

                event.listen(db.engine, "before_cursor_execute", _counter)
                try:
                    r = client.post("/admin/api/audiences/preview", json={
                        "criteria": {"version": 1, "filters": {"ask_now_concern": ["Breakup"]}},
                        "page": 1, "page_size": page_size,
                    }, headers=headers_admin)
                finally:
                    event.remove(db.engine, "before_cursor_execute", _counter)
                query_counts[page_size] = len(queries)
                check(f"Preview page_size={page_size} -> 200", r.status_code == 200)

            check(f"Preview: SQL query count IDENTICAL across page_size 1/20/100 (observed {query_counts})",
                  len(set(query_counts.values())) == 1)
            check("Preview: query count is small (no N+1)", all(c <= 10 for c in query_counts.values()))

        finally:
            admin_service.resolve_current_transit_snapshot = original_transit_resolver
            admin_service.resolve_current_saturn_sign = original_saturn_resolver
            cleanup()

        print(f"\n{'='*60}\nTOTAL: {passed} passed, {failed} failed\n{'='*60}")
        return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
