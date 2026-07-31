# modules/subscription/subscription_service.py

"""
SubscriptionService -- THE only application-layer entry point for all
subscription operations. Every future caller -- Google Play Billing,
Apple StoreKit, PremiumReportService, Admin actions, Webhooks,
Scheduled Jobs -- must call SubscriptionService; nobody should call
EntitlementWriteService directly.

    Caller -> SubscriptionService -> EntitlementService (read, as needed)
                                   -> EntitlementWriteService (all writes)
                                   -> CurrentEntitlement / SubscriptionEvent

This layer owns WORKFLOW, not persistence and not business rules that
already live in EntitlementWriteService (one-time trial, active-
subscription protection, etc. all stay there -- this file never
re-derives them). It never imports CurrentEntitlement or
SubscriptionEvent and never calls db.session; every state change is
delegated to EntitlementWriteService, the only writer of those two
tables. This mirrors PremiumReportService's own relationship to the AI
Report Engine: a thin orchestration layer in front of the one
component allowed to touch storage.

EntitlementService (read) and EntitlementWriteService (write) remain
completely independent of each other; this file is the one place that
may depend on both. In this phase, none of the nine core workflow
methods below actually needs to read first -- each already receives
enough from its caller to know which transition to invoke, and
EntitlementWriteService's own idempotency/no-op handling (duplicate
trial, nothing to renew, etc.) already covers "is this call currently
applicable." Calling EntitlementService first in those methods would
just re-check the same thing EntitlementWriteService is about to check
anyway -- exactly the business-rule duplication this phase says not to
do. EntitlementService is injected and available for the orchestration
methods that genuinely need it: today that's none of the nine, but the
constructor already accepts it so a future method (or one of the
"Future" stubs below) never needs a signature change to start using it.

Note: this lives in modules/subscription/ alongside the older,
account-scoped legacy `Subscription` model/routes (modules/subscription
/models.py, routes.py, routes_webhook.py, utils.py) -- that system is
untouched by this file, is not imported here, and is not read from or
written to by anything below.

Exception behavior: EntitlementWriteService lets infrastructure
failures (SQLAlchemyError, IntegrityError, connection errors, ...)
propagate as real exceptions rather than converting them into a
business result. This service does not catch or reinterpret those --
they propagate through unchanged. Only the structured
EntitlementWriteResult business outcomes it already returns (duplicate
trial, nothing to renew, active-subscription protection, etc.) are
handled here as plain data, passed straight through to the caller.

Every one of the nine core methods below follows the same shape:
    1. an optional pre-delegation hook (today, only receipt validation
       on activate_subscription -- a no-op)
    2. delegate to the matching EntitlementWriteService method
    3. call the (currently no-op) analytics / notification / audit
       hooks with the result

Nothing under "Future" is implemented -- each is a named extension
point a future caller can already be written against, without this
file's public API changing again when the real logic lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.entitlement import (
    EntitlementService,
    EntitlementWriteResult,
    EntitlementWriteService,
)
# Note: this file deliberately does NOT import anything from
# modules.payments at module level. modules/payments/__init__.py
# imports payment_service.py, which itself imports SubscriptionService
# from this file at ITS module level -- a module-level import back
# from here would be a real circular import whose success would
# depend on which of the two packages Flask happens to import first
# at startup. process_webhook_event() below imports GooglePlayProvider
# / ProcessedSubscriptionEventService locally, inside the method body,
# for exactly this reason (by the time the method is actually called,
# both modules have long since finished loading).

# Google Play RTDN notification types (Subscription Purchase System --
# S7A audit) that map onto an existing EntitlementWriteService
# transition via process_webhook_event() below. SUBSCRIPTION_PAUSED
# and SUBSCRIPTION_RESTARTED are deliberately absent -- their business
# rules are not yet decided (see _dispatch_verified_event).
_RTDN_RENEWAL_EVENTS = ("SUBSCRIPTION_RENEWED", "SUBSCRIPTION_RECOVERED")
_RTDN_EXPIRY_EVENTS = ("SUBSCRIPTION_ON_HOLD", "SUBSCRIPTION_EXPIRED")
_RTDN_NOT_YET_IMPLEMENTED_EVENTS = ("SUBSCRIPTION_PAUSED", "SUBSCRIPTION_RESTARTED")
# Real Google notification types the S7A audit found require no
# entitlement transition at all -- claimed for ledger completeness,
# never dispatched to any EntitlementWriteService method.
_RTDN_NO_ACTION_EVENTS = (
    "SUBSCRIPTION_PRICE_CHANGE_CONFIRMED",
    "SUBSCRIPTION_PENDING_PURCHASE_CANCELED",
    "SUBSCRIPTION_PAUSE_SCHEDULE_CHANGED",
    "SUBSCRIPTION_DEFERRED",
)


class SubscriptionService:
    def __init__(
        self,
        entitlement_write_service: Optional[EntitlementWriteService] = None,
        entitlement_service: Optional[EntitlementService] = None,
    ):
        self._entitlement_write_service = entitlement_write_service or EntitlementWriteService()
        self._entitlement_service = entitlement_service or EntitlementService()

    # ------------------------------------------------------------
    # Public workflows -- one per EntitlementWriteService method.
    # ------------------------------------------------------------
    def start_trial(self, profile_id: int) -> EntitlementWriteResult:
        result = self._entitlement_write_service.start_trial(profile_id)
        self._after_transition(profile_id=profile_id, action="start_trial", result=result)
        return result

    def expire_trial(self, profile_id: int) -> EntitlementWriteResult:
        result = self._entitlement_write_service.expire_trial(profile_id)
        self._after_transition(profile_id=profile_id, action="expire_trial", result=result)
        return result

    def activate_subscription(
        self,
        profile_id: int,
        plan: str,
        selected_segment: Optional[str],
        expires_at: datetime,
        transaction_reference: Optional[str] = None,
        store: Optional[str] = None,
        receipt_payload: Optional[dict] = None,
    ) -> EntitlementWriteResult:
        # store/receipt_payload exist here for the future receipt-
        # validation hook below. They are NOT forwarded to
        # EntitlementWriteService.activate_subscription(), since that
        # method's signature does not accept them and it must not be
        # modified in this task.
        self._validate_receipt(
            store=store,
            transaction_reference=transaction_reference,
            receipt_payload=receipt_payload,
        )
        result = self._entitlement_write_service.activate_subscription(
            profile_id=profile_id,
            plan=plan,
            selected_segment=selected_segment,
            expires_at=expires_at,
            transaction_reference=transaction_reference,
        )
        self._after_transition(profile_id=profile_id, action="activate_subscription", result=result)
        return result

    def renew_subscription(
        self,
        profile_id: int,
        expires_at: datetime,
        plan: Optional[str] = None,
        selected_segment: Optional[str] = None,
        transaction_reference: Optional[str] = None,
    ) -> EntitlementWriteResult:
        result = self._entitlement_write_service.renew_subscription(
            profile_id=profile_id,
            expires_at=expires_at,
            plan=plan,
            selected_segment=selected_segment,
            transaction_reference=transaction_reference,
        )
        self._after_transition(profile_id=profile_id, action="renew_subscription", result=result)
        return result

    def enter_grace(self, profile_id: int) -> EntitlementWriteResult:
        result = self._entitlement_write_service.enter_grace(profile_id)
        self._after_transition(profile_id=profile_id, action="enter_grace", result=result)
        return result

    def exit_grace(self, profile_id: int) -> EntitlementWriteResult:
        result = self._entitlement_write_service.exit_grace(profile_id)
        self._after_transition(profile_id=profile_id, action="exit_grace", result=result)
        return result

    def cancel_subscription(self, profile_id: int) -> EntitlementWriteResult:
        result = self._entitlement_write_service.cancel_subscription(profile_id)
        self._after_transition(profile_id=profile_id, action="cancel_subscription", result=result)
        return result

    def expire_subscription(self, profile_id: int) -> EntitlementWriteResult:
        result = self._entitlement_write_service.expire_subscription(profile_id)
        self._after_transition(profile_id=profile_id, action="expire_subscription", result=result)
        return result

    def record_refund(
        self, profile_id: int, transaction_reference: Optional[str] = None,
    ) -> EntitlementWriteResult:
        result = self._entitlement_write_service.record_refund(
            profile_id, transaction_reference=transaction_reference,
        )
        self._after_transition(profile_id=profile_id, action="record_refund", result=result)
        return result

    # ------------------------------------------------------------
    # Future -- named extension points for callers that don't exist
    # yet (Google Play Billing, Apple StoreKit, Webhooks, Scheduled
    # Jobs). Each raises NotImplementedError so a premature call fails
    # loudly and unambiguously rather than silently doing nothing.
    # Designing the shape now means none of the nine methods above,
    # and no future caller written against these, will need to change
    # when the real implementation lands.
    # ------------------------------------------------------------
    def process_webhook_event(
        self, *, provider: str, event_type: str, payload: Dict[str, Any],
    ) -> EntitlementWriteResult:
        """
        Google Play RTDN dispatcher (Subscription Purchase System --
        S7B). The single entry point a future RTDN route would call
        after decoding the Pub/Sub envelope -- this method does not
        trust event_type/payload as the source of truth (per the S7A
        audit's own finding); it re-verifies the purchase with Google
        first and dispatches based on that fresh state, using
        payload only for `purchase_token` / `package_name` / `profile_id`.

        payload keys used:
            purchase_token (str) -- required for every event except
                                     TEST_NOTIFICATION.
            package_name (str, optional) -- falls back to
                                     GOOGLE_PLAY_PACKAGE_NAME.
            profile_id (int) -- required for every event that dispatches
                                     an entitlement transition. Resolving
                                     which profile a bare purchase_token
                                     belongs to (RTDN payloads carry no
                                     app identity at all) is the
                                     caller's responsibility and is
                                     explicitly out of scope here -- a
                                     missing profile_id is reported as
                                     MISSING_PROFILE_ID, never guessed.

        Flow: verify with Google -> extract orderId -> claim via
        ProcessedSubscriptionEvent -> dispatch to an existing
        SubscriptionService/EntitlementWriteService method -> finalize.
        If dispatch raises (including the deliberate
        NotImplementedError for PAUSED/RESTARTED), the claim is left
        unfinished -- same failure posture as every other ledger in
        this codebase; see processed_subscription_event_service.py.

        provider must be "GOOGLE_PLAY" -- Apple App Store Server
        Notifications are a separate, unimplemented phase.
        """
        if event_type == "TEST_NOTIFICATION":
            # Not a real purchase event -- nothing to verify, nothing
            # to claim (there is no purchase_token to key a claim on).
            return EntitlementWriteResult(
                success=True, action="IGNORED_TEST_NOTIFICATION", profile_id=0,
                message="Google Play test notification -- acknowledged, no purchase to verify.",
            )

        if provider != "GOOGLE_PLAY":
            raise NotImplementedError(
                f"process_webhook_event does not support provider={provider!r} yet -- "
                f"Apple App Store Server Notifications are a separate, unimplemented phase."
            )

        # Local imports -- see the module-level note above about why
        # modules.payments is never imported at this file's top level.
        from modules.payments.google_play_provider import GooglePlayProvider
        from modules.payments.google_play_models import GooglePlayVerificationStatus
        from modules.payments.processed_subscription_event_service import (
            ProcessedSubscriptionEventService,
            SubscriptionEventClaimOutcome,
        )

        purchase_token = payload.get("purchase_token")
        profile_id = payload.get("profile_id")

        if not purchase_token:
            return EntitlementWriteResult(
                success=False, action="MISSING_PURCHASE_TOKEN", profile_id=profile_id or 0,
                message="payload['purchase_token'] is required.",
            )

        # Step 1 -- verify with Google. Reused exactly as-is (S3);
        # never modified by this file. The RTDN payload's own
        # notificationType/subscriptionId are never trusted directly --
        # only this fresh read of Google's current state is.
        verification = GooglePlayProvider().verify_subscription_purchase(
            purchase_token=purchase_token, package_name=payload.get("package_name"),
        )

        if verification.verification_status != GooglePlayVerificationStatus.VERIFIED:
            return EntitlementWriteResult(
                success=False, action="VERIFICATION_FAILED", profile_id=profile_id or 0,
                message=verification.error_message or f"verification_status={verification.verification_status}",
            )

        # Step 2 -- extract orderId. Never purchaseToken/
        # linkedPurchaseToken -- those are stable for a subscription's
        # entire lifetime and would make every renewal collide with
        # the first purchase's claim (see the Duplicate Purchase
        # Protection design and the S7A audit).
        order_id = verification.order_id
        if not order_id:
            return EntitlementWriteResult(
                success=False, action="MISSING_ORDER_ID", profile_id=profile_id or 0,
                message="Google Play did not return an orderId for this purchase -- cannot claim.",
            )

        if profile_id is None:
            return EntitlementWriteResult(
                success=False, action="MISSING_PROFILE_ID", profile_id=0,
                message="payload['profile_id'] is required to dispatch this event; resolving "
                        "which profile a bare purchase_token belongs to is out of scope for "
                        "this phase.",
            )

        # Step 3 -- claim via the S5 ledger, keyed on the
        # freshly-verified orderId.
        ledger = ProcessedSubscriptionEventService()
        claim = ledger.claim(
            store="GOOGLE_PLAY", transaction_id=order_id,
            event_type=event_type, profile_id=profile_id,
        )

        if claim.outcome == SubscriptionEventClaimOutcome.ALREADY_FINALIZED:
            stored = claim.stored_response or {}
            return EntitlementWriteResult(
                success=stored.get("success", True),
                action=stored.get("action", "ALREADY_PROCESSED"),
                profile_id=profile_id,
                message=stored.get("message", "This event was already processed."),
            )

        if claim.outcome == SubscriptionEventClaimOutcome.ALREADY_IN_PROGRESS:
            return EntitlementWriteResult(
                success=True, action="ALREADY_IN_PROGRESS", profile_id=profile_id,
                message="This event is already being processed elsewhere, or a previous "
                        "attempt failed and was correctly left unfinished.",
            )

        # Step 4 -- dispatch. Raises (PAUSED/RESTARTED) propagate
        # past finalize() below on purpose -- the claim stays
        # unfinished, exactly like a raised infrastructure error would.
        result = self._dispatch_verified_event(
            event_type=event_type, profile_id=profile_id, verification=verification,
        )

        # Step 5 -- finalize.
        ledger.finalize(
            store="GOOGLE_PLAY", transaction_id=order_id,
            response_payload={
                "success": result.success, "action": result.action, "message": result.message,
            },
            profile_id=profile_id,
        )
        return result

    def _dispatch_verified_event(
        self, *, event_type: str, profile_id: int, verification,
    ) -> EntitlementWriteResult:
        """Routes one freshly-verified Google Play RTDN event to an
        existing SubscriptionService method. No new entitlement logic
        lives here -- every branch below delegates to a method already
        defined above in this same class."""
        if event_type in _RTDN_RENEWAL_EVENTS:
            if verification.expiry_time is None:
                return EntitlementWriteResult(
                    success=False, action="MISSING_EXPIRY", profile_id=profile_id,
                    message="Google Play did not provide a usable expiry_time.",
                )
            return self.renew_subscription(
                profile_id=profile_id, expires_at=verification.expiry_time,
                transaction_reference=verification.order_id,
            )

        if event_type == "SUBSCRIPTION_IN_GRACE_PERIOD":
            return self.enter_grace(profile_id)

        if event_type in _RTDN_EXPIRY_EVENTS:
            return self.expire_subscription(profile_id)

        if event_type == "SUBSCRIPTION_CANCELED":
            return self.cancel_subscription(profile_id)

        if event_type == "SUBSCRIPTION_REVOKED":
            return self.record_refund(profile_id, transaction_reference=verification.order_id)

        if event_type == "SUBSCRIPTION_PURCHASED":
            # Local import -- payment_service.py imports SubscriptionService
            # at its own module level, so importing these from there at
            # THIS module's top level would be a circular import. Reuses
            # the exact same mapping and purchase_state gates S4/S18
            # already defined; this file must never keep a second,
            # divergent copy of either.
            from modules.payments.payment_service import (
                GOOGLE_PLAY_PRODUCT_TO_PLAN,
                _GOOGLE_PLAY_ACTIVATING_STATES,
                _GOOGLE_PLAY_PENDING_STATES,
            )

            # S18 -- RTDN must apply the exact same purchase_state gate
            # PaymentService's own confirm path already applies (see
            # _apply_subscription_business_effect()) before this method
            # existed with it: a PURCHASED notification whose freshly-
            # verified state is not actually active must never activate
            # here just because the HTTP confirm path happened to be the
            # one that already checked. Reusing the same two constants
            # above, not duplicating the state lists, is what keeps the
            # two paths from silently drifting apart again.
            if verification.purchase_state in _GOOGLE_PLAY_PENDING_STATES:
                return EntitlementWriteResult(
                    success=True, action="PENDING", profile_id=profile_id,
                    message="Purchase is pending; no entitlement granted yet.",
                )
            if verification.purchase_state not in _GOOGLE_PLAY_ACTIVATING_STATES:
                return EntitlementWriteResult(
                    success=True, action="NOT_ACTIVATED", profile_id=profile_id,
                    message=(
                        f"purchase_state={verification.purchase_state!r} does not "
                        f"currently grant access."
                    ),
                )

            plan = GOOGLE_PLAY_PRODUCT_TO_PLAN.get(verification.product_id)
            if plan is None:
                return EntitlementWriteResult(
                    success=False, action="UNMAPPED_PRODUCT", profile_id=profile_id,
                    message=f"product_id={verification.product_id!r} has no known plan mapping.",
                )
            if verification.expiry_time is None:
                return EntitlementWriteResult(
                    success=False, action="MISSING_EXPIRY", profile_id=profile_id,
                    message="Google Play did not provide a usable expiry_time.",
                )
            return self.activate_subscription(
                profile_id=profile_id, plan=plan, selected_segment=None,
                expires_at=verification.expiry_time,
                transaction_reference=verification.order_id, store="GOOGLE_PLAY",
            )

        if event_type in _RTDN_NOT_YET_IMPLEMENTED_EVENTS:
            raise NotImplementedError(
                f"{event_type} handling is an explicit, approved-as-deferred placeholder "
                f"-- its business rules (see the RTDN Architecture Audit, S7A) have not "
                f"been finalized. Reported, not guessed."
            )

        if event_type in _RTDN_NO_ACTION_EVENTS:
            return EntitlementWriteResult(
                success=True, action="IGNORED_NO_ACTION_NEEDED", profile_id=profile_id,
                message=f"{event_type} does not require an entitlement transition.",
            )

        return EntitlementWriteResult(
            success=False, action="UNRECOGNIZED_EVENT_TYPE", profile_id=profile_id,
            message=f"event_type={event_type!r} is not a recognized RTDN subscription notification type.",
        )

    def restore_purchases(
        self, profile_id: int, receipts: List[Dict[str, Any]],
    ) -> List[EntitlementWriteResult]:
        """
        FUTURE: given a list of store receipts a client is restoring
        (e.g. after a reinstall), verify each one and call
        activate_subscription/renew_subscription as appropriate,
        returning one EntitlementWriteResult per receipt. Not
        implemented: depends on real receipt verification, which this
        task does not implement.
        """
        raise NotImplementedError(
            "restore_purchases is a designed extension point, not yet implemented."
        )

    def sync_subscription_state(self, profile_id: int) -> Optional[EntitlementWriteResult]:
        """
        FUTURE: the one place this service would read via
        EntitlementService BEFORE deciding which EntitlementWriteService
        write (if any) applies -- e.g. a scheduled job walking profiles
        periodically would call this to reconcile a lapsed trial into
        expire_trial(), a lapsed subscription into enter_grace(), or a
        lapsed grace window into exit_grace(), purely by comparing
        EntitlementService's snapshot against the current time. This
        would not duplicate any EntitlementWriteService business rule
        (idempotency, one-time-trial, etc. all stay there) -- it only
        decides WHICH transition applies, then delegates the mutation
        entirely. Not implemented in this phase; see this phase's
        output notes for why it was left a stub rather than built now.
        """
        raise NotImplementedError(
            "sync_subscription_state is a designed extension point, not yet implemented."
        )

    # ------------------------------------------------------------
    # Future Hooks -- named extension points only. No implementation.
    # ------------------------------------------------------------
    def _validate_receipt(
        self,
        *,
        store: Optional[str],
        transaction_reference: Optional[str],
        receipt_payload: Optional[dict],
    ) -> None:
        """
        FUTURE: verify a purchase claim against the real store/provider
        before trusting it, dispatching on `store`:
            GOOGLE_PLAY -> _validate_google_play_receipt
            APP_STORE   -> _validate_apple_receipt
            (Razorpay is a direct payment provider rather than an app
            store -- see _validate_razorpay_payment for that path)

        No-op for now: activate_subscription() currently trusts
        whatever the caller passes, exactly as EntitlementWriteService.
        activate_subscription() already does.
        """
        return None

    def _validate_google_play_receipt(
        self, transaction_reference: Optional[str], receipt_payload: Optional[dict],
    ) -> None:
        """FUTURE: verify via the Google Play Developer API. Not implemented."""
        return None

    def _validate_apple_receipt(
        self, transaction_reference: Optional[str], receipt_payload: Optional[dict],
    ) -> None:
        """FUTURE: verify via the Apple App Store Server API. Not implemented."""
        return None

    def _validate_razorpay_payment(
        self, transaction_reference: Optional[str], receipt_payload: Optional[dict],
    ) -> None:
        """FUTURE: verify via the Razorpay payments/orders API, for web/
        direct purchases outside an app store. Not implemented."""
        return None

    def _after_transition(self, *, profile_id: int, action: str, result: EntitlementWriteResult) -> None:
        """
        FUTURE: fan out to analytics / notifications / audit logging
        after every workflow call, regardless of outcome. Calls the
        three hooks below; all are no-ops today.
        """
        self._record_analytics(profile_id=profile_id, action=action, result=result)
        self._send_notification(profile_id=profile_id, action=action, result=result)
        self._write_audit_log(profile_id=profile_id, action=action, result=result)

    def _record_analytics(self, *, profile_id: int, action: str, result: EntitlementWriteResult) -> None:
        """FUTURE: emit an analytics event for this subscription workflow transition. Not implemented."""
        return None

    def _send_notification(self, *, profile_id: int, action: str, result: EntitlementWriteResult) -> None:
        """FUTURE: notify the user (push/email) about this subscription state change. Not implemented."""
        return None

    def _write_audit_log(self, *, profile_id: int, action: str, result: EntitlementWriteResult) -> None:
        """
        FUTURE: append an immutable audit-log entry (who/what triggered
        this call, source IP, admin actor if any) -- distinct from
        SubscriptionEvent, which only records the resulting entitlement
        state, not who/why. Not implemented.
        """
        return None
