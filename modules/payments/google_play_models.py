# modules/payments/google_play_models.py

"""
Structured result type for Google Play subscription purchase
verification (Subscription Purchase System -- S3). Same role as
payment_models.py: shape only, no business logic, no entitlement
decision. GooglePlaySubscriptionVerification answers exactly one
question -- "what does Google Play's own record say about this
purchase token, right now" -- and nothing about whether that should
grant, extend, or revoke access. A later phase (explicitly out of
scope here) is responsible for turning `purchase_state` into an
EntitlementWriteService call; this file must never do that itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


class GooglePlayVerificationStatus:
    """
    The outcome of asking Google "is this purchase token real" --
    distinct from Google's own `purchase_state` (subscriptionState),
    which describes the SUBSCRIPTION's lifecycle once we already know
    the token itself is genuine.

        VERIFIED       -- Google returned real subscription data for
                          this token. Says nothing about whether the
                          subscription is currently active, expired,
                          or revoked -- see purchase_state for that.
        INVALID_TOKEN  -- Google rejected the token itself (malformed,
                          or belongs to a different app/package).
        NOT_FOUND      -- Google has no record of this token at all.
        AUTH_ERROR     -- our own service-account credentials are
                          missing, malformed, or rejected by Google --
                          an operational/config problem, not a verdict
                          on the purchase.
        NETWORK_ERROR  -- could not reach Google's API at all (DNS,
                          timeout, connection refused). Expected to
                          happen periodically for a real network call
                          -- distinct from the other statuses precisely
                          so a future retry policy can tell "try again
                          later" apart from "this will never succeed".
        UNKNOWN_ERROR  -- anything else Google's API returned that
                          doesn't fit the above; error_message/
                          raw_response carry the detail for
                          investigation rather than guessing.
    """
    VERIFIED = "VERIFIED"
    INVALID_TOKEN = "INVALID_TOKEN"
    NOT_FOUND = "NOT_FOUND"
    AUTH_ERROR = "AUTH_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class GooglePlaySubscriptionVerification:
    """
    Normalized, read-only snapshot of one purchases.subscriptionsv2.get
    response (or of why that call could not be completed). Every field
    below maps directly onto a field the Subscription Purchase System's
    later phases (explicitly not implemented here) will need --
    nothing here is inferred or decided, only reshaped from Google's
    own response into stable, provider-agnostic names.
    """
    verification_status: str          # GooglePlayVerificationStatus
    purchase_token: str

    package_name: Optional[str] = None
    purchase_state: Optional[str] = None          # Google's raw subscriptionState, passed through verbatim
    acknowledgement_state: Optional[str] = None   # Google's raw acknowledgementState, passed through verbatim
    order_id: Optional[str] = None                # latestOrderId
    product_id: Optional[str] = None               # lineItems[0].productId
    subscription_id: Optional[str] = None          # basePlanId, if Google's response distinguishes it from product_id
    expiry_time: Optional[datetime] = None         # lineItems[0].expiryTime
    start_time: Optional[datetime] = None          # startTime
    auto_renewing: Optional[bool] = None            # lineItems[0].autoRenewingPlan.autoRenewEnabled
    country: Optional[str] = None                   # regionCode
    linked_purchase_token: Optional[str] = None     # present when this purchase supersedes a prior one

    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = field(default_factory=dict)  # the untouched Google API body

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verification_status": self.verification_status,
            "purchase_token": self.purchase_token,
            "package_name": self.package_name,
            "purchase_state": self.purchase_state,
            "acknowledgement_state": self.acknowledgement_state,
            "order_id": self.order_id,
            "product_id": self.product_id,
            "subscription_id": self.subscription_id,
            "expiry_time": self.expiry_time.isoformat() if self.expiry_time else None,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "auto_renewing": self.auto_renewing,
            "country": self.country,
            "linked_purchase_token": self.linked_purchase_token,
            "error_message": self.error_message,
        }


class GooglePlayAcknowledgementStatus:
    """
    The outcome of asking Google to acknowledge a subscription purchase
    (Subscription Purchase System -- S6). Not an exhaustive/closed set
    -- REVOKED/EXPIRED exist because the acknowledgement flow checks
    current purchase_state before ever attempting to acknowledge, and
    those are real, distinct reasons acknowledgement was never
    attempted, not a generic failure.

        ACKNOWLEDGED          -- Google accepted the acknowledgement,
                                 or it was already acknowledged before
                                 this call (see ALREADY_ACKNOWLEDGED --
                                 both mean "Google now considers this
                                 purchase acknowledged", which is what
                                 retry-safety actually requires).
        ALREADY_ACKNOWLEDGED  -- detected either from a fresh
                                 verification check before attempting
                                 the acknowledge call, or from Google's
                                 own error response to the attempt
                                 itself -- both are treated as a
                                 successful outcome for a retry, not a
                                 failure.
        REVOKED               -- current purchase_state is
                                 SUBSCRIPTION_STATE_REVOKED --
                                 acknowledgement was never attempted.
        EXPIRED               -- current purchase_state is
                                 SUBSCRIPTION_STATE_EXPIRED --
                                 acknowledgement was never attempted.
        INVALID_TOKEN         -- Google rejected the token itself.
        NOT_FOUND             -- Google has no record of this token.
        AUTH_ERROR            -- our own credentials are missing,
                                 malformed, or rejected.
        NETWORK_ERROR         -- could not reach Google's API at all.
        UNKNOWN_ERROR         -- anything else; error_message/
                                 raw_response carry the detail.
    """
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ALREADY_ACKNOWLEDGED = "ALREADY_ACKNOWLEDGED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    NOT_FOUND = "NOT_FOUND"
    AUTH_ERROR = "AUTH_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class GooglePlayAcknowledgementResult:
    """Normalized, read-only outcome of one acknowledgement attempt --
    never grants entitlement, never implies anything about business
    state; purely "did Google Play get told about this purchase"."""
    status: str  # GooglePlayAcknowledgementStatus
    purchase_token: str

    purchase_state: Optional[str] = None  # carried through from the pre-check, for context on REVOKED/EXPIRED/ALREADY_ACKNOWLEDGED
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "purchase_token": self.purchase_token,
            "purchase_state": self.purchase_state,
            "error_message": self.error_message,
        }
