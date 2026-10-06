"""Step 2: synthetic regression for the historical webhook-first failure.

Real Flask routes, services, Razorpay HMAC verification and local PostgreSQL.
Only Razorpay HTTP calls and background generation are mocked. The crash test
adds a fault immediately AFTER real finalization returns its committed result.
No historical claims are changed; cleanup is limited to this run's UUIDs.

Run: .\venv\Scripts\python.exe -m unittest test_report_platform_suresh_webhook_first -v
"""

from contextlib import ExitStack
import hashlib
import hmac
import json
import os
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_worker_boot_lazy_clients import _FAKE_FCM_JSON

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Same dedicated local database as the existing R1-R6 regression scripts.
os.environ["DATABASE_URL"] = (
    "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
)
os.environ["FCM_SERVICE_ACCOUNT_JSON"] = _FAKE_FCM_JSON
os.environ["OPENAI_API_KEY"] = "sk-local-test-unused"
os.environ["RAZORPAY_KEY_ID"] = "local-test-unused"
os.environ["RAZORPAY_KEY_SECRET"] = "local-test-unused"

import razorpay
from sqlalchemy import event, text

from app import app
from extensions import db
from models import Order
from config.razorpay_config import _LazyRazorpayClient
from modules.models_processed_payments import ProcessedPayment
from modules.payments.payment_finalization_service import (
    PaymentFinalizationService, ReportPaymentFinalizationStatus as Finalization,
)
from modules.payments.report_generation_dispatcher import (
    ReportGenerationDispatcher, ReportGenerationDispatchStatus as Dispatch,
)


class SimulatedProcessDeath(BaseException):
    """Bypass Flask's normal Exception handling, before dispatch is entered."""


class SureshWebhookFirstRegression(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(app.app_context())
        self.assertEqual(db.engine.url.host, "localhost")
        self.assertEqual(db.engine.dialect.name, "postgresql")
        self.assertEqual(db.session.execute(text("SELECT current_database()")).scalar(),
                         "jyotishasha_local")
        self.token = uuid4().hex
        self.rp_order = "order_step2_" + self.token
        self.payment_id = "pay_step2_" + self.token
        self.payload = {
            "product": "startup_suggestion_report", "name": "Synthetic Gate Customer",
            "email": f"step2-{self.token}@example.com", "phone": "9000000000",
            "dob": "1991-06-15", "tob": "09:20", "pob": "New Delhi",
            "latitude": "28.6139", "longitude": "77.2090", "language": "en",
        }
        self.order_id = None
        self.before_orders = Order.query.count()
        self.inserted_claims = []
        self.ownership_transitions = []
        self.finalizations = []
        self.dispatches = []
        self.crash_after_finalization = False
        self.addCleanup(self.cleanup_rows)

        self.secret = "step2-synthetic-webhook-secret"
        sdk = razorpay.Client(auth=("step2-synthetic-key", "step2-synthetic-secret"))
        self.stack.enter_context(patch.object(_LazyRazorpayClient, "_real_client", sdk))
        self.stack.enter_context(patch(
            "modules.payments.razorpay_provider.RAZORPAY_WEBHOOK_SECRET", self.secret
        ))
        self.create_remote = self.stack.enter_context(patch.object(
            sdk.order, "create", return_value={"id": self.rp_order, "currency": "INR"}
        ))
        self.stack.enter_context(patch.object(
            sdk.order, "fetch", return_value={"id": self.rp_order, "notes": {}}
        ))
        self.fetch_remote = self.stack.enter_context(patch.object(
            sdk.payment, "fetch", return_value={
                "id": self.payment_id, "order_id": self.rp_order,
                "amount": 5100, "status": "captured",
            }
        ))
        # These spies delegate to the real SDK cryptography, never return True blindly.
        self.signature_check = self.stack.enter_context(patch.object(
            sdk.utility, "verify_webhook_signature", wraps=sdk.utility.verify_webhook_signature
        ))
        self.stack.enter_context(patch("requests.sessions.Session.request", side_effect=
                                     AssertionError("Unexpected real HTTP request")))
        # Exercise the actual dispatcher ownership UPDATE and _start_generation,
        # stopping only at the background execution boundary (local thread mode).
        self.stack.enter_context(patch("app_config.USE_CELERY", False))
        self.thread = self.stack.enter_context(patch(
            "modules.payments.report_generation_dispatcher.threading.Thread"
        ))
        self.generator = self.stack.enter_context(patch("tasks.generate_and_send_report"))
        self.email = self.stack.enter_context(patch("email_utils.send_email"))
        self.smtp = self.stack.enter_context(patch("smtplib.SMTP"))

        real_finalize = PaymentFinalizationService.finalize_report_payment

        def finalize(service, request):
            result = real_finalize(service, request)
            self.finalizations.append(result.status)
            if result.status == Finalization.FINALIZED:
                self.assertEqual(result.order_id, self.order_id)
                # A separate connection proves the claim is durably committed,
                # rather than just present in the ORM identity map/transaction.
                with db.engine.connect() as connection:
                    ids = connection.execute(text(
                        "SELECT order_id FROM processed_payments WHERE payment_id=:pid"
                    ), {"pid": self.payment_id}).scalars().all()
                    self.assertEqual(ids, [self.order_id])
                if self.crash_after_finalization:
                    raise SimulatedProcessDeath()
            return result

        self.stack.enter_context(patch.object(
            PaymentFinalizationService, "finalize_report_payment", autospec=True,
            side_effect=finalize,
        ))
        real_dispatch = ReportGenerationDispatcher.dispatch_if_pending

        def dispatch(service, order_id):
            result = real_dispatch(service, order_id)
            self.dispatches.append(result.status)
            return result

        self.stack.enter_context(patch.object(
            ReportGenerationDispatcher, "dispatch_if_pending", autospec=True,
            side_effect=dispatch,
        ))

        def claim_inserted(mapper, connection, claim):
            if claim.payment_id == self.payment_id:
                self.inserted_claims.append(claim.order_id)
                self.assertIsNotNone(claim.order_id, "Claim must be linked at INSERT time")
                self.assertEqual(claim.order_id, self.order_id)

        def sql_executed(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().lower().startswith("update orders "):
                for params in context.compiled_parameters or ():
                    if params.get("report_stage") == "Queued" and cursor.rowcount == 1:
                        self.ownership_transitions.append(cursor.rowcount)

        event.listen(ProcessedPayment, "after_insert", claim_inserted)
        self.stack.callback(event.remove, ProcessedPayment, "after_insert", claim_inserted)
        event.listen(db.engine, "after_cursor_execute", sql_executed)
        self.stack.callback(event.remove, db.engine, "after_cursor_execute", sql_executed)
        self.client = app.test_client()

    def cleanup_rows(self):
        db.session.rollback()
        ProcessedPayment.query.filter_by(payment_id=self.payment_id).delete()
        Order.query.filter_by(email=self.payload["email"]).delete()
        db.session.commit()
        self.assertEqual(ProcessedPayment.query.filter_by(payment_id=self.payment_id).count(), 0)
        self.assertEqual(Order.query.filter_by(email=self.payload["email"]).count(), 0)
        db.session.remove()

    def read_order(self):
        # Every phase reads persisted data through a fresh ORM session.
        db.session.remove()
        self.assertEqual(Order.query.count(), self.before_orders + 1)
        self.assertEqual(Order.query.filter_by(email=self.payload["email"]).count(), 1)
        self.assertEqual(Order.query.filter_by(razorpay_order_id=self.rp_order).count(), 1)
        order = db.session.get(Order, self.order_id)
        self.assertIsNotNone(order)
        for field, value in self.payload.items():
            self.assertEqual(getattr(order, field), value, field)
        self.assertEqual(order.amount_paise, 5100)
        self.assertEqual(order.razorpay_order_id, self.rp_order)
        self.assertEqual(order.email_status, "NOT_ATTEMPTED")
        self.assertIsNone(order.pdf_url)
        return order

    def assert_claim(self, expected):
        claims = ProcessedPayment.query.filter(
            (ProcessedPayment.payment_id == self.payment_id) |
            (ProcessedPayment.reference == self.rp_order)
        ).all()
        self.assertEqual(len(claims), expected)
        for claim in claims:
            self.assertIsNotNone(claim.order_id, "Historical NULL-order claim must never recur")
            self.assertEqual(claim.order_id, self.order_id)
            self.assertEqual(claim.payment_id, self.payment_id)
            self.assertEqual(claim.reference, self.rp_order)
            self.assertEqual(claim.provider, "RAZORPAY")

    def create_pending(self):
        response = self.client.post("/api/razorpay-order", json=self.payload)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.order_id = body["internal_order_id"]
        self.assertEqual(body["amount"], 5100)
        self.assertEqual(body["order_id"], self.rp_order)
        self.create_remote.assert_called_once()
        self.assertEqual(self.create_remote.call_args.args[0]["amount"], 5100)
        order = self.read_order()
        self.assertEqual(order.payment_status, "PAYMENT_PENDING")
        self.assertEqual(order.status, "PENDING")
        self.assertIsNone(order.razorpay_payment_id)
        self.assertEqual(order.report_stage, "Pending")
        self.assert_claim(0)
        self.assertEqual(self.finalizations, [])
        self.assertEqual(self.dispatches, [])
        self.assertEqual(self.ownership_transitions, [])
        self.thread.assert_not_called()

    def server_callback(self):
        # Intentionally has NO product, customer/birth data, notes or internal ID.
        body = json.dumps({"event": "payment.captured", "payload": {"payment": {
            "entity": {"id": self.payment_id, "order_id": self.rp_order}
        }}}, separators=(",", ":"))
        signature = hmac.new(self.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return self.client.post("/webhook", data=body, content_type="application/json",
                                headers={"X-Razorpay-Signature": signature})

    def browser_callback(self):
        signature = hmac.new(b"step2-synthetic-secret",
                             f"{self.rp_order}|{self.payment_id}".encode(),
                             hashlib.sha256).hexdigest()
        return self.client.post("/webhook", json={
            "razorpay_order_id": self.rp_order, "razorpay_payment_id": self.payment_id,
            "razorpay_signature": signature,
        })

    def assert_success(self, response, status):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], status)
        self.assertEqual(response.get_json()["order_id"], self.order_id)

    def assert_paid(self, stage="Queued", dispatch_count=1):
        order = self.read_order()
        self.assertEqual(order.payment_status, "PAID")
        self.assertEqual(order.status, "PAID")
        self.assertEqual(order.razorpay_payment_id, self.payment_id)
        self.assertEqual(order.report_stage, stage)
        self.assert_claim(1)
        self.assertEqual(self.inserted_claims, [self.order_id])
        self.assertEqual(self.dispatches, [Dispatch.DISPATCHED] * dispatch_count)
        self.assertEqual(self.ownership_transitions, [1] * dispatch_count)
        self.assertEqual(self.thread.call_count, dispatch_count)
        self.assertEqual(self.thread.return_value.start.call_count, dispatch_count)
        if dispatch_count:
            self.thread.assert_called_once_with(target=self.generator,
                                                args=(self.order_id,), daemon=True)
        self.generator.assert_not_called()
        self.email.assert_not_called()
        self.smtp.assert_not_called()

    def duplicate_storm(self):
        # Ten duplicate completions, alternating five server and five browser.
        for index in range(10):
            with self.subTest(duplicate=index + 1):
                response = self.server_callback() if index % 2 == 0 else self.browser_callback()
                self.assert_success(response, "already_processing")
                self.assertEqual(self.finalizations[-1], Finalization.ALREADY_FINALIZED)
                self.assert_paid()

    def test_server_first_browser_second_and_ten_duplicates(self):
        self.create_pending()
        self.assert_success(self.server_callback(), "success")
        self.signature_check.assert_called_once()
        self.fetch_remote.assert_called_once_with(self.payment_id)
        self.assertEqual(self.finalizations, [Finalization.FINALIZED])
        self.assert_paid()
        self.assert_success(self.browser_callback(), "already_processing")
        self.assert_paid()
        self.duplicate_storm()
        self.assertEqual(self.finalizations,
                         [Finalization.FINALIZED] + [Finalization.ALREADY_FINALIZED] * 11)
        self.fetch_remote.assert_called_once_with(self.payment_id)

    def test_real_finalization_crash_before_dispatch_then_duplicate_recovery(self):
        self.create_pending()
        self.crash_after_finalization = True
        with self.assertRaises(SimulatedProcessDeath):
            self.server_callback()
        self.assertEqual(self.finalizations, [Finalization.FINALIZED])
        self.assert_paid(stage="Pending", dispatch_count=0)
        self.crash_after_finalization = False
        self.assert_success(self.browser_callback(), "recovered_success")
        self.assertEqual(self.finalizations[-1], Finalization.ALREADY_FINALIZED)
        self.assert_paid()
        self.duplicate_storm()
        self.fetch_remote.assert_called_once_with(self.payment_id)

    def test_amount_mismatch_never_claims_or_dispatches(self):
        self.create_pending()
        self.fetch_remote.return_value["amount"] = 5000
        response = self.server_callback()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "amount_mismatch")
        self.signature_check.assert_called_once()
        self.fetch_remote.assert_called_once_with(self.payment_id)
        self.assertEqual(self.finalizations, [Finalization.AMOUNT_MISMATCH])
        order = self.read_order()
        self.assertEqual(order.payment_status, "PAYMENT_PENDING")
        self.assertEqual(order.status, "PENDING")
        self.assertIsNone(order.razorpay_payment_id)
        self.assertEqual(order.report_stage, "Pending")
        self.assert_claim(0)
        self.assertEqual(self.inserted_claims, [])
        self.assertEqual(self.dispatches, [])
        self.assertEqual(self.ownership_transitions, [])
        self.thread.assert_not_called()
        self.generator.assert_not_called()
        self.email.assert_not_called()
        self.smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
