"""
test_admin_users_api.py
------------------------
Users Module U2 -- GET /admin/api/users and GET /admin/api/users/<id>.

Covers: admin_or_bridge_required auth (both the bridge-key path and the
JWT+ADMIN_USER_IDS fallback, plus outright rejection), pagination,
search, the active/inactive/unknown status rule (U2.1: restricted to
session_start events only -- any other event_name must NOT make a user
Active), ChatPack/subscription "paying" rules, ACTIVE/GRACE vs TRIAL
"active_subscription", the users.id != app_users.id identity-mismatch
case, a user with no AppUser at all, null/invalid DOB -> null age, the
U2.1 bridged app_users.dob fallback (+ users.dob precedence over it),
the detail 404 case, and (U3A) real Birth Astrology (moon_sign/lagna/
nakshatra) exposure + filtering -- reused stored app_users values only,
multi-select OR-within-dimension / AND-across-dimension semantics, and
a runtime proof that no astrology-engine function is ever invoked by
any of these requests.

LOCAL ONLY. No production DB.
"""

import os
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.models_chat_pack import ChatPack  # noqa: E402
from modules.models_premium_subscription import CurrentEntitlement  # noqa: E402
from modules.models_activity_events import ActivityEvent  # noqa: E402

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


ADMIN_UID = 989001

U_ACTIVE = 989010
U_INACTIVE = 989011
U_UNKNOWN_NO_FB = 989012
U_UNKNOWN_NO_ACTIVITY = 989013
U_CHATPACK_PAYER = 989014
U_CHATPACK_FAILED = 989015
U_SUB_ACTIVE = 989016
U_SUB_GRACE = 989017
U_SUB_TRIAL = 989018
U_FREE = 989019
U_NO_APPUSER = 989020
U_DOB_VALID = 989021
U_DOB_NULL = 989022
U_DOB_INVALID = 989023
U_MISMATCH = 989024
U_SEARCHME = 989025
# U2.1 -- Active redefinition (opened the app == session_start only).
U_OTHER_EVENT_ONLY = 989026
# U2.1 -- Age/DOB source audit: bridged app_users.dob fallback, and
# users.dob taking precedence over a differing bridged value.
U_DOB_BRIDGE_ONLY = 989027
U_DOB_PRECEDENCE = 989028
# U3A -- Birth Astrology (moon_sign/lagna/nakshatra), reused stored
# values only, multi-select OR/AND semantics.
U_ASTRO_FULL = 989029       # linked, moon_sign=Taurus, lagna=Leo, nakshatra=Rohini, free
U_ASTRO_PARTIAL = 989030    # linked, but no astrology fields populated at all
U_ASTRO_OTHER1 = 989031     # linked, moon_sign=Cancer (OR-semantics contrast)
U_ASTRO_OTHER2 = 989032     # linked, lagna=Leo but moon_sign=Gemini (AND-semantics contrast)
# U3B.3 -- Pada/Yog/Dosh fixtures (task's own A-G set).
U_YOG_A = 989033   # A: calculated + Gajakesari + Manglik + Pada 1, moon_sign=Taurus, paying
U_YOG_B = 989034   # B: calculated + Budh-Aditya + no Dosh + Pada 2
U_YOG_C = 989035   # C: calculated + Gajakesari AND Dhan Yog + Kaal Sarp + Pada 3, moon_sign=Leo, active sub
U_YOG_D = 989036   # D: calculated + no Yog + no Dosh + Pada 4
U_YOG_E = 989037   # E: linked but UNCALCULATED (all 5 static-astrology fields NULL)
U_YOG_G = 989038   # G: Panch Mahapurush umbrella + Ruchaka sub-yog, Pada 1
# F (unlinked users row) reuses the existing U_UNKNOWN_NO_FB fixture --
# it is already exactly "a users row with no firebase_uid at all",
# there is no reason to duplicate a second identical fixture for it.

# Default list ordering (created_at DESC, id DESC tie-breaker).
# TIE_A/TIE_B deliberately share the exact same created_at -- TIE_B has
# the higher id and must sort before TIE_A under the id DESC tie-break.
U_ORD_OLDEST = 989039
U_ORD_MIDDLE = 989040
U_ORD_NEWEST = 989041
U_ORD_TIE_A = 989042
U_ORD_TIE_B = 989043

ALL_TEST_UIDS = [
    ADMIN_UID, U_ACTIVE, U_INACTIVE, U_UNKNOWN_NO_FB, U_UNKNOWN_NO_ACTIVITY,
    U_CHATPACK_PAYER, U_CHATPACK_FAILED, U_SUB_ACTIVE, U_SUB_GRACE, U_SUB_TRIAL,
    U_FREE, U_NO_APPUSER, U_DOB_VALID, U_DOB_NULL, U_DOB_INVALID, U_MISMATCH,
    U_SEARCHME, U_OTHER_EVENT_ONLY, U_DOB_BRIDGE_ONLY, U_DOB_PRECEDENCE,
    U_ASTRO_FULL, U_ASTRO_PARTIAL, U_ASTRO_OTHER1, U_ASTRO_OTHER2,
    U_YOG_A, U_YOG_B, U_YOG_C, U_YOG_D, U_YOG_E, U_YOG_G,
    U_ORD_OLDEST, U_ORD_MIDDLE, U_ORD_NEWEST, U_ORD_TIE_A, U_ORD_TIE_B,
]

# AppUser ids deliberately NOT matching the User ids above -- explicit
# proof this code never assumes users.id == app_users.id.
AP_SUB_ACTIVE = 500016
AP_SUB_GRACE = 500017
AP_SUB_TRIAL = 500018
AP_MISMATCH = 777024  # far from U_MISMATCH's own id, on purpose
AP_DOB_BRIDGE_ONLY = 500027
AP_DOB_PRECEDENCE = 500028
AP_ASTRO_FULL = 500029
AP_ASTRO_PARTIAL = 500030
AP_ASTRO_OTHER1 = 500031
AP_ASTRO_OTHER2 = 500032
AP_YOG_A = 500033
AP_YOG_B = 500034
AP_YOG_C = 500035
AP_YOG_D = 500036
AP_YOG_E = 500037
AP_YOG_G = 500038

ALL_APPUSER_IDS = [
    AP_SUB_ACTIVE, AP_SUB_GRACE, AP_SUB_TRIAL, AP_MISMATCH,
    AP_DOB_BRIDGE_ONLY, AP_DOB_PRECEDENCE,
    AP_ASTRO_FULL, AP_ASTRO_PARTIAL, AP_ASTRO_OTHER1, AP_ASTRO_OTHER2,
    AP_YOG_A, AP_YOG_B, AP_YOG_C, AP_YOG_D, AP_YOG_E, AP_YOG_G,
]


def fb(uid):
    return f"fb-admin-users-test-{uid}"


def cleanup():
    CurrentEntitlement.query.filter(CurrentEntitlement.profile_id.in_(ALL_APPUSER_IDS)).delete(synchronize_session=False)
    ChatPack.query.filter(ChatPack.user_id.in_(ALL_TEST_UIDS)).delete(synchronize_session=False)
    ActivityEvent.query.filter(ActivityEvent.firebase_uid.in_([fb(u) for u in ALL_TEST_UIDS])).delete(synchronize_session=False)
    AppUser.query.filter(AppUser.id.in_(ALL_APPUSER_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(ALL_TEST_UIDS)).delete(synchronize_session=False)
    db.session.commit()


def make_user(uid, **overrides):
    defaults = dict(
        id=uid,
        email=f"admusr{uid}@example.com",
        provider="password",
        name=f"Test User {uid}",
        phone=f"+91900000{str(uid)[-4:]}",
        created_at=datetime.utcnow(),
    )
    defaults.update(overrides)
    return User(**defaults)


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        now = datetime.utcnow()

        db.session.add(make_user(ADMIN_UID))

        db.session.add(make_user(U_ACTIVE, firebase_uid=fb(U_ACTIVE)))
        db.session.add(make_user(U_INACTIVE, firebase_uid=fb(U_INACTIVE)))
        db.session.add(make_user(U_UNKNOWN_NO_FB, firebase_uid=None))
        db.session.add(make_user(U_UNKNOWN_NO_ACTIVITY, firebase_uid=fb(U_UNKNOWN_NO_ACTIVITY)))
        db.session.add(make_user(U_CHATPACK_PAYER))
        db.session.add(make_user(U_CHATPACK_FAILED))
        db.session.add(make_user(U_SUB_ACTIVE, firebase_uid=fb(U_SUB_ACTIVE)))
        db.session.add(make_user(U_SUB_GRACE, firebase_uid=fb(U_SUB_GRACE)))
        db.session.add(make_user(U_SUB_TRIAL, firebase_uid=fb(U_SUB_TRIAL)))
        db.session.add(make_user(U_FREE))
        db.session.add(make_user(U_NO_APPUSER, firebase_uid=fb(U_NO_APPUSER)))
        db.session.add(make_user(U_DOB_VALID, dob="1990-06-15"))
        db.session.add(make_user(U_DOB_NULL, dob=None))
        db.session.add(make_user(U_DOB_INVALID, dob="not-a-date"))
        db.session.add(make_user(U_MISMATCH, firebase_uid=fb(U_MISMATCH)))
        db.session.add(make_user(
            U_SEARCHME, name="Zzyx Findable Marker", email="zzyx.findable@example.com",
            created_at=now - timedelta(days=500),
        ))
        # U2.1 -- recently engaged via a NON-session_start event only.
        # Locked rule: this must NOT be "active" (must be "unknown" --
        # firebase_uid known, but no session_start ever recorded).
        db.session.add(make_user(U_OTHER_EVENT_ONLY, firebase_uid=fb(U_OTHER_EVENT_ONLY)))
        # U2.1 -- no users.dob at all; a valid DOB exists only on the
        # bridged AppUser row.
        db.session.add(make_user(U_DOB_BRIDGE_ONLY, dob=None, firebase_uid=fb(U_DOB_BRIDGE_ONLY)))
        # U2.1 -- BOTH users.dob and a (different) bridged AppUser.dob
        # are valid -- users.dob must win.
        db.session.add(make_user(U_DOB_PRECEDENCE, dob="1990-06-15", firebase_uid=fb(U_DOB_PRECEDENCE)))
        # U3A -- Birth Astrology fixtures, all linked via firebase_uid.
        db.session.add(make_user(U_ASTRO_FULL, firebase_uid=fb(U_ASTRO_FULL)))
        db.session.add(make_user(U_ASTRO_PARTIAL, firebase_uid=fb(U_ASTRO_PARTIAL)))
        db.session.add(make_user(U_ASTRO_OTHER1, firebase_uid=fb(U_ASTRO_OTHER1)))
        db.session.add(make_user(U_ASTRO_OTHER2, firebase_uid=fb(U_ASTRO_OTHER2)))
        # U3B.3 -- Pada/Yog/Dosh fixtures A-G.
        db.session.add(make_user(U_YOG_A, firebase_uid=fb(U_YOG_A)))
        db.session.add(make_user(U_YOG_B, firebase_uid=fb(U_YOG_B)))
        db.session.add(make_user(U_YOG_C, firebase_uid=fb(U_YOG_C)))
        db.session.add(make_user(U_YOG_D, firebase_uid=fb(U_YOG_D)))
        db.session.add(make_user(U_YOG_E, firebase_uid=fb(U_YOG_E)))
        db.session.add(make_user(U_YOG_G, firebase_uid=fb(U_YOG_G)))

        # Default list ordering fixtures -- distinct, controlled
        # created_at values, isolated from every other fixture via a
        # distinctive search marker in `name`. TIE_A/TIE_B share the
        # exact same created_at to exercise the id DESC tie-breaker.
        ord_tie_ts = now - timedelta(days=10)
        db.session.add(make_user(U_ORD_OLDEST, name="OrderMarker Oldest",
                                  created_at=now - timedelta(days=30)))
        db.session.add(make_user(U_ORD_MIDDLE, name="OrderMarker Middle",
                                  created_at=now - timedelta(days=15)))
        db.session.add(make_user(U_ORD_NEWEST, name="OrderMarker Newest",
                                  created_at=now - timedelta(minutes=1)))
        db.session.add(make_user(U_ORD_TIE_A, name="OrderMarker TieA", created_at=ord_tie_ts))
        db.session.add(make_user(U_ORD_TIE_B, name="OrderMarker TieB", created_at=ord_tie_ts))
        db.session.commit()

        # Activity events -- active vs inactive vs no-activity-at-all,
        # all via ACTIVE_EVENT_NAME ("session_start") per U2.1.
        db.session.add(ActivityEvent(
            event_name="session_start", event_version=1,
            occurred_at=now - timedelta(days=2),
            firebase_uid=fb(U_ACTIVE), platform="backend_internal",
            environment="local", properties={"entry_point": "cold_start"},
        ))
        db.session.add(ActivityEvent(
            event_name="session_start", event_version=1,
            occurred_at=now - timedelta(days=90),
            firebase_uid=fb(U_INACTIVE), platform="backend_internal",
            environment="local", properties={"entry_point": "cold_start"},
        ))
        # U_UNKNOWN_NO_ACTIVITY: firebase_uid known, deliberately ZERO
        # activity_events rows -- must resolve to "unknown", not "inactive".

        # U2.1 -- U_OTHER_EVENT_ONLY: a RECENT event, but not
        # session_start. Must NOT drive status=active (must be "unknown").
        db.session.add(ActivityEvent(
            event_name="asknow_question_submitted", event_version=1,
            occurred_at=now - timedelta(days=2),
            firebase_uid=fb(U_OTHER_EVENT_ONLY), platform="app_android",
            environment="local", properties={},
        ))
        db.session.commit()

        # ChatPack: successful vs failed-only.
        db.session.add(ChatPack(user_id=U_CHATPACK_PAYER, amount=100, questions_total=10, questions_used=2, status="success"))
        db.session.add(ChatPack(user_id=U_CHATPACK_FAILED, amount=100, questions_total=10, questions_used=0, status="failed"))
        # U3B.3 -- U_YOG_A is "paying" (Customer Type + Yog cross-dimension test).
        db.session.add(ChatPack(user_id=U_YOG_A, amount=100, questions_total=10, questions_used=1, status="success"))
        db.session.commit()

        # Subscriptions -- via AppUser bridged by firebase_uid, ids
        # deliberately NOT matching the User ids (identity-mismatch proof).
        db.session.add(AppUser(id=AP_SUB_ACTIVE, firebase_uid=fb(U_SUB_ACTIVE), name="p1"))
        db.session.add(AppUser(id=AP_SUB_GRACE, firebase_uid=fb(U_SUB_GRACE), name="p2"))
        db.session.add(AppUser(id=AP_SUB_TRIAL, firebase_uid=fb(U_SUB_TRIAL), name="p3"))
        db.session.add(AppUser(id=AP_MISMATCH, firebase_uid=fb(U_MISMATCH), name="p4"))
        # U2.1 DOB bridge fixtures.
        db.session.add(AppUser(id=AP_DOB_BRIDGE_ONLY, firebase_uid=fb(U_DOB_BRIDGE_ONLY), name="p5", dob="1985-03-20"))
        db.session.add(AppUser(id=AP_DOB_PRECEDENCE, firebase_uid=fb(U_DOB_PRECEDENCE), name="p6", dob="2000-01-01"))
        # U3A Birth Astrology fixtures.
        db.session.add(AppUser(
            id=AP_ASTRO_FULL, firebase_uid=fb(U_ASTRO_FULL), name="p7",
            moon_sign="Taurus", lagna="Leo", nakshatra="Rohini",
        ))
        # Linked, but astrology fields never populated (e.g. bootstrapped
        # before this code path existed, or with incomplete birth data).
        db.session.add(AppUser(id=AP_ASTRO_PARTIAL, firebase_uid=fb(U_ASTRO_PARTIAL), name="p8"))
        db.session.add(AppUser(
            id=AP_ASTRO_OTHER1, firebase_uid=fb(U_ASTRO_OTHER1), name="p9",
            moon_sign="Cancer", lagna="Aries", nakshatra="Mrigashira",
        ))
        db.session.add(AppUser(
            id=AP_ASTRO_OTHER2, firebase_uid=fb(U_ASTRO_OTHER2), name="p10",
            moon_sign="Gemini", lagna="Leo", nakshatra="Ashwini",
        ))
        # U3B.3 -- Pada/Yog/Dosh fixtures A-G. calculated_at/version/
        # static_yog/static_dosh set DIRECTLY (never via a real Kundali
        # calculation -- per this task's own "no need to invoke
        # astrology calculation merely to prepare Admin test rows").
        db.session.add(AppUser(
            id=AP_YOG_A, firebase_uid=fb(U_YOG_A), name="pA",
            moon_sign="Taurus", lagna="Leo", nakshatra="Rohini", nakshatra_pada=1,
            static_yog={"gajakesari_yog": {"strength": "High"}},
            static_dosh={"manglik": {"severity": "Strong"}},
            static_astrology_calculated_at=now, static_astrology_version=1,
        ))
        db.session.add(AppUser(
            id=AP_YOG_B, firebase_uid=fb(U_YOG_B), name="pB",
            nakshatra_pada=2,
            static_yog={"budh_aditya_yog": {"strength": "Moderate"}},
            static_dosh={},
            static_astrology_calculated_at=now, static_astrology_version=1,
        ))
        db.session.add(AppUser(
            id=AP_YOG_C, firebase_uid=fb(U_YOG_C), name="pC",
            moon_sign="Leo", nakshatra_pada=3,
            static_yog={"gajakesari_yog": {"strength": "High"}, "dhan_yog": {"strength": "Low"}},
            static_dosh={"kaal_sarp": {}},
            static_astrology_calculated_at=now, static_astrology_version=1,
        ))
        db.session.add(AppUser(
            id=AP_YOG_D, firebase_uid=fb(U_YOG_D), name="pD",
            nakshatra_pada=4, static_yog={}, static_dosh={},
            static_astrology_calculated_at=now, static_astrology_version=1,
        ))
        # E: linked, but genuinely UNCALCULATED -- every static-astrology
        # field stays exactly at its column default (NULL).
        db.session.add(AppUser(id=AP_YOG_E, firebase_uid=fb(U_YOG_E), name="pE"))
        db.session.add(AppUser(
            id=AP_YOG_G, firebase_uid=fb(U_YOG_G), name="pG", nakshatra_pada=1,
            static_yog={"panch_mahapurush_rajyog": {"strength": "High"}, "panch_mahapurush_ruchaka": {}},
            static_dosh={},
            static_astrology_calculated_at=now, static_astrology_version=1,
        ))
        db.session.commit()

        db.session.add(CurrentEntitlement(profile_id=AP_SUB_ACTIVE, status="ACTIVE", plan="PRIME_MONTHLY"))
        db.session.add(CurrentEntitlement(profile_id=AP_SUB_GRACE, status="GRACE", plan="PRIME_YEARLY"))
        db.session.add(CurrentEntitlement(profile_id=AP_SUB_TRIAL, status="TRIAL", plan=None))
        db.session.add(CurrentEntitlement(profile_id=AP_MISMATCH, status="ACTIVE", plan="PRIME_MONTHLY"))
        # U3B.3 cross-dimension fixtures: A is "paying" (ChatPack,
        # added below), C has an ACTIVE subscription.
        db.session.add(CurrentEntitlement(profile_id=AP_YOG_C, status="ACTIVE", plan="PRIME_MONTHLY"))
        db.session.commit()

        client = app.test_client()

        try:
            # ==========================================================
            print("=== 1: auth rejected without any admin credential ===")
            # ==========================================================
            resp = client.get("/admin/api/users")
            check("1: no credential at all -> 401", resp.status_code == 401)

            resp2 = client.get(f"/admin/api/users/{U_ACTIVE}")
            check("1: detail endpoint also rejects with no credential -> 401", resp2.status_code == 401)

            # ==========================================================
            print("\n=== 2: JWT + ADMIN_USER_IDS path works ===")
            # ==========================================================
            os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)
            token_admin = create_access_token(identity=str(ADMIN_UID))
            headers_admin = {"Authorization": f"Bearer {token_admin}"}

            resp3 = client.get("/admin/api/users?page_size=5", headers=headers_admin)
            check("2: authenticated admin JWT -> 200", resp3.status_code == 200)
            body3 = resp3.get_json()
            check("2: response has summary/users/pagination keys", set(body3.keys()) == {"summary", "users", "pagination"})

            # ==========================================================
            print("\n=== 3: X-Admin-Bridge-Key path works (Next.js BFF credential) ===")
            # ==========================================================
            os.environ["ADMIN_BRIDGE_SECRET"] = "test-bridge-secret-admin-users"
            resp4 = client.get("/admin/api/users?page_size=5", headers={"X-Admin-Bridge-Key": "test-bridge-secret-admin-users"})
            check("3: correct bridge key, NO JWT at all -> 200", resp4.status_code == 200)

            resp5 = client.get("/admin/api/users", headers={"X-Admin-Bridge-Key": "wrong-key"})
            check("3: wrong bridge key, no JWT -> 401 (falls through to admin_required)", resp5.status_code == 401)
            os.environ.pop("ADMIN_BRIDGE_SECRET", None)

            # ==========================================================
            print("\n=== 4: pagination ===")
            # ==========================================================
            resp6 = client.get("/admin/api/users?page=1&page_size=3", headers=headers_admin)
            body6 = resp6.get_json()
            check("4: page_size respected (<=3 rows returned)", len(body6["users"]) <= 3)
            check("4: pagination.page_size reflects request", body6["pagination"]["page_size"] == 3)
            check("4: pagination.total_count >= number of test users seeded", body6["pagination"]["total_count"] >= len(ALL_TEST_UIDS) - 1)

            # ==========================================================
            print("\n=== 5: search ===")
            # ==========================================================
            resp7 = client.get("/admin/api/users?search=Zzyx Findable Marker", headers=headers_admin)
            body7 = resp7.get_json()
            check("5: search by name finds exactly the marker user", len(body7["users"]) == 1 and body7["users"][0]["id"] == U_SEARCHME)

            resp8 = client.get("/admin/api/users?search=zzyx.findable@example.com", headers=headers_admin)
            body8 = resp8.get_json()
            check("5: search by email finds the same user", len(body8["users"]) == 1 and body8["users"][0]["id"] == U_SEARCHME)

            # ==========================================================
            print("\n=== 6: active / inactive / unknown status ===")
            # ==========================================================
            def get_user_row(body, uid):
                return next((u for u in body["users"] if u["id"] == uid), None)

            resp9 = client.get("/admin/api/users?page_size=200", headers=headers_admin)
            body9 = resp9.get_json()

            row_active = get_user_row(body9, U_ACTIVE)
            check("6: recent activity (2 days ago) -> status=active", row_active and row_active["status"] == "active")
            check("6: active user has a non-null last_active_at", row_active and row_active["last_active_at"] is not None)

            row_inactive = get_user_row(body9, U_INACTIVE)
            check("6: old activity (90 days ago) -> status=inactive", row_inactive and row_inactive["status"] == "inactive")

            row_unknown_no_fb = get_user_row(body9, U_UNKNOWN_NO_FB)
            check("6: no firebase_uid at all -> status=unknown (never inactive)", row_unknown_no_fb and row_unknown_no_fb["status"] == "unknown")

            row_unknown_no_activity = get_user_row(body9, U_UNKNOWN_NO_ACTIVITY)
            check("6: firebase_uid known but zero activity rows -> status=unknown (never inactive)",
                  row_unknown_no_activity and row_unknown_no_activity["status"] == "unknown")

            # U2.1 -- a recent event that is NOT session_start must not
            # make the user "active" (locked rule: only app-open counts).
            row_other_event_only = get_user_row(body9, U_OTHER_EVENT_ONLY)
            check("6 (U2.1): recent asknow_question_submitted ALONE -> status=unknown, not active",
                  row_other_event_only and row_other_event_only["status"] == "unknown")
            check("6 (U2.1): such a user's last_active_at is null (no session_start ever recorded)",
                  row_other_event_only and row_other_event_only["last_active_at"] is None)

            # ==========================================================
            print("\n=== 7: paying via ChatPack ===")
            # ==========================================================
            row_payer = get_user_row(body9, U_CHATPACK_PAYER)
            check("7: successful ChatPack -> ask_now_buyer=True", row_payer and row_payer["ask_now_buyer"] is True)
            check("7: successful ChatPack -> customer_type=paying", row_payer and row_payer["customer_type"] == "paying")

            row_failed_pack = get_user_row(body9, U_CHATPACK_FAILED)
            check("7: only a FAILED ChatPack -> ask_now_buyer=False", row_failed_pack and row_failed_pack["ask_now_buyer"] is False)
            check("7: only a FAILED ChatPack -> customer_type=free", row_failed_pack and row_failed_pack["customer_type"] == "free")

            # ==========================================================
            print("\n=== 8: paying via subscription entitlement ===")
            # ==========================================================
            row_sub_active = get_user_row(body9, U_SUB_ACTIVE)
            check("8: ACTIVE entitlement (plan set) -> customer_type=paying", row_sub_active and row_sub_active["customer_type"] == "paying")
            check("8: ACTIVE entitlement -> active_subscription=True", row_sub_active and row_sub_active["active_subscription"] is True)

            row_sub_grace = get_user_row(body9, U_SUB_GRACE)
            check("8: GRACE entitlement -> active_subscription=True", row_sub_grace and row_sub_grace["active_subscription"] is True)
            check("8: GRACE entitlement -> customer_type=paying", row_sub_grace and row_sub_grace["customer_type"] == "paying")

            row_sub_trial = get_user_row(body9, U_SUB_TRIAL)
            check("8: TRIAL (plan=None) -> active_subscription=False", row_sub_trial and row_sub_trial["active_subscription"] is False)
            check("8: TRIAL (plan=None) -> customer_type=free (trial is not paying)", row_sub_trial and row_sub_trial["customer_type"] == "free")

            row_free = get_user_row(body9, U_FREE)
            check("9: free user (no ChatPack, no subscription) -> customer_type=free", row_free and row_free["customer_type"] == "free")
            check("9: free user -> active_subscription=False", row_free and row_free["active_subscription"] is False)

            # ==========================================================
            print("\n=== 10: users.id / app_users.id mismatch handled via firebase_uid ===")
            # ==========================================================
            row_mismatch = get_user_row(body9, U_MISMATCH)
            check(f"10: U_MISMATCH ({U_MISMATCH}) resolves correctly despite AppUser id being {AP_MISMATCH} (unrelated number)",
                  row_mismatch and row_mismatch["customer_type"] == "paying" and row_mismatch["active_subscription"] is True)

            # ==========================================================
            print("\n=== 11: user without any AppUser remains visible ===")
            # ==========================================================
            row_no_appuser = get_user_row(body9, U_NO_APPUSER)
            check("11: user with firebase_uid but no matching AppUser still appears in the list", row_no_appuser is not None)
            check("11: such a user has active_subscription=False (bridge yields nothing, never guessed)",
                  row_no_appuser and row_no_appuser["active_subscription"] is False)
            check("11: such a user has customer_type=free", row_no_appuser and row_no_appuser["customer_type"] == "free")

            # ==========================================================
            print("\n=== 12: age from DOB -- valid / null / invalid ===")
            # ==========================================================
            row_dob_valid = get_user_row(body9, U_DOB_VALID)
            check("12: valid DOB (1990-06-15) produces a plausible non-null age", row_dob_valid and isinstance(row_dob_valid["age"], int) and 20 < row_dob_valid["age"] < 60)

            row_dob_null = get_user_row(body9, U_DOB_NULL)
            check("12: null DOB -> age is null (never fabricated)", row_dob_null and row_dob_null["age"] is None)

            row_dob_invalid = get_user_row(body9, U_DOB_INVALID)
            check("12: malformed DOB ('not-a-date') -> age is null, no crash", row_dob_invalid and row_dob_invalid["age"] is None)

            # ==========================================================
            print("\n=== 12b (U2.1): DOB resolution -- bridged app_users.dob fallback + precedence ===")
            # ==========================================================
            row_dob_bridge_only = get_user_row(body9, U_DOB_BRIDGE_ONLY)
            check("12b: no users.dob, but a valid bridged app_users.dob (1985-03-20) -> plausible non-null age",
                  row_dob_bridge_only and isinstance(row_dob_bridge_only["age"], int) and 30 < row_dob_bridge_only["age"] < 55)

            row_dob_precedence = get_user_row(body9, U_DOB_PRECEDENCE)
            # users.dob=1990-06-15 (~age 36 in 2026) must win over the
            # bridged app_users.dob=2000-01-01 (~age 26) -- proves
            # precedence, not just "a" DOB being picked arbitrarily.
            check("12b: users.dob takes precedence over a differing bridged app_users.dob",
                  row_dob_precedence and isinstance(row_dob_precedence["age"], int) and row_dob_precedence["age"] >= 30)

            # ==========================================================
            print("\n=== 12c (U3A): Birth Astrology exposure -- linked/unlinked/missing ===")
            # ==========================================================
            row_astro_full = get_user_row(body9, U_ASTRO_FULL)
            check("12c-A: linked profile with all 3 fields -> moon_sign/lagna/nakshatra returned correctly",
                  row_astro_full and row_astro_full["moon_sign"] == "Taurus"
                  and row_astro_full["lagna"] == "Leo" and row_astro_full["nakshatra"] == "Rohini")

            check("12c-B: canonical user with firebase_uid but NO linked AppUser -> all 3 null",
                  row_no_appuser and row_no_appuser["moon_sign"] is None
                  and row_no_appuser["lagna"] is None and row_no_appuser["nakshatra"] is None)

            row_no_fb_at_all = get_user_row(body9, U_UNKNOWN_NO_FB)
            check("12c-B: user with no firebase_uid at all -> all 3 null (bridge never even attempted)",
                  row_no_fb_at_all and row_no_fb_at_all["moon_sign"] is None
                  and row_no_fb_at_all["lagna"] is None and row_no_fb_at_all["nakshatra"] is None)

            row_astro_partial = get_user_row(body9, U_ASTRO_PARTIAL)
            check("12c-C: linked profile that simply never had astrology fields populated -> all 3 null, never fabricated",
                  row_astro_partial and row_astro_partial["moon_sign"] is None
                  and row_astro_partial["lagna"] is None and row_astro_partial["nakshatra"] is None)

            # ==========================================================
            print("\n=== 13: filters narrow the result set correctly ===")
            # ==========================================================
            resp10 = client.get("/admin/api/users?status=active&page_size=200", headers=headers_admin)
            ids10 = {u["id"] for u in resp10.get_json()["users"]}
            check("13: status=active filter includes U_ACTIVE", U_ACTIVE in ids10)
            check("13: status=active filter excludes U_INACTIVE", U_INACTIVE not in ids10)
            check("13: status=active filter excludes unknown users", U_UNKNOWN_NO_FB not in ids10 and U_UNKNOWN_NO_ACTIVITY not in ids10)

            resp11 = client.get("/admin/api/users?customer_type=paying&page_size=200", headers=headers_admin)
            ids11 = {u["id"] for u in resp11.get_json()["users"]}
            check("13: customer_type=paying includes ChatPack payer", U_CHATPACK_PAYER in ids11)
            check("13: customer_type=paying includes subscription payer", U_SUB_ACTIVE in ids11)
            check("13: customer_type=paying excludes free user", U_FREE not in ids11)

            resp12 = client.get("/admin/api/users?active_subscription=true&page_size=200", headers=headers_admin)
            ids12 = {u["id"] for u in resp12.get_json()["users"]}
            check("13: active_subscription=true includes ACTIVE/GRACE, excludes TRIAL", U_SUB_ACTIVE in ids12 and U_SUB_GRACE in ids12 and U_SUB_TRIAL not in ids12)

            resp13 = client.get("/admin/api/users?ask_now_buyer=true&page_size=200", headers=headers_admin)
            ids13 = {u["id"] for u in resp13.get_json()["users"]}
            check("13: ask_now_buyer=true includes the successful ChatPack user only", U_CHATPACK_PAYER in ids13 and U_CHATPACK_FAILED not in ids13)

            resp14 = client.get(f"/admin/api/users?age_min=20&age_max=60&search=admusr{U_DOB_VALID}", headers=headers_admin)
            ids14 = {u["id"] for u in resp14.get_json()["users"]}
            check("13: age_min/age_max range includes the matching valid-DOB user", U_DOB_VALID in ids14)

            # ==========================================================
            print("\n=== 13b (U3A): Birth Astrology filters -- D/E/F/G/H/I ===")
            # ==========================================================
            # D: single Moon Sign -> correct user only.
            respD = client.get("/admin/api/users?moon_sign=Taurus&page_size=200", headers=headers_admin)
            bodyD = respD.get_json()
            idsD = {u["id"] for u in bodyD["users"]}
            check("13b-D: moon_sign=Taurus returns exactly the matching user",
                  idsD & {U_ASTRO_FULL, U_ASTRO_PARTIAL, U_ASTRO_OTHER1, U_ASTRO_OTHER2} == {U_ASTRO_FULL})

            # E: multi-select Moon Sign -> OR semantics.
            respE = client.get("/admin/api/users?moon_sign=Taurus,Cancer&page_size=200", headers=headers_admin)
            idsE = {u["id"] for u in respE.get_json()["users"]}
            check("13b-E: moon_sign=Taurus,Cancer (OR) includes both Taurus and Cancer users",
                  U_ASTRO_FULL in idsE and U_ASTRO_OTHER1 in idsE)
            check("13b-E: moon_sign=Taurus,Cancer (OR) excludes the Gemini user",
                  U_ASTRO_OTHER2 not in idsE)

            # F: Moon Sign + Lagna -> AND semantics (U_ASTRO_OTHER2 has
            # lagna=Leo too, but a different moon_sign -- must be excluded).
            respF = client.get("/admin/api/users?moon_sign=Taurus&lagna=Leo&page_size=200", headers=headers_admin)
            idsF = {u["id"] for u in respF.get_json()["users"]}
            check("13b-F: moon_sign=Taurus AND lagna=Leo matches only the user satisfying BOTH",
                  idsF & {U_ASTRO_FULL, U_ASTRO_OTHER1, U_ASTRO_OTHER2} == {U_ASTRO_FULL})

            # G: Nakshatra filter.
            respG = client.get("/admin/api/users?nakshatra=Rohini&page_size=200", headers=headers_admin)
            idsG = {u["id"] for u in respG.get_json()["users"]}
            check("13b-G: nakshatra=Rohini returns exactly the matching user",
                  idsG & {U_ASTRO_FULL, U_ASTRO_PARTIAL, U_ASTRO_OTHER1, U_ASTRO_OTHER2} == {U_ASTRO_FULL})

            # H: astrology filter combined with an existing (non-astrology)
            # filter -- customer_type. U_ASTRO_FULL is a free user (no
            # ChatPack/subscription seeded for it).
            respH1 = client.get("/admin/api/users?moon_sign=Taurus&customer_type=free&page_size=200", headers=headers_admin)
            idsH1 = {u["id"] for u in respH1.get_json()["users"]}
            check("13b-H: moon_sign=Taurus AND customer_type=free still includes the matching free user",
                  U_ASTRO_FULL in idsH1)

            respH2 = client.get("/admin/api/users?moon_sign=Taurus&customer_type=paying&page_size=200", headers=headers_admin)
            idsH2 = {u["id"] for u in respH2.get_json()["users"]}
            check("13b-H: moon_sign=Taurus AND customer_type=paying excludes the (free) matching user "
                  "-- proves real AND combination with an existing filter, not an OR",
                  U_ASTRO_FULL not in idsH2)

            # I: pagination/counts stay correct under an astrology filter.
            check("13b-I: pagination.total_count for moon_sign=Taurus matches the actual returned-id count",
                  bodyD["pagination"]["total_count"] >= 1 and bodyD["pagination"]["total_count"] == len(bodyD["users"])
                  if bodyD["pagination"]["total_count"] <= bodyD["pagination"]["page_size"] else True)

            # Invalid astrology filter values are rejected cleanly (matches
            # the existing status/customer_type 400 convention).
            resp_bad_moon = client.get("/admin/api/users?moon_sign=NotASign", headers=headers_admin)
            check("13b: invalid moon_sign value -> 400, not 500", resp_bad_moon.status_code == 400)
            resp_bad_nak = client.get("/admin/api/users?nakshatra=NotANakshatra", headers=headers_admin)
            check("13b: invalid nakshatra value -> 400, not 500", resp_bad_nak.status_code == 400)

            # ==========================================================
            print("\n=== 14: invalid query params are rejected cleanly ===")
            # ==========================================================
            resp15 = client.get("/admin/api/users?status=bogus", headers=headers_admin)
            check("14: invalid status value -> 400, not 500", resp15.status_code == 400)

            resp16 = client.get("/admin/api/users?customer_type=bogus", headers=headers_admin)
            check("14: invalid customer_type value -> 400, not 500", resp16.status_code == 400)

            # ==========================================================
            print("\n=== 15: detail endpoint ===")
            # ==========================================================
            resp17 = client.get(f"/admin/api/users/{U_SUB_ACTIVE}", headers=headers_admin)
            check("15: detail 200 for a real user", resp17.status_code == 200)
            body17 = resp17.get_json()
            # U5A -- `ask_now` is now a real top-level section (Ask Now
            # concern intelligence: buyer/total_classified_questions/
            # concerns/category_counts). Updated here the same way
            # U4C.3 already updated this exact check for current_transits.
            check("15: detail response has identity/customer/birth_astrology/ask_now keys only",
                  set(body17.keys()) == {"identity", "customer", "birth_astrology", "ask_now"})
            check("15: detail identity.id matches requested id", body17["identity"]["id"] == U_SUB_ACTIVE)
            check("15: detail customer.active_subscription reflects ACTIVE entitlement", body17["customer"]["active_subscription"] is True)

            resp18 = client.get("/admin/api/users/999999999", headers=headers_admin)
            check("15: nonexistent id -> 404", resp18.status_code == 404)

            # ==========================================================
            print("\n=== 15b (U3A-J): detail endpoint returns real Birth Astrology ===")
            # ==========================================================
            resp19 = client.get(f"/admin/api/users/{U_ASTRO_FULL}", headers=headers_admin)
            body19 = resp19.get_json()
            birth_astrology_19 = dict(body19.get("birth_astrology") or {})
            # U4B.2 -- this fixture has a real moon_sign ("Taurus"), so
            # sade_sati is a genuine {active, phase} object derived from
            # TODAY's real resolved Saturn sign -- not a fixed/mockable
            # value in this test file (which never mocks the Saturn
            # resolver). Verified structurally + against the real
            # classifier for today's actual Saturn sign, then excluded
            # from the exact-equality check below (which still covers
            # every other, genuinely static field unchanged).
            sade_sati_19 = birth_astrology_19.pop("sade_sati", "MISSING_KEY")
            from services.sadhesati_classifier import classify_sade_sati as _classify_for_test
            from services.current_saturn_resolver import resolve_current_saturn_sign as _resolve_for_test
            _today_saturn = _resolve_for_test().saturn_sign
            _expected_sade_sati_19 = _classify_for_test("Taurus", _today_saturn)
            check("15b-J: sade_sati for a fixture WITH a real moon_sign matches classify_sade_sati() for today's real Saturn sign",
                  sade_sati_19 == {"active": _expected_sade_sati_19["active"], "phase": _expected_sade_sati_19["phase"]})
            # U4C.3 -- current_transits also depends on a REAL (unmocked in
            # this file) transit resolution, exactly like sade_sati above --
            # popped and verified structurally/against a live calculation,
            # then excluded from the exact-equality check below (which
            # still covers every other, genuinely static field unchanged).
            from services.current_transit_resolver import resolve_current_transit_snapshot as _resolve_transit_for_test
            from services.personalization_engine import calculate_house as _calculate_house_for_test
            current_transits_19 = birth_astrology_19.pop("current_transits", "MISSING_KEY")
            _live_snapshot = _resolve_transit_for_test()
            check("15b-J: current_transits has all 9 canonical planets",
                  isinstance(current_transits_19, dict)
                  and set(current_transits_19.get("planets", {}).keys())
                  == {"Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Rahu", "Ketu"})
            check("15b-J: current_transits.planets.Jupiter.house matches calculate_house(Leo, <live Jupiter rashi>) for this fixture's real Lagna=Leo",
                  current_transits_19["planets"]["Jupiter"]["house"]
                  == _calculate_house_for_test("Leo", _live_snapshot.rashi("Jupiter")))
            check("15b-J: detail birth_astrology has the exact stored Moon/Lagna/Nakshatra values "
                  "(Pada/Yog/Dosh untouched for this U3A-only fixture -> all null, uncalculated; "
                  # U4A.3 -- current_dasha added (null: this fixture has no UserDashaTimeline rows).
                  "current_dasha also null since this fixture has no Dasha timeline)",
                  birth_astrology_19 == {
                      "moon_sign": "Taurus", "lagna": "Leo", "nakshatra": "Rohini",
                      "nakshatra_pada": None, "static_yog": None, "static_dosh": None,
                      "static_astrology_calculated_at": None, "static_astrology_version": None,
                      "current_dasha": None,
                  })

            resp20 = client.get(f"/admin/api/users/{U_NO_APPUSER}", headers=headers_admin)
            body20 = resp20.get_json()
            birth_astrology_20 = dict(body20.get("birth_astrology") or {})
            # U4C.3 -- current_transits is NEVER null as a whole object (it
            # is a global, unconditional fact -- unlike sade_sati/current_dasha
            # which ARE null-as-a-whole for exactly this no-AppUser case);
            # only each planet's own `house` is null, since this user has no
            # bridged Lagna at all. Popped and verified separately, same
            # reasoning as the U_ASTRO_FULL fixture above.
            current_transits_20 = birth_astrology_20.pop("current_transits", "MISSING_KEY")
            check("15b-J: current_transits is still present (not null) for a user with no linked AppUser -- rashi is a global fact",
                  isinstance(current_transits_20, dict) and "planets" in current_transits_20)
            check("15b-J: every planet's house is null for a user with no linked AppUser (no Lagna to compute from)",
                  all(p["house"] is None for p in current_transits_20["planets"].values()))
            check("15b-J: detail birth_astrology is all-null (except current_transits, checked separately) for a user with no linked AppUser",
                  birth_astrology_20 == {
                      "moon_sign": None, "lagna": None, "nakshatra": None,
                      "nakshatra_pada": None, "static_yog": None, "static_dosh": None,
                      "static_astrology_calculated_at": None, "static_astrology_version": None,
                      # U4A.3 -- current_dasha also null: no bridge at all.
                      "current_dasha": None,
                      # U4B.2 -- sade_sati also null: no moon_sign (no bridge) -> NOT_CALCULATED.
                      "sade_sati": None,
                  })

            # ==========================================================
            print("\n=== 16 (U3A-K): no astrology-engine function is ever invoked ===")
            # ==========================================================
            import full_kundali_api

            def _boom(*args, **kwargs):
                raise AssertionError("calculate_full_kundali() must NEVER be called by list/detail/filter requests")

            original_fn = full_kundali_api.calculate_full_kundali
            full_kundali_api.calculate_full_kundali = _boom
            try:
                r1 = client.get("/admin/api/users?page_size=200", headers=headers_admin)
                r2 = client.get("/admin/api/users?moon_sign=Taurus,Cancer&lagna=Leo&nakshatra=Rohini&page_size=200", headers=headers_admin)
                r3 = client.get(f"/admin/api/users/{U_ASTRO_FULL}", headers=headers_admin)
                check("16-K: plain list request never triggers calculate_full_kundali()", r1.status_code == 200)
                check("16-K: astrology-filtered list request never triggers calculate_full_kundali()", r2.status_code == 200)
                check("16-K: detail request never triggers calculate_full_kundali()", r3.status_code == 200)
            finally:
                full_kundali_api.calculate_full_kundali = original_fn

            # ==========================================================
            print("\n=== 17 (U3B.3): LIST serialization -- NULL vs [] vs populated ===")
            # ==========================================================
            resp21 = client.get("/admin/api/users?page_size=200", headers=headers_admin)
            body21 = resp21.get_json()
            row_a = get_user_row(body21, U_YOG_A)
            row_b = get_user_row(body21, U_YOG_B)
            row_c = get_user_row(body21, U_YOG_C)
            row_d = get_user_row(body21, U_YOG_D)
            row_e = get_user_row(body21, U_YOG_E)
            row_g = get_user_row(body21, U_YOG_G)
            row_f = get_user_row(body21, U_UNKNOWN_NO_FB)  # F: unlinked

            check("17-A: calculated+Gajakesari+Manglik -> active_yog/active_dosh correct machine-key lists",
                  row_a and row_a["active_yog"] == ["gajakesari_yog"] and row_a["active_dosh"] == ["manglik"])
            check("17-A: nakshatra_pada/calculated_at present", row_a and row_a["nakshatra_pada"] == 1
                  and row_a["static_astrology_calculated_at"] is not None)
            check("17-B: calculated+Budh-Aditya+no Dosh -> active_yog populated, active_dosh == [] (calculated, none present)",
                  row_b and row_b["active_yog"] == ["budh_aditya_yog"] and row_b["active_dosh"] == [])
            check("17-C: calculated+2 Yog+Kaal Sarp -> both yog keys present, dosh correct",
                  row_c and set(row_c["active_yog"]) == {"gajakesari_yog", "dhan_yog"} and row_c["active_dosh"] == ["kaal_sarp"])
            check("17-D: calculated, no Yog, no Dosh -> BOTH [] (never null -- calculated is calculated)",
                  row_d and row_d["active_yog"] == [] and row_d["active_dosh"] == [] and row_d["nakshatra_pada"] == 4)
            check("17-E: UNCALCULATED -> active_yog/active_dosh/nakshatra_pada/calculated_at ALL null "
                  "(never fabricated into [])",
                  row_e and row_e["active_yog"] is None and row_e["active_dosh"] is None
                  and row_e["nakshatra_pada"] is None and row_e["static_astrology_calculated_at"] is None)
            check("17-F: unlinked user (no firebase_uid) -> same all-null semantics as uncalculated",
                  row_f and row_f["active_yog"] is None and row_f["active_dosh"] is None and row_f["nakshatra_pada"] is None)
            check("17-G: Panch Mahapurush umbrella + sub-yog both appear as separate active_yog entries",
                  row_g and set(row_g["active_yog"]) == {"panch_mahapurush_rajyog", "panch_mahapurush_ruchaka"})
            check("17: LIST rows never expose raw static_yog/static_dosh JSONB or version (compactness rule)",
                  all("static_yog" not in r and "static_dosh" not in r and "static_astrology_version" not in r
                      for r in (row_a, row_b, row_c, row_d, row_e, row_g)))

            # ==========================================================
            print("\n=== 18 (U3B.3): DETAIL serialization -- full stored JSONB, NULL vs {} ===")
            # ==========================================================
            detail_a = client.get(f"/admin/api/users/{U_YOG_A}", headers=headers_admin).get_json()
            check("18-A: detail birth_astrology has full stored static_yog/static_dosh objects (strength/severity retained)",
                  detail_a["birth_astrology"]["static_yog"] == {"gajakesari_yog": {"strength": "High"}}
                  and detail_a["birth_astrology"]["static_dosh"] == {"manglik": {"severity": "Strong"}})
            check("18-A: detail has nakshatra_pada/calculated_at/version",
                  detail_a["birth_astrology"]["nakshatra_pada"] == 1
                  and detail_a["birth_astrology"]["static_astrology_calculated_at"] is not None
                  and detail_a["birth_astrology"]["static_astrology_version"] == 1)
            check("18-A: no prose (reasons/positives/challenge/description/remedies/upsell) anywhere in the payload",
                  not any(k in str(detail_a["birth_astrology"]) for k in ("reasons", "positives", "challenge", "upsell", "remedies")))

            detail_d = client.get(f"/admin/api/users/{U_YOG_D}", headers=headers_admin).get_json()
            check("18-D: calculated-but-empty -> static_yog/static_dosh are {} (not null)",
                  detail_d["birth_astrology"]["static_yog"] == {} and detail_d["birth_astrology"]["static_dosh"] == {})

            detail_e = client.get(f"/admin/api/users/{U_YOG_E}", headers=headers_admin).get_json()
            check("18-E: UNCALCULATED -> static_yog/static_dosh are null (never {})",
                  detail_e["birth_astrology"]["static_yog"] is None and detail_e["birth_astrology"]["static_dosh"] is None
                  and detail_e["birth_astrology"]["static_astrology_calculated_at"] is None
                  and detail_e["birth_astrology"]["static_astrology_version"] is None)

            # ==========================================================
            print("\n=== 19 (U3B.3): FILTERS -- Pada, Yog, Dosh, Panch, cross-dimension ===")
            # ==========================================================
            def ids_for(qs):
                r = client.get(f"/admin/api/users?{qs}&page_size=200", headers=headers_admin)
                return {u["id"] for u in r.get_json()["users"]}, r

            our_yog_ids = {U_YOG_A, U_YOG_B, U_YOG_C, U_YOG_D, U_YOG_E, U_YOG_G}

            ids, _ = ids_for("nakshatra_pada=1")
            check("19: Pada single (1) -> exactly A and G among our fixtures", ids & our_yog_ids == {U_YOG_A, U_YOG_G})

            ids, _ = ids_for("nakshatra_pada=1,2")
            check("19: Pada multi (1,2) -> A, B, G", ids & our_yog_ids == {U_YOG_A, U_YOG_B, U_YOG_G})

            ids, _ = ids_for("yog=gajakesari_yog")
            check("19: Yog single (gajakesari_yog) -> A and C", ids & our_yog_ids == {U_YOG_A, U_YOG_C})

            ids, _ = ids_for("yog=gajakesari_yog,budh_aditya_yog")
            check("19: Yog multi ANY (gajakesari_yog,budh_aditya_yog) -> A, B, C", ids & our_yog_ids == {U_YOG_A, U_YOG_B, U_YOG_C})

            ids, _ = ids_for("dosh=manglik")
            check("19: Dosh single (manglik) -> A only", ids & our_yog_ids == {U_YOG_A})

            ids, _ = ids_for("dosh=manglik,kaal_sarp")
            check("19: Dosh multi ANY (manglik,kaal_sarp) -> A and C", ids & our_yog_ids == {U_YOG_A, U_YOG_C})

            ids, _ = ids_for("yog=panch_mahapurush_rajyog")
            check("19: Panch Mahapurush umbrella filter -> G only", ids & our_yog_ids == {U_YOG_G})

            ids, _ = ids_for("yog=panch_mahapurush_ruchaka")
            check("19: Panch Mahapurush sub-yog filter -> G only", ids & our_yog_ids == {U_YOG_G})

            # Uncalculated/unlinked never match ANY yog/dosh filter.
            ids, _ = ids_for("yog=gajakesari_yog,budh_aditya_yog,dhan_yog,panch_mahapurush_rajyog,panch_mahapurush_ruchaka")
            check("19: uncalculated (E) never matches any Yog filter", U_YOG_E not in ids)
            ids, _ = ids_for("dosh=manglik,kaal_sarp")
            check("19: uncalculated (E) never matches any Dosh filter", U_YOG_E not in ids)

            # Cross-dimension AND: Moon Sign + Yog.
            ids, _ = ids_for("moon_sign=Taurus&yog=gajakesari_yog")
            check("19: Moon Sign=Taurus AND Yog=gajakesari_yog -> A only (C also has gajakesari but moon_sign=Leo)",
                  ids & our_yog_ids == {U_YOG_A})

            # Pada + Yog.
            ids, _ = ids_for("nakshatra_pada=1&yog=gajakesari_yog")
            check("19: Pada=1 AND Yog=gajakesari_yog -> A only (C has gajakesari but pada=3)",
                  ids & our_yog_ids == {U_YOG_A})

            # Yog + Dosh.
            ids, _ = ids_for("yog=gajakesari_yog&dosh=manglik")
            check("19: Yog=gajakesari_yog AND Dosh=manglik -> A only (C has gajakesari but kaal_sarp, not manglik)",
                  ids & our_yog_ids == {U_YOG_A})

            # Nakshatra + Pada (A: nakshatra=Rohini, pada=1).
            ids, _ = ids_for("nakshatra=Rohini&nakshatra_pada=1")
            check("19: Nakshatra=Rohini AND Pada=1 -> A", ids & our_yog_ids == {U_YOG_A})

            # Lagna + Dosh (A: lagna=Leo, manglik).
            ids, _ = ids_for("lagna=Leo&dosh=manglik")
            check("19: Lagna=Leo AND Dosh=manglik -> A", ids & our_yog_ids == {U_YOG_A})

            # Customer Type + Yog. Both A (ChatPack) and C (ACTIVE
            # entitlement, added for the Active-Subscription+Dosh case
            # below) are legitimately "paying" under the existing,
            # unchanged customer_type rule -- so customer_type=paying
            # correctly includes both. AND-combination is proven instead
            # by customer_type=free excluding both (neither is free),
            # while the SAME yog filter with no customer_type
            # restriction includes both -- proving the customer_type
            # clause actively narrows the set, not a no-op OR.
            ids_paying, _ = ids_for("customer_type=paying&yog=gajakesari_yog")
            check("19: customer_type=paying AND yog=gajakesari_yog -> both A and C (both are genuinely paying)",
                  ids_paying & our_yog_ids == {U_YOG_A, U_YOG_C})
            ids_free, _ = ids_for("customer_type=free&yog=gajakesari_yog")
            check("19: customer_type=free AND yog=gajakesari_yog -> EXCLUDES both (neither A nor C is free) "
                  "-- proves real AND narrowing, not an OR",
                  U_YOG_A not in ids_free and U_YOG_C not in ids_free)

            # Active Subscription + Dosh (C has an ACTIVE entitlement + kaal_sarp).
            ids, _ = ids_for("active_subscription=true&dosh=kaal_sarp")
            check("19: active_subscription=true AND dosh=kaal_sarp -> C", ids & our_yog_ids == {U_YOG_C})

            # Search + Yog.
            ids, _ = ids_for(f"search=admusr{U_YOG_A}&yog=gajakesari_yog")
            check("19: search + yog combine correctly (AND) -> A only", ids & our_yog_ids == {U_YOG_A})

            # ==========================================================
            print("\n=== 20 (U3B.3): pagination reflects filtered counts ===")
            # ==========================================================
            _, r_page1 = ids_for("yog=gajakesari_yog,budh_aditya_yog,dhan_yog&page=1&page_size=2")
            body_p1 = r_page1.get_json()
            check("20: page_size respected under a Yog filter", len(body_p1["users"]) <= 2)
            check("20: pagination.total_count reflects the FILTERED set, not the whole table",
                  body_p1["pagination"]["total_count"] < 200)

            # ==========================================================
            print("\n=== 21 (U3B.3): invalid filter values -> clean 400s ===")
            # ==========================================================
            for bad_qs, err_key in [
                ("nakshatra_pada=0", "invalid_nakshatra_pada"),
                ("nakshatra_pada=5", "invalid_nakshatra_pada"),
                ("nakshatra_pada=abc", "invalid_nakshatra_pada"),
                ("nakshatra_pada=2.5", "invalid_nakshatra_pada"),
                ("yog=not_a_real_yog", "invalid_yog"),
                ("dosh=pitra_dosh", "invalid_dosh"),
                ("dosh=guru_chandal_dosh", "invalid_dosh"),
            ]:
                r = client.get(f"/admin/api/users?{bad_qs}", headers=headers_admin)
                check(f"21: {bad_qs} -> 400 with error={err_key}",
                      r.status_code == 400 and r.get_json().get("error") == err_key)
                check(f"21: {bad_qs} error body exposes no SQL/DB internals",
                      "psycopg2" not in str(r.get_json()).lower() and "sqlalchemy" not in str(r.get_json()).lower())

            # ==========================================================
            print("\n=== 22 (U3B.3): summary cards unaffected by Yog/Dosh ===")
            # ==========================================================
            resp_summary_filtered = client.get("/admin/api/users?yog=gajakesari_yog&page_size=5", headers=headers_admin)
            summary_filtered = resp_summary_filtered.get_json()["summary"]
            resp_summary_unfiltered = client.get("/admin/api/users?page_size=5", headers=headers_admin)
            summary_unfiltered = resp_summary_unfiltered.get_json()["summary"]
            check("22: summary shape is still exactly the 4 existing keys",
                  set(summary_filtered.keys()) == {"total_users", "active_users", "paying_users", "active_subscriptions"})
            check("22: summary counts are IDENTICAL whether or not a Yog filter is applied "
                  "(summary is whole-table, independent of list filters -- unchanged U2 behavior)",
                  summary_filtered == summary_unfiltered)

            # ==========================================================
            print("\n=== 23 (U3B.3): ENGINE-INDEPENDENCE -- list/detail/Pada/Yog/Dosh filters ===")
            # ==========================================================
            full_kundali_api.calculate_full_kundali = _boom
            try:
                r_list = client.get("/admin/api/users?page_size=200", headers=headers_admin)
                r_pada = client.get("/admin/api/users?nakshatra_pada=1,2&page_size=200", headers=headers_admin)
                r_yog = client.get("/admin/api/users?yog=gajakesari_yog,panch_mahapurush_ruchaka&page_size=200", headers=headers_admin)
                r_dosh = client.get("/admin/api/users?dosh=manglik,kaal_sarp&page_size=200", headers=headers_admin)
                r_detail = client.get(f"/admin/api/users/{U_YOG_A}", headers=headers_admin)
                check("23: plain list -> 200 with engine patched to raise", r_list.status_code == 200)
                check("23: Pada filter -> 200 with engine patched to raise", r_pada.status_code == 200)
                check("23: Yog filter -> 200 with engine patched to raise", r_yog.status_code == 200)
                check("23: Dosh filter -> 200 with engine patched to raise", r_dosh.status_code == 200)
                check("23: detail (with populated static_yog/static_dosh) -> 200 with engine patched to raise",
                      r_detail.status_code == 200)
            finally:
                full_kundali_api.calculate_full_kundali = original_fn

            # ==========================================================
            print("\n=== 24 (U3B.3): N+1 / query-count proof ===")
            # ==========================================================
            from sqlalchemy import event
            from sqlalchemy.engine import Engine

            query_count = {"n": 0}

            def _count_queries(conn, cursor, statement, parameters, context, executemany):
                query_count["n"] += 1

            event.listen(Engine, "before_cursor_execute", _count_queries)
            try:
                query_count["n"] = 0
                r_n1 = client.get("/admin/api/users?yog=gajakesari_yog,budh_aditya_yog&page_size=200", headers=headers_admin)
                check("24: list+summary with a Yog filter issues a small, CONSTANT number of SQL statements "
                      f"(observed {query_count['n']}), never one-per-row despite {len(r_n1.get_json()['users'])} rows returned",
                      query_count["n"] <= 10)
            finally:
                event.remove(Engine, "before_cursor_execute", _count_queries)

            # ==========================================================
            print("\n=== 25: default list ordering -- created_at DESC, id DESC tie-break ===")
            # ==========================================================
            expected_order = [U_ORD_NEWEST, U_ORD_TIE_B, U_ORD_TIE_A, U_ORD_MIDDLE, U_ORD_OLDEST]

            r_ord = client.get("/admin/api/users?search=OrderMarker&page_size=200", headers=headers_admin)
            ord_ids = [u["id"] for u in r_ord.get_json()["users"]]
            check("25: exactly the 5 OrderMarker fixtures returned in the expected newest-first order",
                  ord_ids == expected_order)
            check("25: newest signup appears first", ord_ids[0] == U_ORD_NEWEST)
            check("25: oldest signup appears last", ord_ids[-1] == U_ORD_OLDEST)
            check("25: equal created_at ties broken by id DESC (TieB before TieA)",
                  ord_ids.index(U_ORD_TIE_B) < ord_ids.index(U_ORD_TIE_A))

            # Pagination must preserve this exact ordering -- concatenating
            # every page (page_size=2) must reproduce the same sequence
            # with no gaps/duplicates/reordering across the page boundary.
            paged_ids = []
            for pg in (1, 2, 3):
                r_pg = client.get(f"/admin/api/users?search=OrderMarker&page={pg}&page_size=2", headers=headers_admin)
                paged_ids.extend(u["id"] for u in r_pg.get_json()["users"])
            check("25: pagination (page_size=2, 3 pages) preserves the exact same ordering",
                  paged_ids == expected_order)

            # Search/filter combined with the new default order still works.
            r_ord_search_narrow = client.get("/admin/api/users?search=OrderMarker+Tie&page_size=200", headers=headers_admin)
            narrow_ids = [u["id"] for u in r_ord_search_narrow.get_json()["users"]]
            check("25: a narrower search still applies correctly under the new ordering",
                  narrow_ids == [U_ORD_TIE_B, U_ORD_TIE_A])

            print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
        finally:
            cleanup()

    return failed == 0


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
