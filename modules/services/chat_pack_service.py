# modules/services/chat_pack_service.py

"""
ChatPack Service (₹51 → 8 Questions Pack)

Handles:
- Creating Razorpay order (₹51)
- Verifying payment
- Creating active chat pack (8 questions)
- Deducting questions when user asks
- Checking remaining questions

Model Used:
- modules/models_chat_pack.py → ChatPack
"""

from datetime import datetime
from extensions import db
from config.razorpay_config import razorpay_client
from modules.models_chat_pack import ChatPack


CHATPACK_AMOUNT = 51
CHATPACK_QUESTIONS = 8


# ----------------------------------------------------------
# 1) CREATE ORDER
# ----------------------------------------------------------
def create_chatpack_order(user_id):
    """
    Step-1: Create Razorpay order for ₹51 ChatPack.
    """
    amount_paise = CHATPACK_AMOUNT * 100  # Razorpay needs paise

    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"chatpack51_{user_id}_{int(datetime.utcnow().timestamp())}",
        "notes": {"type": "chatpack_51"},
    }

    razorpay_order = razorpay_client.order.create(payload)

    # Create pending DB entry
    pack = ChatPack(
        user_id=user_id,
        amount=CHATPACK_AMOUNT,
        questions_total=CHATPACK_QUESTIONS,
        status="pending",
        razorpay_order_id=razorpay_order["id"],
    )
    db.session.add(pack)
    db.session.commit()

    return pack.to_dict()


# ----------------------------------------------------------
# 2) VERIFY PAYMENT
# ----------------------------------------------------------
def verify_chatpack_payment(order_id, payment_id, user_id):
    """
    Step-2: Mark payment success and activate ChatPack (8 Q).
    """
    pack = ChatPack.query.filter_by(
        razorpay_order_id=order_id, user_id=user_id
    ).first()

    if not pack:
        raise ValueError("ChatPack order not found")

    # Update status
    pack.razorpay_payment_id = payment_id
    pack.status = "success"
    pack.verified_at = datetime.utcnow()

    db.session.commit()

    return {
        "success": True,
        "message": "ChatPack 51 activated successfully",
        "pack": pack.to_dict(),
    }


# ----------------------------------------------------------
# 3) GET ACTIVE PACK
# ----------------------------------------------------------
def get_active_pack(user_id):
    """
    Returns the latest active pack (if any).
    Active = status=success AND remaining_questions > 0
    """
    packs = ChatPack.query.filter_by(
        user_id=user_id,
        status="success"
    ).order_by(ChatPack.id.desc()).all()

    for p in packs:
        if p.remaining_questions() > 0:
            return p

    return None


# ----------------------------------------------------------
# 4) DEDUCT QUESTION FROM ACTIVE PACK
# ----------------------------------------------------------
def deduct_question(user_id):
    """
    Deduct 1 question from active pack.
    Returns dict with success status + remaining questions.
    """
    pack = get_active_pack(user_id)

    if not pack:
        return {"success": False, "message": "No active ChatPack 51 remaining"}

    if pack.remaining_questions() <= 0:
        return {"success": False, "message": "No remaining questions in pack"}

    pack.questions_used += 1
    db.session.commit()

    return {
        "success": True,
        "message": "Question deducted",
        "remaining": pack.remaining_questions(),
        "pack_id": pack.id,
    }


# ----------------------------------------------------------
# 5) STATUS FOR POSTMAN TEST
# ----------------------------------------------------------
def get_pack_status(user_id):
    """
    Helper endpoint for debugging.
    Returns active pack info or empty.
    """
    pack = get_active_pack(user_id)

    if not pack:
        return {
            "has_pack": False,
            "remaining": 0,
        }

    return {
        "has_pack": True,
        "remaining": pack.remaining_questions(),
        "pack": pack.to_dict(),
    }

# ----------------------------------------------------------
# 6) REWARD QUESTION — Watch Ads → +1 Question
# ----------------------------------------------------------
def add_reward_question(user_id):
    """
    If user has NO pack → create mini pack (1 question)
    If user HAS pack → increment questions_total by 1
    (questions_used remains SAME)
    """

    # Check if user has any active pack
    active_pack = get_active_pack(user_id)

    # ------------------------------------------------------
    # CASE A: No Active Pack → create mini-pack (1 Q)
    # ------------------------------------------------------
    if not active_pack:
        mini_pack = ChatPack(
            user_id=user_id,
            amount=0,  # free reward pack
            questions_total=1,
            questions_used=0,
            status="success",
            razorpay_order_id="REWARD_AD",
            razorpay_payment_id="REWARD_AD",
            verified_at=datetime.utcnow()
        )
        db.session.add(mini_pack)
        db.session.commit()

        return {
            "success": True,
            "message": "Mini reward pack created (+1 question)",
            "total_tokens": 1
        }

    # ------------------------------------------------------
    # CASE B: Has Active Pack → increase total questions by +1
    # ------------------------------------------------------
    active_pack.questions_total += 1
    db.session.commit()

    remaining = active_pack.remaining_questions()

    return {
        "success": True,
        "message": "Reward added to existing pack (+1 question)",
        "total_tokens": remaining
    }