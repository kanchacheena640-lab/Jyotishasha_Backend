# modules/services/chatpack_google_verify.py

"""
Google Play ChatPack Verify (₹51 / 8 Questions)

Phase-1:
- Trust Google purchase token (no Google API call yet)
- Activate ChatPack (8 questions)

Phase-2 (later):
- Add Google Play Developer API verification
"""

from datetime import datetime
from extensions import db
from modules.models_chat_pack import ChatPack


def verify_google_chatpack(user_id: int, product_id: str, purchase_token: str):
    """
    Verify Google Play purchase and activate ChatPack

    Args:
        user_id (int)
        product_id (str)
        purchase_token (str)

    Returns:
        dict
    """

    # 🔒 Basic validation
    if not user_id or not product_id or not purchase_token:
        return {
            "success": False,
            "error": "Missing required fields"
        }

    # ✅ Create new ChatPack (8 Questions)
    pack = ChatPack(
        user_id=user_id,
        amount=51,
        questions_total=8,
        questions_used=0,
        status="success",
        razorpay_order_id=f"GP_{product_id}",
        razorpay_payment_id=purchase_token,
        verified_at=datetime.utcnow(),
    )

    db.session.add(pack)
    db.session.commit()

    remaining = pack.questions_total - pack.questions_used

    return {
        "success": True,
        "remaining_tokens": remaining,
        "message": "Google Play ChatPack activated"
    }
