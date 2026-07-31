"""add selected_segment to current_entitlements and subscription_events

Revision ID: c3f6a8e2b4d1
Revises: b7e2a4f9c1d6
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c3f6a8e2b4d1'
down_revision = 'b7e2a4f9c1d6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'current_entitlements',
        sa.Column('selected_segment', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'subscription_events',
        sa.Column('selected_segment', sa.String(length=20), nullable=True),
    )


def downgrade():
    op.drop_column('subscription_events', 'selected_segment')
    op.drop_column('current_entitlements', 'selected_segment')
