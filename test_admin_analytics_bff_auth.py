"""
test_admin_analytics_bff_auth.py
-------------------------------------------------
Admin Analytics A1 (Access Layer): proves routes/routes_analytics.py's
6 endpoints and routes/routes_website_analytics.py's 2 endpoints all
now accept the SAME admin_or_bridge_required credential
(routes/routes_app_version.py) the Next.js Admin BFF sends as
X-Admin-Bridge-Key, while the existing admin_required JWT +
ADMIN_USER_IDS check keeps working, completely unmodified, for any
other caller -- exactly the same auth matrix test_admin_orders_bff.py
already established for Admin Orders.

This test proves ONLY the auth gate + unchanged response contract. It
does not re-verify metric math (that is analytics_service.py's/
website_analytics_service.py's own test suite's job, untouched by A1).

  A. GET /admin/api/analytics/overview auth matrix: no auth -> 401;
     non-admin JWT -> 403; admin JWT -> 200 (regression, unchanged
     response contract); bridge unset -> 401; wrong bridge key -> 401;
     correct bridge key -> 200, response body IDENTICAL to the JWT path
     (same window, same data).
  B. Spot-check the remaining 5 routes/routes_analytics.py endpoints
     (engagement/asknow/reports/subscriptions/notifications) each
     accept the bridge credential with no JWT at all -> 200.
  C. GET /admin/api/website-analytics/metrics/<metric_id> auth matrix:
     same shape as A, using metric_id=cta_clicks_total (QUALITY_READY,
     scalar, no dimension required) -- proves the SEPARATE blueprint
     also got the same fix.
  D. POST /admin/api/website-analytics/metrics/batch: bridge credential
     alone (no JWT) -> 200, unchanged response contract.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real OpenAI/FCM/Razorpay call is ever made.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("RAZORPAY_KEY_ID", "test-dummy-not-used")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test-dummy-not-used")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402

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


ADMIN_UID = 986201
NON_ADMIN_UID = 986202
BRIDGE_SECRET = "test-bridge-secret-analytics-654"


def cleanup_users():
    User.query.filter(User.id.in_([ADMIN_UID, NON_ADMIN_UID])).delete(synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup_users()
        db.session.add(User(id=ADMIN_UID, email="analytics-bff-admin@example.com", provider="password"))
        db.session.add(User(id=NON_ADMIN_UID, email="analytics-bff-nonadmin@example.com", provider="password"))
        db.session.commit()
        os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)

        client = app.test_client()
        token_admin = create_access_token(identity=str(ADMIN_UID))
        token_non_admin = create_access_token(identity=str(NON_ADMIN_UID))

        window_qs = "start=2020-01-01T00:00:00Z&end=2030-01-01T00:00:00Z"

        try:
            # ==========================================================
            print("\n=== A: GET /admin/api/analytics/overview auth matrix ===")
            # ==========================================================
            url = f"/admin/api/analytics/overview?{window_qs}"

            resp = client.get(url)
            check("A: no auth at all -> 401", resp.status_code == 401)

            resp = client.get(url, headers={"Authorization": f"Bearer {token_non_admin}"})
            check("A: authenticated non-admin -> 403", resp.status_code == 403)

            resp = client.get(url, headers={"Authorization": f"Bearer {token_admin}"})
            check("A: admin JWT -> 200 (unchanged regression path)", resp.status_code == 200)
            admin_jwt_body = resp.get_json()
            check(
                "A: admin JWT response has unchanged contract shape",
                isinstance(admin_jwt_body, dict) and "data" in admin_jwt_body
                and set(["total_events", "unique_users", "app_sessions", "new_signups",
                          "interactive_logins", "dau", "wau", "mau"]).issubset(admin_jwt_body["data"].keys()),
            )

            os.environ.pop("ADMIN_BRIDGE_SECRET", None)
            resp = client.get(url, headers={"X-Admin-Bridge-Key": "whatever"})
            check("A: bridge header ignored when ADMIN_BRIDGE_SECRET unset -> 401", resp.status_code == 401)

            os.environ["ADMIN_BRIDGE_SECRET"] = BRIDGE_SECRET
            resp = client.get(url, headers={"X-Admin-Bridge-Key": "wrong-key"})
            check("A: wrong bridge key -> 401", resp.status_code == 401)

            resp = client.get(url, headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
            check("A: correct bridge key, no JWT at all -> 200", resp.status_code == 200)
            bridge_body = resp.get_json()
            check("A: bridge-path response contract identical to JWT-path", bridge_body == admin_jwt_body)

            # ==========================================================
            print("\n=== B: remaining routes_analytics.py endpoints accept bridge credential ===")
            # ==========================================================
            for path in ("engagement", "asknow", "reports", "subscriptions", "notifications"):
                resp = client.get(f"/admin/api/analytics/{path}?{window_qs}", headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
                check(f"B: /admin/api/analytics/{path} bridge credential -> 200", resp.status_code == 200)
                resp_no_auth = client.get(f"/admin/api/analytics/{path}?{window_qs}")
                check(f"B: /admin/api/analytics/{path} no auth -> 401 (still gated)", resp_no_auth.status_code == 401)

            # ==========================================================
            print("\n=== C: GET /admin/api/website-analytics/metrics/<metric_id> auth matrix ===")
            # ==========================================================
            metric_url = "/admin/api/website-analytics/metrics/cta_clicks_total?period=28d"

            resp = client.get(metric_url)
            check("C: no auth at all -> 401", resp.status_code == 401)

            resp = client.get(metric_url, headers={"Authorization": f"Bearer {token_non_admin}"})
            check("C: authenticated non-admin -> 403", resp.status_code == 403)

            resp = client.get(metric_url, headers={"Authorization": f"Bearer {token_admin}"})
            check("C: admin JWT -> 200 (unchanged regression path)", resp.status_code == 200)
            admin_metric_body = resp.get_json()
            check(
                "C: admin JWT response has unchanged contract shape",
                admin_metric_body.get("metric_id") == "cta_clicks_total" and "status" in admin_metric_body and "data" in admin_metric_body,
            )

            resp = client.get(metric_url, headers={"X-Admin-Bridge-Key": "wrong-key"})
            check("C: wrong bridge key -> 401", resp.status_code == 401)

            resp = client.get(metric_url, headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
            check("C: correct bridge key, no JWT at all -> 200", resp.status_code == 200)
            bridge_metric_body = resp.get_json()
            check(
                "C: bridge-path response contract identical to JWT-path (excluding volatile window bounds)",
                {k: v for k, v in bridge_metric_body.items() if k not in ("start", "end")}
                == {k: v for k, v in admin_metric_body.items() if k not in ("start", "end")},
            )

            # ==========================================================
            print("\n=== D: POST /admin/api/website-analytics/metrics/batch bridge credential ===")
            # ==========================================================
            resp = client.post(
                "/admin/api/website-analytics/metrics/batch",
                json={"period": "28d", "metrics": [{"metric_id": "cta_clicks_total"}]},
            )
            check("D: no auth at all -> 401", resp.status_code == 401)

            resp = client.post(
                "/admin/api/website-analytics/metrics/batch",
                json={"period": "28d", "metrics": [{"metric_id": "cta_clicks_total"}]},
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("D: correct bridge key, no JWT at all -> 200", resp.status_code == 200)
            batch_body = resp.get_json()
            check(
                "D: batch response has unchanged contract shape",
                isinstance(batch_body.get("results"), list) and batch_body["results"][0].get("metric_id") == "cta_clicks_total",
            )

            os.environ.pop("ADMIN_BRIDGE_SECRET", None)

        finally:
            os.environ.pop("ADMIN_BRIDGE_SECRET", None)
            cleanup_users()

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
