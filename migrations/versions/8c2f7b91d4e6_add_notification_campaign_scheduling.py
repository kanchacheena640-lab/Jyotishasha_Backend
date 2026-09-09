"""N5 campaign scheduling: adds scheduling columns to the existing N4
execution table and widens the N3/N4 campaign/execution state CHECKs.
No table is created or dropped, no existing row is altered, and no
existing column's meaning changes -- purely additive.

Revision ID: 8c2f7b91d4e6
Revises: 5a1e9d2f4c73
"""
from alembic import op
import sqlalchemy as sa

revision = '8c2f7b91d4e6'
down_revision = '5a1e9d2f4c73'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('notification_campaign_executions', sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True))
    op.add_column('notification_campaign_executions', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    # Distinct from the existing started_at (N4: when transport attempts
    # began) -- this is when the SCHEDULER first claimed/began processing
    # this due execution, before any resolution/safety check has run.
    op.add_column('notification_campaign_executions', sa.Column('dispatch_started_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_notification_campaign_executions_due', 'notification_campaign_executions', ['state', 'scheduled_for'])

    op.drop_constraint('ck_notification_campaign_executions_state', 'notification_campaign_executions', type_='check')
    op.create_check_constraint(
        'ck_notification_campaign_executions_state', 'notification_campaign_executions',
        "state in ('SCHEDULED','RESOLVING','PAUSED','FROZEN','SENDING','COMPLETED','PARTIAL','FAILED','EXPIRED','BLOCKED','CANCELLED')",
    )

    op.drop_constraint('ck_notification_campaigns_state', 'notification_campaigns', type_='check')
    op.create_check_constraint(
        'ck_notification_campaigns_state', 'notification_campaigns',
        "state in ('DRAFT','SCHEDULED','PROCESSING','COMPLETED','PARTIAL','FAILED','CANCELLED')",
    )


def downgrade():
    op.drop_constraint('ck_notification_campaigns_state', 'notification_campaigns', type_='check')
    op.create_check_constraint(
        'ck_notification_campaigns_state', 'notification_campaigns',
        "state in ('DRAFT','PROCESSING','COMPLETED','PARTIAL','FAILED')",
    )

    op.drop_constraint('ck_notification_campaign_executions_state', 'notification_campaign_executions', type_='check')
    op.create_check_constraint(
        'ck_notification_campaign_executions_state', 'notification_campaign_executions',
        "state in ('RESOLVING','PAUSED','FROZEN','SENDING','COMPLETED','PARTIAL','FAILED')",
    )

    op.drop_index('ix_notification_campaign_executions_due', table_name='notification_campaign_executions')
    op.drop_column('notification_campaign_executions', 'dispatch_started_at')
    op.drop_column('notification_campaign_executions', 'expires_at')
    op.drop_column('notification_campaign_executions', 'scheduled_for')
