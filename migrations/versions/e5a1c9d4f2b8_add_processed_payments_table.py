"""add processed_payments table for payment idempotency

Revision ID: e5a1c9d4f2b8
Revises: c3f6a8e2b4d1
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5a1c9d4f2b8'
down_revision = 'c3f6a8e2b4d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'processed_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('payment_id', sa.String(length=120), nullable=False),
        sa.Column('reference', sa.String(length=120), nullable=True),
        sa.Column('order_id', sa.Integer(), nullable=True),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'payment_id', name='uq_processed_payments_provider_payment_id'),
    )
    op.create_index('ix_processed_payments_payment_id', 'processed_payments', ['payment_id'])


def downgrade():
    op.drop_index('ix_processed_payments_payment_id', table_name='processed_payments')
    op.drop_table('processed_payments')
