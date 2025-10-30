"""
modules/models_subscription.py
-------------------------------
Tracks monthly/yearly subscription orders via Razorpay.
Links with AppUser but keeps user table untouched.
"""

from datetime import datetime
from extensions import db


class SubscriptionOrder(db.Model):
    __tablename__ = "subscription_orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    razorpay_order_id = db.Column(db.String(120), nullable=False)
    payment_id = db.Column(db.String(120), nullable=True)
    plan_type = db.Column(db.String(20), nullable=False)  # monthly, yearly, pro_monthly, pro_yearly
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending | success | failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "razorpay_order_id": self.razorpay_order_id,
            "payment_id": self.payment_id,
            "plan_type": self.plan_type,
            "amount": self.amount,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }

    def __repr__(self):
        return f"<SubscriptionOrder id={self.id} plan={self.plan_type} status={self.status}>"
