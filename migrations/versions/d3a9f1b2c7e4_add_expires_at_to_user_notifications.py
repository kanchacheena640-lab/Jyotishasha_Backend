"""add expires_at to user_notifications

Revision ID: d3a9f1b2c7e4
Revises: f32c4878fcf0
Create Date: 2026-07-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd3a9f1b2c7e4'
down_revision = 'f32c4878fcf0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_notifications',
        sa.Column('expires_at', sa.DateTime(), nullable=True)
    )


def downgrade():
    op.drop_column('user_notifications', 'expires_at')
