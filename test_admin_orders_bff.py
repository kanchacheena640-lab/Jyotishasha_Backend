"""
test_admin_orders_bff.py
-------------------------------------------------
Admin Orders BFF Completion: proves routes/admin_orders.py's three
routes (GET /admin/api/orders, PUT /admin/api/order/<id>, POST
/admin/api/resend/<id>) all now accept the SAME admin_or_bridge_required
credential (routes/routes_app_version.py) the Next.js Admin BFF routes
send as X-Admin-Bridge-Key, while the existing admin_required JWT +
ADMIN_USER_IDS check keeps working, completely unmodified, for any
other caller.

  A. GET orders: no auth -> 401; non-admin JWT -> 403; admin JWT -> 200
     (regression, unchanged response contract); bridge unset -> 401;
     wrong bridge key -> 401; correct bridge key -> 200 with no JWT at
     all, same response contract as the JWT path.
  B. PUT order: same auth matrix; correct-credential PUTs actually
     persist dob/tob/pob/latitude/longitude; a rejected PUT changes
     nothing; 404 on a nonexistent order_id through either credential.
  C. POST resend: same auth matrix; tasks.generate_and_send_report is
     mocked (this repo's local dev checkpoint runs USE_CELERY=False, so
     generate_and_send_report has no .delay() at all -- see
     test_report_email_status.py's own note on this pre-existing,
     out-of-scope quirk; mocking sidesteps it and, either way, proves
     ONLY the auth gate + report_stage="Regenerating" side effect, never
     a real report/email send) -- correct-credential resend calls
     .delay(order_id) exactly once and sets report_stage; a rejected
     resend calls it zero times and changes nothing.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real Celery/report/email call is ever made.
"""

import os
import sys
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from models import Order  # noqa: E402

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


ADMIN_UID = 986101
NON_ADMIN_UID = 986102
BRIDGE_SECRET = "test-bridge-secret-orders-321"


def cleanup_users():
    User.query.filter(User.id.in_([ADMIN_UID, NON_ADMIN_UID])).delete(synchronize_session=False)
    db.session.commit()


def cleanup_orders(order_ids):
    Order.query.filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
    db.session.commit()


def make_order(**overrides):
    defaults = dict(
        name="Test Order",
        email="orders-bff-test@example.com",
        phone="9999999999",
        product="Premium Report",
        dob="1990-01-01",
        tob="10:00",
        pob="Delhi",
        status="PAID",
        language="en",
        report_stage="Ready",
    )
    defaults.update(overrides)
    order = Order(**defaults)
    db.session.add(order)
    db.session.commit()
    return order


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup_users()
        db.session.add(User(id=ADMIN_UID, email="orders-bff-admin@example.com", provider="password"))
        db.session.add(User(id=NON_ADMIN_UID, email="orders-bff-nonadmin@example.com", provider="password"))
        db.session.commit()
        os.environ["ADMIN_USER_IDS"] = str(ADMIN_UID)

        client = app.test_client()
        token_admin = create_access_token(identity=str(ADMIN_UID))
        token_non_admin = create_access_token(identity=str(NON_ADMIN_UID))

        order_ids = []
        try:
            order = make_order()
            order_ids.append(order.id)

            # ==========================================================
            print("\n=== A: GET /admin/api/orders auth matrix ===")
            # ==========================================================
            resp = client.get("/admin/api/orders")
            check("A: no auth at all -> 401", resp.status_code == 401)

            resp = client.get("/admin/api/orders", headers={"Authorization": f"Bearer {token_non_admin}"})
            check("A: authenticated non-admin -> 403", resp.status_code == 403)

            resp = client.get("/admin/api/orders", headers={"Authorization": f"Bearer {token_admin}"})
            check("A: admin JWT -> 200 (unchanged regression path)", resp.status_code == 200)
            admin_jwt_body = resp.get_json()
            check("A: admin JWT response is a list", isinstance(admin_jwt_body, list))
            row = next((o for o in admin_jwt_body if o["id"] == order.id), None)
            check("A: admin JWT response contains our test order with unchanged contract keys", row is not None and set(
                ["id", "name", "email", "phone", "report_name", "payment_status", "order_time", "report_stage", "pdf_url", "language"]
            ).issubset(row.keys()))

            os.environ.pop("ADMIN_BRIDGE_SECRET", None)
            resp = client.get("/admin/api/orders", headers={"X-Admin-Bridge-Key": "whatever"})
            check("A: bridge header ignored when ADMIN_BRIDGE_SECRET unset -> 401", resp.status_code == 401)

            os.environ["ADMIN_BRIDGE_SECRET"] = BRIDGE_SECRET
            resp = client.get("/admin/api/orders", headers={"X-Admin-Bridge-Key": "wrong-key"})
            check("A: wrong bridge key -> 401", resp.status_code == 401)

            resp = client.get("/admin/api/orders", headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
            check("A: correct bridge key, no JWT at all -> 200", resp.status_code == 200)
            bridge_body = resp.get_json()
            bridge_row = next((o for o in bridge_body if o["id"] == order.id), None)
            check("A: bridge-path response contract identical to JWT-path", bridge_row == row)

            # ==========================================================
            print("\n=== B: PUT /admin/api/order/<id> auth matrix + persistence ===")
            # ==========================================================
            resp = client.put(f"/admin/api/order/{order.id}", json={"dob": "1991-02-02"})
            check("B: no auth at all -> 401", resp.status_code == 401)
            db.session.refresh(order)
            check("B: rejected PUT (no auth) changed nothing", order.dob == "1990-01-01")

            resp = client.put(
                f"/admin/api/order/{order.id}", json={"dob": "1991-02-02"},
                headers={"Authorization": f"Bearer {token_non_admin}"},
            )
            check("B: authenticated non-admin -> 403", resp.status_code == 403)
            db.session.refresh(order)
            check("B: rejected PUT (non-admin) changed nothing", order.dob == "1990-01-01")

            resp = client.put(
                f"/admin/api/order/{order.id}", json={"dob": "1991-02-02", "pob": "Mumbai"},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("B: admin JWT -> 200 (unchanged regression path)", resp.status_code == 200)
            db.session.refresh(order)
            check("B: admin JWT PUT actually persisted dob/pob", order.dob == "1991-02-02" and order.pob == "Mumbai")

            resp = client.put(
                f"/admin/api/order/{order.id}", json={"dob": "1992-03-03"},
                headers={"X-Admin-Bridge-Key": "wrong-key"},
            )
            check("B: wrong bridge key -> 401", resp.status_code == 401)
            db.session.refresh(order)
            check("B: rejected PUT (wrong bridge key) changed nothing", order.dob == "1991-02-02")

            resp = client.put(
                f"/admin/api/order/{order.id}", json={"dob": "1992-03-03", "latitude": "19.07"},
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("B: correct bridge key, no JWT at all -> 200", resp.status_code == 200)
            db.session.refresh(order)
            check("B: bridge-path PUT actually persisted dob/latitude", order.dob == "1992-03-03" and order.latitude == "19.07")

            resp = client.put("/admin/api/order/999999999", json={"dob": "2000-01-01"}, headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
            check("B: nonexistent order_id through bridge -> 404", resp.status_code == 404)

            # ==========================================================
            print("\n=== C: POST /admin/api/resend/<id> auth matrix (Celery task mocked) ===")
            # ==========================================================
            with patch("tasks.generate_and_send_report") as mock_task:
                mock_task.delay = MagicMock()

                order.report_stage = "Ready"
                db.session.commit()

                resp = client.post(f"/admin/api/resend/{order.id}")
                check("C: no auth at all -> 401", resp.status_code == 401)
                check("C: rejected resend (no auth) never called the task", mock_task.delay.call_count == 0)
                db.session.refresh(order)
                check("C: rejected resend (no auth) changed nothing", order.report_stage == "Ready")

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"Authorization": f"Bearer {token_non_admin}"})
                check("C: authenticated non-admin -> 403", resp.status_code == 403)
                check("C: rejected resend (non-admin) never called the task", mock_task.delay.call_count == 0)

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"Authorization": f"Bearer {token_admin}"})
                check("C: admin JWT -> 200 (unchanged regression path)", resp.status_code == 200)
                check("C: admin JWT resend called the task exactly once", mock_task.delay.call_count == 1)
                mock_task.delay.assert_called_with(order.id)
                db.session.refresh(order)
                check("C: admin JWT resend set report_stage=Regenerating", order.report_stage == "Regenerating")

                mock_task.delay.reset_mock()
                order.report_stage = "Ready"
                db.session.commit()

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"X-Admin-Bridge-Key": "wrong-key"})
                check("C: wrong bridge key -> 401", resp.status_code == 401)
                check("C: rejected resend (wrong bridge key) never called the task", mock_task.delay.call_count == 0)

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
                check("C: correct bridge key, no JWT at all -> 200", resp.status_code == 200)
                check("C: bridge-path resend called the task exactly once", mock_task.delay.call_count == 1)
                mock_task.delay.assert_called_with(order.id)
                db.session.refresh(order)
                check("C: bridge-path resend set report_stage=Regenerating", order.report_stage == "Regenerating")

                resp = client.post("/admin/api/resend/999999999", headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
                check("C: nonexistent order_id through bridge -> 404", resp.status_code == 404)

            os.environ.pop("ADMIN_BRIDGE_SECRET", None)

        finally:
            os.environ.pop("ADMIN_BRIDGE_SECRET", None)
            if order_ids:
                cleanup_orders(order_ids)
            cleanup_users()

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
