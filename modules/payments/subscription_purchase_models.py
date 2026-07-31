# modules/payments/subscription_purchase_models.py

"""
Structured internal result for PaymentService's SUBSCRIPTION business
effect (Subscription Purchase System -- S4). Same role as
CreatedReportOrder for REPORT_PURCHASE: a plain dataclass, never a raw
dict, describing exactly what happened -- built here for internal
clarity, then reduced to a dict via to_dict() at the one point it
needs to become PaymentVerificationResult.raw_payload, matching
REPORT_PURCHASE's own existing dict-shaped contract there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class SubscriptionPurchaseOutcome:
    """
    What PaymentService decided to do with a verified Google Play
    subscription purchase -- distinct from GooglePlayVerificationStatus
    (which only says whether the purchase token itself is real) and
    from EntitlementWriteResult.action (which is EntitlementWriteService's
    own, separate vocabulary for what it did).

        ACTIVATED          -- purchase_state granted access, a known
                              plan was resolved, and
                              SubscriptionService.activate_subscription()
                              reported success.
        PENDING            -- purchase_state is Google's own "not yet
                              paid" state (e.g. a pending cash/deferred
                              payment method) -- no entitlement action
                              taken, deliberately.
        NOT_ACTIVATED      -- purchase_state is real but does not
                              currently grant access (grace/on-hold/
                              paused/cancelled/expired/revoked) -- see
                              the Google Play Lifecycle design review
                              for why activation is withheld for all of
                              these; renewal/cancellation/refund
                              handling itself is explicitly out of
                              scope for this phase.
        UNMAPPED_PRODUCT   -- the purchase's product_id has no entry in
                              GOOGLE_PLAY_PRODUCT_TO_PLAN -- reported,
                              never guessed (same "report a missing
                              mapping" rule already established for the
                              legacy migration's plan-name gap).
        ACTIVATION_FAILED  -- SubscriptionService.activate_subscription()
                              itself returned a structured failure (e.g.
                              a SELECTED-access plan with no
                              selected_segment available from Google
                              Play data at all) -- reported, not guessed.
    """
    ACTIVATED = "ACTIVATED"
    PENDING = "PENDING"
    NOT_ACTIVATED = "NOT_ACTIVATED"
    UNMAPPED_PRODUCT = "UNMAPPED_PRODUCT"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"


@dataclass
class SubscriptionPurchaseResult:
    outcome: str                    # SubscriptionPurchaseOutcome
    profile_id: int
    activated: bool
    purchase_state: Optional[str] = None
    plan: Optional[str] = None
    # Google's own order id (a string, e.g. "GPA.1234-5678-9012-34567")
    # -- deliberately NOT called "order_id" in this dict.
    # PaymentService._finalize_claim()/_record_dispatch_failure() are
    # shared, purpose-agnostic code that already read a business_details
    # "order_id" key and write it into ProcessedPayment.order_id, an
    # Integer column sized for REPORT_PURCHASE's real Order.id. A
    # subscription purchase creates no Order row at all -- reusing that
    # key name here would both corrupt that column (a string into an
    # Integer) and break _decide_retry()'s own correctness assumption
    # that a SUBSCRIPTION claim's order_id is always None.
    provider_order_id: Optional[str] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "profile_id": self.profile_id,
            "activated": self.activated,
            "purchase_state": self.purchase_state,
            "plan": self.plan,
            "provider_order_id": self.provider_order_id,
            "message": self.message,
        }
