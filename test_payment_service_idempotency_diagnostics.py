"""
test_payment_service_idempotency_diagnostics.py
----------------------------------
Regression + diagnostic-loss fix for the silent HTTP 500 in
POST /api/reports/google/confirm (production correlation_id
8c85db2690294b8ebebf40f30ebaf5f3, product=sadhesati_report).

Root cause: ProcessedPayment.payment_id/.reference were VARCHAR(120) --
a bound copied from Razorpay's own short payment_id -- but a real
Google Play purchase_token is commonly 150-190+ characters. Inserting
one raised sqlalchemy.exc.DataError (StringDataRightTruncation), a
DIFFERENT exception class from the IntegrityError PaymentService.
_try_claim() already handled for its own, unrelated purpose (a genuine
concurrent-claim race). Uncaught, it propagated silently past every
log_payment_event() call in process_payment() straight to the route's
generic except-Exception-500, with zero trace in the logs.

Fix (two parts, both tested here):
  1. Migration 9f4d2a7e1c6b widens payment_id/reference to VARCHAR(255)
     -- the actual root-cause fix.
  2. PaymentService.process_payment()'s previously-unprotected
     idempotency-claim zone (_find_processed_payment/_try_claim) now
     logs any exception (exc_info=True) before re-raising, so this
     CLASS of invisible-500 can never recur silently again, whatever
     its cause.

Uses the LOCAL scratch Postgres DB ONLY (already widened locally for
this test run -- see the diagnosis session's own repro). GooglePlayProvider
is monkeypatched -- NO real Google Play API call is ever made.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from models import Order  # noqa: E402
from modules.models_processed_payments import ProcessedPayment  # noqa: E402
from modules.payments.google_play_provider import GooglePlayProvider  # noqa: E402
from modules.payments.payment_models import (  # noqa: E402
    PaymentProviderType,
    PaymentPurpose,
    PaymentRequest,
    PaymentStatus,
    PaymentVerificationResult,
)
import modules.payments.payment_service as payment_service_module  # noqa: E402
from modules.payments.payment_service import PaymentService  # noqa: E402

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


# A realistic Google Play purchase token length -- real ones are
# commonly 150-190+ characters, well past the old VARCHAR(120) bound.
LONG_TOKEN_A = "lmssjcojemplatampcugbfeaoj1owaj" + ("A" * 140)
LONG_TOKEN_B = "lmssjcojemplatampcugbfeaoj1owaj" + ("B" * 140)
SHORT_TOKEN = "pay_ShortRazorpayStyleId123"  # legacy-length, must remain unaffected


def cleanup():
    for token in (LONG_TOKEN_A, LONG_TOKEN_B, SHORT_TOKEN, "race-token"):
        claim = ProcessedPayment.query.filter_by(payment_id=token).first()
        if claim is not None and claim.order_id is not None:
            Order.query.filter_by(id=claim.order_id).delete()
        ProcessedPayment.query.filter_by(payment_id=token).delete()
    db.session.commit()


def fake_verify(self, request):
    return PaymentVerificationResult(
        status=PaymentStatus.VERIFIED,
        provider=PaymentProviderType.GOOGLE_PLAY,
        reference=request.reference,
        verified=True,
        message="Google Play verification: VERIFIED",
        raw_payload={},
    )


def report_request(payment_id, name_suffix=""):
    return PaymentRequest(
        provider=PaymentProviderType.GOOGLE_PLAY,
        purpose=PaymentPurpose.REPORT_PURCHASE,
        reference=payment_id,
        payment_id=payment_id,
        order_payload={
            "name": f"Diag Test{name_suffix}",
            "email": f"diag-500{name_suffix}@example.com",
            "product": "sadhesati_report",
            "dob": "1990-01-01",
            "tob": "10:00",
            "pob": "Delhi, India",
        },
        metadata={"product_id": "sadhesati_report"},
    )


class LogCapture:
    """Replaces payment_service_module.log_payment_event entirely for
    the duration of a test -- records every call so tests can assert
    exactly what was (or wasn't) logged, including exc_info."""

    def __init__(self):
        self.events = []

    def __call__(self, event, *, correlation_id, status, provider=None, product=None,
                 razorpay_order_id=None, razorpay_payment_id=None, email=None,
                 order_id=None, error=None, exc_info=False):
        self.events.append({
            "event": event, "status": status, "error": error, "exc_info": exc_info,
        })

    def has(self, event_name, exc_info=None):
        for e in self.events:
            if e["event"] == event_name and (exc_info is None or e["exc_info"] == exc_info):
                return True
        return False


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        real_verify = GooglePlayProvider.verify
        GooglePlayProvider.verify = fake_verify

        try:
            # ==========================================================
            print("=== A: long (171-char) Google Play purchase_token now succeeds end-to-end ===")
            # ==========================================================
            result_a = PaymentService().process_payment(report_request(LONG_TOKEN_A, "A"))
            check("A: no exception, VERIFIED returned", result_a.status == PaymentStatus.VERIFIED)
            check("A: order_id present in raw_payload", result_a.raw_payload is not None and result_a.raw_payload.get("order_id") is not None)
            order_a = Order.query.get(result_a.raw_payload["order_id"])
            check("A: Order row actually created", order_a is not None)
            claim_a = ProcessedPayment.query.filter_by(payment_id=LONG_TOKEN_A).first()
            check("A: ProcessedPayment claim stored the FULL 171-char token, not truncated", claim_a is not None and claim_a.payment_id == LONG_TOKEN_A)
            check("A: ProcessedPayment claim finalized with the order_id", claim_a is not None and claim_a.order_id == order_a.id)

            # ==========================================================
            print("\n=== B: short/legacy-length token unaffected by the widening ===")
            # ==========================================================
            result_b = PaymentService().process_payment(report_request(SHORT_TOKEN, "B"))
            check("B: short token still succeeds", result_b.status == PaymentStatus.VERIFIED)
            claim_b = ProcessedPayment.query.filter_by(payment_id=SHORT_TOKEN).first()
            check("B: short token stored correctly", claim_b is not None and claim_b.payment_id == SHORT_TOKEN)

            # ==========================================================
            print("\n=== C: genuine concurrent-claim race (IntegrityError) still returns False, not an exception ===")
            # ==========================================================
            race_request = report_request("race-token", "C")
            first_claim_ok = PaymentService()._try_claim(race_request)
            second_claim_ok = PaymentService()._try_claim(race_request)
            check("C: first claim wins", first_claim_ok is True)
            check("C: second (racing) claim correctly loses -- False, not an exception", second_claim_ok is False)
            rows = ProcessedPayment.query.filter_by(payment_id="race-token").all()
            check("C: exactly ONE claim row exists despite two attempts", len(rows) == 1)

            # ==========================================================
            print("\n=== D: an unexpected exception in the idempotency LOOKUP is now logged, not silent ===")
            # ==========================================================
            capture_d = LogCapture()
            real_log_fn = payment_service_module.log_payment_event
            payment_service_module.log_payment_event = capture_d

            real_find = PaymentService._find_processed_payment

            def boom_find(self, request):
                raise RuntimeError("simulated unexpected DB failure in lookup")

            PaymentService._find_processed_payment = boom_find

            threw_d = False
            try:
                PaymentService().process_payment(report_request("tok-d-unused", "D"))
            except RuntimeError:
                threw_d = True
            finally:
                PaymentService._find_processed_payment = real_find
                payment_service_module.log_payment_event = real_log_fn

            check("D: exception still propagates (never swallowed)", threw_d is True)
            check("D: idempotency_lookup_exception WAS logged with a traceback (exc_info=True)", capture_d.has("idempotency_lookup_exception", exc_info=True))

            # ==========================================================
            print("\n=== E: an unexpected exception in the CLAIM step is now logged, not silent (this is the exact shape of the production bug) ===")
            # ==========================================================
            capture_e = LogCapture()
            payment_service_module.log_payment_event = capture_e

            real_try_claim = PaymentService._try_claim

            def boom_claim(self, request):
                raise RuntimeError("simulated unexpected DB failure in claim (e.g. a DataError)")

            PaymentService._try_claim = boom_claim

            threw_e = False
            try:
                PaymentService().process_payment(report_request("tok-e-unused", "E"))
            except RuntimeError:
                threw_e = True
            finally:
                PaymentService._try_claim = real_try_claim
                payment_service_module.log_payment_event = real_log_fn

            check("E: exception still propagates (never swallowed)", threw_e is True)
            check("E: idempotency_claim_exception WAS logged with a traceback (exc_info=True)", capture_e.has("idempotency_claim_exception", exc_info=True))

        finally:
            GooglePlayProvider.verify = real_verify

        cleanup()

    # ==========================================================
    print("\n=== F: route-level end-to-end -- long token via the real HTTP route ===")
    # ==========================================================
    with app.app_context():
        cleanup()
        real_verify2 = GooglePlayProvider.verify
        GooglePlayProvider.verify = fake_verify
        try:
            client = app.test_client()
            resp = client.post(
                "/api/reports/google/confirm",
                json={
                    "purchase_token": LONG_TOKEN_B,
                    "product_id": "sadhesati_report",
                    "name": "Route Test", "email": "diag-500-route@example.com",
                    "product": "sadhesati_report", "dob": "1990-01-01",
                    "tob": "10:00", "pob": "Delhi, India",
                },
            )
            check("F: route returns 200, not 500", resp.status_code == 200)
            body = resp.get_json()
            check("F: response carries a real order_id", body is not None and body.get("order_id") is not None)
        finally:
            GooglePlayProvider.verify = real_verify2
        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
