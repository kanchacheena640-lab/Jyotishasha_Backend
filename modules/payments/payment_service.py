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

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Order
from modules.models_processed_payments import ProcessedPayment
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
            return result

        existing = self._find_processed_payment(request)
        if existing is not None:
            return self._handle_retry(request, existing, log_ctx)

        if not self._try_claim(request):
            # Lost a concurrent race for this exact payment_id --
            # someone else's request is (or just finished) processing
            # it. Re-check rather than proceed, so we never create a
            # second Order for the same payment.
            existing = self._find_processed_payment(request)
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

    def _try_claim(self, request: PaymentRequest) -> bool:
        """Attempt to atomically claim (provider, payment_id) by
        inserting a placeholder row. Returns True if this call won the
        claim, False if a concurrent request already holds it (the
        UNIQUE constraint made our insert fail)."""
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
