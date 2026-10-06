"""
test_report_platform_r4_payment_finalization.py
-------------------------------------------------
Paid Report Platform v1.0 -- R4 (Payment Finalization & Idempotency
Core).

Proves PaymentFinalizationService.finalize_report_payment() structurally
eliminates the Suresh failure class: it never creates an Order, never
reconstructs customer data from a payload, never changes Order.product,
verifies payment/order/amount independently via Razorpay before any
PAID transition, claims idempotently with order_id populated at claim
time, and never dispatches report generation.

Razorpay's own network API (RazorpayProvider.verify /
RazorpayProvider.fetch_payment) is mocked throughout -- no real
network call is ever made. Orders are advanced to PAYMENT_PENDING
directly by the test (simulating the future R6 route-wiring step),
per this phase's own explicit allowance ("Tests may prepare this state
directly").

No route, app.py, PaymentService, or frontend code is touched or
exercised here. LOCAL ONLY -- connects exclusively to jyotishasha_local.
"""

import os
import sys
from unittest.mock import patch

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
from modules.models_processed_payments import ProcessedPayment  # noqa: E402
from modules.payments.order_service import OrderService  # noqa: E402
from modules.payments.payment_models import (  # noqa: E402
    PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus, PaymentVerificationResult,
)
from modules.payments.payment_finalization_service import (  # noqa: E402
    PaymentFinalizationService, ReportPaymentFinalizationStatus,
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


STANDARD_SLUG = "startup_suggestion_report"
LOVE_SLUG = "relationship_future_report"
MARKER_EMAIL_PREFIX = "r4-finalize-test"
_counter = {"n": 0}


def _unique(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def valid_standard_payload(**overrides):
    payload = {
        "product": STANDARD_SLUG, "name": "Suresh",
        "email": f"{MARKER_EMAIL_PREFIX}-standard@example.com",
        "phone": "9999999999", "dob": "1994-01-26", "tob": "08:40",
        "pob": "Sindhnur Rural", "latitude": "15.6167", "longitude": "76.6833",
        "language": "en",
    }
    payload.update(overrides)
    return payload


def make_pending_order(slug=STANDARD_SLUG, **overrides):
    """Real, validated Order via R3's own create_pending_order(), then
    advanced to PAYMENT_PENDING with a razorpay_order_id -- exactly
    what the future R6 route will do, prepared directly here per this
    phase's own explicit test allowance."""
    order = OrderService().create_pending_order(valid_standard_payload(product=slug, **overrides))
    order.razorpay_order_id = _unique("order_r4test")
    order.payment_status = "PAYMENT_PENDING"
    db.session.commit()
    db.session.refresh(order)
    return order


def make_request(order, payment_id=None, provider=PaymentProviderType.RAZORPAY):
    return PaymentRequest(
        provider=provider, purpose=PaymentPurpose.REPORT_PURCHASE,
        reference=order.razorpay_order_id, payment_id=payment_id or _unique("pay_r4test"),
        signature="sig_test", metadata={},
    )


def verified_result(reference):
    return PaymentVerificationResult(
        status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY,
        reference=reference, verified=True, message="ok",
    )


def failed_result(reference):
    return PaymentVerificationResult(
        status=PaymentStatus.FAILED, provider=PaymentProviderType.RAZORPAY,
        reference=reference, verified=False, message="signature mismatch",
    )


def payment_record_for(order, payment_id, amount_paise=None):
    return {
        "id": payment_id, "order_id": order.razorpay_order_id,
        "amount": order.amount_paise if amount_paise is None else amount_paise,
        "status": "captured",
    }


def cleanup():
    Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()
    db.session.execute(text("DELETE FROM processed_payments WHERE payment_id LIKE 'pay_r4test%'"))
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )
        cleanup()
        service = PaymentFinalizationService()

        # ==============================================================
        print("\n=== 2-4: price snapshot stored as paise, exact ===")
        # ==============================================================
        std_order = make_pending_order(STANDARD_SLUG)
        check("2/3: startup_suggestion_report (₹51) -> amount_paise == 5100 exactly", std_order.amount_paise == 5100)
        love_payload = valid_standard_payload(
            product=LOVE_SLUG, phone=None,
            partner={"name": "Girl", "dob": "1992-08-15", "tob": "06:30", "pob": "Mumbai", "latitude": 19.076, "longitude": 72.8777},
        )
        del love_payload["phone"]
        love_order = OrderService().create_pending_order(love_payload)
        check("4: relationship_future_report (₹199) -> amount_paise == 19900 exactly", love_order.amount_paise == 19900)
        Order.query.filter_by(id=love_order.id).delete(synchronize_session=False)
        db.session.commit()

        # ==============================================================
        print("\n=== 1/5-10: valid finalization ===")
        # ==============================================================
        order = make_pending_order()
        original_name, original_dob, original_product = order.name, order.dob, order.product
        request = make_request(order)
        with patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "verify", return_value=verified_result(order.razorpay_order_id),
        ), patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "fetch_payment", staticmethod(lambda pid: payment_record_for(order, pid)),
        ):
            result = service.finalize_report_payment(request)

        check("1: result.status == FINALIZED", result.status == ReportPaymentFinalizationStatus.FINALIZED)
        db.session.refresh(order)
        check("1: payment_status PAYMENT_PENDING -> PAID", order.payment_status == "PAID")
        check("5: Order.product unchanged after finalization", order.product == original_product)
        check("6: customer/birth fields unchanged", order.name == original_name and order.dob == original_dob)
        claims = ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=request.payment_id).all()
        check("7: exactly one ProcessedPayment created", len(claims) == 1)
        check("8: ProcessedPayment.order_id populated (at claim time)", claims[0].order_id == order.id)
        check("9: razorpay_payment_id stored on Order", order.razorpay_payment_id == request.payment_id)
        check("10: legacy Order.status becomes PAID", order.status == "PAID")

        # ==============================================================
        print("\n=== 11/12: idempotent retries ===")
        # ==============================================================
        for i in range(10):
            retry_result = service.finalize_report_payment(request)
            if i == 0:
                check("11: same payment retry -> ALREADY_FINALIZED", retry_result.status == ReportPaymentFinalizationStatus.ALREADY_FINALIZED)
        claims_after = ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=request.payment_id).count()
        check("12: 10 repeated callbacks -> still exactly one claim", claims_after == 1)
        db.session.refresh(order)
        check("11/12: Order still correctly PAID, not double-processed", order.payment_status == "PAID")

        # ==============================================================
        print("\n=== 13: simulated concurrent duplicate claim (white-box) ===")
        # ==============================================================
        order2 = make_pending_order()
        request2 = make_request(order2)
        # Simulate a concurrent winner having already inserted the claim
        # for order2's OWN payment_id, then calling the private
        # transactional method directly to exercise the IntegrityError
        # branch specifically (see _claim_and_finalize()'s own comment).
        db.session.add(ProcessedPayment(provider=PaymentProviderType.RAZORPAY, payment_id=request2.payment_id, reference=order2.razorpay_order_id, order_id=order2.id))
        db.session.commit()
        result13 = service._claim_and_finalize(request2, order2, {"correlation_id": "test", "provider": PaymentProviderType.RAZORPAY, "razorpay_order_id": order2.razorpay_order_id, "razorpay_payment_id": request2.payment_id})
        check("13: concurrent duplicate claim resolves to ALREADY_FINALIZED (one effective finalization)", result13.status == ReportPaymentFinalizationStatus.ALREADY_FINALIZED)
        check("13: still exactly one claim for that payment_id", ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=request2.payment_id).count() == 1)

        # ==============================================================
        print("\n=== 14: same payment_id against a DIFFERENT Order ===")
        # ==============================================================
        order3 = make_pending_order()
        conflicting_request = PaymentRequest(
            provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE,
            reference=order3.razorpay_order_id, payment_id=request.payment_id,  # reuse order's OWN already-claimed payment_id
            signature="sig_test", metadata={},
        )
        result14 = service.finalize_report_payment(conflicting_request)
        check("14: same payment_id against a different Order -> PAYMENT_ALREADY_CLAIMED_DIFFERENT_ORDER", result14.status == ReportPaymentFinalizationStatus.PAYMENT_ALREADY_CLAIMED_DIFFERENT_ORDER)
        db.session.refresh(order3)
        check("14: order3 was NOT mutated", order3.payment_status == "PAYMENT_PENDING")
        check("14: original claim's order_id was not reassigned", ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=request.payment_id).first().order_id == order.id)

        # ==============================================================
        print("\n=== 15: different payment_id against an already-PAID Order ===")
        # ==============================================================
        different_payment_request = make_request(order)  # order is already PAID from step 1
        result15 = service.finalize_report_payment(different_payment_request)
        check("15: different payment_id for already-PAID Order -> DIFFERENT_PAYMENT_FOR_PAID_ORDER", result15.status == ReportPaymentFinalizationStatus.DIFFERENT_PAYMENT_FOR_PAID_ORDER)
        db.session.refresh(order)
        check("15: original razorpay_payment_id was not replaced", order.razorpay_payment_id == request.payment_id)
        check("15: no second claim was created for the new payment_id", ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=different_payment_request.payment_id).first() is None)

        # ==============================================================
        print("\n=== 16: unknown razorpay_order_id ===")
        # ==============================================================
        orphan_request = PaymentRequest(
            provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE,
            reference="order_never_existed_r4test", payment_id=_unique("pay_r4test"),
            signature="sig_test", metadata={},
        )
        result16 = service.finalize_report_payment(orphan_request)
        check("16: unknown razorpay_order_id -> ORPHANED_PAYMENT", result16.status == ReportPaymentFinalizationStatus.ORPHANED_PAYMENT)
        check("16: no Order was fabricated", Order.query.filter_by(razorpay_order_id="order_never_existed_r4test").first() is None)

        # ==============================================================
        print("\n=== 17: CREATED Order cannot finalize ===")
        # ==============================================================
        created_order = OrderService().create_pending_order(valid_standard_payload(email=f"{MARKER_EMAIL_PREFIX}-created@example.com"))
        created_order.razorpay_order_id = _unique("order_r4test")  # simulate having an id, but payment_status still CREATED
        db.session.commit()
        result17 = service.finalize_report_payment(make_request(created_order))
        check("17: CREATED Order rejected -> INVALID_STATE", result17.status == ReportPaymentFinalizationStatus.INVALID_STATE)
        db.session.refresh(created_order)
        check("17: still CREATED, not PAID", created_order.payment_status == "CREATED")

        # ==============================================================
        print("\n=== 18: amount mismatch -> unpaid ===")
        # ==============================================================
        order18 = make_pending_order()
        request18 = make_request(order18)
        with patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "verify", return_value=verified_result(order18.razorpay_order_id),
        ), patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "fetch_payment", staticmethod(lambda pid: payment_record_for(order18, pid, amount_paise=order18.amount_paise + 1)),
        ):
            result18 = service.finalize_report_payment(request18)
        check("18: amount mismatch -> AMOUNT_MISMATCH", result18.status == ReportPaymentFinalizationStatus.AMOUNT_MISMATCH)
        db.session.refresh(order18)
        check("18: Order remains unpaid", order18.payment_status == "PAYMENT_PENDING")
        check("18: no claim was created", ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=request18.payment_id).first() is None)

        # ==============================================================
        print("\n=== 19: payment/order mismatch -> unpaid ===")
        # ==============================================================
        order19 = make_pending_order()
        request19 = make_request(order19)
        with patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "verify", return_value=verified_result(order19.razorpay_order_id),
        ), patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "fetch_payment", staticmethod(lambda pid: {"id": pid, "order_id": "some_other_razorpay_order", "amount": order19.amount_paise, "status": "captured"}),
        ):
            result19 = service.finalize_report_payment(request19)
        check("19: payment's own order_id != resolved Order -> ORDER_PAYMENT_MISMATCH", result19.status == ReportPaymentFinalizationStatus.ORDER_PAYMENT_MISMATCH)
        db.session.refresh(order19)
        check("19: Order remains unpaid", order19.payment_status == "PAYMENT_PENDING")

        # ==============================================================
        print("\n=== 20: invalid verification/signature -> unpaid ===")
        # ==============================================================
        order20 = make_pending_order()
        request20 = make_request(order20)
        with patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "verify", return_value=failed_result(order20.razorpay_order_id),
        ):
            result20 = service.finalize_report_payment(request20)
        check("20: failed verification -> VERIFICATION_FAILED", result20.status == ReportPaymentFinalizationStatus.VERIFICATION_FAILED)
        db.session.refresh(order20)
        check("20: Order remains unpaid, no DB business effect", order20.payment_status == "PAYMENT_PENDING")
        check("20: no claim was created", ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=request20.payment_id).first() is None)

        # ==============================================================
        print("\n=== 21: legacy ProcessedPayment order_id=NULL -> manual review ===")
        # ==============================================================
        order21 = make_pending_order()
        legacy_payment_id = _unique("pay_r4test")
        db.session.add(ProcessedPayment(provider=PaymentProviderType.RAZORPAY, payment_id=legacy_payment_id, reference=order21.razorpay_order_id, order_id=None))
        db.session.commit()
        result21 = service.finalize_report_payment(make_request(order21, payment_id=legacy_payment_id))
        check("21: legacy order_id=NULL claim -> LEGACY_STUCK", result21.status == ReportPaymentFinalizationStatus.LEGACY_STUCK)
        db.session.refresh(order21)
        check("21: legacy claim was NOT auto-repaired/released", order21.payment_status == "PAYMENT_PENDING")
        check("21: legacy claim's order_id was NOT auto-populated", ProcessedPayment.query.filter_by(payment_id=legacy_payment_id).first().order_id is None)

        # ==============================================================
        print("\n=== 22: simulated commit failure leaves no partial state ===")
        # ==============================================================
        order22 = make_pending_order()
        request22 = make_request(order22)
        with patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "verify", return_value=verified_result(order22.razorpay_order_id),
        ), patch.object(
            __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
            "fetch_payment", staticmethod(lambda pid: payment_record_for(order22, pid)),
        ), patch.object(db.session, "commit", side_effect=RuntimeError("simulated crash at commit")):
            try:
                service.finalize_report_payment(request22)
                check("22: simulated commit failure raised", False)
            except RuntimeError:
                check("22: simulated commit failure raised", True)
        # The patch context has exited -- db.session.commit is real again.
        db.session.rollback()
        check("22: no partial claim persisted", ProcessedPayment.query.filter_by(provider=PaymentProviderType.RAZORPAY, payment_id=request22.payment_id).first() is None)
        db.session.refresh(order22)
        check("22: Order left exactly as PAYMENT_PENDING, not PAID", order22.payment_status == "PAYMENT_PENDING")

        # ==============================================================
        print("\n=== 23: no generation dispatcher ever called ===")
        # ==============================================================
        order23 = make_pending_order()
        request23 = make_request(order23)
        with patch("tasks.generate_and_send_report") as mock_task, \
             patch("modules.love.love_report_router.route_report_generation") as mock_route, \
             patch.object(OrderService, "redispatch_report_generation") as mock_redispatch, \
             patch.object(
                 __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
                 "verify", return_value=verified_result(order23.razorpay_order_id),
             ), patch.object(
                 __import__("modules.payments.razorpay_provider", fromlist=["RazorpayProvider"]).RazorpayProvider,
                 "fetch_payment", staticmethod(lambda pid: payment_record_for(order23, pid)),
             ):
            result23 = service.finalize_report_payment(request23)
        check("23: finalization succeeded", result23.status == ReportPaymentFinalizationStatus.FINALIZED)
        check("23: tasks.generate_and_send_report was never called", mock_task.delay.call_count == 0 and mock_task.call_count == 0)
        check("23: route_report_generation was never called", mock_route.call_count == 0)
        check("23: OrderService.redispatch_report_generation was never called", mock_redispatch.call_count == 0)

        cleanup()

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
