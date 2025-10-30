"""
modules/models_asknow.py
------------------------
Tracks ₹99 AskNow token purchases.
Each order = 10 tokens credited to user.
"""

from datetime import datetime
from extensions import db


class AskNowOrder(db.Model):
    __tablename__ = "asknow_orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    razorpay_order_id = db.Column(db.String(120), nullable=False)
    payment_id = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), default="pending")   # pending | success | failed
    tokens_added = db.Column(db.Integer, default=10)
    amount = db.Column(db.Integer, default=99)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "razorpay_order_id": self.razorpay_order_id,
            "payment_id": self.payment_id,
            "status": self.status,
            "tokens_added": self.tokens_added,
            "amount": self.amount,
            "created_at": self.created_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }

    def __repr__(self):
        return f"<AskNowOrder id={self.id} user={self.user_id} status={self.status}>"
