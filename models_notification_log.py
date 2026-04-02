from extensions import db
from datetime import datetime


class NotificationLog(db.Model):
    __tablename__ = "notification_logs"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, nullable=False)
    event_id = db.Column(db.Integer, nullable=False)

    slot = db.Column(db.String(20), nullable=False)  # morning / evening

    sent_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'event_id', 'slot', name='unique_user_event_slot'),
        db.Index('idx_user_slot', 'user_id', 'slot')
    )