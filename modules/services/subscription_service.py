"""
modules/services/subscription_service.py
----------------------------------------
Handles subscription order creation, verification, and AppUser updates.
"""

from datetime import datetime, timedelta
from extensions import db
from modules.models_subscription import SubscriptionOrder
from modules.user_service import get_user_by_id
from config.razorpay_config import razorpay_client

# Subscription Migration Phase 1 -- temporary dual-write, see
# modules/subscription/dual_write_adapter.py for what this is and why.
# Unlike modules/subscription/routes_webhook.py, no user_id -> profile_id
# resolution is needed here: get_user_by_id() below already resolves
# this file's "user_id" against AppUser (see that function), so it is
# already a profile_id in every call site in this file, not a genuine
# users.id -- passed straight through.
from modules.subscription.dual_write_adapter import mirror_subscription_activation


# Amount mapping (in ₹)
PLAN_PRICES = {
    "monthly": 49,
    "yearly": 539,
    "pro_monthly": 99,
    "pro_yearly": 999,
}


def create_subscription_order(user_id, plan_type):
    """Create Razorpay order for subscription"""
    if plan_type not in PLAN_PRICES:
        raise ValueError("Invalid subscription plan type")

    amount = PLAN_PRICES[plan_type]
    amount_paise = int(amount * 100)

    # ✅ Create Razorpay order
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"sub_{user_id}_{int(datetime.utcnow().timestamp())}",
        "notes": {"plan": plan_type},
    }

    razorpay_order = razorpay_client.order.create(payload)

    # ✅ Save order in DB
    order = SubscriptionOrder(
        user_id=user_id,
        razorpay_order_id=razorpay_order["id"],
        plan_type=plan_type,
        amount=amount,
        status="pending",
    )
    db.session.add(order)
    db.session.commit()

    return order.to_dict()


def verify_subscription_payment(order_id, payment_id, user_id, signature):
    """
    Mark subscription as successful and update user's plan.

    Task 17C -- SECURITY FIX: this function previously activated a
    subscription purely on a caller-supplied order_id/payment_id
    matching a persisted, pending SubscriptionOrder for this user --
    with NO cryptographic proof the payment claim was real.
    razorpay_provider.py's own module docstring already named this
    exact file as one of several pre-existing unverified call sites
    ("every one of them ... trusted a client-supplied order_id/
    payment_id with no cryptographic check"), alongside the Ask Now
    ChatPack path -- which was fixed; this one was not, until now.
    `signature` is REQUIRED (no default) so this function can never be
    called without one -- reused, not reimplemented: the SAME
    RazorpayProvider.verify() boundary chat_pack_service.py's own
    verify_chatpack_payment() already uses, which itself fails closed
    on a missing/invalid signature.

    The existing `razorpay_order_id=order_id, user_id=user_id` lookup
    below is UNCHANGED and does double duty: it is both the pre-existing
    ownership check (a caller can only ever verify an order that
    already belongs to the user_id it claims) AND, once real
    verification is added, the binding that makes a payment/signature
    replayed against a DIFFERENT SubscriptionOrder's own order_id
    structurally impossible -- the signature is an HMAC over this
    exact order_id + payment_id, so a signature valid for one order_id
    can never verify against another.

    Idempotent: an order already at status="success" (a replayed/
    retried verify call) returns the same success response without
    re-verifying or re-activating -- mirrors verify_chatpack_payment()'s
    own established idempotency posture exactly, so Ask Now and
    subscription payments behave the same way under retry.
    """
    order = SubscriptionOrder.query.filter_by(razorpay_order_id=order_id, user_id=user_id).first()
    if not order:
        raise ValueError("Order not found")

    if order.status == "success":
        # Already verified and activated by an earlier call -- no new
        # business effect. Reuses the durable facts already on the row
        # rather than recomputing/re-deriving anything.
        return {
            "success": True,
            "plan": order.plan_type,
            "already_processed": True,
        }

    # Real cryptographic verification -- reused, not reimplemented. See
    # this function's own docstring for why RazorpayProvider (not a new
    # framework) is the right call here.
    from modules.payments.payment_models import (
        PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus,
    )
    from modules.payments.razorpay_provider import RazorpayProvider

    verification = RazorpayProvider().verify(PaymentRequest(
        provider=PaymentProviderType.RAZORPAY,
        purpose=PaymentPurpose.SUBSCRIPTION,
        reference=order_id,
        payment_id=payment_id,
        signature=signature,
    ))

    if verification.status != PaymentStatus.VERIFIED:
        # Never grant entitlement for a payment that didn't verify --
        # the order stays "pending" (same convention verify_chatpack_
        # payment() already established); nothing is credited/activated.
        raise ValueError(f"Payment verification failed: {verification.message}")

    # Reached ONLY once the signature is proven real.
    order.payment_id = payment_id
    order.status = "success"
    order.verified_at = datetime.utcnow()
    db.session.commit()

    # ✅ Update user subscription
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")

    user.subscription = order.plan_type

    # ✅ Add expiry logic (30 days or 365 days)
    now = datetime.utcnow()
    if "yearly" in order.plan_type:
        expiry = now + timedelta(days=365)
    else:
        expiry = now + timedelta(days=30)

    # Save expiry to user if field exists
    if hasattr(user, "subscription_expiry"):
        user.subscription_expiry = expiry

    db.session.commit()

    # Phase 1 dual-write: mirror this activation into System C.
    # Best-effort -- cannot affect the result below, which has already
    # succeeded.
    mirror_subscription_activation(
        user_id, plan=order.plan_type, expires_at=expiry, transaction_reference=payment_id,
    )

    return {"success": True, "plan": order.plan_type, "expiry": expiry.isoformat()}
