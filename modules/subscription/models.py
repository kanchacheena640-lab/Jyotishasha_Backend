from datetime import datetime, timedelta
from extensions import db

class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plan = db.Column(db.String(50), nullable=False, default="free")
    status = db.Column(db.String(20), nullable=False, default="active")
    start_at = db.Column(db.DateTime, default=datetime.utcnow)
    end_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=10))
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship("User", backref="subscription")

    def is_currently_active(self) -> bool:
        return self.status == "active" and self.end_at >= datetime.utcnow()

    def to_dict(self):
        return {
            "plan": self.plan,
            "status": self.status,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "is_active": self.is_currently_active()
        }
