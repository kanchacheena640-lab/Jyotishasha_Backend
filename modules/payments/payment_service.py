# modules/payments/payment_service.py

"""
PaymentService -- THE single orchestration layer for all payment
providers, per this phase's objective. Every future payment entry
point (a hardened Website Razorpay checkout, a future Google Play
purchase callback, a future Apple StoreKit callback) is meant to call
process_payment() here rather than verifying/handling payments inline
the way every existing route in this codebase does today.

    Caller -> PaymentService.process_payment(PaymentRequest)
                  |
                  |-- 1. resolve + verify    -> PaymentProviderRegistry -> PaymentProvider
                  |-- 2. idempotency check   -> ProcessedPayment ledger (Payment Hardening Phase 3)
                  |-- 3. retry decision      -> RetryDecision (Phase 5, only if payment already seen)
                  |-- 4. business delegation -> OrderService           (REPORT_PURCHASE)
                  |                          -> SubscriptionService    (SUBSCRIPTION, via
                  |                             _apply_subscription_business_effect --
                  |                             Subscription Purchase System S4)
                  '-- returns PaymentVerificationResult

Payment providers never generate reports or touch business tables
directly -- verification and business effect are two separate steps,
and this file is the only thing that ever calls both a provider and a
business service for the same payment.

Idempotency (Payment Hardening Phase 3): a payment is never processed
twice, even under concurrent requests (browser double-click, a network
retry racing the original, a duplicate webhook delivery). This is
enforced by modules/models_processed_payments.py::ProcessedPayment, a
table with a DB-level UNIQUE constraint on (provider, payment_id) --
the actual mechanism, not just a convention. The sequence is:
    1. read-check: has this payment_id already been fully processed?
       If so, return its stored result immediately -- no Order, no
       dispatch.
    2. claim: insert a placeholder row for (provider, payment_id)
       before doing anything else. If a concurrent request already
       inserted one first, the UNIQUE constraint makes this insert
       fail -- that request backs off and defers to whichever request
       won the race, rather than also creating an Order.
    3. only the request that won the claim proceeds to the business
       effect (OrderService), then fills in the claimed row with the
       real order_id/response so future duplicates return the same
       result.

Structured logging and failure recovery (Payment Hardening Phase 4):
every process_payment() call gets one correlation_id, logged via
modules/payments/payment_logger.py at each stage. No exception is ever
swallowed -- each is logged (with a full stack trace via exc_info) at
the point it is caught, then re-raised unchanged.

Safe retry policy (Payment Hardening Phase 5, refined in Phase 6): a
retry is only ever recognized for a payment_id this service has
already claimed (i.e. verification already succeeded once before).
What happens next is decided purely from Order.report_stage -- no
schema change:
    PENDING     -> REJECT (dispatch hasn't even started the pipeline
                   yet; nothing to resume)
    PROCESSING  -> REJECT (the pipeline is actively running RIGHT NOW
                   -- never resume, or two concurrent runs would
                   produce a duplicate GPT call, a PDF write race, and
                   a duplicate email)
    READY       -> IGNORE (the pipeline already fully succeeded --
                   PDF generated, email sent. Return the stored
                   result; do nothing further)
    FAILED      -> RESUME (the pipeline finished running and
                   definitively failed. Re-trigger generation for the
                   SAME order_id via OrderService.redispatch_report_
                   generation() -- never a new Order, never
                   re-verifying payment)

Phase 6 closes the gap Phase 5 shipped with: previously, "Pending"
(dispatch not yet started) and a genuine mid-flight run were both
indistinguishable from a truly failed attempt -- all three left
report_stage stuck at "Pending" forever, since the pipeline never
recorded an in-progress state. tasks.py and love_premium_task.py (both
otherwise still untouched in their actual generation logic) now write
report_stage="Processing" as their very first step before any real
work begins, and report_stage="Failed" in their outer exception
handler if generation does not complete. RESUME is now only reachable
when the pipeline has DEFINITIVELY finished failing, never while it
might still be legitimately running.

Honest limitation, unchanged from Phase 5: the pipeline still has no
internal checkpointing beyond this one Processing/Ready/Failed
tracking -- a single retry re-runs kundali -> GPT -> PDF -> email from
the start. There is still no way to "resume from just the PDF step" or
distinguish "AI failed" from "PDF failed" from "email failed" without
restructuring the pipeline into separately-resumable stages, which
remains out of scope. RESUME means "safely re-run the whole pipeline
for the existing order, now only once the previous attempt has
provably finished failing" -- still correct and non-duplicating (same
order_id, no new Order, no re-verification), just not stage-granular.

Atomic resume ownership (Payment Hardening Phase 6.2): the Resume
Safety Audit found that deciding RESUME (a plain read of
report_stage) and acting on it (dispatching) were two separate steps
-- two concurrent retries could both read "Failed" before either's
dispatched background worker got far enough to write "Processing",
and both would then redispatch. _try_acquire_resume_ownership() closes
this with a single conditional UPDATE (`WHERE report_stage='Failed'`)
that atomically claims the Failed -> Processing transition; only the
caller whose UPDATE actually matched a row (rowcount == 1) proceeds to
redispatch, and every other concurrent caller is told the payment is
already being processed. This is enforced entirely by the database's
own row-level update semantics -- no Python threading.Lock, no
in-memory flag, no Redis -- so it holds across multiple worker
processes and hosts, not just within one.

To make RESUME possible at all, OrderService.create_paid_report_order()
raises ReportDispatchError (carrying the already-committed order_id)
instead of a bare exception when dispatch fails -- see
modules/payments/order_service.py. Without that, a dispatch-stage
failure would leave no record of which order_id was created.

Subscription business delegation (Subscription Purchase System S4):
_apply_subscription_business_effect() is the SUBSCRIPTION counterpart
to _apply_business_effect()'s REPORT_PURCHASE branch. It reads the
normalized GooglePlaySubscriptionVerification data GooglePlayProvider.
verify() already produced (via verification_result.raw_payload -- now
threaded into _apply_business_effect() as a second parameter, the one
change this phase made to this method's own signature) and decides,
from Google's own purchase_state, whether to call
SubscriptionService.activate_subscription() at all. SubscriptionService
itself (modules/subscription/subscription_service.py) and
EntitlementWriteService remain completely unmodified -- this file adds
one more caller of an existing method, exactly like OrderService's
relationship to REPORT_PURCHASE. Renewals, cancellations, refunds, RTDN,
purchase acknowledgement, and Apple are all explicitly out of scope for
this phase and are not implemented anywhere in this file.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Order
from modules.models_processed_payments import ProcessedPayment
from modules.payments.google_play_models import GooglePlayVerificationStatus
from modules.payments.google_play_provider import GooglePlayProvider
from modules.payments.order_service import OrderService, ReportDispatchError
from modules.payments.payment_logger import log_payment_event, new_correlation_id
from modules.payments.payment_models import (
    PaymentProviderType,
    PaymentPurpose,
    PaymentRequest,
    PaymentStatus,
    PaymentVerificationResult,
    RetryDecision,
)
from modules.payments.payment_provider_registry import (
    PaymentProviderRegistry,
    get_default_registry,
)
from modules.payments.subscription_purchase_mapping_service import (
    SubscriptionPurchaseMappingService,
)
from modules.payments.subscription_purchase_models import (
    SubscriptionPurchaseOutcome,
    SubscriptionPurchaseResult,
)
from modules.subscription.subscription_service import SubscriptionService

# Phase 4B -- the existing, unmodified Phase-2 ledger write path. This
# import introduces no circular dependency: modules.activity_events.*
# imports nothing from modules.payments/modules.subscription/modules.
# entitlement (confirmed the same way Phase 4A's subscription
# instrumentation confirmed it for modules.entitlement).
from modules.activity_events.service import record_event

# Subscription Purchase System -- S4, populated in S11. Google Play's
# own product_id (configured in the Play Console) has no inherent
# relationship to this codebase's own plan names -- there is no way to
# derive this mapping, only to be told it. Now centrally defined in
# config/google_play_products.py (the real, finalized Play Console
# product lineup) and imported here, rather than hardcoded in this
# file -- this name is kept so nothing else that already reads it
# (this method below, and the RTDN dispatcher's own local import in
# modules/subscription/subscription_service.py, both unmodified) needs
# to change. An unknown product_id still correctly reports
# SubscriptionPurchaseOutcome.UNMAPPED_PRODUCT rather than guessing --
# EntitlementWriteService's own SUBSCRIPTION_PLANS remain the single
# source of truth for which plan names are valid at all.
from config.google_play_products import GOOGLE_PLAY_PRODUCT_TO_PLAN

# Google Play subscriptionState values (raw, from GooglePlaySubscription
# Verification.purchase_state) that represent a moment access should be
# granted -- see the Google Play Lifecycle design review. Every other
# real state (grace/on-hold/paused/cancelled/expired/revoked) is
# deliberately NOT in this set: this phase only activates, it never
# renews/downgrades/revokes (all explicitly out of scope).
_GOOGLE_PLAY_ACTIVATING_STATES = ("SUBSCRIPTION_STATE_ACTIVE",)
_GOOGLE_PLAY_PENDING_STATES = ("SUBSCRIPTION_STATE_PENDING",)

_activity_events_logger = logging.getLogger("activity_events")

# Phase 4B -- analytics-only purpose value for a payment that never goes
# through PaymentPurpose at all (Ask Now's ChatPack flows bypass
# PaymentService entirely -- see chat_pack_service.py/chatpack_google_
# verify.py). NOT added to PaymentPurpose itself: that enum drives
# _apply_business_effect()'s dispatch decision, and ChatPack has no
# business dispatch here to affect. properties.purpose has no closed
# enum in event_schemas.py (only failure_reason does), so this literal
# needs no schema change.
PAYMENT_PURPOSE_ASK_NOW_CHAT_PACK = "ASK_NOW_CHAT_PACK"

# Phase 4B -- maps GooglePlayVerificationStatus (the provider's own
# structured outcome, never raw error text) to the frozen FAILURE_
# REASONS vocabulary (modules/activity_events/event_schemas.py). Every
# value on the right already exists in that frozen set -- confirmed
# before writing this mapping, per the design freeze's explicit
# instruction not to widen event_schemas.py.
_GOOGLE_FAILURE_REASON_BY_VERIFICATION_STATUS = {
    GooglePlayVerificationStatus.INVALID_TOKEN: "invalid_input",
    GooglePlayVerificationStatus.NOT_FOUND: "not_found",
    GooglePlayVerificationStatus.AUTH_ERROR: "upstream_error",
    GooglePlayVerificationStatus.NETWORK_ERROR: "upstream_error",
    GooglePlayVerificationStatus.UNKNOWN_ERROR: "unknown",
}


class PaymentService:
    def __init__(
        self,
        provider_registry: Optional[PaymentProviderRegistry] = None,
        order_service: Optional[OrderService] = None,
        subscription_service: Optional[SubscriptionService] = None,
    ):
        self._provider_registry = provider_registry or get_default_registry()
        self._order_service = order_service or OrderService()
        self._subscription_service = subscription_service or SubscriptionService()

    def process_payment(self, request: PaymentRequest) -> PaymentVerificationResult:
        correlation_id = new_correlation_id()
        email = (request.order_payload or {}).get("email")
        product = (request.order_payload or {}).get("product")
        log_ctx = dict(
            correlation_id=correlation_id,
            provider=request.provider,
            product=product,
            razorpay_order_id=request.reference,
            razorpay_payment_id=request.payment_id,
            email=email,
        )

        log_payment_event("payment_attempt_received", status="STARTED", **log_ctx)

        try:
            provider = self._provider_registry.resolve(request.provider)
            log_payment_event("verification_started", status="STARTED", **log_ctx)
            result = provider.verify(request)
        except Exception as exc:
            log_payment_event(
                "verification_exception", status="FAILED",
                error=str(exc), exc_info=True, **log_ctx,
            )
            raise

        log_payment_event(
            "verification_result",
            status=result.status,
            error=None if result.status == PaymentStatus.VERIFIED else result.message,
            **log_ctx,
        )
        if result.status != PaymentStatus.VERIFIED:
            # Phase 4B -- the ONLY structured PaymentStatus.FAILED return
            # in this method. Never instruments the exception-raising
            # branches below (verification_exception, idempotency_claim_
            # exception, order_creation_failed, ReportDispatchError) --
            # those are infrastructure/bug-shaped failures already fully
            # captured by log_payment_event()'s own exc_info logging, not
            # genuine payment-verification rejections.
            if request.provider == PaymentProviderType.RAZORPAY:
                failure_reason = self._classify_razorpay_failure(request)
            elif request.provider == PaymentProviderType.GOOGLE_PLAY:
                failure_reason = self._classify_google_failure(result)
            else:
                failure_reason = "unknown"
            self._emit_payment_event(
                event_name="payment_failed",
                correlation_id=correlation_id,
                provider=request.provider,
                purpose=request.purpose,
                profile_id=request.profile_id,
                failure_reason=failure_reason,
                campaign_context=request.campaign_context,
            )
            return result

        existing = self._find_processed_payment_logged(request, log_ctx)
        if existing is not None:
            return self._handle_retry(request, existing, log_ctx)

        try:
            claimed = self._try_claim(request)
        except Exception as exc:
            # Diagnostic-loss fix (production incident,
            # correlation_id 8c85db26...): everything between
            # verification_result=VERIFIED and this point previously
            # had NO logging of its own -- a real production case was
            # a Google Play purchase_token (~171 chars) exceeding
            # ProcessedPayment.payment_id's old VARCHAR(120) bound,
            # raising sqlalchemy.exc.DataError. That is a DIFFERENT
            # exception class from the IntegrityError _try_claim()
            # already handles for its own, unrelated purpose (a
            # genuine concurrent-claim race), so it was never caught
            # there -- it propagated silently past every
            # log_payment_event() call in this method straight to the
            # caller's generic except-Exception-500, with zero trace
            # anywhere in the logs. The column is now widened
            # (migration 9f4d2a7e1c6b) -- this log line is the
            # defense-in-depth half of the fix, so ANY future
            # exception in this exact zone (whatever its cause) is now
            # loud and diagnosable, never silent again.
            log_payment_event(
                "idempotency_claim_exception", status="FAILED",
                error=str(exc), exc_info=True, **log_ctx,
            )
            raise

        if not claimed:
            # Lost a concurrent race for this exact payment_id --
            # someone else's request is (or just finished) processing
            # it. Re-check rather than proceed, so we never create a
            # second Order for the same payment.
            existing = self._find_processed_payment_logged(request, log_ctx)
            if existing is not None:
                return self._handle_retry(request, existing, log_ctx)
            log_payment_event(
                "duplicate_payment_in_progress", status=PaymentStatus.DUPLICATE, **log_ctx,
            )
            return PaymentVerificationResult(
                status=PaymentStatus.DUPLICATE,
                provider=request.provider,
                reference=request.reference,
                verified=True,
                message="This payment is already being processed.",
            )

        log_payment_event("order_creation_started", status="STARTED", **log_ctx)
        try:
            business_details = self._apply_business_effect(request, result)
        except ReportDispatchError as exc:
            # The Order WAS committed -- record its order_id on the
            # claim (response_payload stays None) so a later retry can
            # be classified RESUME instead of staying stuck forever
            # with no known order_id to resume.
            self._record_dispatch_failure(request, exc.order_id)
            log_payment_event(
                "order_creation_failed", status="FAILED", order_id=exc.order_id,
                error=str(exc.original_exception), exc_info=True, **log_ctx,
            )
            raise
        except Exception as exc:
            # Never leave partially committed payment state -- but note
            # what that means here specifically: PaymentService cannot
            # tell, from a non-ReportDispatchError exception, whether a
            # real Order was already created (e.g. it wasn't -- the
            # failure happened before OrderService even got to the
            # Order insert). The claim is deliberately left in its
            # unfinished state rather than deleted: any further request
            # for this exact payment_id is safely treated as "already
            # being processed" / REJECT (see _decide_retry) rather than
            # retried automatically, since we cannot yet prove it's
            # safe to do so.
            log_payment_event(
                "order_creation_failed", status="FAILED",
                error=str(exc), exc_info=True, **log_ctx,
            )
            raise

        # Phase 4B -- captured from the ORIGINAL provider.verify() result
        # (still `result` here), BEFORE the next line overwrites
        # result.raw_payload with business_details. For Google Play this
        # is the only safe extraction point left -- see
        # _safe_google_order_reference()'s own docstring for why
        # request.reference/result.reference must never be used instead.
        if request.provider == PaymentProviderType.RAZORPAY:
            order_reference = request.reference
        elif request.provider == PaymentProviderType.GOOGLE_PLAY:
            order_reference = self._safe_google_order_reference(result.raw_payload)
        else:
            order_reference = None

        # Callers (e.g. app.py's /webhook) need order_id/task_id to
        # reconstruct their existing response contract -- carried here
        # rather than adding a new field to PaymentVerificationResult,
        # since raw_payload already exists exactly for caller-specific
        # business detail like this.
        result.raw_payload = business_details
        self._finalize_claim(request, business_details)
        log_payment_event(
            "payment_processed", status="SUCCESS",
            order_id=business_details.get("order_id"), **log_ctx,
        )

        # Phase 4B -- the main payment_verified producer point: reached
        # only after _apply_business_effect() (the SUBSCRIPTION/REPORT_
        # PURCHASE business commit) AND _finalize_claim() have both
        # already completed. Fires regardless of the SubscriptionPurchase
        # Outcome (ACTIVATED/PENDING/NOT_ACTIVATED/UNMAPPED_PRODUCT/
        # ACTIVATION_FAILED) -- payment_verified means the PAYMENT itself
        # verified, never a stand-in for subscription_started (Phase 4A
        # already reports that separately, from inside
        # EntitlementWriteService, only when an entitlement write
        # actually happens).
        entity_type, entity_id = self._payment_entity(request, business_details)
        self._emit_payment_event(
            event_name="payment_verified",
            correlation_id=correlation_id,
            provider=request.provider,
            purpose=request.purpose,
            profile_id=request.profile_id,
            entity_type=entity_type,
            entity_id=entity_id,
            order_reference=order_reference,
            dedupe_key=self._payment_verified_dedupe_key(request),
            campaign_context=request.campaign_context,
        )
        return result

    # ------------------------------------------------------------
    # Safe Retry Policy (Payment Hardening Phase 5)
    # ------------------------------------------------------------
    def _handle_retry(
        self, request: PaymentRequest, existing: ProcessedPayment, log_ctx: Dict[str, Any],
    ) -> PaymentVerificationResult:
        """
        The single place a retry for an already-seen payment_id is
        decided and acted on. Never re-runs verification (the caller
        already passed that above) and never creates a new Order.
        """
        decision = self._decide_retry(existing)

        if decision == RetryDecision.IGNORE:
            log_payment_event(
                "retry_ignored_already_ready", status=PaymentStatus.DUPLICATE,
                order_id=existing.order_id, **log_ctx,
            )
            # Phase 4B -- the ONE true "already processed, no new
            # business effect will be applied" branch (report_stage is
            # already "Ready"). REJECT and the lost-claim-race
            # "duplicate_payment_in_progress" branch below are
            # deliberately NOT instrumented here -- both are genuinely
            # in-flight/ambiguous, not a confirmed duplicate.
            self._emit_payment_event(
                event_name="payment_duplicate_ignored",
                correlation_id=log_ctx.get("correlation_id"),
                provider=request.provider,
                purpose=request.purpose,
                profile_id=request.profile_id,
                # Task 10A S14 -- diagnostic value only (never re-derives
                # a conversion from this event); the SAME transaction's
                # attribution snapshot, not a fresh claim.
                campaign_context=request.campaign_context,
            )
            return self._duplicate_result(request, existing)

        if decision == RetryDecision.RESUME:
            # Payment Hardening Phase 6.2: the read that produced
            # RetryDecision.RESUME is not itself exclusive -- two
            # concurrent retries can both observe report_stage=="Failed"
            # a moment apart. Only one may actually dispatch. That is
            # decided here, atomically, by a single conditional UPDATE
            # -- never by a Python-level lock (which cannot coordinate
            # across separate worker processes) -- so exactly one
            # concurrent caller wins ownership and proceeds.
            if not self._try_acquire_resume_ownership(existing.order_id):
                log_payment_event(
                    "retry_resume_ownership_lost", status=PaymentStatus.DUPLICATE,
                    order_id=existing.order_id, **log_ctx,
                )
                return PaymentVerificationResult(
                    status=PaymentStatus.DUPLICATE,
                    provider=request.provider,
                    reference=request.reference,
                    verified=True,
                    message="This payment is already being processed.",
                )

            log_payment_event(
                "retry_resuming_pipeline", status="RESUMING",
                order_id=existing.order_id, **log_ctx,
            )
            try:
                resumed = self._order_service.redispatch_report_generation(existing.order_id)
            except Exception as exc:
                log_payment_event(
                    "retry_resume_failed", status="FAILED", order_id=existing.order_id,
                    error=str(exc), exc_info=True, **log_ctx,
                )
                raise

            response_payload = {
                "order_id": resumed.order_id,
                "status": resumed.status,
                "report_stage": resumed.report_stage,
                "task_id": resumed.task_id,
            }
            existing.order_id = resumed.order_id
            existing.response_payload = response_payload
            db.session.commit()
            log_payment_event(
                "retry_resumed", status="SUCCESS", order_id=resumed.order_id, **log_ctx,
            )
            # Phase 4B -- the SECOND payment_verified producer point,
            # reached only when a retry was classified RESUME and this
            # call actually won ownership and successfully redispatched.
            #
            # Semantic correction (pre-commit review): RESUME is
            # recovery/resumption of DOWNSTREAM business processing
            # (report generation) for a payment that was already
            # provider-verified -- it is never a new payment
            # verification. Proof, traced from this file's own code:
            # _handle_retry() (and therefore RESUME) is only ever
            # reached when _find_processed_payment_logged() already
            # found an existing ProcessedPayment row for this exact
            # (provider, payment_id); that row is only ever created by
            # _try_claim(), which only ever runs after provider.verify()
            # already returned VERIFIED for this same payment_id (see
            # process_payment()'s own "if result.status != VERIFIED:
            # return result" gate, well before _try_claim() is reached).
            # RESUME's own action, redispatch_report_generation(), only
            # re-triggers the report pipeline for the EXISTING order_id
            # -- it never calls provider.verify() again and never
            # creates a new ProcessedPayment claim. So RESUME and the
            # main success path always represent the SAME one real
            # provider payment, never two.
            #
            # dedupe_key is therefore the SAME canonical
            # payment_verified:<provider>:<payment_id> identity the main
            # path uses -- never a distinct RESUME-namespaced key. This
            # is deliberate, not a re-introduced bug: one real payment
            # must produce at most one canonical payment_verified row.
            # If the main path's own attempt already persisted one
            # (the common case -- dispatch itself returned without
            # raising, so the main path reached its own emission before
            # report_stage could ever later become "Failed"),
            # record_event()'s own dedupe mechanism correctly makes
            # this second attempt a no-op. If the main path's attempt
            # never persisted one (e.g. a synchronous ReportDispatchError
            # meant process_payment() re-raised before ever reaching its
            # own emission line, or analytics itself failed at that
            # moment), this RESUME emission correctly backfills the same
            # canonical row -- still exactly one. RESUME only ever
            # applies to an Order-backed (REPORT_PURCHASE) retry -- no
            # fresh provider.verify() ran here, so there is no Google
            # raw_payload available to source order_reference from;
            # Razorpay's own request.reference remains safe and
            # available regardless.
            self._emit_payment_event(
                event_name="payment_verified",
                correlation_id=log_ctx.get("correlation_id"),
                provider=request.provider,
                purpose=request.purpose,
                profile_id=request.profile_id,
                entity_type="order",
                entity_id=str(resumed.order_id),
                order_reference=(
                    request.reference
                    if request.provider == PaymentProviderType.RAZORPAY
                    else None
                ),
                dedupe_key=self._payment_verified_dedupe_key(request),
                campaign_context=request.campaign_context,
            )
            return PaymentVerificationResult(
                status=PaymentStatus.VERIFIED,
                provider=request.provider,
                reference=request.reference,
                verified=True,
                message="Resumed report generation for the existing order.",
                raw_payload=response_payload,
            )

        # RetryDecision.REJECT
        log_payment_event("retry_rejected", status=PaymentStatus.DUPLICATE, **log_ctx)
        return PaymentVerificationResult(
            status=PaymentStatus.DUPLICATE,
            provider=request.provider,
            reference=request.reference,
            verified=True,
            message="This payment is already being processed.",
        )

    def _decide_retry(self, existing: ProcessedPayment) -> str:
        """
        Classify a retry using ONLY Order.report_stage -- no schema
        change. Payment Hardening Phase 6's retry rule table:
            Pending    -> REJECT (dispatch hasn't started the pipeline yet)
            Processing -> REJECT (running right now -- never resume a
                          run that might still be in flight)
            Ready      -> IGNORE (already fully succeeded)
            Failed     -> RESUME (definitively finished failing)
        Any other/unrecognized value is treated as REJECT, the safe
        default. See module docstring for the still-standing honest
        limitation (RESUME re-runs the whole pipeline; it cannot
        resume from one specific internal stage).
        """
        if existing.order_id is None:
            return RetryDecision.REJECT

        order = Order.query.get(existing.order_id)
        if order is None:
            return RetryDecision.REJECT

        if order.report_stage == "Ready":
            return RetryDecision.IGNORE

        if order.report_stage == "Failed":
            return RetryDecision.RESUME

        # "Pending" (dispatch not yet started) or "Processing"
        # (actively running right now) -- neither is safe to resume.
        return RetryDecision.REJECT

    def _try_acquire_resume_ownership(self, order_id: int) -> bool:
        """
        Payment Hardening Phase 6.2 -- the fix for the race the Resume
        Safety Audit found. Atomically transitions Order.report_stage
        from "Failed" to "Processing" in a single conditional UPDATE:

            UPDATE orders SET report_stage='Processing'
            WHERE id=:order_id AND report_stage='Failed'

        This is one SQL statement -- the database itself guarantees
        that if two concurrent requests issue it for the same
        order_id, only one can find the row still matching
        report_stage='Failed' and actually update it; the other
        updates zero rows. Returns True only for the caller that
        performed the transition (rowcount == 1) -- the sole owner
        allowed to dispatch. Deliberately not a Python threading.Lock
        or in-memory flag: those cannot coordinate across separate
        worker processes or hosts, and this must (per this phase's
        requirements) work across both.
        """
        rows_updated = Order.query.filter_by(
            id=order_id, report_stage="Failed",
        ).update(
            {"report_stage": "Processing"}, synchronize_session=False,
        )
        db.session.commit()
        return rows_updated == 1

    # ------------------------------------------------------------
    def _apply_business_effect(
        self, request: PaymentRequest, verification_result: PaymentVerificationResult,
    ) -> Optional[Dict[str, Any]]:
        if request.purpose == PaymentPurpose.REPORT_PURCHASE:
            if not request.order_payload:
                raise ValueError("order_payload is required for a REPORT_PURCHASE payment.")
            created = self._order_service.create_paid_report_order(request.order_payload)
            return {
                "order_id": created.order_id,
                "status": created.status,
                "report_stage": created.report_stage,
                "task_id": created.task_id,
            }

        if request.purpose == PaymentPurpose.SUBSCRIPTION:
            return self._apply_subscription_business_effect(request, verification_result)

        raise ValueError(f"Unknown payment purpose: {request.purpose!r}")

    # ------------------------------------------------------------
    # Subscription Purchase System -- S4.
    #
    #     Purchase Request -> GooglePlayProvider.verify() (already ran,
    #     above, before this method is ever reached) -> Verification
    #     Result -> [validate verification] -> [create internal
    #     subscription purchase result] -> return outcome.
    #
    # This method is the "validate verification" + "create internal
    # result" steps. It never acknowledges the Google Play purchase,
    # never processes RTDN/renewals/cancellations/refunds, and never
    # writes CurrentEntitlement/SubscriptionEvent directly -- the one
    # and only entitlement-writing call is
    # self._subscription_service.activate_subscription(), the exact
    # same, unmodified SubscriptionService every other caller in this
    # codebase already goes through.
    #
    # Duplicate-purchase protection is deliberately NOT built here: the
    # existing ProcessedPayment claim (provider="GOOGLE_PLAY",
    # payment_id=purchase_token), already run by process_payment()
    # above for every purpose, already prevents the same purchase_token
    # from reaching this method twice concurrently or from a resubmit --
    # see this method's own docstring note below on why the existing
    # _decide_retry() path degrades safely for a purpose it wasn't
    # written with in mind, rather than needing its own copy.
    # ------------------------------------------------------------
    def _apply_subscription_business_effect(
        self, request: PaymentRequest, verification_result: PaymentVerificationResult,
    ) -> Dict[str, Any]:
        if request.profile_id is None:
            raise ValueError("profile_id is required for a SUBSCRIPTION payment.")

        # verification_result.status == VERIFIED (guaranteed by the
        # caller, process_payment(), before this method is ever
        # reached) proves only that Google Play has a real record of
        # this purchase_token -- per GooglePlayProvider's own
        # documented contract, it says nothing about whether the
        # subscription's CURRENT state should grant access. That
        # business judgment is made here, reading the normalized data
        # verify() already produced, in verification_result.raw_payload.
        purchase_data = verification_result.raw_payload or {}
        purchase_state = purchase_data.get("purchase_state")
        product_id = purchase_data.get("product_id")
        order_id = purchase_data.get("order_id")

        # Subscription Purchase System -- S7E, made atomic with the
        # entitlement write in S15. Record which profile this
        # purchase_token belongs to as soon as it's known, before the
        # purchase_state branches below -- a later RTDN for this exact
        # token (or a replacement token linked to it) needs this
        # mapping to resolve identity regardless of whether activation
        # ends up succeeding here (RTDN itself never carries
        # profile_id; see routes/routes_rtdn.py and
        # SubscriptionPurchaseMappingService).
        #
        # commit=False here: this write is staged, not committed, so it
        # shares one transaction with whatever happens next. Every
        # early-return branch below that does NOT reach
        # activate_subscription() commits it immediately itself (S15
        # requirement 2 only applies once an entitlement write is
        # actually attempted -- a PENDING/NOT_ACTIVATED/UNMAPPED_PRODUCT
        # purchase has no entitlement half to stay consistent with).
        # The activation path commits nothing itself and instead relies
        # on activate_subscription()'s own existing, unmodified final
        # commit to commit both together -- if that commit never
        # happens (an exception, rolled back), this mapping write is
        # rolled back with it, never left as an orphaned commit.
        if request.payment_id:
            SubscriptionPurchaseMappingService().upsert(
                purchase_token=request.payment_id,
                profile_id=request.profile_id,
                provider="GOOGLE_PLAY",
                product_id=product_id,
                order_id=order_id,
                linked_purchase_token=purchase_data.get("linked_purchase_token"),
                commit=False,
            )

        if purchase_state in _GOOGLE_PLAY_PENDING_STATES:
            db.session.commit()
            return SubscriptionPurchaseResult(
                outcome=SubscriptionPurchaseOutcome.PENDING,
                profile_id=request.profile_id,
                activated=False,
                purchase_state=purchase_state,
                provider_order_id=order_id,
                message="Purchase is pending; no entitlement granted yet.",
            ).to_dict()

        if purchase_state not in _GOOGLE_PLAY_ACTIVATING_STATES:
            db.session.commit()
            return SubscriptionPurchaseResult(
                outcome=SubscriptionPurchaseOutcome.NOT_ACTIVATED,
                profile_id=request.profile_id,
                activated=False,
                purchase_state=purchase_state,
                provider_order_id=order_id,
                message=f"purchase_state={purchase_state!r} does not currently grant access.",
            ).to_dict()

        plan = GOOGLE_PLAY_PRODUCT_TO_PLAN.get(product_id)
        if plan is None:
            db.session.commit()
            return SubscriptionPurchaseResult(
                outcome=SubscriptionPurchaseOutcome.UNMAPPED_PRODUCT,
                profile_id=request.profile_id,
                activated=False,
                purchase_state=purchase_state,
                provider_order_id=order_id,
                message=f"product_id={product_id!r} has no known plan mapping -- reported, not guessed.",
            ).to_dict()

        expires_at = self._parse_expiry(purchase_data.get("expiry_time"))
        if expires_at is None:
            db.session.commit()
            return SubscriptionPurchaseResult(
                outcome=SubscriptionPurchaseOutcome.ACTIVATION_FAILED,
                profile_id=request.profile_id,
                activated=False,
                purchase_state=purchase_state,
                plan=plan,
                provider_order_id=order_id,
                message="Google Play did not provide a usable expiry_time; cannot activate.",
            ).to_dict()

        # The one and only entitlement-writing call in this whole
        # method -- SubscriptionService (unmodified) delegates to
        # EntitlementWriteService (unmodified) exactly as it already
        # does for every other caller. request.selected_segment (S12)
        # replaces the previously-hardcoded None; EntitlementWriteService's
        # own existing, unmodified plan-access check is what actually
        # requires/ignores it per plan -- not this method. Its own final
        # db.session.commit() (unchanged) is what commits the mapping
        # write staged above, atomically with this one.
        write_result = self._subscription_service.activate_subscription(
            profile_id=request.profile_id,
            plan=plan,
            selected_segment=request.selected_segment,
            expires_at=expires_at,
            transaction_reference=order_id,
        )

        # Subscription Purchase System -- S10. Acknowledge ONLY after a
        # successful activation -- never for a failed/pending/unmapped
        # purchase (all already returned above by this point). Never
        # affects the result returned below either way; see
        # _acknowledge_google_play_purchase()'s own docstring for this
        # phase's failure policy.
        if write_result.success:
            self._acknowledge_google_play_purchase(
                purchase_token=request.payment_id,
                package_name=(request.metadata or {}).get("package_name"),
                already_acknowledged=(
                    purchase_data.get("acknowledgement_state")
                    == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
                ),
            )

        return SubscriptionPurchaseResult(
            outcome=(
                SubscriptionPurchaseOutcome.ACTIVATED
                if write_result.success
                else SubscriptionPurchaseOutcome.ACTIVATION_FAILED
            ),
            profile_id=request.profile_id,
            activated=write_result.success,
            purchase_state=purchase_state,
            plan=plan,
            provider_order_id=order_id,
            message=write_result.message,
        ).to_dict()

    # ------------------------------------------------------------
    # Subscription Purchase System -- S10. Automatic acknowledgement.
    #
    #     Subscription activated successfully -> GooglePlayProvider.
    #     acknowledge_subscription() -> log structured result -> return
    #     (the ORIGINAL activation result, untouched by this method).
    #
    # Called ONLY from _apply_subscription_business_effect(), and only
    # after write_result.success is True -- never for a failed
    # verification, a pending purchase, an unmapped product, or a
    # failed activation, all of which return before this point is ever
    # reached.
    #
    # Failure policy: acknowledgement failure must never roll back an
    # already-successful activation. acknowledge_subscription() (S6,
    # unmodified) already returns a structured GooglePlayAcknowledgementResult
    # for every failure mode (network, auth, invalid token, revoked,
    # expired, unknown) rather than raising -- this method logs
    # whatever it returns and always returns None either way. The
    # try/except below is a pure defensive backstop matching that
    # contract, not a workaround for one; a future RTDN or a manual
    # retry gets another chance to acknowledge, so a failure here is
    # never the only opportunity.
    # ------------------------------------------------------------
    def _acknowledge_google_play_purchase(
        self, *, purchase_token: Optional[str], package_name: Optional[str],
        already_acknowledged: bool,
    ) -> None:
        if not purchase_token:
            return

        correlation_id = new_correlation_id()
        log_ctx = dict(
            correlation_id=correlation_id, provider=PaymentProviderType.GOOGLE_PLAY,
            razorpay_payment_id=purchase_token,
        )

        if already_acknowledged:
            log_payment_event(
                "google_play_acknowledge_skipped", status="ALREADY_ACKNOWLEDGED", **log_ctx,
            )
            return

        try:
            result = GooglePlayProvider().acknowledge_subscription(
                purchase_token=purchase_token, package_name=package_name,
            )
        except Exception as exc:
            log_payment_event(
                "google_play_acknowledge_failed", status="UNEXPECTED_EXCEPTION",
                error=str(exc), exc_info=True, **log_ctx,
            )
            return

        log_payment_event(
            "google_play_acknowledge_result", status=result.status,
            error=result.error_message, **log_ctx,
        )

    @staticmethod
    def _parse_expiry(expiry_time: Any) -> Optional[datetime]:
        """expiry_time arrives as the ISO string GooglePlaySubscription
        Verification.to_dict() produces (verification_result.raw_payload
        is always a plain dict, never a live dataclass) -- never raises
        on a malformed/missing value, since that is a legitimate,
        structured ACTIVATION_FAILED outcome here, not an exception."""
        if not expiry_time:
            return None
        if isinstance(expiry_time, datetime):
            return expiry_time
        try:
            return datetime.fromisoformat(str(expiry_time).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------
    # Idempotency (Payment Hardening Phase 3) -- backed by
    # ProcessedPayment's DB-level UNIQUE(provider, payment_id).
    # ------------------------------------------------------------
    def _find_processed_payment(self, request: PaymentRequest) -> Optional[ProcessedPayment]:
        if not request.payment_id:
            return None
        return ProcessedPayment.query.filter_by(
            provider=request.provider, payment_id=request.payment_id,
        ).first()

    def _find_processed_payment_logged(
        self, request: PaymentRequest, log_ctx: Dict[str, Any],
    ) -> Optional[ProcessedPayment]:
        """Same as _find_processed_payment(), with the diagnostic-loss
        fix: any exception here (DB connectivity, schema mismatch,
        etc.) is now logged with a full traceback before propagating,
        instead of silently reaching the caller's generic
        except-Exception-500 with no trace anywhere in the logs. See
        process_payment()'s own comment on the _try_claim() call site
        for the production incident this class of gap caused."""
        try:
            return self._find_processed_payment(request)
        except Exception as exc:
            log_payment_event(
                "idempotency_lookup_exception", status="FAILED",
                error=str(exc), exc_info=True, **log_ctx,
            )
            raise

    def _try_claim(self, request: PaymentRequest) -> bool:
        """Attempt to atomically claim (provider, payment_id) by
        inserting a placeholder row. Returns True if this call won the
        claim, False if a concurrent request already holds it (the
        UNIQUE constraint made our insert fail -- IntegrityError,
        specifically -- a genuine, expected race, not an error).

        Any OTHER database exception (e.g. DataError from a value
        exceeding a column's length -- the production incident this
        fix addresses) is NOT a race and must not be treated like one;
        it is rolled back here (so the session is left clean for the
        caller's own exception logging and anything that runs
        afterward) and re-raised, letting process_payment()'s own
        try/except around this call log it properly."""
        claim = ProcessedPayment(
            provider=request.provider,
            payment_id=request.payment_id,
            reference=request.reference,
        )
        db.session.add(claim)
        try:
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
            return False
        except Exception:
            db.session.rollback()
            raise

    def _finalize_claim(self, request: PaymentRequest, business_details: Dict[str, Any]) -> None:
        claim = ProcessedPayment.query.filter_by(
            provider=request.provider, payment_id=request.payment_id,
        ).first()
        if claim is not None:
            claim.order_id = business_details.get("order_id")
            claim.response_payload = business_details
            db.session.commit()

    def _record_dispatch_failure(self, request: PaymentRequest, order_id: int) -> None:
        """
        Record the order_id that WAS committed even though dispatch
        subsequently failed -- response_payload stays None (the
        pipeline is not confirmed complete), but a later retry can now
        find this order_id and be classified RESUME instead of REJECT.
        """
        claim = ProcessedPayment.query.filter_by(
            provider=request.provider, payment_id=request.payment_id,
        ).first()
        if claim is not None:
            claim.order_id = order_id
            db.session.commit()

    def _release_claim(self, request: PaymentRequest) -> None:
        """
        Delete an unfinished claim row (response_payload still None),
        freeing this payment_id to be claimed again from scratch. NOT
        called automatically anywhere in this file -- kept available
        for a human (e.g. an admin reconciliation tool) to call only
        after confirming no Order actually resulted from a failed
        attempt that never even reached ReportDispatchError (i.e.
        failed before the Order was created at all). Never touches a
        claim that has an order_id recorded or was fully finalized.
        """
        claim = ProcessedPayment.query.filter_by(
            provider=request.provider, payment_id=request.payment_id,
        ).first()
        if claim is not None and claim.response_payload is None and claim.order_id is None:
            db.session.delete(claim)
            db.session.commit()

    def _duplicate_result(
        self, request: PaymentRequest, existing: ProcessedPayment,
    ) -> PaymentVerificationResult:
        return PaymentVerificationResult(
            status=PaymentStatus.DUPLICATE,
            provider=request.provider,
            reference=request.reference,
            verified=True,
            message="Payment already processed; returning the existing result.",
            raw_payload=existing.response_payload,
        )

    # ------------------------------------------------------------
    # Phase 4B -- observational only. See _emit_payment_event()'s own
    # docstring for the non-regression guarantee. Nothing below this
    # point ever changes what process_payment()/_handle_retry() decide
    # or return.
    # ------------------------------------------------------------
    @staticmethod
    def _hash_google_purchase_token(purchase_token: str) -> str:
        """Deterministic, one-way identifier for Google Play's
        purchase_token -- a long-lived, replayable, credential-like
        value (see payment_logger.py's own docstring) that must never
        reach activity_events in raw form. The ONLY place this hash is
        used is dedupe_key -- never properties, never entity_id, never
        correlation_id. Stdlib hashlib only; no new dependency, no new
        crypto abstraction."""
        return hashlib.sha256(purchase_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_google_order_reference(raw_payload: Optional[Dict[str, Any]]) -> Optional[str]:
        """Google Play's own order_id (e.g. "GPA.xxxx-xxxx-xxxx-xxxxx"),
        extracted from a GooglePlayProvider verification's raw_payload
        dict. NEVER request.reference/result.reference -- for every
        Google Play PaymentRequest built anywhere in this codebase
        today (routes_google_purchase_confirm.py, routes_google_report_
        confirm.py), that field is actually the purchase_token itself,
        not an order id. Returns None -- never falls back to the token
        -- when Google's response never carried an order_id."""
        return (raw_payload or {}).get("order_id")

    @staticmethod
    def _classify_razorpay_failure(request: PaymentRequest) -> str:
        """Mirrors RazorpayProvider.verify()'s own three FAILED
        branches using the same request-shape facts that method itself
        checks -- never parses result.message (provider-ish free
        text). Returns a value already present in the frozen
        FAILURE_REASONS vocabulary."""
        if not request.reference or not request.payment_id:
            return "invalid_input"
        if request.metadata.get("source") == "webhook":
            # The server-webhook path never carries/needs a checkout
            # signature (see RazorpayProvider.verify()) -- a FAILED
            # result reaching this point for that path is not a
            # signature mismatch.
            return "invalid_input"
        if not request.signature:
            return "invalid_input"
        return "signature_mismatch"

    @staticmethod
    def _classify_google_failure(result: PaymentVerificationResult) -> str:
        """Maps GooglePlayProvider's own structured verification_status
        (never raw error text) to the frozen FAILURE_REASONS
        vocabulary. Also covers the REPORT_PURCHASE-only case where
        verification_status is VERIFIED but purchase_state is not the
        purchased state (Canceled/Pending) -- Google itself declined to
        complete this purchase, from this backend's perspective."""
        raw = result.raw_payload or {}
        verification_status = raw.get("verification_status")
        if verification_status == GooglePlayVerificationStatus.VERIFIED:
            return "provider_declined"
        return _GOOGLE_FAILURE_REASON_BY_VERIFICATION_STATUS.get(verification_status, "unknown")

    @staticmethod
    def _payment_verified_dedupe_key(request: PaymentRequest) -> Optional[str]:
        """Derived from the SAME stable provider payment identity
        ProcessedPayment's own UNIQUE(provider, payment_id) already
        uses for business-layer dedupe (Phase 4B design freeze -- see
        payment_service.py's own module docstring). Razorpay's
        payment_id is safe to use as-is; Google Play's payment_id is
        the purchase_token and is ALWAYS hashed first -- never placed
        into dedupe_key raw."""
        if not request.payment_id:
            return None
        if request.provider == PaymentProviderType.RAZORPAY:
            return f"payment_verified:RAZORPAY:{request.payment_id}"
        if request.provider == PaymentProviderType.GOOGLE_PLAY:
            return f"payment_verified:GOOGLE_PLAY:{PaymentService._hash_google_purchase_token(request.payment_id)}"
        return None

    @staticmethod
    def _payment_entity(request: PaymentRequest, business_details: Dict[str, Any]):
        """Only ever the entity this payment's own business_details
        dict already, truthfully carries -- never fabricated, never an
        extra lookup. REPORT_PURCHASE's business_details always has a
        real Order.id. SUBSCRIPTION's SubscriptionPurchaseResult.to_dict()
        carries no comparable stable row id at this layer -- the actual
        SubscriptionEvent.id lives inside EntitlementWriteService,
        already reported separately by Phase 4A's own subscription_*
        events -- so entity stays (None, None) rather than guessing."""
        if request.purpose == PaymentPurpose.REPORT_PURCHASE:
            order_id = business_details.get("order_id")
            if order_id is not None:
                return "order", str(order_id)
        return None, None

    def _emit_payment_event(
        self,
        *,
        event_name: str,
        correlation_id: Optional[str],
        provider: str,
        purpose: str,
        profile_id: Optional[int] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        order_reference: Optional[str] = None,
        failure_reason: Optional[str] = None,
        dedupe_key: Optional[str] = None,
        campaign_context: Optional[Dict[str, str]] = None,
    ) -> None:
        """Called ONLY after this service's own authoritative business
        commit for the request has already completed (see each call
        site's own comment for exactly which commit). record_event()
        (Phase 2, unmodified) already guarantees it never raises and
        never touches db.session; this method is additionally wrapped
        in its own try/except so an unexpected error in the small
        amount of mapping logic above -- not in record_event() itself
        -- can never propagate back into a caller whose
        PaymentVerificationResult has already been decided. Purely
        observational: nothing here can influence what is returned.

        campaign_context (Task 10A) is always the durable transaction
        snapshot each call site already resolved onto its own
        PaymentRequest (modules/payments/campaign_attribution.py) --
        this method never re-derives, re-validates, or trusts a fresh
        value itself; record_event() applies its own, unmodified
        sanitize_campaign_context() as the final defense-in-depth pass,
        exactly like every other campaign_context producer already
        relies on."""
        properties: Dict[str, Any] = {"purpose": purpose, "provider": provider}
        if order_reference is not None:
            properties["order_reference"] = order_reference
        if failure_reason is not None:
            properties["failure_reason"] = failure_reason

        try:
            record_event(
                event_name=event_name,
                occurred_at=datetime.now(timezone.utc),
                platform="backend_internal",
                source="payment_service",
                firebase_uid=None,
                profile_id=profile_id,
                correlation_id=correlation_id,
                entity_type=entity_type,
                entity_id=entity_id,
                properties=properties,
                campaign_context=campaign_context,
                dedupe_key=dedupe_key,
            )
        except Exception:
            _activity_events_logger.warning(
                "payment_service: unexpected error emitting %s (swallowed -- "
                "the payment result already decided is unaffected)",
                event_name, exc_info=True,
            )
