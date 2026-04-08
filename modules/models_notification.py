from datetime import datetime, timezone
from extensions import db

class UserNotification(db.Model):
    __tablename__ = "user_notifications"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, nullable=False)

    title = db.Column(db.String(255))
    body = db.Column(db.Text)

    data = db.Column(db.JSON)

    is_read = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))