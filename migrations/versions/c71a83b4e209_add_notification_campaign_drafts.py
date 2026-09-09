"""N3 durable isolated campaign drafts only.

Revision ID: c71a83b4e209
Revises: 9f2a5c7e1b83
No existing business table is altered and no data is backfilled.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c71a83b4e209'
down_revision = '9f2a5c7e1b83'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('notification_campaigns',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column('public_key', sa.String(32), nullable=False, unique=True),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('body', sa.String(500), nullable=False),
        sa.Column('audience_mode', sa.String(24), nullable=False),
        sa.Column('saved_audience_id', sa.Integer(), nullable=False),
        sa.Column('draft_criteria', postgresql.JSONB(), nullable=False),
        sa.Column('criteria_version', sa.Integer(), nullable=False),
        sa.Column('draft_criteria_hash', sa.String(64), nullable=False),
        sa.Column('action', postgresql.JSONB(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state = 'DRAFT'", name='ck_notification_campaigns_draft'),
        sa.CheckConstraint("audience_mode = 'SAVED_AUDIENCE'", name='ck_notification_campaigns_audience_mode'),
        sa.CheckConstraint('revision > 0', name='ck_notification_campaigns_revision'),
    )
    op.create_index('ix_notification_campaigns_saved_audience_id','notification_campaigns',['saved_audience_id'])


def downgrade():
    op.drop_index('ix_notification_campaigns_saved_audience_id',table_name='notification_campaigns')
    op.drop_table('notification_campaigns')
