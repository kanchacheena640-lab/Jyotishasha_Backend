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

from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSON
from extensions import db


class NotificationJob(db.Model):
    """
    Admin/Marketing broadcast job (dashboard-created or future scheduled
    campaigns) -- NOT for event notifications, which are generated
    exclusively by services.event_scheduler.run_daily_event_job().

    Example:
    - Title: "Deepavali Pujan Muhurta"
    - Body: "Today 7:15–8:30 PM, do Laxmi Pujan..."
    - Type: "blog" / "daily" / "custom"
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
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp()
    )

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
    
# ===============================
# USER NOTIFICATION (BELL SYSTEM)
# ===============================
class UserNotification(db.Model):
    __tablename__ = "user_notifications"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, nullable=False, index=True)

    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)

    # 🔥 IMPORTANT: metadata for routing + filtering
    data = db.Column(JSON, nullable=True, default=dict)

    # 🔔 read / unread state
    is_read = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        index=True
    )

    # 🕒 timestamps
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=db.func.current_timestamp(),
        index=True
    )

    # (optional future use)
    read_at = db.Column(db.DateTime, nullable=True)

    # 🕓 auto-dismiss: when set, this notification should stop being
    # shown (Bell + tray) even if the user never taps it -- e.g. the
    # morning Panchang notification expires at 5 PM the same day.
    # NULL means "never auto-expires".
    #
    # N-FIX-2A: timezone=True (matches dismissed_at below, and
    # NotificationCampaignBellItem.expires_at) -- was previously a naive
    # DateTime while every writer (services/notification_lifecycle.py,
    # services/event_scheduler.py's Panchang calc) produced a naive-UTC
    # value and the ONE real comparison site
    # (notifications/campaign_bell_service.py's now/expires_at filter)
    # compares against an AWARE datetime.now(timezone.utc). Proven via
    # direct Postgres testing that this mismatch produces a WRONG
    # comparison result whenever the connection's session TimeZone GUC
    # is not UTC (e.g. Asia/Calcutta) -- see migration
    # 0aea42c0e4d0_make_user_notifications_expires_at_tz_aware.py's own
    # docstring for the full root-cause writeup and the explicit
    # AT TIME ZONE 'UTC' conversion this required (a plain ALTER COLUMN
    # TYPE would have silently corrupted every existing row under a
    # non-UTC session).
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # N6 -- presentation-only "Clear"/individual-dismiss marker. Never
    # read by services/attention_policy.py or services/event_scheduler.py
    # -- see notifications/campaign_bell_models.py's own docstring for
    # the full reasoning (this column exists so the SAME presentation-only
    # dismiss/clear semantics apply to A/B rows as to Campaign C's own
    # isolated Bell table, without touching either pipeline's selection/
    # cooldown/dedupe/budget/trim logic). NULL means "not dismissed".
    dismissed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # ===============================
    # HELPER METHODS
    # ===============================
    def mark_read(self):
        self.is_read = True
        self.read_at = datetime.now(timezone.utc)
# ===============================
# NOTIFICATION LOG (DUPLICATE CONTROL)
# ===============================
class NotificationLog(db.Model):
    __tablename__ = "notification_logs"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, nullable=False)
    event_id = db.Column(db.String(100), nullable=False)
    slot = db.Column(db.String(20), nullable=False)

    sent_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )