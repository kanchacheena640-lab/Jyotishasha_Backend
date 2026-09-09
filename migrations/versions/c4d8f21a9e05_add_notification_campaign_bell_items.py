"""N6 monitoring/history/metrics + unified Bell presentation.

Two purely additive changes:
  1. New, wholly separate table notification_campaign_bell_items for
     Campaign C's own Bell presentation rows -- see
     notifications/campaign_bell_models.py's own docstring for why this
     is NOT a row in the existing user_notifications table (proven
     push-budget and retention-trim isolation risks).
  2. A nullable dismissed_at column added to the EXISTING user_notifications
     table, so "Clear"/individual-dismiss can be presentation-only across
     both A/B and Campaign C without touching any A/B selection, cooldown,
     dedupe, push-budget or retention-trim logic -- none of that code reads
     or writes this column; only the Bell LIST query's own WHERE clause
     (notifications/user_notification_routes.py) is extended to also
     require dismissed_at IS NULL, mirroring the existing expires_at
     filter it already has.

No existing row, table, or column is altered or dropped. No CHECK
constraint on user_notifications changes.

Revision ID: c4d8f21a9e05
Revises: 8c2f7b91d4e6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c4d8f21a9e05'
down_revision = '8c2f7b91d4e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user_notifications', sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'notification_campaign_bell_items',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('execution_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('notification_campaign_executions.id'), nullable=False),
        sa.Column('campaign_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('notification_campaigns.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('app_user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('body', sa.String(500), nullable=False),
        sa.Column('action', postgresql.JSONB(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('execution_id', 'user_id', name='uq_notification_campaign_bell_items_execution_user'),
    )
    op.create_index('ix_notification_campaign_bell_items_user', 'notification_campaign_bell_items', ['user_id', 'created_at'])


def downgrade():
    op.drop_index('ix_notification_campaign_bell_items_user', table_name='notification_campaign_bell_items')
    op.drop_table('notification_campaign_bell_items')
    op.drop_column('user_notifications', 'dismissed_at')
