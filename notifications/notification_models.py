# notifications/notification_models.py

"""
Notification DB models for Jyotishasha.

NOTE:
- Adjust `from your_app import db` line according to your existing project.
- Typical pattern:
    from extensions import db
  or
    from app import db
"""

from datetime import datetime
from sqlalchemy.dialects.postgresql import JSON
from extensions import db


class NotificationJob(db.Model):
    """
    Single notification job.

    Example:
    - Title: "Deepavali Pujan Muhurta"
    - Body: "Today 7:15–8:30 PM, do Laxmi Pujan..."
    - Type: "festival" / "blog" / "daily" / "custom"
    - Audience: JSON filter (zodiac, age_group, interest, etc.)
    - Payload: Extra data for app routing (screen, slug, etc.)
    """

    __tablename__ = "notification_jobs"

    id = db.Column(db.Integer, primary_key=True)

    # Display content
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(500), nullable=False)

    # ✅ NEW: Hindi content support
    title_hi = db.Column(db.String(200), nullable=True)
    body_hi = db.Column(db.String(500), nullable=True)

    type = db.Column(db.String(50), nullable=False)  # e.g. 'festival', 'blog', 'daily', 'custom'

    # Targeting info (who should receive)
    audience = db.Column(JSON, nullable=False, default=dict)
    # Example audience JSON:
    # {
    #   "mode": "all" | "zodiac" | "lagna" | "age_group" | "interest" | "mixed",
    #   "zodiac": ["aries", "leo"],
    #   "lagna": ["scorpio"],
    #   "age_group": ["young_adult"],
    #   "interest": ["love"],
    #   "subscription": ["free", "monthly"]
    # }

    # Extra data for app routing
    payload = db.Column(JSON, nullable=False, default=dict)
    # Example payload:
    # {
    #   "screen": "blog",
    #   "url": "...",
    #   "blog_title": "..."
    # }

    # Scheduling
    scheduled_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Processing state
    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending"
    )  # 'pending' | 'processing' | 'sent' | 'cancelled' | 'failed'

    # Meta
    total_recipients = db.Column(db.Integer, nullable=True)   # filled after send
    success_count = db.Column(db.Integer, nullable=True)
    failure_count = db.Column(db.Integer, nullable=True)

    def mark_processing(self):
        self.status = "processing"

    def mark_sent(self, success: int, failed: int):
        self.status = "sent"
        self.success_count = success
        self.failure_count = failed

    def mark_failed(self):
        self.status = "failed"

    def mark_cancelled(self):
        self.status = "cancelled"

    def is_due(self, now: datetime) -> bool:
        return self.status == "pending" and self.scheduled_at <= now
