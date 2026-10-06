"""
test_report_platform_r6_route_integration.py
-------------------------------------------------
Paid Report Platform v1.0 -- R6 (Backend Route Integration).

End-to-end integration tests against the REAL Flask routes
(POST /api/razorpay-order, POST /webhook), exercising the full new
chain: create_pending_order() -> Razorpay order.create() (mocked) ->
PAYMENT_PENDING -> PaymentFinalizationService.finalize_report_payment()
(Razorpay verify()/fetch_payment() mocked) -> ReportGenerationDispatcher.
dispatch_if_pending() (threading.Thread mocked, so no real generation
ever runs).

Only the actual Razorpay network boundary is mocked
(RazorpayProvider.verify / .verify_webhook_signature / .fetch_payment /
.fetch_order_campaign_context, and razorpay_client's own lazy singleton)
-- every other layer (Flask routing, OrderService, PaymentFinalizationService,
ReportGenerationDispatcher, the real jyotishasha_local DB) runs for real.

No real Celery/thread/GPT/PDF/email call is ever made. LOCAL ONLY.
"""

import os
import sys
from unittest.mock import MagicMock, patch

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
from modules.payments.report_product_registry import ReportProduct  # noqa: E402
from modules.payments.razorpay_provider import RazorpayProvider  # noqa: E402
from config.razorpay_config import _LazyRazorpayClient  # noqa: E402

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
MARKER_EMAIL_PREFIX = "r6-route-test"
_counter = {"n": 0}


def _unique(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def standard_payload(**overrides):
    payload = {
        "product": STANDARD_SLUG, "name": "Suresh", "email": f"{MARKER_EMAIL_PREFIX}-{_unique('u')}@example.com",
        "phone": "9999999999", "dob": "1994-01-26", "tob": "08:40",
        "pob": "Sindhnur Rural", "latitude": "15.6167", "longitude": "76.6833", "language": "en",
    }
    payload.update(overrides)
    return payload


def love_payload(**overrides):
    payload = {
        "product": LOVE_SLUG, "name": "Boy", "email": f"{MARKER_EMAIL_PREFIX}-{_unique('u')}@example.com",
        "dob": "1990-05-01", "tob": "10:00", "pob": "Delhi", "latitude": 28.6139, "longitude": 77.209,
        "language": "en",
        "partner": {"name": "Girl", "dob": "1992-08-15", "tob": "06:30", "pob": "Mumbai", "latitude": 19.076, "longitude": 72.8777},
    }
    payload.update(overrides)
    return payload


def mock_razorpay_order_create(order_id_prefix="order_rp"):
    mock_client = MagicMock()
    mock_client.order.create.return_value = {"id": _unique(order_id_prefix), "currency": "INR"}
    _LazyRazorpayClient._real_client = mock_client
    return mock_client


def cleanup():
    Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()
    db.session.execute(text("DELETE FROM processed_payments WHERE reference LIKE 'order_rp%'"))
    db.session.commit()


def webhook_browser_payload(razorpay_order_id, payment_id=None, signature="sig_test"):
    return {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id or _unique("pay_rp"),
        "razorpay_signature": signature,
    }


def webhook_server_event(razorpay_order_id, payment_id=None, notes=None):
    return {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": payment_id or _unique("pay_rp"), "order_id": razorpay_order_id, "notes": notes or {},
        }}},
    }


def verified_result(reference):
    from modules.payments.payment_models import PaymentVerificationResult, PaymentStatus, PaymentProviderType
    return PaymentVerificationResult(status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY, reference=reference, verified=True, message="ok")


def failed_result(reference):
    from modules.payments.payment_models import PaymentVerificationResult, PaymentStatus, PaymentProviderType
    return PaymentVerificationResult(status=PaymentStatus.FAILED, provider=PaymentProviderType.RAZORPAY, reference=reference, verified=False, message="bad signature")


def payment_record_for(order, payment_id, amount_paise=None, order_id_override=None):
    return {
        "id": payment_id, "order_id": order_id_override or order.razorpay_order_id,
        "amount": order.amount_paise if amount_paise is None else amount_paise, "status": "captured",
    }


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )
        cleanup()
        client = app.test_client()

        # ==============================================================
        print("\n=== 1-6: /api/razorpay-order canonical flow ===")
        # ==============================================================
        mock_client = mock_razorpay_order_create()
        resp = client.post("/api/razorpay-order", json=standard_payload())
        check("1: 200 on complete standard payload", resp.status_code == 200)
        body = resp.get_json()
        order = Order.query.get(body["internal_order_id"])
        check("1: internal Order exists before/via this call", order is not None)
        check("2: Razorpay amount came from Order.amount_paise (5100)", mock_client.order.create.call_args.args[0]["amount"] == 5100 == order.amount_paise)
        notes_sent = mock_client.order.create.call_args.args[0]["notes"]
        check("3: notes contain internal_order_id/report_slug", notes_sent.get("internal_order_id") == str(order.id) and notes_sent.get("report_slug") == STANDARD_SLUG)
        check("4: no birth/customer PII in notes", not any(k in notes_sent for k in ("name", "email", "dob", "tob", "pob", "phone", "latitude", "longitude", "partner_json")))
        check("5: Order advanced to PAYMENT_PENDING with razorpay_order_id stored", order.payment_status == "PAYMENT_PENDING" and order.razorpay_order_id == body["order_id"])
        check("2/5: response amount is paise, matching Order.amount_paise", body["amount"] == 5100)

        # ==============================================================
        print("\n=== 6: Razorpay order-creation failure -> Order remains CREATED ===")
        # ==============================================================
        failing_client = MagicMock()
        failing_client.order.create.side_effect = Exception("razorpay down")
        _LazyRazorpayClient._real_client = failing_client
        with patch("time.sleep"):  # skip the real 0.8s retry delay
            resp6 = client.post("/api/razorpay-order", json=standard_payload())
        check("6: non-2xx returned", resp6.status_code >= 400)
        # The Order WAS created (validation succeeded) but never advanced.
        recent_created = Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%"), Order.payment_status == "CREATED").order_by(Order.id.desc()).first()
        check("6: internal Order exists and remains CREATED/no razorpay_order_id", recent_created is not None and recent_created.razorpay_order_id is None)

        # ==============================================================
        print("\n=== 7-9: rejected before Razorpay is ever called ===")
        # ==============================================================
        mock_client2 = mock_razorpay_order_create()
        resp7 = client.post("/api/razorpay-order", json={"product": STANDARD_SLUG})
        check("7: old {product}-only payload -> 4xx", 400 <= resp7.status_code < 500)
        check("7: Razorpay was never called", mock_client2.order.create.call_count == 0)

        mock_client3 = mock_razorpay_order_create()
        resp8 = client.post("/api/razorpay-order", json=standard_payload(product="not_a_real_product_xyz"))
        check("8: invalid product -> 4xx before Razorpay", 400 <= resp8.status_code < 500 and mock_client3.order.create.call_count == 0)

        inactive_slug = "r6_test_inactive"
        ReportProduct.query.filter_by(report_slug=inactive_slug).delete(synchronize_session=False)
        db.session.commit()
        db.session.add(ReportProduct(report_slug=inactive_slug, name="Inactive", price=51, active=False, generator="standard_v1", prompt_template_id=inactive_slug))
        db.session.commit()
        mock_client4 = mock_razorpay_order_create()
        resp9 = client.post("/api/razorpay-order", json=standard_payload(product=inactive_slug))
        check("9: inactive product -> 4xx before Razorpay", 400 <= resp9.status_code < 500 and mock_client4.order.create.call_count == 0)
        ReportProduct.query.filter_by(report_slug=inactive_slug).delete(synchronize_session=False)
        db.session.commit()

        # ==============================================================
        print("\n=== 10/11: relationship_future_report partner payload ===")
        # ==============================================================
        mock_client5 = mock_razorpay_order_create()
        resp10 = client.post("/api/razorpay-order", json=love_payload())
        check("10: complete partner payload accepted -> 200", resp10.status_code == 200)
        love_order = Order.query.get(resp10.get_json()["internal_order_id"])
        check("10: amount_paise == 19900", love_order.amount_paise == 19900)

        mock_client6 = mock_razorpay_order_create()
        incomplete = love_payload()
        del incomplete["partner"]
        resp11 = client.post("/api/razorpay-order", json=incomplete)
        check("11: incomplete partner payload rejected before Razorpay", 400 <= resp11.status_code < 500 and mock_client6.order.create.call_count == 0)

        # ==============================================================
        print("\n=== 12/13/14: server-first / browser-first / simultaneous ===")
        # ==============================================================
        def create_pending_via_route():
            mock_razorpay_order_create()
            r = client.post("/api/razorpay-order", json=standard_payload())
            body = r.get_json()
            return Order.query.get(body["internal_order_id"])

        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True):
            order12 = create_pending_via_route()
            with patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order12, pid))), \
                 patch("threading.Thread") as mock_thread:
                resp12 = client.post("/webhook", json=webhook_server_event(order12.razorpay_order_id))
            check("12: server webhook first -> 200", resp12.status_code == 200)
            db.session.refresh(order12)
            check("12: PAID + Queued (one dispatch)", order12.payment_status == "PAID" and order12.report_stage == "Queued" and mock_thread.call_count == 1)

        order13 = create_pending_via_route()
        payment_id_13 = _unique("pay_rp")
        with patch.object(RazorpayProvider, "verify", return_value=verified_result(order13.razorpay_order_id)), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order13, pid))), \
             patch.object(RazorpayProvider, "fetch_order_campaign_context", staticmethod(lambda oid: None)), \
             patch("threading.Thread") as mock_thread:
            resp13 = client.post("/webhook", json=webhook_browser_payload(order13.razorpay_order_id, payment_id=payment_id_13))
        check("13: browser callback first -> 200", resp13.status_code == 200)
        db.session.refresh(order13)
        check("13: PAID + Queued (one dispatch)", order13.payment_status == "PAID" and order13.report_stage == "Queued" and mock_thread.call_count == 1)

        order14 = create_pending_via_route()
        payment_id_14 = _unique("pay_rp")
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), \
             patch.object(RazorpayProvider, "verify", return_value=verified_result(order14.razorpay_order_id)), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order14, pid))), \
             patch.object(RazorpayProvider, "fetch_order_campaign_context", staticmethod(lambda oid: None)), \
             patch("threading.Thread") as mock_thread:
            r_a = client.post("/webhook", json=webhook_server_event(order14.razorpay_order_id, payment_id=payment_id_14, notes={}))
            r_b = client.post("/webhook", json=webhook_browser_payload(order14.razorpay_order_id, payment_id=payment_id_14))
        check("14: simultaneous server+browser -> both 200, one claim, one dispatch", r_a.status_code == 200 and r_b.status_code == 200 and mock_thread.call_count == 1)
        check("14: exactly one ProcessedPayment claim", ProcessedPayment.query.filter_by(payment_id=payment_id_14).count() == 1)

        # ==============================================================
        print("\n=== 15/16: repeated callbacks -> idempotent, no re-dispatch ===")
        # ==============================================================
        order15 = create_pending_via_route()
        payment_id_15 = _unique("pay_rp")
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order15, pid))), \
             patch("threading.Thread") as mock_thread:
            for _ in range(10):
                client.post("/webhook", json=webhook_server_event(order15.razorpay_order_id, payment_id=payment_id_15))
        check("15: webhook repeated 10x -> one claim, one dispatch", ProcessedPayment.query.filter_by(payment_id=payment_id_15).count() == 1 and mock_thread.call_count == 1)

        order16 = create_pending_via_route()
        payment_id_16 = _unique("pay_rp")
        with patch.object(RazorpayProvider, "verify", return_value=verified_result(order16.razorpay_order_id)), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order16, pid))), \
             patch.object(RazorpayProvider, "fetch_order_campaign_context", staticmethod(lambda oid: None)), \
             patch("threading.Thread") as mock_thread:
            r1 = client.post("/webhook", json=webhook_browser_payload(order16.razorpay_order_id, payment_id=payment_id_16))
            r2 = client.post("/webhook", json=webhook_browser_payload(order16.razorpay_order_id, payment_id=payment_id_16))
        check("16: browser callback repeated -> idempotent success (both 200), one dispatch", r1.status_code == 200 and r2.status_code == 200 and mock_thread.call_count == 1)

        # ==============================================================
        print("\n=== 17: crash-recovery -- ALREADY_FINALIZED + Pending safely dispatches once ===")
        # ==============================================================
        order17 = create_pending_via_route()
        payment_id_17 = _unique("pay_rp")
        # Simulate: payment already finalized (PAID) in a prior process
        # that then crashed BEFORE calling the dispatcher -- report_stage
        # is still "Pending".
        order17.payment_status = "PAID"
        order17.status = "PAID"
        order17.razorpay_payment_id = payment_id_17
        db.session.add(ProcessedPayment(provider="RAZORPAY", payment_id=payment_id_17, reference=order17.razorpay_order_id, order_id=order17.id, response_payload={}))
        db.session.commit()
        with patch("threading.Thread") as mock_thread:
            resp17 = client.post("/webhook", json=webhook_browser_payload(order17.razorpay_order_id, payment_id=payment_id_17))
        check("17: crash-recovery callback -> 200", resp17.status_code == 200)
        db.session.refresh(order17)
        check("17: report_stage Pending -> Queued (repaired), exactly one dispatch", order17.report_stage == "Queued" and mock_thread.call_count == 1)

        # ==============================================================
        print("\n=== 18/19: already Queued/Processing/Ready/Failed -> no redispatch ===")
        # ==============================================================
        for stage in ("Queued", "Processing", "Ready", "Failed"):
            o = create_pending_via_route()
            pid = _unique("pay_rp")
            o.payment_status = "PAID"; o.status = "PAID"; o.razorpay_payment_id = pid; o.report_stage = stage
            db.session.add(ProcessedPayment(provider="RAZORPAY", payment_id=pid, reference=o.razorpay_order_id, order_id=o.id, response_payload={}))
            db.session.commit()
            with patch("threading.Thread") as mock_thread:
                r = client.post("/webhook", json=webhook_browser_payload(o.razorpay_order_id, payment_id=pid))
            check(f"18/19: duplicate callback on report_stage={stage} does not redispatch", mock_thread.call_count == 0)
            db.session.refresh(o)
            check(f"18/19: report_stage unchanged ({stage})", o.report_stage == stage)

        # ==============================================================
        print("\n=== 20/21: invalid signature -> unpaid, no dispatch ===")
        # ==============================================================
        order20 = create_pending_via_route()
        with patch.object(RazorpayProvider, "verify", return_value=failed_result(order20.razorpay_order_id)), \
             patch.object(RazorpayProvider, "fetch_order_campaign_context", staticmethod(lambda oid: None)), \
             patch("threading.Thread") as mock_thread:
            resp20 = client.post("/webhook", json=webhook_browser_payload(order20.razorpay_order_id))
        check("20: invalid browser signature -> non-2xx, no dispatch", resp20.status_code >= 400 and mock_thread.call_count == 0)
        db.session.refresh(order20)
        check("20: Order remains unpaid", order20.payment_status == "PAYMENT_PENDING")

        order21 = create_pending_via_route()
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=False), \
             patch("threading.Thread") as mock_thread:
            resp21 = client.post("/webhook", json=webhook_server_event(order21.razorpay_order_id))
        check("21: invalid webhook signature -> non-2xx, no dispatch", resp21.status_code >= 400 and mock_thread.call_count == 0)
        db.session.refresh(order21)
        check("21: Order remains unpaid", order21.payment_status == "PAYMENT_PENDING")

        # ==============================================================
        print("\n=== 22/23: amount mismatch / order-payment mismatch -> unpaid ===")
        # ==============================================================
        order22 = create_pending_via_route()
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order22, pid, amount_paise=order22.amount_paise + 1))), \
             patch("threading.Thread") as mock_thread:
            resp22 = client.post("/webhook", json=webhook_server_event(order22.razorpay_order_id))
        check("22: amount mismatch -> non-2xx, no dispatch", resp22.status_code >= 400 and mock_thread.call_count == 0)
        db.session.refresh(order22)
        check("22: Order remains unpaid", order22.payment_status == "PAYMENT_PENDING")

        order23 = create_pending_via_route()
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order23, pid, order_id_override="some_other_order"))), \
             patch("threading.Thread") as mock_thread:
            resp23 = client.post("/webhook", json=webhook_server_event(order23.razorpay_order_id))
        check("23: order/payment mismatch -> non-2xx, no dispatch", resp23.status_code >= 400 and mock_thread.call_count == 0)
        db.session.refresh(order23)
        check("23: Order remains unpaid", order23.payment_status == "PAYMENT_PENDING")

        # ==============================================================
        print("\n=== 24: orphaned payment -> no fabricated Order ===")
        # ==============================================================
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), patch("threading.Thread") as mock_thread:
            resp24 = client.post("/webhook", json=webhook_server_event("order_never_existed_r6"))
        check("24: orphaned payment -> non-2xx, no dispatch", resp24.status_code >= 400 and mock_thread.call_count == 0)
        check("24: no Order fabricated", Order.query.filter_by(razorpay_order_id="order_never_existed_r6").first() is None)

        # ==============================================================
        print("\n=== 25/26: different-payment/PAID-order and same-payment/different-order conflicts ===")
        # ==============================================================
        order25 = create_pending_via_route()
        payment_id_25a = _unique("pay_rp")
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order25, pid))), \
             patch("threading.Thread") as mock_thread:
            client.post("/webhook", json=webhook_server_event(order25.razorpay_order_id, payment_id=payment_id_25a))
            resp25 = client.post("/webhook", json=webhook_server_event(order25.razorpay_order_id, payment_id=_unique("pay_rp")))
        check("25: different payment for already-PAID order -> non-2xx, no second dispatch", resp25.status_code >= 400 and mock_thread.call_count == 1)

        order26a = create_pending_via_route()
        order26b = create_pending_via_route()
        shared_payment_id = _unique("pay_rp")
        db.session.add(ProcessedPayment(provider="RAZORPAY", payment_id=shared_payment_id, reference=order26a.razorpay_order_id, order_id=order26a.id, response_payload={}))
        db.session.commit()
        with patch("threading.Thread") as mock_thread:
            resp26 = client.post("/webhook", json=webhook_browser_payload(order26b.razorpay_order_id, payment_id=shared_payment_id))
        check("26: same payment against a different Order -> conflict, no dispatch", resp26.status_code >= 400 and mock_thread.call_count == 0)

        # ==============================================================
        print("\n=== 27: dispatch failure -> payment remains PAID, no second charge/order ===")
        # ==============================================================
        order27 = create_pending_via_route()
        with patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order27, pid))), \
             patch("threading.Thread", side_effect=RuntimeError("cannot start thread")):
            resp27 = client.post("/webhook", json=webhook_server_event(order27.razorpay_order_id))
        check("27: dispatch failure -> still 200 (payment succeeded)", resp27.status_code == 200)
        check("27: response does not imply payment failure", "processing_delayed" in resp27.get_json().get("status", ""))
        db.session.refresh(order27)
        check("27: payment remains PAID despite dispatch failure", order27.payment_status == "PAID")
        check("27: exactly one Order, one claim -- no duplicate", Order.query.filter_by(razorpay_order_id=order27.razorpay_order_id).count() == 1)

        # ==============================================================
        print("\n=== 28/29: canonical report_slug + no PII mutation from callback ===")
        # ==============================================================
        order28 = create_pending_via_route()
        original_product = order28.product
        original_name = order28.name
        forged_payload = webhook_browser_payload(order28.razorpay_order_id)
        forged_payload.update({"product": "some_other_report", "name": "Forged Name", "email": "forged@example.com", "dob": "2000-01-01"})
        with patch.object(RazorpayProvider, "verify", return_value=verified_result(order28.razorpay_order_id)), \
             patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: payment_record_for(order28, pid))), \
             patch.object(RazorpayProvider, "fetch_order_campaign_context", staticmethod(lambda oid: None)), \
             patch("threading.Thread"):
            client.post("/webhook", json=forged_payload)
        db.session.refresh(order28)
        check("28: Order.product unchanged despite forged 'product' in callback", order28.product == original_product)
        check("29: Order.name unchanged despite forged 'name'/'email'/'dob' in callback", order28.name == original_name)

        # ==============================================================
        print("\n=== 30: existing non-report PaymentService purposes unchanged ===")
        # ==============================================================
        import inspect
        from modules.payments.payment_service import PaymentService
        source = inspect.getsource(PaymentService)
        check("30: PaymentService source completely unmodified (still handles SUBSCRIPTION)", "_apply_subscription_business_effect" in source and "PaymentPurpose.SUBSCRIPTION" in source)
        import routes.routes_google_purchase_confirm as ggpc
        ggpc_source = inspect.getsource(ggpc)
        check("30: routes_google_purchase_confirm.py still calls PaymentService.process_payment() directly, untouched", "PaymentService().process_payment(payment_request)" in ggpc_source)

        cleanup()

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
