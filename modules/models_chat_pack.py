# modules/models_chat_pack.py

"""
ChatPack 51 Model

Tracks paid chat packs for users.

Current rules:
- Each pack currently: ₹51 for 8 questions
- No expiry date (valid till all questions are used)
"""

from datetime import datetime
from extensions import db


class ChatPack(db.Model):
    __tablename__ = "chat_packs"

    id = db.Column(db.Integer, primary_key=True)

    # Kis user ne pack kharida
    user_id = db.Column(db.Integer, nullable=False, index=True)

    # Pricing & pack info
    amount = db.Column(db.Integer, default=51, nullable=False)  # ₹51
    questions_total = db.Column(db.Integer, default=8, nullable=False)
    questions_used = db.Column(db.Integer, default=0, nullable=False)

    # Razorpay / payment details
    razorpay_order_id = db.Column(db.String(120), nullable=True, index=True)
    razorpay_payment_id = db.Column(db.String(120), nullable=True)
    status = db.Column(
        db.String(20),
        default="pending",
        nullable=False,
    )  # pending | success | failed

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)

    def remaining_questions(self) -> int:
        """Kitne sawal abhi bhi baaki hain."""
        return max(0, (self.questions_total or 0) - (self.questions_used or 0))

    def is_active(self) -> bool:
        """
        Active ka matlab:
        - payment success ho chuka hai
        - aur abhi bhi remaining questions > 0
        """
        return self.status == "success" and self.remaining_questions() > 0

    def to_dict(self) -> dict:
        """Frontend / API ke liye saab data ek jagah."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "amount": self.amount,
            "questions_total": self.questions_total,
            "questions_used": self.questions_used,
            "remaining_questions": self.remaining_questions(),
            "razorpay_order_id": self.razorpay_order_id,
            "razorpay_payment_id": self.razorpay_payment_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<ChatPack id={self.id} user={self.user_id} "
            f"status={self.status} used={self.questions_used}/"
            f"{self.questions_total}>"
        )
