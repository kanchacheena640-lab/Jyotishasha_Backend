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


def verify_subscription_payment(order_id, payment_id, user_id):
    """Mark subscription as successful and update user's plan"""
    order = SubscriptionOrder.query.filter_by(razorpay_order_id=order_id, user_id=user_id).first()
    if not order:
        raise ValueError("Order not found")

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
    return {"success": True, "plan": order.plan_type, "expiry": expiry.isoformat()}
