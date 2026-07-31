# modules/payments/payment_models.py

"""
Plain constants and dataclasses shared by every payment provider and
by PaymentService. No business logic lives here -- this file only
defines the shape everything else agrees on, the same role
modules/models_ai_reports.py's constants and modules/entitlement's
dataclasses play for their own subsystems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class PaymentProviderType:
    """Which payment rail a request came through."""
    RAZORPAY = "RAZORPAY"
    GOOGLE_PLAY = "GOOGLE_PLAY"
    APPLE = "APPLE"

    ALL = (RAZORPAY, GOOGLE_PLAY, APPLE)


class PaymentStatus:
    """The outcome of a verification attempt."""
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class RetryDecision:
    """
    Payment Hardening Phase 5 -- how a retry (browser refresh, API
    retry, network retry, duplicate webhook) for an already-seen
    payment_id should be handled, based solely on the existing
    Order.status / Order.report_stage (no schema change):
        IGNORE  -- report_stage is already "Ready"; the pipeline fully
                   succeeded, so return the stored result and do
                   nothing further (no duplicate PDF/email/AI job).
        RESUME  -- the Order exists but report_stage never reached
                   "Ready" (the pipeline failed or never finished);
                   re-trigger generation for the SAME order_id, never
                   creating a new Order and never re-verifying payment.
        REJECT  -- no Order is known yet for this payment_id (still
                   actively being created, or failed before an order_id
                   was ever recorded) -- neither safe to ignore nor to
                   resume, since there is nothing to resume yet.
    """
    IGNORE = "IGNORE"
    RESUME = "RESUME"
    REJECT = "REJECT"


class PaymentPurpose:
    """
    What the payment is FOR -- orthogonal to which provider processed
    it. This is what PaymentService uses to decide whether the
    verified payment's business effect belongs to OrderService (a
    one-time report purchase) or SubscriptionService (a recurring
    entitlement). Only the two values below are handled in Phase 1;
    more (e.g. a chat-pack credit purchase) can be added later without
    changing this shape.
    """
    REPORT_PURCHASE = "REPORT_PURCHASE"
    SUBSCRIPTION = "SUBSCRIPTION"


@dataclass
class PaymentRequest:
    """
    Everything a PaymentProvider needs to verify one payment, and
    everything PaymentService needs to route its business effect
    afterward. Callers build one of these from whatever their entry
    point receives (a website checkout callback, a future Google Play
    purchase token, ...) -- providers and PaymentService never reach
    back into a Flask request object themselves.
    """
    provider: str          # PaymentProviderType
    purpose: str           # PaymentPurpose
    reference: str          # provider-specific order/transaction id (e.g. Razorpay order_id)
    payment_id: Optional[str] = None   # e.g. Razorpay payment_id
    signature: Optional[str] = None    # e.g. Razorpay signature
    amount: Optional[int] = None       # smallest currency unit (e.g. paise), if known
    currency: Optional[str] = None
    profile_id: Optional[int] = None   # required for PaymentPurpose.SUBSCRIPTION
    # Subscription Purchase System -- S12. Required only for an
    # ACCESS_SELECTED plan (e.g. SILVER_MONTHLY/SILVER_YEARLY); an
    # ACCESS_ALL plan (e.g. GOLD_*/PLATINUM_YEARLY) ignores this either
    # way -- EntitlementWriteService's own existing, unmodified plan-
    # access check already only enforces it for ACCESS_SELECTED plans.
    # One of modules/models_ai_reports.py's AI_REPORT_SEGMENTS, or None.
    selected_segment: Optional[str] = None
    order_payload: Optional[Dict[str, Any]] = None  # required for PaymentPurpose.REPORT_PURCHASE
    raw_payload: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentVerificationResult:
    """Structured result from a PaymentProvider.verify() call -- never
    a raw SDK response or a bare boolean."""
    status: str            # PaymentStatus
    provider: str           # PaymentProviderType
    reference: str
    verified: bool
    message: str = ""
    raw_payload: Optional[Dict[str, Any]] = None
