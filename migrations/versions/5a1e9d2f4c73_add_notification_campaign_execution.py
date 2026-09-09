"""N4 Send Now execution/delivery/attempt/idempotency schema.

Revision ID: 5a1e9d2f4c73
Revises: c71a83b4e209

Widens notification_campaigns' N3 DRAFT-only CHECK to the minimum N1-
compatible state set Send Now needs (DRAFT/PROCESSING/COMPLETED/
PARTIAL/FAILED -- no SCHEDULED/CANCELLED/EXPIRED; those remain N5+),
adds a nullable hold_reason column (N1 Section 9's "visible campaign
hold_reason while campaign remains PROCESSING" during a drift pause),
and creates four new, wholly additive tables. No existing row is
altered, no existing table's data is touched, and no NotificationJob/
NotificationLog/UserNotification (A/B legacy) table is modified.

No token/token-fingerprint column is created anywhere in this
migration: N4 deliberately never persists a durable raw or encrypted
FCM token snapshot (see notifications/campaign_execution_service.py's
own module docstring for the reasoning) -- the current token is
re-resolved fresh at each attempt, which is both simpler and more
N1-Section-7-compliant ("revalidate ... current token fingerprint
[before] each attempt") than a stored snapshot would be.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '5a1e9d2f4c73'
down_revision = 'c71a83b4e209'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('ck_notification_campaigns_draft', 'notification_campaigns', type_='check')
    op.create_check_constraint(
        'ck_notification_campaigns_state', 'notification_campaigns',
        "state in ('DRAFT','PROCESSING','COMPLETED','PARTIAL','FAILED')",
    )
    op.add_column('notification_campaigns', sa.Column('hold_reason', sa.String(40), nullable=True))

    op.create_table('notification_campaign_executions',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('campaign_id', postgresql.UUID(as_uuid=False),
                  sa.ForeignKey('notification_campaigns.id'), nullable=False, unique=True),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('hold_reason', sa.String(40), nullable=True),
        # Approved definition freeze (N1 Section 5 P2 / N4.6) -- captured
        # once at Send Now approval and never rewritten by a later
        # SavedAudience edit. Deliberately a full copy, not a foreign key
        # alone, so this remains readable/auditable even if the
        # SavedAudience row is later edited or deactivated.
        sa.Column('approved_saved_audience_id', sa.Integer(), nullable=False),
        sa.Column('approved_criteria', postgresql.JSONB(), nullable=False),
        sa.Column('approved_criteria_version', sa.Integer(), nullable=False),
        sa.Column('approved_criteria_hash', sa.String(64), nullable=False),
        sa.Column('approved_title', sa.String(200), nullable=False),
        sa.Column('approved_body', sa.String(500), nullable=False),
        sa.Column('approved_action', postgresql.JSONB(), nullable=False),
        # N1 Section 22/26 confirmations -- booleans only; the literal
        # typed "SEND TO ALL USERS" phrase itself is never persisted.
        sa.Column('all_users_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('large_audience_acknowledged', sa.Boolean(), nullable=False, server_default=sa.false()),
        # Drift baseline (N1 P7 / N4.11) -- the client-supplied recent-
        # preview snapshot used ONLY for drift comparison, re-recorded
        # explicitly on every reconfirmation (never silently accepted).
        sa.Column('baseline_generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('baseline_matched_user_count', sa.Integer(), nullable=False),
        sa.Column('baseline_eligible_recipient_count', sa.Integer(), nullable=False),
        sa.Column('baseline_recorded_at', sa.DateTime(timezone=True), nullable=False),
        # Authoritative live resolution at dispatch time (N1 Section 6).
        sa.Column('resolved_matched_user_count', sa.Integer(), nullable=True),
        sa.Column('resolved_eligible_recipient_count', sa.Integer(), nullable=True),
        sa.Column('resolved_excluded_recipient_count', sa.Integer(), nullable=True),
        sa.Column('resolved_exclusion_counts', postgresql.JSONB(), nullable=True),
        sa.Column('resolver_policy_version', sa.String(32), nullable=True),
        sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        # Atomic claim/lease (N1 Section 10 / N4.20) -- row lock +
        # compare-and-set fields, never a Python-memory lock.
        sa.Column('lease_owner', sa.String(64), nullable=True),
        sa.Column('lease_generation', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state in ('RESOLVING','PAUSED','FROZEN','SENDING','COMPLETED','PARTIAL','FAILED')",
            name='ck_notification_campaign_executions_state'),
    )

    op.create_table('notification_campaign_deliveries',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('execution_id', postgresql.UUID(as_uuid=False),
                  sa.ForeignKey('notification_campaign_executions.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('app_user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False, server_default='PENDING'),
        sa.Column('suppression_reason', sa.String(40), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_owner', sa.String(64), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_attempted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_attempted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('PENDING','ACCEPTED','FAILED_RETRYABLE','FAILED_PERMANENT','UNKNOWN','SUPPRESSED')",
            name='ck_notification_campaign_deliveries_status'),
        sa.UniqueConstraint('execution_id', 'user_id', name='uq_notification_campaign_deliveries_execution_user'),
    )
    op.create_index('ix_notification_campaign_deliveries_execution_status',
                     'notification_campaign_deliveries', ['execution_id', 'status'])
    op.create_index('ix_notification_campaign_deliveries_claim',
                     'notification_campaign_deliveries', ['execution_id', 'next_attempt_at'])

    op.create_table('notification_campaign_attempts',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('delivery_id', postgresql.UUID(as_uuid=False),
                  sa.ForeignKey('notification_campaign_deliveries.id'), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        # Nullable: NULL is the durable pre-invocation "ATTEMPTING"
        # marker (N1 Section 11 / N4.19) written before transport.send()
        # is ever called, then filled in by the same row afterward. A
        # row still NULL after its delivery's lease expires is what
        # campaign_worker.py's own _reap_expired_leases() reconciles to
        # UNKNOWN -- never left ambiguous, never silently retried.
        sa.Column('outcome', sa.String(24), nullable=True),
        sa.Column('provider', sa.String(24), nullable=False),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('error_class', sa.String(32), nullable=True),
        sa.CheckConstraint(
            "outcome in ('ACCEPTED','FAILED_RETRYABLE','FAILED_PERMANENT','UNKNOWN')",
            name='ck_notification_campaign_attempts_outcome'),
        sa.UniqueConstraint('delivery_id', 'attempt_number', name='uq_notification_campaign_attempts_delivery_number'),
    )
    op.create_index('ix_notification_campaign_attempts_delivery', 'notification_campaign_attempts', ['delivery_id'])

    op.create_table('notification_send_now_requests',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('campaign_id', postgresql.UUID(as_uuid=False),
                  sa.ForeignKey('notification_campaigns.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('execution_id', postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column('response_status', sa.Integer(), nullable=False),
        sa.Column('response_body', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('campaign_id', 'idempotency_key', name='uq_notification_send_now_requests_campaign_key'),
    )


def downgrade():
    op.drop_table('notification_send_now_requests')
    op.drop_index('ix_notification_campaign_attempts_delivery', table_name='notification_campaign_attempts')
    op.drop_table('notification_campaign_attempts')
    op.drop_index('ix_notification_campaign_deliveries_claim', table_name='notification_campaign_deliveries')
    op.drop_index('ix_notification_campaign_deliveries_execution_status', table_name='notification_campaign_deliveries')
    op.drop_table('notification_campaign_deliveries')
    op.drop_table('notification_campaign_executions')
    op.drop_column('notification_campaigns', 'hold_reason')
    op.drop_constraint('ck_notification_campaigns_state', 'notification_campaigns', type_='check')
    op.create_check_constraint('ck_notification_campaigns_draft', 'notification_campaigns', "state = 'DRAFT'")
