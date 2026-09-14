# modules/payments/payment_finalization_service.py

"""
PaymentFinalizationService -- Paid Report Platform v1.0, R4 (Payment
Finalization & Idempotency Core).

NOT WIRED to anything yet: no route, no PaymentService call site, no
app.py change calls this in R4. It exists as a focused, independently
testable service so R5/R6 can later decide how/when to invoke it,
without this phase guessing that design. PaymentService.process_payment()
and OrderService.create_paid_report_order() remain completely
unmodified and are still the ONLY payment path any live request goes
through today.

Purpose: finalize an ALREADY-VALIDATED, ALREADY-PENDING report Order
(created by OrderService.create_pending_order(), R3) into PAID --
structurally eliminating the Suresh failure class (a payment verified
before the Order it belongs to could be fully identified) by never
constructing an Order from payment-time data at all. This service:

    - NEVER creates an Order (contrast: the OLD, still-live
      OrderService.create_paid_report_order() creates one from
      whatever the webhook/browser payload happened to contain).
    - NEVER reconstructs customer/birth/report data from a webhook or
      browser payload -- the Order, resolved by razorpay_order_id
      alone, is the only source of that data from this point on.
    - NEVER changes Order.product/report_slug -- the resolved Order's
      own value is read, never overwritten.
    - NEVER dispatches report generation (no Celery, no thread, no
      call into tasks.py/love_report_router.py/redispatch_report_
      generation() of any kind) -- see GENERATION RETRY RULE below.

GENERATION RETRY RULE (locked, per this phase's own instruction):
payment finalization confirms payment state ONLY. A repeated webhook/
browser callback for an already-PAID Order must never re-trigger
Luna/PDF/email generation from here -- that dispatch decision belongs
entirely to a later phase (R5+), which will decide, from the returned
ReportPaymentFinalizationStatus, whether/when to queue generation.

Idempotency: reuses modules/models_processed_payments.py::
ProcessedPayment and its existing DB-level UNIQUE(provider,
payment_id) exactly as PaymentService already does -- no new ledger,
no new constraint. The one structural improvement over the existing
PaymentService path: order_id is written into the claim AT CLAIM TIME
(the Order was already resolved, by razorpay_order_id, before the
claim is even attempted), never left NULL pending a business-effect
step that could fail afterward -- this is precisely the gap the
forensic audit identified as the Suresh incident's root cause.

Transaction safety: the ProcessedPayment insert and the Order's
conditional payment_status/status/razorpay_payment_id transition are
staged in the SAME SQLAlchemy session and committed together in ONE
`db.session.commit()` call (see _claim_and_finalize() below) -- either
both persist or neither does. A lost claim-insert race (IntegrityError
on the UNIQUE constraint) rolls back before anything is committed, and
a conditional Order UPDATE matching zero rows (a concurrent Order-state
change the claim's own uniqueness didn't happen to prevent) also rolls
back the not-yet-committed claim insert alongside it -- never a
committed claim with an unflipped Order, and never a flipped Order
with no claim recorded.

Legacy rows: a ProcessedPayment already existing for this payment_id
with order_id IS NULL (a pre-R4, pre-price-snapshot claim, possibly
including a real historical incident like Suresh's) is NEVER
automatically released, reassigned, or repaired here -- returns
LEGACY_STUCK. Recovery for those rows is explicitly a later, separate,
human-reviewed task.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Order
from modules.models_processed_payments import ProcessedPayment
from modules.payments.payment_logger import log_payment_event, new_correlation_id
from modules.payments.payment_models import (
    PaymentPurpose,
    PaymentRequest,
    PaymentStatus,
)
from modules.payments.razorpay_provider import RazorpayProvider


class ReportPaymentFinalizationStatus:
    """Typed outcome of PaymentFinalizationService.finalize_report_payment().
    Every value maps to exactly one of R4's Section D rules (see each
    branch's own comment in finalize_report_payment() for which rule it
    implements)."""

    # Success paths
    FINALIZED = "FINALIZED"                    # rule 1: PAYMENT_PENDING -> PAID, first time
    ALREADY_FINALIZED = "ALREADY_FINALIZED"     # rules 2/3: idempotent -- same payment_id, same Order

    # Safe rejections -- Order remains exactly as it was, no business effect
    ORPHANED_PAYMENT = "ORPHANED_PAYMENT"                 # rule 6
    INVALID_STATE = "INVALID_STATE"                       # rules 7/8
    VERIFICATION_FAILED = "VERIFICATION_FAILED"           # rule 11
    ORDER_PAYMENT_MISMATCH = "ORDER_PAYMENT_MISMATCH"     # rule 10
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"                   # rule 9
    AMOUNT_UNVERIFIABLE = "AMOUNT_UNVERIFIABLE"           # defensive: Order.amount_paise is NULL (legacy Order reached PAYMENT_PENDING somehow) -- fails closed, same as a mismatch, never silently skipped
    PAYMENT_LOOKUP_FAILED = "PAYMENT_LOOKUP_FAILED"       # defensive: Razorpay's own Payment API could not be reached to independently confirm order/amount -- fails closed

    # CRITICAL conflicts -- always logged at CRITICAL, always manual-review-worthy
    PAYMENT_ALREADY_CLAIMED_DIFFERENT_ORDER = "PAYMENT_ALREADY_CLAIMED_DIFFERENT_ORDER"  # rule 4
    DIFFERENT_PAYMENT_FOR_PAID_ORDER = "DIFFERENT_PAYMENT_FOR_PAID_ORDER"                # rule 5
    LEGACY_STUCK = "LEGACY_STUCK"                                                        # Section F


@dataclass
class ReportPaymentFinalizationResult:
    status: str                      # ReportPaymentFinalizationStatus
    order_id: Optional[int] = None
    message: str = ""


class PaymentFinalizationService:
    """Focused on PaymentPurpose.REPORT_PURCHASE only -- raises
    ValueError immediately (a caller-code-bug, not a payment-data
    problem) for any other purpose. Not a general-purpose replacement
    for PaymentService; SUBSCRIPTION/Google Play payments are entirely
    out of this service's scope."""

    def finalize_report_payment(self, request: PaymentRequest) -> ReportPaymentFinalizationResult:
        if request.purpose != PaymentPurpose.REPORT_PURCHASE:
            raise ValueError(
                f"PaymentFinalizationService.finalize_report_payment() only handles "
                f"REPORT_PURCHASE, got {request.purpose!r}."
            )

        correlation_id = new_correlation_id()
        log_ctx = dict(
            correlation_id=correlation_id,
            provider=request.provider,
            razorpay_order_id=request.reference,
            razorpay_payment_id=request.payment_id,
        )

        # ---------------------------------------------------------
        # 1/2/3/4. Resolve the Order by razorpay_order_id ONLY -- never
        # created here, never inferred from any payload field.
        # ---------------------------------------------------------
        order = Order.query.filter_by(razorpay_order_id=request.reference).first()
        if order is None:
            log_payment_event("report_payment_orphaned", status="FAILED", **log_ctx)
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.ORPHANED_PAYMENT,
                message="No Order found for this razorpay_order_id.",
            )

        # ---------------------------------------------------------
        # Section F -- a pre-existing claim for this exact payment_id.
        # Checked BEFORE any order-state/verification work: idempotency
        # rules 2/3/4 and the legacy-stuck rule all key off this alone.
        # ---------------------------------------------------------
        existing_claim = None
        if request.payment_id:
            existing_claim = ProcessedPayment.query.filter_by(
                provider=request.provider, payment_id=request.payment_id,
            ).first()
        if existing_claim is not None:
            return self._resolve_existing_claim(existing_claim, order, log_ctx)

        # ---------------------------------------------------------
        # Rules 5/7/8 -- Order-state guard. Only a genuinely
        # PAYMENT_PENDING Order (created by create_pending_order(),
        # then advanced by the future R6 route once a real Razorpay
        # order_id was saved) may proceed to verification at all.
        # ---------------------------------------------------------
        if order.payment_status == "PAID":
            if order.razorpay_payment_id == request.payment_id:
                # No claim row existed (e.g. a pre-existing PAID Order
                # from before R4, or a claim manually removed) but the
                # Order itself already agrees with this payment_id --
                # still a safe idempotent success, never a conflict.
                log_payment_event("report_payment_idempotent", status="SUCCESS", order_id=order.id, **log_ctx)
                return ReportPaymentFinalizationResult(
                    status=ReportPaymentFinalizationStatus.ALREADY_FINALIZED, order_id=order.id,
                    message="Order is already PAID with this exact payment_id.",
                )
            # rule 5 -- a DIFFERENT payment_id for an already-PAID Order.
            log_payment_event(
                "report_payment_conflict", status="CRITICAL", order_id=order.id,
                error="different payment_id presented for an already-PAID Order", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.DIFFERENT_PAYMENT_FOR_PAID_ORDER, order_id=order.id,
                message="This Order is already PAID under a different payment_id. Manual review required.",
            )

        if order.payment_status != "PAYMENT_PENDING":
            # rules 7/8 -- CREATED, PAYMENT_FAILED, or any other value.
            log_payment_event(
                "report_payment_invalid_state", status="FAILED", order_id=order.id,
                error=f"payment_status={order.payment_status!r} is not finalizable", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.INVALID_STATE, order_id=order.id,
                message=f"Order.payment_status={order.payment_status!r} cannot be finalized.",
            )

        # ---------------------------------------------------------
        # Rule 11 -- real provider verification, existing convention,
        # completely unmodified (same RazorpayProvider.verify() every
        # live payment already goes through).
        # ---------------------------------------------------------
        verification = RazorpayProvider().verify(request)
        if verification.status != PaymentStatus.VERIFIED:
            log_payment_event(
                "report_payment_invalid_state", status="FAILED", order_id=order.id,
                error=f"provider verification failed: {verification.message}", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.VERIFICATION_FAILED, order_id=order.id,
                message=verification.message,
            )

        # ---------------------------------------------------------
        # Rules 9/10 -- independent, Razorpay-side confirmation of
        # order-linkage AND captured amount, via RazorpayProvider.
        # fetch_payment() (R4) -- never trusted from a webhook/browser
        # payload field alone.
        # ---------------------------------------------------------
        payment_record = RazorpayProvider.fetch_payment(request.payment_id)
        if payment_record is None:
            log_payment_event(
                "report_payment_invalid_state", status="FAILED", order_id=order.id,
                error="could not independently fetch payment from Razorpay", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.PAYMENT_LOOKUP_FAILED, order_id=order.id,
                message="Could not independently verify this payment with Razorpay.",
            )

        if payment_record.get("order_id") != request.reference:
            log_payment_event(
                "report_payment_order_mismatch", status="CRITICAL", order_id=order.id,
                error=f"payment's own order_id={payment_record.get('order_id')!r} != {request.reference!r}", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.ORDER_PAYMENT_MISMATCH, order_id=order.id,
                message="This payment does not belong to the resolved Razorpay order.",
            )

        if order.amount_paise is None:
            # Defensive only -- create_pending_order() (R3/R4) always
            # populates this for a new-platform Order; a PAYMENT_PENDING
            # Order with no snapshot should not exist, but amount
            # correctness must never be silently skipped if it does.
            log_payment_event(
                "report_payment_amount_mismatch", status="CRITICAL", order_id=order.id,
                error="Order.amount_paise is NULL -- cannot verify amount", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.AMOUNT_UNVERIFIABLE, order_id=order.id,
                message="Order has no recorded expected amount; cannot verify payment amount.",
            )

        captured_amount = payment_record.get("amount")
        if captured_amount != order.amount_paise:
            log_payment_event(
                "report_payment_amount_mismatch", status="CRITICAL", order_id=order.id,
                error=f"captured={captured_amount!r} expected={order.amount_paise!r}", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.AMOUNT_MISMATCH, order_id=order.id,
                message=f"Captured amount {captured_amount!r} does not match expected {order.amount_paise!r}.",
            )

        # ---------------------------------------------------------
        # Rule 1 + Section E -- the one atomic claim + PAID transition.
        # ---------------------------------------------------------
        return self._claim_and_finalize(request, order, log_ctx)

    # ------------------------------------------------------------
    def _resolve_existing_claim(self, existing_claim: ProcessedPayment, order: Order, log_ctx: dict) -> ReportPaymentFinalizationResult:
        if existing_claim.order_id is None:
            # Section F -- a legacy (pre-R4) or otherwise-unfinished
            # claim. Never auto-repaired here.
            log_payment_event("report_payment_legacy_stuck", status="MANUAL_REVIEW", **log_ctx)
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.LEGACY_STUCK,
                message="A ProcessedPayment claim already exists for this payment_id with no order_id. Manual review required.",
            )
        if existing_claim.order_id == order.id:
            # rules 2/3 -- idempotent success, including the "lost the
            # claim race but it was for the SAME Order" case.
            log_payment_event("report_payment_idempotent", status="SUCCESS", order_id=order.id, **log_ctx)
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.ALREADY_FINALIZED, order_id=order.id,
                message="This payment was already finalized for this exact Order.",
            )
        # rule 4 -- same payment_id, but claimed against a DIFFERENT Order.
        log_payment_event(
            "report_payment_conflict", status="CRITICAL", order_id=order.id,
            error=f"payment_id already claimed for order_id={existing_claim.order_id!r}, not {order.id!r}", **log_ctx,
        )
        return ReportPaymentFinalizationResult(
            status=ReportPaymentFinalizationStatus.PAYMENT_ALREADY_CLAIMED_DIFFERENT_ORDER, order_id=order.id,
            message="This payment_id is already claimed for a different Order. Manual review required.",
        )

    def _claim_and_finalize(self, request: PaymentRequest, order: Order, log_ctx: dict) -> ReportPaymentFinalizationResult:
        """
        ONE transaction: claim insertion + Order's conditional
        PAYMENT_PENDING -> PAID transition + razorpay_payment_id
        assignment, committed together or not at all. Never dispatches
        generation (see module docstring's GENERATION RETRY RULE).
        """
        claim = ProcessedPayment(
            provider=request.provider, payment_id=request.payment_id,
            reference=request.reference, order_id=order.id,
        )
        db.session.add(claim)
        try:
            # Runs the INSERT now (surfacing the UNIQUE-constraint
            # IntegrityError here, before any Order mutation is even
            # attempted) without committing -- the conditional UPDATE
            # below still shares this same, still-open transaction.
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            # Lost the race for this exact payment_id (rule 3) -- some
            # concurrent call already claimed it. Refetch and apply the
            # same idempotency decision an existing claim would get.
            existing_claim = ProcessedPayment.query.filter_by(
                provider=request.provider, payment_id=request.payment_id,
            ).first()
            if existing_claim is None:
                # Should not happen (the IntegrityError proves a row
                # exists) -- fail safe rather than guess.
                log_payment_event(
                    "report_payment_invalid_state", status="FAILED", order_id=order.id,
                    error="lost claim race but could not refetch the winning claim", **log_ctx,
                )
                return ReportPaymentFinalizationResult(
                    status=ReportPaymentFinalizationStatus.INVALID_STATE, order_id=order.id,
                    message="Could not resolve a concurrent claim for this payment_id.",
                )
            return self._resolve_existing_claim(existing_claim, order, log_ctx)
        except Exception:
            db.session.rollback()
            log_payment_event(
                "report_payment_invalid_state", status="FAILED", order_id=order.id,
                error="unexpected exception while inserting the payment claim", exc_info=True, **log_ctx,
            )
            raise

        rows_updated = Order.query.filter_by(id=order.id, payment_status="PAYMENT_PENDING").update(
            {"payment_status": "PAID", "status": "PAID", "razorpay_payment_id": request.payment_id},
            synchronize_session=False,
        )
        if rows_updated != 1:
            # Section E -- the Order's own state changed between our
            # earlier guard-check and this UPDATE (a genuine concurrent
            # transition this claim's own UNIQUE constraint did not, by
            # itself, prevent). Roll back EVERYTHING, including the
            # just-flushed-but-not-yet-committed claim insert -- never
            # leave a committed claim with an unflipped Order.
            db.session.rollback()
            log_payment_event(
                "report_payment_invalid_state", status="FAILED", order_id=order.id,
                error="Order.payment_status changed concurrently; rolled back cleanly", **log_ctx,
            )
            return ReportPaymentFinalizationResult(
                status=ReportPaymentFinalizationStatus.INVALID_STATE, order_id=order.id,
                message="Order's payment state changed concurrently; no changes were applied.",
            )

        try:
            db.session.commit()
        except Exception:
            # Section E -- a failure here (simulated crash, DB hiccup)
            # must leave NEITHER the claim NOR the Order transition
            # persisted. Neither statement has been committed yet, so
            # rollback undoes both together, exactly like the IntegrityError
            # and rows_updated != 1 branches above already do.
            db.session.rollback()
            log_payment_event(
                "report_payment_invalid_state", status="FAILED", order_id=order.id,
                error="commit failed while finalizing payment; rolled back cleanly", exc_info=True, **log_ctx,
            )
            raise

        log_payment_event("report_payment_finalized", status="SUCCESS", order_id=order.id, **log_ctx)
        return ReportPaymentFinalizationResult(
            status=ReportPaymentFinalizationStatus.FINALIZED, order_id=order.id,
            message="Payment finalized; Order is now PAID.",
        )
