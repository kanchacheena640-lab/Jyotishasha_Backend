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
  C. POST resend: same auth matrix; ReconciliationService is mocked so
     this remains an auth/route-contract test and never starts a real
     report. Correct credentials call retry_delivery(order_id); rejected
     requests never cross that boundary, and the route itself invents
     no report stage.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real Celery/report/email call is ever made.
"""

import os
import sys
from types import SimpleNamespace
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
        payment_status="PAID",
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

            resp = client.get(f"/admin/download/{order.id}")
            check("A: report download without auth -> 401", resp.status_code == 401)
            resp = client.get(
                f"/admin/download/{order.id}",
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("A: authorized report download reaches resource lookup", resp.status_code == 404)

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

            # Admin Orders P0 fix: update_order() now rejects a CHANGED pob
            # that isn't accompanied by a valid lat/long pair (stale-
            # coordinate guard) -- a real place selection always supplies
            # BOTH together, so this fixture does too.
            resp = client.put(
                f"/admin/api/order/{order.id}",
                json={"dob": "1991-02-02", "pob": "Mumbai", "latitude": "19.076", "longitude": "72.8777"},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("B: admin JWT -> 200 (unchanged regression path)", resp.status_code == 200)
            db.session.refresh(order)
            check(
                "B: admin JWT PUT actually persisted dob/pob/latitude/longitude",
                order.dob == "1991-02-02" and order.pob == "Mumbai"
                and order.latitude == "19.076" and order.longitude == "72.8777",
            )

            # A changed pob with NO coordinates at all -- exactly the stale-
            # coordinate mismatch the P0 fix exists to prevent -- is a 400,
            # and leaves the order completely untouched.
            resp = client.put(
                f"/admin/api/order/{order.id}", json={"pob": "Kolkata"},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("B: changed pob with no lat/long -> 400 invalid_place", resp.status_code == 400 and resp.get_json().get("error") == "invalid_place")
            db.session.refresh(order)
            check("B: rejected place-only PUT changed nothing", order.pob == "Mumbai" and order.latitude == "19.076")

            # An UNCHANGED pob (identical to what's already stored) is never
            # blocked by the guard, even with no lat/long in the request.
            resp = client.put(
                f"/admin/api/order/{order.id}", json={"dob": "1991-02-03", "pob": "Mumbai"},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("B: unchanged pob (no lat/long in request) -> 200, not blocked", resp.status_code == 200)
            db.session.refresh(order)
            check("B: unchanged-pob PUT persisted dob, left latitude untouched", order.dob == "1991-02-03" and order.latitude == "19.076")

            # Reset dob back to the value the rest of this test's B section expects next.
            resp = client.put(
                f"/admin/api/order/{order.id}", json={"dob": "1991-02-02"},
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            check("B: dob-only reset for the rest of section B -> 200", resp.status_code == 200)

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
            print("\n=== B2: NULL/empty/real coordinate preservation on an unchanged place ===")
            # NULL Coordinate Preservation Fix: OrderList.tsx now omits
            # latitude/longitude from the PUT body entirely for an
            # unchanged place, relying on update_order()'s own
            # data.get("latitude", order.latitude) default to leave
            # whatever is already stored completely untouched. These three
            # dedicated fixtures prove the ENDPOINT side of that contract
            # for each starting representation, independent of the
            # frontend -- an omitted key must never be coerced into any
            # other representation.
            # ==========================================================
            null_order = make_order(latitude=None, longitude=None)
            order_ids.append(null_order.id)
            resp = client.put(
                f"/admin/api/order/{null_order.id}", json={"dob": "1993-04-04", "pob": null_order.pob},
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("B2: unchanged pob, coordinates OMITTED, starting NULL -> 200", resp.status_code == 200)
            db.session.refresh(null_order)
            check("B2: NULL latitude/longitude remain exactly NULL (never coerced to \"\")", null_order.latitude is None and null_order.longitude is None)
            check("B2: dob still persisted normally alongside the preserved NULL coordinates", null_order.dob == "1993-04-04")

            empty_order = make_order(latitude="", longitude="")
            order_ids.append(empty_order.id)
            resp = client.put(
                f"/admin/api/order/{empty_order.id}", json={"dob": "1993-04-05", "pob": empty_order.pob},
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("B2: unchanged pob, coordinates OMITTED, starting \"\" -> 200", resp.status_code == 200)
            db.session.refresh(empty_order)
            check("B2: \"\" latitude/longitude remain exactly \"\" (not normalized to NULL or anything else)", empty_order.latitude == "" and empty_order.longitude == "")

            real_coord_order = make_order(latitude="19.0760", longitude="72.8777")
            order_ids.append(real_coord_order.id)
            resp = client.put(
                f"/admin/api/order/{real_coord_order.id}", json={"dob": "1993-04-06", "pob": real_coord_order.pob},
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("B2: unchanged pob, coordinates OMITTED, starting real values -> 200", resp.status_code == 200)
            db.session.refresh(real_coord_order)
            check(
                "B2: existing real latitude/longitude preserved byte-for-byte (no float round-trip, no re-formatting)",
                real_coord_order.latitude == "19.0760" and real_coord_order.longitude == "72.8777",
            )

            # A CHANGED pob with no resolved coordinates must still be
            # blocked exactly as before -- this fix never weakens that rule.
            resp = client.put(
                f"/admin/api/order/{real_coord_order.id}", json={"pob": "A Different City"},
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("B2: changed pob with no coordinates in the payload -> still 400 invalid_place (rule not weakened)", resp.status_code == 400 and resp.get_json().get("error") == "invalid_place")
            db.session.refresh(real_coord_order)
            check("B2: rejected changed-pob attempt left the order untouched", real_coord_order.pob != "A Different City" and real_coord_order.latitude == "19.0760")

            # A CHANGED pob WITH freshly-resolved coordinates (the autocomplete path) still works normally.
            resp = client.put(
                f"/admin/api/order/{real_coord_order.id}",
                json={"pob": "Pune, Maharashtra, India", "latitude": "18.5204", "longitude": "73.8567"},
                headers={"X-Admin-Bridge-Key": BRIDGE_SECRET},
            )
            check("B2: changed pob WITH valid new coordinates -> 200 (fresh-selection path unaffected)", resp.status_code == 200)
            db.session.refresh(real_coord_order)
            check(
                "B2: the new place and its freshly-resolved coordinates were persisted together",
                real_coord_order.pob == "Pune, Maharashtra, India" and real_coord_order.latitude == "18.5204" and real_coord_order.longitude == "73.8567",
            )

            # ==========================================================
            print("\n=== C: POST /admin/api/resend/<id> auth matrix (reconciliation mocked) ===")
            # ==========================================================
            with patch("routes.admin_orders.ReconciliationService") as mock_service_cls:
                mock_service = mock_service_cls.return_value
                success = SimpleNamespace(
                    resumed=True, task_id=None,
                    decision=SimpleNamespace(report_stage="Ready", reason="claimed"),
                )
                mock_service.retry_delivery.return_value = success

                order.report_stage = "Ready"
                db.session.commit()

                resp = client.post(f"/admin/api/resend/{order.id}")
                check("C: no auth at all -> 401", resp.status_code == 401)
                check("C: rejected resend (no auth) never called reconciliation", mock_service.retry_delivery.call_count == 0)
                db.session.refresh(order)
                check("C: rejected resend (no auth) changed nothing", order.report_stage == "Ready")

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"Authorization": f"Bearer {token_non_admin}"})
                check("C: authenticated non-admin -> 403", resp.status_code == 403)
                check("C: rejected resend (non-admin) never called reconciliation", mock_service.retry_delivery.call_count == 0)

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"Authorization": f"Bearer {token_admin}"})
                check("C: admin JWT -> 200 (unchanged regression path)", resp.status_code == 200)
                check("C: admin JWT resend called reconciliation exactly once", mock_service.retry_delivery.call_count == 1)
                mock_service.retry_delivery.assert_called_with(order.id)
                db.session.refresh(order)
                check("C: route itself does not invent a report stage", order.report_stage == "Ready")

                mock_service.retry_delivery.reset_mock()
                order.report_stage = "Ready"
                db.session.commit()

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"X-Admin-Bridge-Key": "wrong-key"})
                check("C: wrong bridge key -> 401", resp.status_code == 401)
                check("C: rejected resend (wrong bridge key) never called reconciliation", mock_service.retry_delivery.call_count == 0)

                resp = client.post(f"/admin/api/resend/{order.id}", headers={"X-Admin-Bridge-Key": BRIDGE_SECRET})
                check("C: correct bridge key, no JWT at all -> 200", resp.status_code == 200)
                check("C: bridge-path resend called reconciliation exactly once", mock_service.retry_delivery.call_count == 1)
                mock_service.retry_delivery.assert_called_with(order.id)
                db.session.refresh(order)
                check("C: bridge route itself does not invent a report stage", order.report_stage == "Ready")

                mock_service.retry_delivery.return_value = SimpleNamespace(
                    resumed=False, task_id=None,
                    decision=SimpleNamespace(report_stage=None, reason="No Order exists"),
                )
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
