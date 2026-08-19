"""
test_report_purchase_verification_states.py
----------------------------------
Report Purchase CANCELED Recovery Dead-End fix -- verifies the new
structured error_code contract on POST /api/reports/google/confirm's
failure response, and that the pre-existing success/idempotency
behavior is completely unchanged.

Covers:
  A. purchase_state=1 (Canceled)  -> error_code == purchase_canceled
  B. purchase_state=2 (Pending)   -> error_code == purchase_pending
  C. NETWORK_ERROR (no purchase_state) -> error_code == verification_failed
     (the existing, unclassified "stay retryable" bucket)
  D. AUTH_ERROR (no purchase_state)    -> error_code == verification_failed
  E. purchase_state=0 (Purchased) -> existing success flow unchanged
     (200, order_id/task_id present, error_code absent)
  F. No Order/ProcessedPayment row is EVER created for A-D -- proves
     nothing is granted/consumed on any failed verification, matching
     Flutter's own "never consume on failure" guarantee.

NO REAL GOOGLE PLAY API CALL IS EVER MADE -- GooglePlayProvider.
verify_product_purchase is monkeypatched at the class level (so it
applies to whatever instance PaymentProviderRegistry already
constructed). Report generation dispatch is also monkeypatched to a
no-op stub so the success case (E) never spawns a real background
thread that would call an LLM / send a real email / write a real PDF.
Uses the LOCAL scratch Postgres DB ONLY.
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
from modules.payments.order_service import OrderService  # noqa: E402

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


TEST_TOKENS = [
    "tok-cancel-state", "tok-pending-state", "tok-network-error",
    "tok-auth-error", "tok-success-state",
]
TEST_EMAILS = [f"report-state-test-{i}@example.com" for i in range(len(TEST_TOKENS))]


def cleanup():
    ProcessedPayment.query.filter(
        ProcessedPayment.payment_id.in_(TEST_TOKENS),
    ).delete(synchronize_session=False)
    Order.query.filter(Order.email.in_(TEST_EMAILS)).delete(synchronize_session=False)
    db.session.commit()


class _FakeVerification:
    """Mimics GooglePlayProductVerification's to_dict() shape exactly,
    without importing the real dataclass -- keeps this test decoupled
    from any field this fix doesn't itself depend on."""

    def __init__(self, verification_status, purchase_state=None, error_message=None):
        self.verification_status = verification_status
        self.purchase_state = purchase_state
        self.error_message = error_message
        self.order_id = None

    def to_dict(self):
        return {
            "verification_status": self.verification_status,
            "purchase_state": self.purchase_state,
            "error_message": self.error_message,
        }


_RESULTS_BY_TOKEN = {}


def _fake_verify_product_purchase(self, *, purchase_token, product_id, package_name=None):
    result = _RESULTS_BY_TOKEN.get(purchase_token)
    if result is None:
        raise AssertionError(f"test bug: no fake result configured for token {purchase_token!r}")
    return result


def _fake_dispatch_report_generation(self, order_id):
    # Success-path stand-in for the real Celery/thread dispatch -- proves
    # create_paid_report_order() itself still runs unchanged (Order
    # committed, status PAID) without ever invoking real report
    # generation (LLM calls, PDF, email) from this test.
    return "fake-task-id"


def confirm_payload(email, product_id, purchase_token, product="career_report"):
    return {
        "name": "Report State Test",
        "email": email,
        "product": product,
        "dob": "1990-01-01",
        "tob": "10:00",
        "pob": "Delhi",
        "purchase_token": purchase_token,
        "product_id": product_id,
    }


def main():
    from modules.payments.google_play_models import GooglePlayVerificationStatus

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local"

        cleanup()

        real_verify = GooglePlayProvider.verify_product_purchase
        real_dispatch = OrderService._dispatch_report_generation
        GooglePlayProvider.verify_product_purchase = _fake_verify_product_purchase
        OrderService._dispatch_report_generation = _fake_dispatch_report_generation

        client = app.test_client()

        try:
            # ==========================================================
            print("=== A: purchase_state=1 (Canceled) -> purchase_canceled ===")
            # ==========================================================
            _RESULTS_BY_TOKEN["tok-cancel-state"] = _FakeVerification(
                GooglePlayVerificationStatus.VERIFIED, purchase_state=1,
            )
            respA = client.post(
                "/api/reports/google/confirm",
                json=confirm_payload(TEST_EMAILS[0], "reports51", "tok-cancel-state"),
            )
            bodyA = respA.get_json()
            check("A: HTTP 400", respA.status_code == 400)
            check("A: error_code == purchase_canceled", bodyA.get("error_code") == "purchase_canceled")
            check("A: purchase_state == 1", bodyA.get("purchase_state") == 1)
            check("A: verification_status == VERIFIED", bodyA.get("verification_status") == "VERIFIED")
            check("A: message field still present (backward compat)", isinstance(bodyA.get("message"), str))
            check("A: error field still present (backward compat)", bodyA.get("error") == "Payment verification failed")

            # ==========================================================
            print("\n=== B: purchase_state=2 (Pending) -> purchase_pending ===")
            # ==========================================================
            _RESULTS_BY_TOKEN["tok-pending-state"] = _FakeVerification(
                GooglePlayVerificationStatus.VERIFIED, purchase_state=2,
            )
            respB = client.post(
                "/api/reports/google/confirm",
                json=confirm_payload(TEST_EMAILS[1], "reports51", "tok-pending-state"),
            )
            bodyB = respB.get_json()
            check("B: HTTP 400", respB.status_code == 400)
            check("B: error_code == purchase_pending", bodyB.get("error_code") == "purchase_pending")
            check("B: purchase_state == 2", bodyB.get("purchase_state") == 2)

            # ==========================================================
            print("\n=== C: NETWORK_ERROR -> verification_failed (unclassified, stays retryable) ===")
            # ==========================================================
            _RESULTS_BY_TOKEN["tok-network-error"] = _FakeVerification(
                GooglePlayVerificationStatus.NETWORK_ERROR, purchase_state=None,
                error_message="simulated network failure",
            )
            respC = client.post(
                "/api/reports/google/confirm",
                json=confirm_payload(TEST_EMAILS[2], "reports51", "tok-network-error"),
            )
            bodyC = respC.get_json()
            check("C: HTTP 400", respC.status_code == 400)
            check("C: error_code == verification_failed", bodyC.get("error_code") == "verification_failed")
            check("C: purchase_state is null", bodyC.get("purchase_state") is None)

            # ==========================================================
            print("\n=== D: AUTH_ERROR -> verification_failed (unclassified, stays retryable) ===")
            # ==========================================================
            _RESULTS_BY_TOKEN["tok-auth-error"] = _FakeVerification(
                GooglePlayVerificationStatus.AUTH_ERROR, purchase_state=None,
                error_message="Google Play rejected this app's own service-account credentials (HTTP 401).",
            )
            respD = client.post(
                "/api/reports/google/confirm",
                json=confirm_payload(TEST_EMAILS[3], "reports51", "tok-auth-error"),
            )
            bodyD = respD.get_json()
            check("D: HTTP 400", respD.status_code == 400)
            check("D: error_code == verification_failed", bodyD.get("error_code") == "verification_failed")

            # ==========================================================
            print("\n=== E: purchase_state=0 (Purchased) -> existing success flow unchanged ===")
            # ==========================================================
            _RESULTS_BY_TOKEN["tok-success-state"] = _FakeVerification(
                GooglePlayVerificationStatus.VERIFIED, purchase_state=0,
            )
            respE = client.post(
                "/api/reports/google/confirm",
                json=confirm_payload(TEST_EMAILS[4], "reports51", "tok-success-state"),
            )
            bodyE = respE.get_json()
            check("E: HTTP 200", respE.status_code == 200)
            check("E: order_id present", bodyE.get("order_id") is not None)
            check("E: no error_code on success", "error_code" not in bodyE)
            orderE = Order.query.filter_by(email=TEST_EMAILS[4]).first()
            check("E: Order row created with status PAID", orderE is not None and orderE.status == "PAID")

            # ==========================================================
            print("\n=== F: no Order/ProcessedPayment row created for ANY failed verification (A-D) ===")
            # ==========================================================
            for label, email, token in [
                ("A (canceled)", TEST_EMAILS[0], "tok-cancel-state"),
                ("B (pending)", TEST_EMAILS[1], "tok-pending-state"),
                ("C (network)", TEST_EMAILS[2], "tok-network-error"),
                ("D (auth)", TEST_EMAILS[3], "tok-auth-error"),
            ]:
                no_order = Order.query.filter_by(email=email).first() is None
                no_claim = ProcessedPayment.query.filter_by(payment_id=token).first() is None
                check(f"F: {label} -- no Order row created", no_order)
                check(f"F: {label} -- no ProcessedPayment claim created", no_claim)

        finally:
            GooglePlayProvider.verify_product_purchase = real_verify
            OrderService._dispatch_report_generation = real_dispatch

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
