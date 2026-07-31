"""add processing_started_at to orders for abandoned-Processing detection

Revision ID: f9b3c6e1a7d4
Revises: e5a1c9d4f2b8
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f9b3c6e1a7d4'
down_revision = 'e5a1c9d4f2b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orders', sa.Column('processing_started_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('orders', 'processing_started_at')
