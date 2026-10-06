"""
test_report_platform_r3_pending_order.py
-------------------------------------------------
Paid Report Platform v1.0 -- R3 (Pre-Payment Order Service).

Proves OrderService.create_pending_order() persists a COMPLETE report
Order before any payment, validates every proven-required field for
both generators (standard_v1 and love_premium_v1), never leaves a
partial row on rejection, and never mutates the existing, unmodified
create_paid_report_order() path.

No route, PaymentService, app.py, or frontend code is touched or
exercised here -- this is OrderService-level only, per R3's own scope.
LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from models import Order  # noqa: E402
from modules.payments.report_product_registry import ReportProduct  # noqa: E402
from modules.payments.order_service import OrderService, OrderValidationError  # noqa: E402

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


STANDARD_SLUG = "startup_suggestion_report"
LOVE_SLUG = "relationship_future_report"
MARKER_EMAIL_PREFIX = "r3-pending-order-test"


def valid_standard_payload(**overrides):
    payload = {
        "product": STANDARD_SLUG,
        "name": "Suresh",
        "email": f"{MARKER_EMAIL_PREFIX}-standard@example.com",
        "phone": "9999999999",
        "dob": "1994-01-26",
        "tob": "08:40",
        "pob": "Sindhnur Rural",
        "latitude": "15.6167",
        "longitude": "76.6833",
        "language": "en",
    }
    payload.update(overrides)
    return payload


def valid_love_payload(**overrides):
    payload = {
        "product": LOVE_SLUG,
        "name": "Boy Name",
        "email": f"{MARKER_EMAIL_PREFIX}-love@example.com",
        "dob": "1990-05-01",
        "tob": "10:00",
        "pob": "Delhi",
        "latitude": 28.6139,
        "longitude": 77.2090,
        "language": "en",
        "partner": {
            "name": "Girl Name",
            "dob": "1992-08-15",
            "tob": "06:30",
            "pob": "Mumbai",
            "latitude": 19.0760,
            "longitude": 72.8777,
        },
    }
    payload.update(overrides)
    return payload


def cleanup():
    Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()


def count_orders_for_marker():
    return Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).count()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        service = OrderService()

        # ==============================================================
        print("\n=== 1-7: valid standard report -> exactly one correct pending Order ===")
        # ==============================================================
        order = service.create_pending_order(valid_standard_payload())
        db.session.refresh(order)
        check("1: exactly one Order created", count_orders_for_marker() == 1)
        check("2: all required customer/birth fields persisted correctly",
              order.name == "Suresh" and order.phone == "9999999999" and order.dob == "1994-01-26"
              and order.tob == "08:40" and order.pob == "Sindhnur Rural"
              and order.latitude == "15.6167" and order.longitude == "76.6833")
        check("3: canonical report_slug persisted in Order.product", order.product == STANDARD_SLUG)
        check("4: payment_status == CREATED", order.payment_status == "CREATED")
        check("5: report_stage == Pending", order.report_stage == "Pending")
        check("6: email_status == NOT_ATTEMPTED", order.email_status == "NOT_ATTEMPTED")
        check("7: razorpay_order_id/payment_id are NULL", order.razorpay_order_id is None and order.razorpay_payment_id is None)
        check("bonus: status == PENDING (existing backward-compatible pre-payment value)", order.status == "PENDING")
        cleanup()

        # ==============================================================
        print("\n=== 8-10: slug/product resolution rejections ===")
        # ==============================================================
        try:
            service.create_pending_order(valid_standard_payload(product=""))
            check("8: missing slug rejected", False)
        except OrderValidationError:
            check("8: missing slug rejected", True)
        check("8: zero Order created for missing slug", count_orders_for_marker() == 0)

        try:
            service.create_pending_order(valid_standard_payload(product="not_a_real_report_xyz"))
            check("9: unknown slug rejected", False)
        except OrderValidationError:
            check("9: unknown slug rejected", True)
        check("9: zero Order created for unknown slug", count_orders_for_marker() == 0)

        inactive_slug = "r3_test_inactive_product"
        ReportProduct.query.filter_by(report_slug=inactive_slug).delete(synchronize_session=False)
        db.session.commit()
        db.session.add(ReportProduct(
            report_slug=inactive_slug, name="Inactive Test Product", price=51,
            active=False, generator="standard_v1", prompt_template_id=inactive_slug,
        ))
        db.session.commit()
        try:
            service.create_pending_order(valid_standard_payload(product=inactive_slug))
            check("10: inactive product rejected", False)
        except OrderValidationError:
            check("10: inactive product rejected", True)
        check("10: zero Order created for inactive product", count_orders_for_marker() == 0)
        ReportProduct.query.filter_by(report_slug=inactive_slug).delete(synchronize_session=False)
        db.session.commit()

        # ==============================================================
        print("\n=== 11-13: required-field rejections (standard) ===")
        # ==============================================================
        try:
            service.create_pending_order(valid_standard_payload(name=""))
            check("11: missing name rejected", False)
        except OrderValidationError:
            check("11: missing name rejected", True)
        check("11: zero Order created", count_orders_for_marker() == 0)

        try:
            service.create_pending_order(valid_standard_payload(email=""))
            check("12: missing email rejected", False)
        except OrderValidationError:
            check("12: missing email rejected", True)
        check("12: zero Order created", count_orders_for_marker() == 0)

        for field in ("phone", "dob", "tob", "pob", "latitude", "longitude"):
            bad = valid_standard_payload()
            bad[field] = ""
            try:
                service.create_pending_order(bad)
                check(f"13: missing standard field '{field}' rejected", False)
            except OrderValidationError:
                check(f"13: missing standard field '{field}' rejected", True)
            check(f"13: zero Order created for missing '{field}'", count_orders_for_marker() == 0)

        # latitude=0 / longitude=0 must NOT be treated as missing (real,
        # valid coordinates -- the equator / prime meridian).
        zero_coords = valid_standard_payload(latitude=0, longitude=0)
        order = service.create_pending_order(zero_coords)
        check("13b: latitude/longitude of 0 are accepted as real values, not rejected as missing", order.id is not None)
        cleanup()

        # ==============================================================
        print("\n=== 14-16: relationship_future_report partner validation ===")
        # ==============================================================
        no_partner = valid_love_payload()
        del no_partner["partner"]
        try:
            service.create_pending_order(no_partner)
            check("14: love-premium without partner payload rejected", False)
        except OrderValidationError:
            check("14: love-premium without partner payload rejected", True)
        check("14: zero Order created", count_orders_for_marker() == 0)

        incomplete_partner = valid_love_payload()
        incomplete_partner["partner"] = {"name": "Girl Name"}  # missing dob/tob/pob/lat/long
        try:
            service.create_pending_order(incomplete_partner)
            check("14b: love-premium with incomplete partner payload rejected", False)
        except OrderValidationError:
            check("14b: love-premium with incomplete partner payload rejected", True)
        check("14b: zero Order created", count_orders_for_marker() == 0)

        order = service.create_pending_order(valid_love_payload())
        db.session.refresh(order)
        check("15: love-premium with complete partner payload succeeds", order.id is not None)
        check("15: canonical report_slug persisted", order.product == LOVE_SLUG)
        check(
            "16: partner_payload persists exactly in the existing compatible format",
            order.partner_payload == {
                "name": "Girl Name", "dob": "1992-08-15", "tob": "06:30",
                "pob": "Mumbai", "latitude": 19.0760, "longitude": 72.8777,
            },
        )
        # relationship_future_report has no phone field anywhere in its
        # live form -- confirm this service does not require or invent one.
        check("bonus: relationship_future_report Order has no phone value forced", order.phone is None)
        cleanup()

        # ==============================================================
        print("\n=== 17-18: validation failure leaves no partial row, repeatedly ===")
        # ==============================================================
        for attempt in range(3):
            try:
                service.create_pending_order(valid_standard_payload(dob=""))
            except OrderValidationError:
                pass
        check("17/18: three repeated validation failures created zero rows total", count_orders_for_marker() == 0)

        # ==============================================================
        print("\n=== 19: existing create_paid_report_order() behavior unchanged ===")
        # ==============================================================
        try:
            service.create_paid_report_order({"name": "X", "email": f"{MARKER_EMAIL_PREFIX}-paid@example.com"})
            check("19: create_paid_report_order still rejects a missing product", False)
        except ValueError as exc:
            check(
                "19: create_paid_report_order's own exact error message is unchanged",
                str(exc) == "name, email, and product are required to create a report order.",
            )
        check("19: zero Order created by the rejected call", count_orders_for_marker() == 0)

        # ==============================================================
        print("\n=== C: mark_paid_and_dispatch is a reserved, unimplemented R4 boundary ===")
        # ==============================================================
        try:
            service.mark_paid_and_dispatch(1)
            check("C: mark_paid_and_dispatch raises NotImplementedError (R4 boundary)", False)
        except NotImplementedError:
            check("C: mark_paid_and_dispatch raises NotImplementedError (R4 boundary)", True)

        cleanup()

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
