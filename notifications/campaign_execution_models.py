"""N4 Send Now execution/delivery/attempt/idempotency identities.

No token/token-fingerprint column exists anywhere here -- see
notifications/campaign_execution_service.py's own module docstring for
why N4 deliberately never persists a durable raw or encrypted FCM
token snapshot.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB, UUID
from extensions import db


class NotificationCampaignExecution(db.Model):
    __tablename__ = 'notification_campaign_executions'
    id = db.Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id = db.Column(UUID(as_uuid=False), db.ForeignKey('notification_campaigns.id'), nullable=False, unique=True)
    state = db.Column(db.String(24), nullable=False)
    hold_reason = db.Column(db.String(40), nullable=True)

    approved_saved_audience_id = db.Column(db.Integer, nullable=False)
    approved_criteria = db.Column(JSONB, nullable=False)
    approved_criteria_version = db.Column(db.Integer, nullable=False)
    approved_criteria_hash = db.Column(db.String(64), nullable=False)
    approved_title = db.Column(db.String(200), nullable=False)
    approved_body = db.Column(db.String(500), nullable=False)
    approved_action = db.Column(JSONB, nullable=False)

    all_users_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    large_audience_acknowledged = db.Column(db.Boolean, nullable=False, default=False)

    baseline_generated_at = db.Column(db.DateTime(timezone=True), nullable=False)
    baseline_matched_user_count = db.Column(db.Integer, nullable=False)
    baseline_eligible_recipient_count = db.Column(db.Integer, nullable=False)
    baseline_recorded_at = db.Column(db.DateTime(timezone=True), nullable=False)

    resolved_matched_user_count = db.Column(db.Integer, nullable=True)
    resolved_eligible_recipient_count = db.Column(db.Integer, nullable=True)
    resolved_excluded_recipient_count = db.Column(db.Integer, nullable=True)
    resolved_exclusion_counts = db.Column(JSONB, nullable=True)
    resolver_policy_version = db.Column(db.String(32), nullable=True)

    frozen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # N5 -- scheduling. NULL for an N4 Send Now execution (dispatched
    # immediately, never SCHEDULED). scheduled_for/expires_at are the
    # UTC scheduling authority (N1 Section 20/N5 Section 2); dispatch_
    # started_at is when the scheduler first claimed/began processing
    # this due execution -- distinct from started_at above, which marks
    # when transport attempts began (may be later, or never, if the
    # execution ends up PAUSED/EXPIRED/BLOCKED before freezing).
    scheduled_for = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dispatch_started_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Reused for BOTH N4's per-delivery worker claim semantics' own
    # execution-level analogue AND N5's due-scheduler claim -- the same
    # SELECT...FOR UPDATE SKIP LOCKED + compare-and-set lease convention
    # already established for NotificationCampaignDelivery below.
    lease_owner = db.Column(db.String(64), nullable=True)
    lease_generation = db.Column(db.Integer, nullable=False, default=0)
    lease_until = db.Column(db.DateTime(timezone=True), nullable=True)

    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.CheckConstraint(
            "state in ('SCHEDULED','RESOLVING','PAUSED','FROZEN','SENDING','COMPLETED','PARTIAL','FAILED','EXPIRED','BLOCKED','CANCELLED')",
            name='ck_notification_campaign_executions_state'),
    )


class NotificationCampaignDelivery(db.Model):
    __tablename__ = 'notification_campaign_deliveries'
    id = db.Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id = db.Column(UUID(as_uuid=False), db.ForeignKey('notification_campaign_executions.id'), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    app_user_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='PENDING')
    suppression_reason = db.Column(db.String(40), nullable=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(db.DateTime(timezone=True), nullable=True)
    lease_owner = db.Column(db.String(64), nullable=True)
    lease_until = db.Column(db.DateTime(timezone=True), nullable=True)
    first_attempted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_attempted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    accepted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.CheckConstraint(
            "status in ('PENDING','ACCEPTED','FAILED_RETRYABLE','FAILED_PERMANENT','UNKNOWN','SUPPRESSED')",
            name='ck_notification_campaign_deliveries_status'),
        db.UniqueConstraint('execution_id', 'user_id', name='uq_notification_campaign_deliveries_execution_user'),
    )


class NotificationCampaignAttempt(db.Model):
    __tablename__ = 'notification_campaign_attempts'
    id = db.Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    delivery_id = db.Column(UUID(as_uuid=False), db.ForeignKey('notification_campaign_deliveries.id'), nullable=False)
    attempt_number = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Nullable: NULL is the durable pre-invocation "ATTEMPTING" marker --
    # see the migration's own comment for the full crash-safety reasoning.
    outcome = db.Column(db.String(24), nullable=True)
    provider = db.Column(db.String(24), nullable=False)
    error_code = db.Column(db.String(64), nullable=True)
    error_class = db.Column(db.String(32), nullable=True)

    __table_args__ = (
        db.CheckConstraint("outcome in ('ACCEPTED','FAILED_RETRYABLE','FAILED_PERMANENT','UNKNOWN')",
                          name='ck_notification_campaign_attempts_outcome'),
        db.UniqueConstraint('delivery_id', 'attempt_number', name='uq_notification_campaign_attempts_delivery_number'),
    )


class NotificationSendNowRequest(db.Model):
    """N1 Section 21 / N4.5 idempotency ledger. One row per (campaign,
    idempotency_key). Never a substitute for the executions table's own
    unique(campaign_id) -- that is what actually prevents a second
    execution; this table lets a retried/duplicated HTTP request replay
    the exact original response instead of re-running validation."""
    __tablename__ = 'notification_send_now_requests'
    id = db.Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id = db.Column(UUID(as_uuid=False), db.ForeignKey('notification_campaigns.id'), nullable=False)
    idempotency_key = db.Column(db.String(128), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    execution_id = db.Column(UUID(as_uuid=False), nullable=True)
    response_status = db.Column(db.Integer, nullable=False)
    response_body = db.Column(JSONB, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('campaign_id', 'idempotency_key', name='uq_notification_send_now_requests_campaign_key'),
    )
