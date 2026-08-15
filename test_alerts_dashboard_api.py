"""
test_alerts_dashboard_api.py
-------------------------------
Local-only entry point for the "Alerts & Opportunities" subscription
API (routes/routes_alerts_dashboard.py -- GET /api/alerts/current).

Exercises the route through Flask's real test client, with a real JWT
(flask_jwt_extended.create_access_token), exactly the way a Flutter
client would call it. Uses the LOCAL scratch Postgres DB ONLY, same
convention as every other test_alerts_*.py script. No FCM call is
possible from this endpoint at all (it never sends anything), so
nothing needs monkeypatching there.

Covers, in order:
  1. Auth failure -- no token -> 401
  2. No profile associated with the authenticated account -> 403 no_profile
  3. Cross-account profile_id in the query string -> 403 forbidden
  4. Locked -- Prime with a different section selected (not Alerts) -> 403 locked
  5. Locked -- expired subscription -> 403 locked
  6. Success, zero current alerts -- Prime+Alerts selected, nothing active -> 200, []
  7. Success, one current alert -- exact response field contract, no
     confidence/state/internal fields ever present
  8. Success, two current alerts (max cap) from a 4-candidate pool --
     raw candidates never exposed, only the selected <=2 returned
  9. Trial grants Alerts access (no selected_segment needed)
  10. Prime Plus (ACCESS_ALL) grants Alerts access (no selected_segment needed)
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
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.alerts.persistence_repository import AlertPersistenceRepository  # noqa: E402

# Distinct profile/user id range -- not used by any other test_*.py
# fixture in this repo (avoids the exact cross-test DB-pollution
# pattern already hit once this session).
U_NO_PROFILE = 98010
U_NORMAL = 98011      # backs every "normal owner" scenario below (owns P_ZERO)
U_ONE = 98012          # owns P_ONE
U_MULTI = 98013        # owns P_MULTI
U_TRIAL = 98014        # owns P_TRIAL
U_PRIME_PLUS = 98015   # owns P_PRIME_PLUS
U_WRONG_SEGMENT = 98016
U_EXPIRED = 98017

P_CROSS_TARGET = 98021   # a real profile U_NORMAL does NOT own
P_LOCKED_WRONG_SEGMENT = 98022
P_LOCKED_EXPIRED = 98023
P_ZERO = 98024
P_ONE = 98025
P_MULTI = 98026
P_TRIAL = 98027
P_PRIME_PLUS = 98028

ALL_PROFILES = (
    P_CROSS_TARGET, P_LOCKED_WRONG_SEGMENT, P_LOCKED_EXPIRED, P_ZERO,
    P_ONE, P_MULTI, P_TRIAL, P_PRIME_PLUS,
)
ALL_USERS = (
    U_NO_PROFILE, U_NORMAL, U_ONE, U_MULTI, U_TRIAL, U_PRIME_PLUS,
    U_WRONG_SEGMENT, U_EXPIRED,
)

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
    for p in ALL_PROFILES:
        db.session.execute(text("DELETE FROM alert_micro_events WHERE profile_id = :p"), {"p": p})
        db.session.execute(text("DELETE FROM current_entitlements WHERE profile_id = :p"), {"p": p})
        db.session.execute(text("DELETE FROM app_users WHERE id = :p"), {"p": p})
    for u in ALL_USERS:
        db.session.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
    db.session.commit()


def seed_alert(repo, profile_id, event_id, category, severity, priority, confidence, evaluated_at):
    repo.save_detection(
        profile_id=profile_id, event_id=event_id, category=category,
        state="NEW", confidence=confidence, priority=priority,
        active_from=date(evaluated_at.year, evaluated_at.month, evaluated_at.day),
        active_until=date(evaluated_at.year, evaluated_at.month, evaluated_at.day) + timedelta(days=1),
        evaluated_at=evaluated_at,
    )
    row = repo.read(profile_id=profile_id, event_id=event_id)
    row.severity = severity
    db.session.commit()


def link(conn, user_id, profile_id, email):
    fb = f"fb-dashboard-{user_id}"
    conn.execute(text(
        "INSERT INTO users (id, email, provider, firebase_uid) VALUES (:id, :email, 'password', :fb)"
    ), {"id": user_id, "email": email, "fb": fb})
    conn.execute(text("UPDATE app_users SET firebase_uid = :fb WHERE id = :p"), {"fb": fb, "p": profile_id})


def bearer(user_id):
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()

        with db.engine.connect() as conn:
            for p in ALL_PROFILES:
                conn.execute(text(
                    "INSERT INTO app_users (id, tz, subscription, asknow_tokens, fcm_token) "
                    "VALUES (:id, 'IST', 'free', 0, 'tok')"
                ), {"id": p})
            conn.commit()

        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, provider, firebase_uid) "
                "VALUES (:id, :email, 'password', NULL)"
            ), {"id": U_NO_PROFILE, "email": "dashboard-api-no-profile@test.local"})
            link(conn, U_NORMAL, P_ZERO, "dashboard-api-normal@test.local")
            link(conn, U_ONE, P_ONE, "dashboard-api-one@test.local")
            link(conn, U_MULTI, P_MULTI, "dashboard-api-multi@test.local")
            link(conn, U_TRIAL, P_TRIAL, "dashboard-api-trial@test.local")
            link(conn, U_PRIME_PLUS, P_PRIME_PLUS, "dashboard-api-primeplus@test.local")
            link(conn, U_WRONG_SEGMENT, P_LOCKED_WRONG_SEGMENT, "dashboard-api-wrongseg@test.local")
            link(conn, U_EXPIRED, P_LOCKED_EXPIRED, "dashboard-api-expired@test.local")
            conn.commit()

        now = datetime(2026, 8, 15, 12, 0, 0)
        with db.engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO current_entitlements "
                "(profile_id, status, plan, selected_segment, subscription_started_at, subscription_expires_at, created_at, updated_at) "
                "VALUES (:p, 'ACTIVE', 'PRIME_MONTHLY', 'LOVE', :s, :e, now(), now())"
            ), {"p": P_LOCKED_WRONG_SEGMENT, "s": now - timedelta(days=1), "e": now + timedelta(days=29)})
            conn.execute(text(
                "INSERT INTO current_entitlements "
                "(profile_id, status, plan, selected_segment, subscription_started_at, subscription_expires_at, created_at, updated_at) "
                "VALUES (:p, 'EXPIRED', 'PRIME_MONTHLY', 'ALERTS', :s, :e, now(), now())"
            ), {"p": P_LOCKED_EXPIRED, "s": now - timedelta(days=60), "e": now - timedelta(days=30)})
            conn.execute(text(
                "INSERT INTO current_entitlements "
                "(profile_id, status, plan, selected_segment, subscription_started_at, subscription_expires_at, created_at, updated_at) "
                "VALUES (:p, 'ACTIVE', 'PRIME_MONTHLY', 'ALERTS', :s, :e, now(), now())"
            ), {"p": P_ZERO, "s": now - timedelta(days=1), "e": now + timedelta(days=29)})
            conn.execute(text(
                "INSERT INTO current_entitlements "
                "(profile_id, status, plan, selected_segment, subscription_started_at, subscription_expires_at, created_at, updated_at) "
                "VALUES (:p, 'ACTIVE', 'PRIME_MONTHLY', 'ALERTS', :s, :e, now(), now())"
            ), {"p": P_ONE, "s": now - timedelta(days=1), "e": now + timedelta(days=29)})
            conn.execute(text(
                "INSERT INTO current_entitlements "
                "(profile_id, status, trial_started_at, trial_expires_at, created_at, updated_at) "
                "VALUES (:p, 'TRIAL', :s, :e, now(), now())"
            ), {"p": P_MULTI, "s": now - timedelta(days=1), "e": now + timedelta(days=6)})
            conn.execute(text(
                "INSERT INTO current_entitlements "
                "(profile_id, status, trial_started_at, trial_expires_at, created_at, updated_at) "
                "VALUES (:p, 'TRIAL', :s, :e, now(), now())"
            ), {"p": P_TRIAL, "s": now - timedelta(days=1), "e": now + timedelta(days=6)})
            conn.execute(text(
                "INSERT INTO current_entitlements "
                "(profile_id, status, plan, subscription_started_at, subscription_expires_at, created_at, updated_at) "
                "VALUES (:p, 'ACTIVE', 'PRIME_PLUS_MONTHLY', :s, :e, now(), now())"
            ), {"p": P_PRIME_PLUS, "s": now - timedelta(days=1), "e": now + timedelta(days=29)})
            conn.commit()

        repo = AlertPersistenceRepository()

        # One eligible alert for P_ONE.
        seed_alert(repo, P_ONE, "financial_gain_opportunity", "financial", "HIGH", "high", 0.9, now)

        # Four eligible, non-conflicting-enough candidates for P_MULTI --
        # selection must still narrow to <=2.
        seed_alert(repo, P_MULTI, "financial_gain_opportunity", "financial", "HIGH", "high", 0.9, now)
        seed_alert(repo, P_MULTI, "mood_positive", "emotional", "LOW", "high", 0.85, now)
        seed_alert(repo, P_MULTI, "travel_opportunity", "travel", "LOW", "medium", 0.6, now)
        seed_alert(repo, P_MULTI, "foreign_travel_opportunity", "travel", "LOW", "medium", 0.55, now)

        # One eligible alert for P_TRIAL and P_PRIME_PLUS (entitlement-path checks only).
        seed_alert(repo, P_TRIAL, "financial_gain_opportunity", "financial", "HIGH", "high", 0.9, now)
        seed_alert(repo, P_PRIME_PLUS, "financial_gain_opportunity", "financial", "HIGH", "high", 0.9, now)

        client = app.test_client()

        print("\n=== Test 1: auth failure -- no token ===")
        resp = client.get("/api/alerts/current")
        check("no token -> 401", resp.status_code == 401)

        print("\n=== Test 2: no profile associated with this account ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_NO_PROFILE))
        body = resp.get_json()
        check("no profile -> 403", resp.status_code == 403)
        check("no profile -> status=no_profile", body.get("status") == "no_profile")

        print("\n=== Test 3: cross-account profile_id rejected ===")
        resp = client.get(
            f"/api/alerts/current?profile_id={P_CROSS_TARGET}", headers=bearer(U_NORMAL),
        )
        body = resp.get_json()
        check("cross-account profile_id -> 403", resp.status_code == 403)
        check("cross-account profile_id -> status=forbidden", body.get("status") == "forbidden")

        print("\n=== Test 4: locked -- Prime with a different section selected ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_WRONG_SEGMENT))
        body = resp.get_json()
        check("wrong segment -> 403", resp.status_code == 403)
        check("wrong segment -> status=locked", body.get("status") == "locked")

        print("\n=== Test 5: locked -- expired subscription ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_EXPIRED))
        body = resp.get_json()
        check("expired -> 403", resp.status_code == 403)
        check("expired -> status=locked", body.get("status") == "locked")

        print("\n=== Test 6: success, zero current alerts ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_NORMAL))
        body = resp.get_json()
        check("zero alerts -> 200", resp.status_code == 200)
        check("zero alerts -> status=success", body.get("status") == "success")
        check("zero alerts -> alerts=[]", body.get("alerts") == [])

        print("\n=== Test 7: success, one current alert -- exact field contract ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_ONE))
        body = resp.get_json()
        check("one alert -> 200", resp.status_code == 200)
        alerts = body.get("alerts", [])
        check("exactly 1 alert returned", len(alerts) == 1)
        if alerts:
            item = alerts[0]
            expected_keys = {
                "alert_id", "event_id", "title", "message", "category",
                "severity", "priority", "valid_from", "valid_until",
            }
            check("response keys are exactly the minimal contract (no more, no less)", set(item.keys()) == expected_keys)
            check("no 'confidence' key ever present", "confidence" not in item)
            check("no 'state' key ever present", "state" not in item)
            check("no DOB/TOB/POB/lat/lng key ever present", not ({"dob", "tob", "pob", "lat", "lng"} & set(item.keys())))
            check("event_id correct", item["event_id"] == "financial_gain_opportunity")
            check("title is the catalog title, not a raw internal name", item["title"] == "Financial Gain Opportunity")
            check("category correct", item["category"] == "financial")
            check("severity correct", item["severity"] == "HIGH")

        print("\n=== Test 8: success, two current alerts from a 4-candidate pool ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_MULTI))
        body = resp.get_json()
        check("multi-candidate -> 200", resp.status_code == 200)
        alerts = body.get("alerts", [])
        check("raw candidates never dumped -- at most 2 of the 4 real candidates returned", len(alerts) <= 2)
        check("at least 1 alert returned (a real strong candidate exists)", len(alerts) >= 1)
        returned_ids = {a["event_id"] for a in alerts}
        check("selected ids are a real subset of the 4 seeded candidates", returned_ids <= {
            "financial_gain_opportunity", "mood_positive", "travel_opportunity", "foreign_travel_opportunity",
        })
        check("strongest candidate (financial_gain_opportunity) is selected", "financial_gain_opportunity" in returned_ids)

        print("\n=== Test 9: trial grants Alerts access (no selected_segment needed) ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_TRIAL))
        body = resp.get_json()
        check("trial -> 200", resp.status_code == 200)
        check("trial -> status=success", body.get("status") == "success")
        check("trial -> alert present", len(body.get("alerts", [])) == 1)

        print("\n=== Test 10: Prime Plus (ACCESS_ALL) grants Alerts access ===")
        resp = client.get("/api/alerts/current", headers=bearer(U_PRIME_PLUS))
        body = resp.get_json()
        check("prime plus -> 200", resp.status_code == 200)
        check("prime plus -> status=success", body.get("status") == "success")
        check("prime plus -> alert present", len(body.get("alerts", [])) == 1)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
