"""N3 authoring identity, plus (N4) the minimum campaign-level state
needed to reflect a Send Now execution's own lifecycle. No target,
token or delivery state lives here -- see
notifications/campaign_execution_models.py for that."""
import uuid
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB, UUID
from extensions import db


class NotificationCampaign(db.Model):
    __tablename__ = 'notification_campaigns'
    id = db.Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    public_key = db.Column(db.String(32), unique=True, nullable=False, default=lambda: uuid.uuid4().hex)
    # N4 widened N3's DRAFT-only CHECK to add PROCESSING/COMPLETED/
    # PARTIAL/FAILED (migration 5a1e9d2f4c73). N5 further adds SCHEDULED
    # (a DRAFT scheduled for a future UTC time) and CANCELLED (a
    # SCHEDULED/PAUSED execution cancelled before target freeze) --
    # migration 8c2f7b91d4e6. P4.5 widens CANCELLED's own meaning
    # (no new migration needed -- the string was already valid) to also
    # cover a FROZEN execution cancelled AFTER target freeze but BEFORE
    # any transport attempt -- see campaign_schedule_service.py's own
    # _cancel_unsent_frozen(). EXPIRED/BLOCKED are execution-level-only
    # states (campaign_execution_models.py); a campaign whose execution
    # ends up EXPIRED or BLOCKED is reflected here as FAILED, with
    # hold_reason carrying the specific reason.
    state = db.Column(db.String(24), nullable=False, default='DRAFT')
    # N4 -- mirrors the execution's own hold_reason while campaign
    # stays PROCESSING (N1 Section 9: "a pre-freeze safety hold ... and
    # a visible campaign hold_reason while campaign remains PROCESSING").
    hold_reason = db.Column(db.String(40), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(500), nullable=False)
    audience_mode = db.Column(db.String(24), nullable=False, default='SAVED_AUDIENCE')
    saved_audience_id = db.Column(db.Integer, nullable=False, index=True)
    # Reference retained if source disappears, so the UI can surface its loss.
    # No FK that changes frozen audience/account deletion behavior.
    draft_criteria = db.Column(JSONB, nullable=False)
    criteria_version = db.Column(db.Integer, nullable=False)
    draft_criteria_hash = db.Column(db.String(64), nullable=False)
    action = db.Column(JSONB, nullable=False)
    created_by = db.Column(db.Integer, nullable=True)
    updated_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        db.CheckConstraint("state in ('DRAFT','SCHEDULED','PROCESSING','COMPLETED','PARTIAL','FAILED','CANCELLED')",
                          name='ck_notification_campaigns_state'),
        db.CheckConstraint("audience_mode = 'SAVED_AUDIENCE'", name='ck_notification_campaigns_audience_mode'),
        db.CheckConstraint('revision > 0', name='ck_notification_campaigns_revision'),
    )
