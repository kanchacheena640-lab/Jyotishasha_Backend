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

Trust Foundation Phase 0 (Ask Now auth + payment audit): verify_chatpack_
payment() previously trusted a client-supplied order_id/payment_id/user_id
outright and unconditionally set status="success" -- no cryptographic
proof the payment was ever real. Confirmed independently by
modules/payments/razorpay_provider.py's own docstring, which names this
exact file among the pre-existing call sites that never verified a
signature. Fixed here by reusing RazorpayProvider -- the SAME provider
already used elsewhere in this codebase for Razorpay verification (Report
purchases, /webhook) -- rather than re-implementing the HMAC check or
inventing a second payment framework. This file still creates no Order
row and still only writes ChatPack, exactly as before; RazorpayProvider
only answers "is this payment claim real," same contract it already has
for every other caller.
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
def verify_chatpack_payment(order_id, payment_id, signature, user_id):
    """
    Step-2: Cryptographically verify the Razorpay payment (Trust
    Foundation Phase 0 -- signature is now REQUIRED, not optional) before
    marking success and activating ChatPack (8 Q).

    Idempotent: a pack already at status="success" (a replayed/retried
    verify call for a purchase this function already activated) returns
    the same success response without re-verifying or re-crediting --
    mirrors the idempotency posture chatpack_google_verify.py already
    established for the Google Play path, so both Ask Now payment paths
    behave the same way under retry.
    """
    pack = ChatPack.query.filter_by(
        razorpay_order_id=order_id, user_id=user_id
    ).first()

    if not pack:
        raise ValueError("ChatPack order not found")

    if pack.status == "success":
        return {
            "success": True,
            "message": "ChatPack 51 already verified and active",
            "pack": pack.to_dict(),
            "already_processed": True,
        }

    # Real cryptographic verification -- reused, not reimplemented. See
    # this module's own docstring for why RazorpayProvider (not a new
    # framework) is the right call here.
    from modules.payments.payment_models import (
        PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus,
    )
    from modules.payments.razorpay_provider import RazorpayProvider

    verification = RazorpayProvider().verify(PaymentRequest(
        provider=PaymentProviderType.RAZORPAY,
        # REPORT_PURCHASE is the closer of the two existing values for a
        # one-time (non-recurring) payment -- PaymentPurpose's own
        # docstring already anticipates "a chat-pack credit purchase" as
        # a future third value; RazorpayProvider.verify() itself never
        # reads `purpose` at all, so this choice affects nothing about
        # the verification outcome, only future readers of this call.
        purpose=PaymentPurpose.REPORT_PURCHASE,
        reference=order_id,
        payment_id=payment_id,
        signature=signature,
    ))

    if verification.status != PaymentStatus.VERIFIED:
        # Never grant entitlement for a payment that didn't verify --
        # the pack stays "pending"; nothing is credited.
        raise ValueError(
            f"Payment verification failed: {verification.message}"
        )

    # Update status -- only reached once the signature is proven real.
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