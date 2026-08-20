"""add ai_insight/ai_action/ai_generated_at to alert_micro_events

Revision ID: c2f8a6d1e3b7
Revises: 9f4d2a7e1c6b
Create Date: 2026-08-20

AI-Written Personalized Alert Content: adds three nullable columns to
alert_micro_events so a genuinely new/reactivated alert occurrence's
AI-generated body (SIGNAL -> real-life implication -> practical action)
persists once and is reused by every downstream surface (push, Bell,
dashboard), instead of being regenerated per request or lost entirely.

Purely additive -- no existing column altered, no data migrated. NULL
(the default for all three, on every existing row) means "not yet
AI-generated"; modules/alerts/notification_content_adapter.py falls
back to the existing deterministic per-category template whenever
ai_insight is NULL, so this migration cannot break any existing alert.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c2f8a6d1e3b7'
down_revision = '9f4d2a7e1c6b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alert_micro_events', sa.Column('ai_insight', sa.Text(), nullable=True))
    op.add_column('alert_micro_events', sa.Column('ai_action', sa.Text(), nullable=True))
    op.add_column('alert_micro_events', sa.Column('ai_generated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('alert_micro_events', 'ai_generated_at')
    op.drop_column('alert_micro_events', 'ai_action')
    op.drop_column('alert_micro_events', 'ai_insight')
