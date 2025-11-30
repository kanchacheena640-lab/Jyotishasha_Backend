"""
DEPRECATED SERVICE — DO NOT USE

This file belonged to the OLD AskNow ₹99 token model (10 tokens per order).
The entire AskNow token system has been permanently discontinued.

🔥 New final chat model uses:
- 1 Free Question Per Day
- ₹51 Chat Pack (8 Questions)
- Unified chat engine → services/chat_engine.py
- Free quota tracking → modules/models_free_daily.py
- Paid pack tracking → modules/models_chat_pack.py

❗ This file is kept ONLY for reference and should NOT be imported or used
anywhere in the new production system.
"""

from datetime import datetime
from extensions import db
from config.razorpay_config import razorpay_client
from modules.models_asknow import AskNowOrder
from modules.user_service import get_user_by_id


# ✅ Fixed price for the pack
ASKNOW_PRICE = 99
ASKNOW_TOKENS = 10


def create_asknow_order(user_id):
    """Create a ₹99 Razorpay order and store pending AskNowOrder."""
    amount_paise = ASKNOW_PRICE * 100

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"asknow_{user_id}_{int(datetime.utcnow().timestamp())}",
        "notes": {"type": "asknow_tokens"},
    }

    razorpay_order = razorpay_client.order.create(payload)

    order = AskNowOrder(
        user_id=user_id,
        razorpay_order_id=razorpay_order["id"],
        amount=ASKNOW_PRICE,
        tokens_added=ASKNOW_TOKENS,
        status="pending",
    )
    db.session.add(order)
    db.session.commit()

    return order.to_dict()


def verify_asknow_payment(order_id, payment_id, user_id):
    """Verify payment, add tokens to user, and mark order success."""
    order = AskNowOrder.query.filter_by(
        razorpay_order_id=order_id, user_id=user_id
    ).first()
    if not order:
        raise ValueError("Order not found")

    # Mark order success
    order.payment_id = payment_id
    order.status = "success"
    order.verified_at = datetime.utcnow()

    # ✅ Add tokens to AppUser
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")

    user.asknow_tokens = (user.asknow_tokens or 0) + order.tokens_added
    db.session.commit()

    return {
        "success": True,
        "message": f"{order.tokens_added} tokens added successfully",
        "total_tokens": user.asknow_tokens,
    }


def deduct_token(user_id):
    """Deduct one token when user uses an ad-free AskNow reply."""
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found")

    if user.asknow_tokens and user.asknow_tokens > 0:
        user.asknow_tokens -= 1
        db.session.commit()
        return {"success": True, "remaining_tokens": user.asknow_tokens}
    else:
        return {"success": False, "message": "No tokens left"}
