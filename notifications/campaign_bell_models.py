"""N6 -- ISOLATED Campaign C (ADMIN_CAMPAIGN) Bell presentation storage.

Deliberately NOT a row in notifications.notification_models.UserNotification
(A/B's own Bell table). Two proven, code-verified reasons (N6 discovery
audit, not hypothetical):

  1. services/attention_policy.py::count_pushes_sent_today() counts EVERY
     UserNotification row created "today" (IST) for a user against A/B's
     shared DAILY_PUSH_CAP=2, EXCLUDING ONLY rows tagged
     data["delivery_channel"] == "bell_only". A Campaign C row sharing
     that table would silently consume A/B's daily push budget unless
     every single write got that exact tag forever -- a fragile,
     unenforceable invariant to hang cross-pipeline isolation on.

  2. services/event_scheduler.py's own "keep newest 10 per user" physical
     retention trim deletes every UserNotification row beyond the 10
     newest for that user_id, GLOBALLY, with NO source filter at all
     today. A shared table would let a single Campaign C send physically
     evict genuine, still-relevant A/B Bell rows (or have its own rows
     evicted by unrelated A/B churn) -- exactly the "trimming"
     interference N1's Bell contract (Section 19) forbids.

A wholly separate table sidesteps both risks structurally rather than by
convention: this model is never read or written by attention_policy.py,
event_scheduler.py, or modules/alerts/ -- so A/B's push-budget accounting
and retention trim are provably unaffected by Campaign C's existence, with
no per-write discipline required. The unified Bell read API
(notifications/campaign_bell_service.py) merges both sources ONLY at read
time for presentation -- it never writes into, deletes from, or queries
UserNotification for selection/dedupe/cooldown purposes, only reads rows
A/B's own code already produced independently.

Lifecycle: one row is created per frozen delivery target, at the exact
same moment (same DB transaction) NotificationCampaignDelivery rows are
created in campaign_execution_service.py::_freeze_targets() -- see that
function's own N6 addition for why "at target freeze" is the chosen,
documented Bell-row-creation point (independent of transport/push outcome,
matching how A/B's own Bell rows are written regardless of push success).
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB, UUID
from extensions import db


class NotificationCampaignBellItem(db.Model):
    __tablename__ = 'notification_campaign_bell_items'
    id = db.Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id = db.Column(UUID(as_uuid=False), db.ForeignKey('notification_campaign_executions.id'), nullable=False)
    campaign_id = db.Column(UUID(as_uuid=False), db.ForeignKey('notification_campaigns.id'), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    app_user_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(500), nullable=False)
    # Frozen N3/N4 action shape reused verbatim -- {"type": "NONE"|
    # "APP_DEEP_LINK"|"WEB_URL", "target": str|null}. Never widened here.
    action = db.Column(JSONB, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    read_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Presentation-only "Clear"/individual-dismiss marker -- never mutates
    # or is mutated by campaign/execution/delivery/attempt/attribution
    # history; those tables have no dismissed_at concept at all.
    dismissed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('execution_id', 'user_id', name='uq_notification_campaign_bell_items_execution_user'),
    )
