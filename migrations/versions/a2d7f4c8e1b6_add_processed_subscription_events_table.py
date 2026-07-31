"""add processed_subscription_events table for subscription event idempotency

Revision ID: a2d7f4c8e1b6
Revises: f9b3c6e1a7d4
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a2d7f4c8e1b6'
down_revision = 'f9b3c6e1a7d4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'processed_subscription_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store', sa.String(length=20), nullable=False),
        sa.Column('transaction_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=40), nullable=True),
        sa.Column('profile_id', sa.Integer(), nullable=True),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'store', 'transaction_id',
            name='uq_processed_subscription_events_store_transaction_id',
        ),
    )
    op.create_index(
        'ix_processed_subscription_events_transaction_id',
        'processed_subscription_events', ['transaction_id'],
    )


def downgrade():
    op.drop_index(
        'ix_processed_subscription_events_transaction_id',
        table_name='processed_subscription_events',
    )
    op.drop_table('processed_subscription_events')
