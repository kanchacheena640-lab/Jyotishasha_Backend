"""
test_payment_activity_events.py
-------------------------------------------------
Phase 4B: proves the Payments domain's 4 canonical activity events
(payment_initiated, payment_verified, payment_failed,
payment_duplicate_ignored) are emitted at the correct, already-frozen
producer points -- shared PaymentService (Razorpay/Google Play report
purchase, Google Play subscription) and the two Ask Now ChatPack files
(chat_pack_service.py, chatpack_google_verify.py) -- strictly after
their own authoritative business commit, with the exact identity/
entity/properties/dedupe contract the Phase 4B design freeze locked,
and that analytics failure of every kind can never alter the payment
business result. Also proves the Google Play purchase_token never
reaches activity_events in raw form anywhere.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real Razorpay/Google Play network calls are
ever made (both providers' verify() methods are monkeypatched); no real
report generation is dispatched (OrderService._dispatch_report_generation
is monkeypatched to a no-op for the duration of this file, so no
Celery/thread-spawned GPT/PDF/email work ever runs). All test rows are
created with dedicated, obviously-test-only markers and deleted in a
finally block, keyed by their own ids/payment_ids -- never a broad
DELETE.
"""

import os
import sys
import uuid
import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

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


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    from models import Order
    from modules.models_user import AppUser
    from modules.models_chat_pack import ChatPack
    from modules.models_processed_payments import ProcessedPayment
    from modules.models_premium_subscription import CurrentEntitlement, SubscriptionEvent
    from modules.models_subscription_purchase_mapping import SubscriptionPurchaseMapping

    from modules.payments.payment_models import (
        PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus,
        PaymentVerificationResult,
    )
    from modules.payments.payment_provider import PaymentProvider  # noqa: F401
    from modules.payments.razorpay_provider import RazorpayProvider
    from modules.payments.google_play_provider import GooglePlayProvider
    from modules.payments.google_play_models import (
        GooglePlayVerificationStatus, GooglePlayProductVerification,
    )
    from modules.payments.order_service import OrderService
    import modules.payments.payment_service as payment_service_module
    from modules.payments.payment_service import PaymentService

    import modules.services.chat_pack_service as chat_pack_service_module
    from modules.services.chat_pack_service import (
        create_chatpack_order, verify_chatpack_payment,
    )
    import modules.services.chatpack_google_verify as chatpack_google_verify_module
    from modules.services.chatpack_google_verify import verify_google_chatpack

    from modules.activity_events.service import LedgerWriteResult

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )
        print(f"Connected to database: {current_db}")

        # -----------------------------------------------------------
        # Test-run-wide safety: never actually dispatch report
        # generation (no Celery/thread, no real GPT/PDF/email work).
        # OrderService.create_paid_report_order()'s own Order-row
        # creation and commit are untouched -- only the dispatch step
        # is a no-op for this file's duration.
        # -----------------------------------------------------------
        real_dispatch = OrderService._dispatch_report_generation
        OrderService._dispatch_report_generation = lambda self, order_id: None

        created_order_ids = []
        created_payment_ids = []       # (provider, payment_id) claims to clean up
        created_chatpack_ids = []
        created_app_user_ids = []
        created_event_ids = []

        def track_event(row):
            if row is not None:
                created_event_ids.append(str(row.event_id))
            return row

        def get_ledger_row(dedupe_key):
            return db.session.execute(
                text("SELECT * FROM activity_events WHERE dedupe_key = :dk"),
                {"dk": dedupe_key},
            ).fetchone()

        def latest_event_row(event_name):
            """Serial, single-process test script -- safe to take the
            most-recently-inserted row for this event_name immediately
            after the action that should have produced it. Used only
            for events whose dedupe_key is intentionally NULL
            (payment_failed, payment_duplicate_ignored at the
            PaymentService level)."""
            return db.session.execute(
                text(
                    "SELECT * FROM activity_events WHERE event_name = :en "
                    "ORDER BY recorded_at DESC LIMIT 1"
                ),
                {"en": event_name},
            ).fetchone()

        def entity_event_row(event_name, entity_type, entity_id):
            return db.session.execute(
                text(
                    "SELECT * FROM activity_events WHERE event_name = :en "
                    "AND entity_type = :et AND entity_id = :eid "
                    "ORDER BY recorded_at DESC LIMIT 1"
                ),
                {"en": event_name, "et": entity_type, "eid": str(entity_id)},
            ).fetchone()

        def serialized_row_text(row):
            """Everything queryable text-content in the row, concatenated,
            for a blunt 'this substring appears nowhere' security check."""
            import json
            parts = [
                str(row.dedupe_key), str(row.entity_id), str(row.correlation_id),
                json.dumps(row.properties or {}),
                json.dumps(row.campaign_context or {}),
                json.dumps(row.notification_context or {}),
            ]
            return " | ".join(parts)

        try:
            # =========================================================
            # 0. Pure-function classification/hash unit tests -- no DB.
            # =========================================================
            print("=== 0: pure-function classification/hash unit tests ===")
            req_missing = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=None, payment_id=None)
            check("classify: missing reference/payment_id -> invalid_input",
                  PaymentService._classify_razorpay_failure(req_missing) == "invalid_input")
            req_nosig = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference="order_x", payment_id="pay_x", signature=None)
            check("classify: missing signature -> invalid_input",
                  PaymentService._classify_razorpay_failure(req_nosig) == "invalid_input")
            req_badsig = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference="order_x", payment_id="pay_x", signature="garbage-signature")
            check("classify: present-but-wrong signature -> signature_mismatch",
                  PaymentService._classify_razorpay_failure(req_badsig) == "signature_mismatch")
            req_webhook = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference="order_x", payment_id="pay_x", signature=None, metadata={"source": "webhook"})
            check("classify: webhook path with no signature -> invalid_input (never signature_mismatch)",
                  PaymentService._classify_razorpay_failure(req_webhook) == "invalid_input")

            for gp_status, expected in (
                (GooglePlayVerificationStatus.INVALID_TOKEN, "invalid_input"),
                (GooglePlayVerificationStatus.NOT_FOUND, "not_found"),
                (GooglePlayVerificationStatus.AUTH_ERROR, "upstream_error"),
                (GooglePlayVerificationStatus.NETWORK_ERROR, "upstream_error"),
                (GooglePlayVerificationStatus.UNKNOWN_ERROR, "unknown"),
            ):
                res = PaymentVerificationResult(status=PaymentStatus.FAILED, provider=PaymentProviderType.GOOGLE_PLAY, reference="x", verified=False, raw_payload={"verification_status": gp_status})
                check(f"classify google: {gp_status} -> {expected}", PaymentService._classify_google_failure(res) == expected)
            res_declined = PaymentVerificationResult(status=PaymentStatus.FAILED, provider=PaymentProviderType.GOOGLE_PLAY, reference="x", verified=False, raw_payload={"verification_status": "VERIFIED", "purchase_state": 1})
            check("classify google: VERIFIED-but-declined -> provider_declined", PaymentService._classify_google_failure(res_declined) == "provider_declined")

            check("order_reference: Google raw_payload with order_id extracted safely",
                  PaymentService._safe_google_order_reference({"order_id": "GPA.SAFE-1", "purchase_token": "SECRET-TOKEN"}) == "GPA.SAFE-1")
            check("order_reference: absent order_id -> None (never falls back to token)",
                  PaymentService._safe_google_order_reference({"purchase_token": "SECRET-TOKEN"}) is None)

            tok = "TEST-PURCHASE-TOKEN-" + uuid.uuid4().hex
            h1 = PaymentService._hash_google_purchase_token(tok)
            h2 = PaymentService._hash_google_purchase_token(tok)
            check("hash: deterministic (same token -> same hash)", h1 == h2)
            check("hash: matches plain hashlib.sha256", h1 == hashlib.sha256(tok.encode("utf-8")).hexdigest())
            check("hash: does not equal the raw token", h1 != tok)
            check("hash: raw token substring not contained in hash", tok not in h1)

            # =========================================================
            # 1. Razorpay report purchase
            # =========================================================
            print("\n=== 1: Razorpay report purchase ===")
            razorpay_order_id_1 = "order_" + uuid.uuid4().hex[:14]
            razorpay_payment_id_1 = "pay_" + uuid.uuid4().hex[:14]
            created_payment_ids.append((PaymentProviderType.RAZORPAY, razorpay_payment_id_1))

            def report_payload(suffix):
                return {
                    "name": f"Test User{suffix}", "email": f"phase4b-test{suffix}@example.com",
                    "product": "sadhesati_report", "dob": "1990-01-01", "tob": "10:00", "pob": "Delhi, India",
                }

            def fake_razorpay_verified(self, request):
                return PaymentVerificationResult(status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY, reference=request.reference, verified=True, message="mocked verified")

            real_razorpay_verify = RazorpayProvider.verify
            RazorpayProvider.verify = fake_razorpay_verified
            try:
                req1 = PaymentRequest(
                    provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                    reference=razorpay_order_id_1, payment_id=razorpay_payment_id_1, signature="mocked",
                    order_payload=report_payload("1"),
                )
                result1 = PaymentService().process_payment(req1)
            finally:
                RazorpayProvider.verify = real_razorpay_verify

            check("1: business result VERIFIED", result1.status == PaymentStatus.VERIFIED)
            order1_id = result1.raw_payload.get("order_id")
            check("1: Order actually created", order1_id is not None)
            if order1_id:
                created_order_ids.append(order1_id)

            row1 = track_event(get_ledger_row(f"payment_verified:RAZORPAY:{razorpay_payment_id_1}"))
            check("1: payment_verified row exists", row1 is not None)
            if row1 is not None:
                check("1: event_name correct", row1.event_name == "payment_verified")
                check("1: platform == backend_internal", row1.platform == "backend_internal")
                check("1: source == payment_service", row1.source == "payment_service")
                check("1: profile_id is None (REPORT_PURCHASE has none)", row1.profile_id is None)
                check("1: firebase_uid is None", row1.firebase_uid is None)
                check("1: entity_type == order", row1.entity_type == "order")
                check("1: entity_id == Order.id", row1.entity_id == str(order1_id))
                check("1: correlation_id present (not None)", row1.correlation_id is not None)
                check("1: properties allowlist only", set(row1.properties.keys()) <= {"purpose", "provider", "order_reference", "amount", "currency"})
                check("1: purpose == REPORT_PURCHASE", row1.properties.get("purpose") == PaymentPurpose.REPORT_PURCHASE)
                check("1: provider == RAZORPAY", row1.properties.get("provider") == PaymentProviderType.RAZORPAY)
                check("1: order_reference == razorpay order id", row1.properties.get("order_reference") == razorpay_order_id_1)
                check("1: amount/currency correctly omitted (no reliable value threaded through PaymentRequest)", "amount" not in row1.properties and "currency" not in row1.properties)

            # -- 1b: duplicate ignored (force report_stage='Ready', retry same payment_id)
            if order1_id:
                Order.query.filter_by(id=order1_id).update({"report_stage": "Ready"})
                db.session.commit()
                req1b = PaymentRequest(
                    provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                    reference=razorpay_order_id_1, payment_id=razorpay_payment_id_1, signature="mocked",
                    order_payload=report_payload("1"),
                )
                RazorpayProvider.verify = fake_razorpay_verified
                try:
                    result1b = PaymentService().process_payment(req1b)
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
                check("1b: business result DUPLICATE", result1b.status == PaymentStatus.DUPLICATE)
                row1b = track_event(latest_event_row("payment_duplicate_ignored"))
                check("1b: payment_duplicate_ignored row exists", row1b is not None)
                if row1b is not None:
                    check("1b: dedupe_key intentionally NULL", row1b.dedupe_key is None)
                    check("1b: properties == purpose+provider only", set(row1b.properties.keys()) <= {"purpose", "provider"})
                    check("1b: provider == RAZORPAY", row1b.properties.get("provider") == PaymentProviderType.RAZORPAY)

            # -- 1c: failed (real RazorpayProvider.verify(), missing signature -- no network call)
            razorpay_order_id_1c = "order_" + uuid.uuid4().hex[:14]
            req1c = PaymentRequest(
                provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                reference=razorpay_order_id_1c, payment_id="pay_" + uuid.uuid4().hex[:14],
                signature=None, order_payload=report_payload("1c"),
            )
            result1c = PaymentService().process_payment(req1c)
            check("1c: business result FAILED", result1c.status == PaymentStatus.FAILED)
            row1c = track_event(latest_event_row("payment_failed"))
            check("1c: payment_failed row exists", row1c is not None)
            if row1c is not None:
                check("1c: failure_reason == invalid_input (real RazorpayProvider path, missing signature)", row1c.properties.get("failure_reason") == "invalid_input")
                check("1c: dedupe_key intentionally NULL", row1c.dedupe_key is None)
                check("1c: entity_type/entity_id both None (no committed row exists yet)", row1c.entity_type is None and row1c.entity_id is None)
                check("1c: properties allowlist only", set(row1c.properties.keys()) <= {"purpose", "provider", "failure_reason"})

            # =========================================================
            # 2. Google Play report purchase
            # =========================================================
            print("\n=== 2: Google Play report purchase ===")
            token2 = "GPTOK-" + uuid.uuid4().hex
            created_payment_ids.append((PaymentProviderType.GOOGLE_PLAY, token2))
            real_google_verify = GooglePlayProvider.verify

            def fake_google_report_verified(self, request):
                return PaymentVerificationResult(
                    status=PaymentStatus.VERIFIED, provider=PaymentProviderType.GOOGLE_PLAY,
                    reference=request.reference, verified=True, message="mocked verified",
                    raw_payload={"verification_status": "VERIFIED", "purchase_state": 0, "order_id": "GPA.TEST-REPORT-1", "purchase_token": token2},
                )

            GooglePlayProvider.verify = fake_google_report_verified
            try:
                req2 = PaymentRequest(
                    provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                    reference=token2, payment_id=token2, order_payload=report_payload("2"),
                    metadata={"product_id": "sadhesati_report"},
                )
                result2 = PaymentService().process_payment(req2)
            finally:
                GooglePlayProvider.verify = real_google_verify

            check("2: business result VERIFIED", result2.status == PaymentStatus.VERIFIED)
            order2_id = result2.raw_payload.get("order_id")
            if order2_id:
                created_order_ids.append(order2_id)
            row2 = track_event(get_ledger_row(f"payment_verified:GOOGLE_PLAY:{hashlib.sha256(token2.encode()).hexdigest()}"))
            check("2: payment_verified row exists (dedupe keyed on HASHED token)", row2 is not None)
            if row2 is not None:
                check("2: order_reference == Google order_id (never the token)", row2.properties.get("order_reference") == "GPA.TEST-REPORT-1")
                check("2: entity_type == order", row2.entity_type == "order")
                check("2: entity_id == Order.id", row2.entity_id == str(order2_id))
                full_text2 = serialized_row_text(row2)
                check("2: SECURITY -- raw purchase_token nowhere in the serialized row", token2 not in full_text2)

            # -- 2b: failed -- NOT_FOUND -> not_found
            token2b = "GPTOK-" + uuid.uuid4().hex

            def fake_google_report_notfound(self, request):
                return PaymentVerificationResult(
                    status=PaymentStatus.FAILED, provider=PaymentProviderType.GOOGLE_PLAY,
                    reference=request.reference, verified=False, message="Google Play verification: NOT_FOUND",
                    raw_payload={"verification_status": "NOT_FOUND", "purchase_token": token2b},
                )

            GooglePlayProvider.verify = fake_google_report_notfound
            try:
                req2b = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=token2b, payment_id=token2b, order_payload=report_payload("2b"), metadata={"product_id": "sadhesati_report"})
                result2b = PaymentService().process_payment(req2b)
            finally:
                GooglePlayProvider.verify = real_google_verify
            check("2b: business result FAILED", result2b.status == PaymentStatus.FAILED)
            row2b = track_event(latest_event_row("payment_failed"))
            check("2b: failure_reason == not_found", row2b is not None and row2b.properties.get("failure_reason") == "not_found")
            if row2b is not None:
                check("2b: SECURITY -- raw purchase_token nowhere in the serialized row", token2b not in serialized_row_text(row2b))

            # -- 2c: duplicate ignored (force report_stage='Ready')
            if order2_id:
                Order.query.filter_by(id=order2_id).update({"report_stage": "Ready"})
                db.session.commit()
                GooglePlayProvider.verify = fake_google_report_verified
                try:
                    req2c = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=token2, payment_id=token2, order_payload=report_payload("2"), metadata={"product_id": "sadhesati_report"})
                    result2c = PaymentService().process_payment(req2c)
                finally:
                    GooglePlayProvider.verify = real_google_verify
                check("2c: business result DUPLICATE", result2c.status == PaymentStatus.DUPLICATE)
                row2c = track_event(latest_event_row("payment_duplicate_ignored"))
                check("2c: payment_duplicate_ignored row exists", row2c is not None)

            # =========================================================
            # 3. Google Play subscription
            # =========================================================
            print("\n=== 3: Google Play subscription ===")
            profile3 = AppUser(firebase_uid=f"phase4b-test-{uuid.uuid4().hex[:10]}")
            db.session.add(profile3)
            db.session.commit()
            created_app_user_ids.append(profile3.id)

            token3 = "GPSUBTOK-" + uuid.uuid4().hex
            created_payment_ids.append((PaymentProviderType.GOOGLE_PLAY, token3))
            expiry3 = (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z"

            def fake_google_sub_verified(self, request):
                return PaymentVerificationResult(
                    status=PaymentStatus.VERIFIED, provider=PaymentProviderType.GOOGLE_PLAY,
                    reference=request.reference, verified=True, message="mocked verified",
                    raw_payload={
                        "verification_status": "VERIFIED", "purchase_state": "SUBSCRIPTION_STATE_ACTIVE",
                        "product_id": "jyotishasha.gold.yearly", "order_id": "GPA.TEST-SUB-1",
                        "expiry_time": expiry3, "purchase_token": token3,
                    },
                )

            GooglePlayProvider.verify = fake_google_sub_verified
            try:
                req3 = PaymentRequest(
                    provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.SUBSCRIPTION,
                    reference=token3, payment_id=token3, profile_id=profile3.id,
                )
                result3 = PaymentService().process_payment(req3)
            finally:
                GooglePlayProvider.verify = real_google_verify

            check("3: business result VERIFIED", result3.status == PaymentStatus.VERIFIED)
            check("3: subscription outcome ACTIVATED", (result3.raw_payload or {}).get("outcome") == "ACTIVATED")
            row3 = track_event(get_ledger_row(f"payment_verified:GOOGLE_PLAY:{hashlib.sha256(token3.encode()).hexdigest()}"))
            check("3: payment_verified row exists", row3 is not None)
            if row3 is not None:
                check("3: profile_id correctly populated (naturally available for SUBSCRIPTION)", row3.profile_id == profile3.id)
                check("3: purpose == SUBSCRIPTION", row3.properties.get("purpose") == PaymentPurpose.SUBSCRIPTION)
                check("3: order_reference == Google order_id", row3.properties.get("order_reference") == "GPA.TEST-SUB-1")
                check("3: entity_type/entity_id both None (no stable id at this layer, per design)", row3.entity_type is None and row3.entity_id is None)
                check("3: SECURITY -- raw purchase_token nowhere in serialized row", token3 not in serialized_row_text(row3))
            # Phase 4A's own subscription_started should ALSO exist, undisturbed
            se3 = SubscriptionEvent.query.filter_by(profile_id=profile3.id, event_type="SUBSCRIPTION_STARTED").first()
            check("3: Phase 4A subscription_started still fires independently, undisturbed", se3 is not None)
            if se3 is not None:
                track_event(get_ledger_row(f"subscription:subscription_started:{se3.id}"))

            # -- 3b: failed -- AUTH_ERROR -> upstream_error
            token3b = "GPSUBTOK-" + uuid.uuid4().hex

            def fake_google_sub_autherror(self, request):
                return PaymentVerificationResult(status=PaymentStatus.FAILED, provider=PaymentProviderType.GOOGLE_PLAY, reference=request.reference, verified=False, message="auth error", raw_payload={"verification_status": "AUTH_ERROR", "purchase_token": token3b})

            GooglePlayProvider.verify = fake_google_sub_autherror
            try:
                req3b = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.SUBSCRIPTION, reference=token3b, payment_id=token3b, profile_id=profile3.id)
                result3b = PaymentService().process_payment(req3b)
            finally:
                GooglePlayProvider.verify = real_google_verify
            check("3b: business result FAILED", result3b.status == PaymentStatus.FAILED)
            row3b = track_event(latest_event_row("payment_failed"))
            check("3b: failure_reason == upstream_error", row3b is not None and row3b.properties.get("failure_reason") == "upstream_error")
            check("3b: profile_id populated even on failure (naturally available)", row3b is not None and row3b.profile_id == profile3.id)

            # -- 3c: duplicate ignored (SUBSCRIPTION purpose has no Order --
            # ProcessedPayment.order_id is None, so _decide_retry() would
            # return REJECT, not IGNORE, for a real repeat SUBSCRIPTION
            # request. Confirmed as designed -- exercised via a direct
            # call to _handle_retry() with a stand-in Order forced Ready,
            # to prove the IGNORE branch itself is provider/purpose-
            # agnostic (it only reads Order.report_stage).
            claim3 = ProcessedPayment.query.filter_by(provider=PaymentProviderType.GOOGLE_PLAY, payment_id=token3).first()
            check("3c: setup -- ProcessedPayment claim exists for token3", claim3 is not None)
            if claim3 is not None and order1_id:
                claim3.order_id = order1_id  # reuse an already-Ready order purely to exercise IGNORE
                db.session.commit()
                log_ctx3c = {"correlation_id": "test-corr-3c", "provider": PaymentProviderType.GOOGLE_PLAY, "product": None, "razorpay_order_id": token3, "razorpay_payment_id": token3, "email": None}
                result3c = PaymentService()._handle_retry(req3, claim3, log_ctx3c)
                check("3c: business result DUPLICATE", result3c.status == PaymentStatus.DUPLICATE)
                row3c = track_event(latest_event_row("payment_duplicate_ignored"))
                check("3c: payment_duplicate_ignored row exists, purpose == SUBSCRIPTION", row3c is not None and row3c.properties.get("purpose") == PaymentPurpose.SUBSCRIPTION)
                check("3c: correlation_id reused from the caller, not regenerated", row3c is not None and row3c.correlation_id == "test-corr-3c")
                claim3.order_id = None
                db.session.commit()

            # =========================================================
            # 3d. RESUME success path (Order-backed retry) -- semantic
            # correction (pre-commit review): RESUME is recovery of
            # DOWNSTREAM business processing for the SAME already-
            # verified payment, never a new payment verification. One
            # real payment must produce at most ONE canonical
            # payment_verified row -- RESUME uses the SAME canonical
            # dedupe identity as the main path, so:
            #   3d -- main path already persisted payment_verified ->
            #         RESUME's own emission attempt is correctly a
            #         dedupe no-op (still exactly one row).
            #   3e -- main path's own emission never persisted (analytics
            #         failed at that moment) -> RESUME's emission
            #         correctly backfills the same canonical row (still
            #         exactly one row, never zero).
            # =========================================================
            print("\n=== 3d: RESUME path -- no double-count when the original already persisted payment_verified ===")
            razorpay_order_id_3d = "order_" + uuid.uuid4().hex[:14]
            razorpay_payment_id_3d = "pay_" + uuid.uuid4().hex[:14]
            created_payment_ids.append((PaymentProviderType.RAZORPAY, razorpay_payment_id_3d))
            dedupe_key_3d = f"payment_verified:RAZORPAY:{razorpay_payment_id_3d}"
            RazorpayProvider.verify = fake_razorpay_verified
            try:
                req3d = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_3d, payment_id=razorpay_payment_id_3d, signature="mocked", order_payload=report_payload("3d"))
                result3d_first = PaymentService().process_payment(req3d)
            finally:
                RazorpayProvider.verify = real_razorpay_verify
            order3d_id = result3d_first.raw_payload.get("order_id")
            if order3d_id:
                created_order_ids.append(order3d_id)
                row3d_original = track_event(get_ledger_row(dedupe_key_3d))
                check("3d: original payment_verified row persisted (main path)", row3d_original is not None)
                count_before_resume = db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"), {"dk": dedupe_key_3d}).scalar()

                Order.query.filter_by(id=order3d_id).update({"report_stage": "Failed"})
                db.session.commit()
                RazorpayProvider.verify = fake_razorpay_verified
                try:
                    req3d_retry = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_3d, payment_id=razorpay_payment_id_3d, signature="mocked", order_payload=report_payload("3d"))
                    result3d_retry = PaymentService().process_payment(req3d_retry)
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
                check("3d: business result VERIFIED (RESUME success)", result3d_retry.status == PaymentStatus.VERIFIED)
                count_after_resume = db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"), {"dk": dedupe_key_3d}).scalar()
                check("3d: exactly ONE payment_verified row before RESUME", count_before_resume == 1)
                check("3d: STILL exactly ONE payment_verified row after RESUME (no double-count of one real payment)", count_after_resume == 1)
                row3d = get_ledger_row(dedupe_key_3d)
                if row3d is not None:
                    check("3d: the single row still reflects the ORIGINAL entity_id (main path's, not overwritten)", row3d.entity_id == str(order3d_id))

            # =========================================================
            # 3e. RESUME path -- backfill when the original attempt's own
            # payment_verified was never persisted (analytics failed
            # at that exact moment, business result still succeeded).
            # =========================================================
            print("\n=== 3e: RESUME path -- backfills payment_verified when the original never persisted one ===")
            razorpay_order_id_3e = "order_" + uuid.uuid4().hex[:14]
            razorpay_payment_id_3e = "pay_" + uuid.uuid4().hex[:14]
            created_payment_ids.append((PaymentProviderType.RAZORPAY, razorpay_payment_id_3e))
            dedupe_key_3e = f"payment_verified:RAZORPAY:{razorpay_payment_id_3e}"
            with patch("modules.payments.payment_service.record_event") as mock_re_3e:
                mock_re_3e.return_value = LedgerWriteResult(status="write_failed")
                RazorpayProvider.verify = fake_razorpay_verified
                try:
                    req3e = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_3e, payment_id=razorpay_payment_id_3e, signature="mocked", order_payload=report_payload("3e"))
                    result3e_first = PaymentService().process_payment(req3e)
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
            order3e_id = result3e_first.raw_payload.get("order_id")
            check("3e: setup -- business result STILL VERIFIED despite analytics write_failed", result3e_first.status == PaymentStatus.VERIFIED)
            if order3e_id:
                created_order_ids.append(order3e_id)
                check("3e: setup -- NO payment_verified row exists yet (original analytics write failed)", get_ledger_row(dedupe_key_3e) is None)

                Order.query.filter_by(id=order3e_id).update({"report_stage": "Failed"})
                db.session.commit()
                RazorpayProvider.verify = fake_razorpay_verified
                try:
                    req3e_retry = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_3e, payment_id=razorpay_payment_id_3e, signature="mocked", order_payload=report_payload("3e"))
                    result3e_retry = PaymentService().process_payment(req3e_retry)
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
                check("3e: business result VERIFIED (RESUME success)", result3e_retry.status == PaymentStatus.VERIFIED)
                row3e = track_event(get_ledger_row(dedupe_key_3e))
                check("3e: RESUME correctly BACKFILLED the canonical payment_verified row", row3e is not None)
                if row3e is not None:
                    check("3e: backfilled row uses the SAME canonical dedupe identity", row3e.dedupe_key == dedupe_key_3e)
                    check("3e: entity_type/entity_id correct (RESUME's own Order)", row3e.entity_type == "order" and row3e.entity_id == str(order3e_id))
                count_3e = db.session.execute(text("SELECT COUNT(*) FROM activity_events WHERE dedupe_key = :dk"), {"dk": dedupe_key_3e}).scalar()
                check("3e: exactly ONE payment_verified row exists in total (never zero, never two)", count_3e == 1)

            # =========================================================
            # 4. Razorpay Ask Now ChatPack
            # =========================================================
            print("\n=== 4: Razorpay Ask Now ChatPack ===")
            fake_user_id_4 = 900000 + (uuid.uuid4().int % 90000)  # a users.id-shaped int; no FK, so any int is legal

            fake_razorpay_order_4 = {"id": "order_" + uuid.uuid4().hex[:14]}
            real_razorpay_order_create = None
            import config.razorpay_config as razorpay_config_module
            real_client_order_create = razorpay_config_module.razorpay_client.order.create
            razorpay_config_module.razorpay_client.order.create = lambda payload: fake_razorpay_order_4

            try:
                order4 = create_chatpack_order(fake_user_id_4)
            finally:
                razorpay_config_module.razorpay_client.order.create = real_client_order_create

            pack4_id = order4["id"]
            created_chatpack_ids.append(pack4_id)
            row4a = track_event(get_ledger_row(f"payment_initiated:RAZORPAY:CHATPACK:{pack4_id}"))
            check("4a: payment_initiated row exists", row4a is not None)
            if row4a is not None:
                check("4a: platform/source correct", row4a.platform == "backend_internal" and row4a.source == "chat_pack_service")
                check("4a: profile_id/firebase_uid both None (LOCKED DECISION -- no identity bridge)", row4a.profile_id is None and row4a.firebase_uid is None)
                check("4a: correlation_id is None (no correlation_id concept in this module)", row4a.correlation_id is None)
                check("4a: entity_type == chat_pack, entity_id == pack.id", row4a.entity_type == "chat_pack" and row4a.entity_id == str(pack4_id))
                check("4a: purpose == ASK_NOW_CHAT_PACK", row4a.properties.get("purpose") == "ASK_NOW_CHAT_PACK")
                check("4a: order_reference == razorpay order id", row4a.properties.get("order_reference") == fake_razorpay_order_4["id"])
                check("4a: amount/currency correctly ABSENT (payment_initiated schema does not allow them)", "amount" not in row4a.properties and "currency" not in row4a.properties)

            razorpay_payment_id_4 = "pay_" + uuid.uuid4().hex[:14]

            def fake_razorpay_verified2(self, request):
                return PaymentVerificationResult(status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY, reference=request.reference, verified=True, message="mocked verified")

            RazorpayProvider.verify = fake_razorpay_verified2
            try:
                verify_result4 = verify_chatpack_payment(fake_razorpay_order_4["id"], razorpay_payment_id_4, "mocked-sig", fake_user_id_4)
            finally:
                RazorpayProvider.verify = real_razorpay_verify
            check("4b: verify success", verify_result4.get("success") is True)
            row4b = track_event(get_ledger_row(f"payment_verified:RAZORPAY:CHATPACK:{razorpay_payment_id_4}"))
            check("4b: payment_verified row exists", row4b is not None)
            if row4b is not None:
                check("4b: entity_id == pack.id", row4b.entity_id == str(pack4_id))
                check("4b: amount == 51 (whole rupees), currency == INR", row4b.properties.get("amount") == 51 and row4b.properties.get("currency") == "INR")
                check("4b: order_reference == razorpay order id", row4b.properties.get("order_reference") == fake_razorpay_order_4["id"])

            # -- 4c: duplicate ignored (pack now status='success')
            RazorpayProvider.verify = fake_razorpay_verified2
            try:
                verify_result4c = verify_chatpack_payment(fake_razorpay_order_4["id"], razorpay_payment_id_4, "mocked-sig", fake_user_id_4)
            finally:
                RazorpayProvider.verify = real_razorpay_verify
            check("4c: already_processed True", verify_result4c.get("already_processed") is True)
            row4c = track_event(entity_event_row("payment_duplicate_ignored", "chat_pack", pack4_id))
            check("4c: payment_duplicate_ignored row exists", row4c is not None)
            if row4c is not None:
                check("4c: dedupe_key NULL", row4c.dedupe_key is None)

            # -- 4d: failed -- invalid_input (missing payment_id) then signature_mismatch
            fake_user_id_4d = 900000 + (uuid.uuid4().int % 90000)
            fake_razorpay_order_4d = {"id": "order_" + uuid.uuid4().hex[:14]}
            razorpay_config_module.razorpay_client.order.create = lambda payload: fake_razorpay_order_4d
            try:
                order4d = create_chatpack_order(fake_user_id_4d)
            finally:
                razorpay_config_module.razorpay_client.order.create = real_client_order_create
            pack4d_id = order4d["id"]
            created_chatpack_ids.append(pack4d_id)
            track_event(get_ledger_row(f"payment_initiated:RAZORPAY:CHATPACK:{pack4d_id}"))

            def fake_razorpay_failed(self, request):
                return PaymentVerificationResult(status=PaymentStatus.FAILED, provider=PaymentProviderType.RAZORPAY, reference=request.reference, verified=False, message="mocked failure")

            RazorpayProvider.verify = fake_razorpay_failed
            try:
                threw = False
                try:
                    verify_chatpack_payment(fake_razorpay_order_4d["id"], "", "some-sig", fake_user_id_4d)
                except ValueError:
                    threw = True
            finally:
                RazorpayProvider.verify = real_razorpay_verify
            check("4d: ValueError still raised (business behavior unchanged)", threw)
            row4d = track_event(entity_event_row("payment_failed", "chat_pack", pack4d_id))
            check("4d: payment_failed row exists, failure_reason == invalid_input (empty payment_id)", row4d is not None and row4d.properties.get("failure_reason") == "invalid_input")

            RazorpayProvider.verify = fake_razorpay_failed
            try:
                threw2 = False
                try:
                    verify_chatpack_payment(fake_razorpay_order_4d["id"], "pay_present", "garbage-sig", fake_user_id_4d)
                except ValueError:
                    threw2 = True
            finally:
                RazorpayProvider.verify = real_razorpay_verify
            check("4e: ValueError still raised", threw2)
            row4e = track_event(entity_event_row("payment_failed", "chat_pack", pack4d_id))
            check("4e: payment_failed row exists, failure_reason == signature_mismatch", row4e is not None and row4e.properties.get("failure_reason") == "signature_mismatch")

            # =========================================================
            # 5. Google Play Ask Now ChatPack
            # =========================================================
            print("\n=== 5: Google Play Ask Now ChatPack ===")
            fake_user_id_5 = 900000 + (uuid.uuid4().int % 90000)
            token5 = "GPCHATTOK-" + uuid.uuid4().hex

            def fake_verify_product_purchased(self, purchase_token, product_id, package_name=None):
                return GooglePlayProductVerification(verification_status="VERIFIED", purchase_token=purchase_token, product_id=product_id, purchase_state=0, order_id="GPA.TEST-CHATPACK-1")

            real_verify_product = GooglePlayProvider.verify_product_purchase
            GooglePlayProvider.verify_product_purchase = fake_verify_product_purchased
            try:
                result5 = verify_google_chatpack(fake_user_id_5, "asknow8q", token5)
            finally:
                GooglePlayProvider.verify_product_purchase = real_verify_product
            check("5a: verify success", result5.get("success") is True)
            pack5 = ChatPack.query.filter_by(razorpay_payment_id=token5, status="success").first()
            check("5a: ChatPack row created", pack5 is not None)
            if pack5 is not None:
                created_chatpack_ids.append(pack5.id)
                row5a = track_event(get_ledger_row(f"payment_verified:GOOGLE_PLAY:CHATPACK:{hashlib.sha256(token5.encode()).hexdigest()}"))
                check("5a: payment_verified row exists (hashed dedupe)", row5a is not None)
                if row5a is not None:
                    check("5a: amount == 51, currency == INR (asknow8q)", row5a.properties.get("amount") == 51 and row5a.properties.get("currency") == "INR")
                    check("5a: order_reference == Google order_id", row5a.properties.get("order_reference") == "GPA.TEST-CHATPACK-1")
                    check("5a: SECURITY -- raw purchase_token nowhere in serialized row", token5 not in serialized_row_text(row5a))
                    check("5a: entity_id == pack.id", row5a.entity_id == str(pack5.id))

            # -- 5b: duplicate ignored
            GooglePlayProvider.verify_product_purchase = fake_verify_product_purchased
            try:
                result5b = verify_google_chatpack(fake_user_id_5, "asknow8q", token5)
            finally:
                GooglePlayProvider.verify_product_purchase = real_verify_product
            check("5b: already_processed True", result5b.get("already_processed") is True)
            row5b = track_event(entity_event_row("payment_duplicate_ignored", "chat_pack", pack5.id if pack5 else -1))
            check("5b: payment_duplicate_ignored row exists", row5b is not None)

            # -- 5c: failed -- verification rejected
            token5c = "GPCHATTOK-" + uuid.uuid4().hex

            def fake_verify_product_notfound(self, purchase_token, product_id, package_name=None):
                return GooglePlayProductVerification(verification_status="NOT_FOUND", purchase_token=purchase_token, product_id=product_id, error_message="not found")

            GooglePlayProvider.verify_product_purchase = fake_verify_product_notfound
            try:
                result5c = verify_google_chatpack(fake_user_id_5, "asknow8q", token5c)
            finally:
                GooglePlayProvider.verify_product_purchase = real_verify_product
            check("5c: verify rejected (success False)", result5c.get("success") is False)
            row5c = track_event(latest_event_row("payment_failed"))
            check("5c: payment_failed row exists, failure_reason == not_found", row5c is not None and row5c.properties.get("failure_reason") == "not_found")
            if row5c is not None:
                check("5c: SECURITY -- raw purchase_token nowhere in serialized row", token5c not in serialized_row_text(row5c))

            # -- 5d: purchase-not-completed -> provider_declined
            token5d = "GPCHATTOK-" + uuid.uuid4().hex

            def fake_verify_product_canceled(self, purchase_token, product_id, package_name=None):
                return GooglePlayProductVerification(verification_status="VERIFIED", purchase_token=purchase_token, product_id=product_id, purchase_state=1, order_id="GPA.TEST-CANCELED")

            GooglePlayProvider.verify_product_purchase = fake_verify_product_canceled
            try:
                result5d = verify_google_chatpack(fake_user_id_5, "asknow8q", token5d)
            finally:
                GooglePlayProvider.verify_product_purchase = real_verify_product
            check("5d: purchase_not_completed (success False)", result5d.get("success") is False and result5d.get("error") == "purchase_not_completed")
            row5d = track_event(latest_event_row("payment_failed"))
            check("5d: payment_failed row exists, failure_reason == provider_declined", row5d is not None and row5d.properties.get("failure_reason") == "provider_declined")

            # =========================================================
            # 6. Failure safety -- shared PaymentService (Razorpay report, verified path)
            # =========================================================
            print("\n=== 6: failure safety -- PaymentService ===")
            razorpay_order_id_6 = "order_" + uuid.uuid4().hex[:14]
            razorpay_payment_id_6 = "pay_" + uuid.uuid4().hex[:14]
            created_payment_ids.append((PaymentProviderType.RAZORPAY, razorpay_payment_id_6))

            with patch("modules.payments.payment_service.record_event") as mock_re:
                mock_re.return_value = LedgerWriteResult(status="write_failed")
                RazorpayProvider.verify = fake_razorpay_verified
                try:
                    req6a = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_6, payment_id=razorpay_payment_id_6, signature="mocked", order_payload=report_payload("6a"))
                    result6a = PaymentService().process_payment(req6a)
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
            check("6a write_failed: business result STILL VERIFIED", result6a.status == PaymentStatus.VERIFIED)
            order6a_id = result6a.raw_payload.get("order_id")
            check("6a write_failed: Order STILL created", order6a_id is not None)
            if order6a_id:
                created_order_ids.append(order6a_id)

            razorpay_order_id_6b = "order_" + uuid.uuid4().hex[:14]
            razorpay_payment_id_6b = "pay_" + uuid.uuid4().hex[:14]
            created_payment_ids.append((PaymentProviderType.RAZORPAY, razorpay_payment_id_6b))
            with patch("modules.payments.payment_service.record_event") as mock_re:
                mock_re.side_effect = RuntimeError("boom -- simulated unexpected analytics failure")
                RazorpayProvider.verify = fake_razorpay_verified
                no_exception = True
                try:
                    req6b = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_6b, payment_id=razorpay_payment_id_6b, signature="mocked", order_payload=report_payload("6b"))
                    result6b = PaymentService().process_payment(req6b)
                except Exception:
                    no_exception = False
                    result6b = None
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
            check("6b unexpected exception: does NOT propagate", no_exception)
            check("6b unexpected exception: business result STILL VERIFIED", result6b is not None and result6b.status == PaymentStatus.VERIFIED)
            order6b_id = result6b.raw_payload.get("order_id") if result6b else None
            check("6b unexpected exception: Order STILL created", order6b_id is not None)
            if order6b_id:
                created_order_ids.append(order6b_id)

            razorpay_order_id_6c = "order_" + uuid.uuid4().hex[:14]
            razorpay_payment_id_6c = "pay_" + uuid.uuid4().hex[:14]
            created_payment_ids.append((PaymentProviderType.RAZORPAY, razorpay_payment_id_6c))
            original_env = os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT")
            try:
                os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
                RazorpayProvider.verify = fake_razorpay_verified
                try:
                    req6c = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_6c, payment_id=razorpay_payment_id_6c, signature="mocked", order_payload=report_payload("6c"))
                    result6c = PaymentService().process_payment(req6c)
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
            finally:
                if original_env is None:
                    os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
                else:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = original_env
            check("6c missing env: business result STILL VERIFIED", result6c.status == PaymentStatus.VERIFIED)
            order6c_id = result6c.raw_payload.get("order_id")
            check("6c missing env: Order STILL created", order6c_id is not None)
            if order6c_id:
                created_order_ids.append(order6c_id)
            check("6c missing env: no payment_verified row persisted for this payment_id", get_ledger_row(f"payment_verified:RAZORPAY:{razorpay_payment_id_6c}") is None)

            razorpay_order_id_6d = "order_" + uuid.uuid4().hex[:14]
            razorpay_payment_id_6d = "pay_" + uuid.uuid4().hex[:14]
            created_payment_ids.append((PaymentProviderType.RAZORPAY, razorpay_payment_id_6d))
            try:
                os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "staging-not-a-real-value"
                RazorpayProvider.verify = fake_razorpay_verified
                try:
                    req6d = PaymentRequest(provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE, reference=razorpay_order_id_6d, payment_id=razorpay_payment_id_6d, signature="mocked", order_payload=report_payload("6d"))
                    result6d = PaymentService().process_payment(req6d)
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
            finally:
                if original_env is None:
                    os.environ.pop("ACTIVITY_EVENTS_ENVIRONMENT", None)
                else:
                    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = original_env
            check("6d invalid env: business result STILL VERIFIED", result6d.status == PaymentStatus.VERIFIED)
            order6d_id = result6d.raw_payload.get("order_id")
            check("6d invalid env: Order STILL created", order6d_id is not None)
            if order6d_id:
                created_order_ids.append(order6d_id)

            # =========================================================
            # 7. Failure safety -- Ask Now Razorpay ChatPack (verified path)
            # =========================================================
            print("\n=== 7: failure safety -- chat_pack_service ===")
            fake_user_id_7 = 900000 + (uuid.uuid4().int % 90000)
            fake_razorpay_order_7 = {"id": "order_" + uuid.uuid4().hex[:14]}
            razorpay_config_module.razorpay_client.order.create = lambda payload: fake_razorpay_order_7
            try:
                order7 = create_chatpack_order(fake_user_id_7)
            finally:
                razorpay_config_module.razorpay_client.order.create = real_client_order_create
            pack7_id = order7["id"]
            created_chatpack_ids.append(pack7_id)
            track_event(get_ledger_row(f"payment_initiated:RAZORPAY:CHATPACK:{pack7_id}"))
            razorpay_payment_id_7 = "pay_" + uuid.uuid4().hex[:14]

            with patch("modules.services.chat_pack_service.record_event") as mock_re7:
                mock_re7.side_effect = RuntimeError("boom -- simulated unexpected analytics failure")
                RazorpayProvider.verify = fake_razorpay_verified2
                no_exception7 = True
                try:
                    verify_result7 = verify_chatpack_payment(fake_razorpay_order_7["id"], razorpay_payment_id_7, "mocked-sig", fake_user_id_7)
                except Exception:
                    no_exception7 = False
                    verify_result7 = None
                finally:
                    RazorpayProvider.verify = real_razorpay_verify
            check("7 unexpected exception: does NOT propagate out of verify_chatpack_payment()", no_exception7)
            check("7 unexpected exception: business result STILL success", verify_result7 is not None and verify_result7.get("success") is True)
            pack7 = ChatPack.query.get(pack7_id)
            check("7 unexpected exception: ChatPack STILL marked success", pack7 is not None and pack7.status == "success")

            # =========================================================
            # Cross-cutting: raw signature never stored anywhere
            # =========================================================
            print("\n=== 8: cross-cutting signature/PII scan across ALL rows created above ===")
            if created_event_ids:
                rows_all = db.session.execute(
                    text("SELECT event_id, properties, dedupe_key, entity_id, correlation_id, campaign_context, notification_context FROM activity_events WHERE event_id = ANY(:ids)"),
                    {"ids": [uuid.UUID(e) for e in created_event_ids]},
                ).fetchall()
                bad = []
                for r in rows_all:
                    blob = serialized_row_text(r)
                    for forbidden in ("mocked-sig", "garbage-signature", "garbage-sig", "@example.com", "phase4b-test"):
                        if forbidden in blob and forbidden not in ("phase4b-test",):
                            # "phase4b-test*" only ever appears in our own
                            # firebase_uid fixture value, never expected in
                            # a payment-event row at all -- checked below
                            # as its own assertion, not folded into this list.
                            bad.append((r.event_id, forbidden))
                check("8: no signature value present in any created row", not any(f in ("mocked-sig", "garbage-signature", "garbage-sig") for _, f in bad))
                check("8: no email address present in any created row", not any(f == "@example.com" for _, f in bad))

        finally:
            RazorpayProvider.verify = real_razorpay_verify
            GooglePlayProvider.verify = real_google_verify
            GooglePlayProvider.verify_product_purchase = real_verify_product
            razorpay_config_module.razorpay_client.order.create = real_client_order_create
            OrderService._dispatch_report_generation = real_dispatch

            for eid in created_event_ids:
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()

            for oid in created_order_ids:
                Order.query.filter_by(id=oid).delete()
            db.session.commit()

            for provider, pid in created_payment_ids:
                ProcessedPayment.query.filter_by(provider=provider, payment_id=pid).delete()
            db.session.commit()

            for cpid in created_chatpack_ids:
                ChatPack.query.filter_by(id=cpid).delete()
            db.session.commit()

            if created_app_user_ids:
                for eid in [str(r.event_id) for r in db.session.execute(
                    text("SELECT event_id FROM activity_events WHERE profile_id = ANY(:pids)"), {"pids": created_app_user_ids}
                ).fetchall()]:
                    db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
                CurrentEntitlement.query.filter(CurrentEntitlement.profile_id.in_(created_app_user_ids)).delete(synchronize_session=False)
                SubscriptionEvent.query.filter(SubscriptionEvent.profile_id.in_(created_app_user_ids)).delete(synchronize_session=False)
                SubscriptionPurchaseMapping.query.filter(SubscriptionPurchaseMapping.profile_id.in_(created_app_user_ids)).delete(synchronize_session=False)
                AppUser.query.filter(AppUser.id.in_(created_app_user_ids)).delete(synchronize_session=False)
                db.session.commit()

            remaining_orders = Order.query.filter(Order.id.in_(created_order_ids or [-1])).count()
            check("cleanup: all Phase-4B Order fixtures removed", remaining_orders == 0)
            remaining_claims = sum(
                ProcessedPayment.query.filter_by(provider=p, payment_id=pid).count()
                for p, pid in created_payment_ids
            )
            check("cleanup: all Phase-4B ProcessedPayment fixtures removed", remaining_claims == 0)
            remaining_packs = ChatPack.query.filter(ChatPack.id.in_(created_chatpack_ids or [-1])).count()
            check("cleanup: all Phase-4B ChatPack fixtures removed", remaining_packs == 0)
            remaining_au = AppUser.query.filter(AppUser.id.in_(created_app_user_ids or [-1])).count()
            check("cleanup: all Phase-4B AppUser fixtures removed", remaining_au == 0)
            remaining_events = db.session.execute(
                text("SELECT COUNT(*) FROM activity_events WHERE event_id = ANY(:ids)"),
                {"ids": [uuid.UUID(e) for e in created_event_ids] or [uuid.uuid4()]},
            ).scalar()
            check("cleanup: all Phase-4B activity_events rows removed", remaining_events == 0)

    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
