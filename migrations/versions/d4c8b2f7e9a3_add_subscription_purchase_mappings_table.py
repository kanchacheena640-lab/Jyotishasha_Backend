"""add subscription_purchase_mappings table for RTDN identity resolution

Revision ID: d4c8b2f7e9a3
Revises: a2d7f4c8e1b6
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4c8b2f7e9a3'
down_revision = 'a2d7f4c8e1b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'subscription_purchase_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('purchase_token', sa.String(length=255), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('product_id', sa.String(length=120), nullable=True),
        sa.Column('order_id', sa.String(length=120), nullable=True),
        sa.Column('linked_purchase_token', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['app_users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('purchase_token', name='uq_subscription_purchase_mappings_purchase_token'),
    )
    op.create_index(
        'ix_subscription_purchase_mappings_profile_id',
        'subscription_purchase_mappings', ['profile_id'],
    )
    op.create_index(
        'ix_subscription_purchase_mappings_linked_purchase_token',
        'subscription_purchase_mappings', ['linked_purchase_token'],
    )


def downgrade():
    op.drop_index(
        'ix_subscription_purchase_mappings_linked_purchase_token',
        table_name='subscription_purchase_mappings',
    )
    op.drop_index(
        'ix_subscription_purchase_mappings_profile_id',
        table_name='subscription_purchase_mappings',
    )
    op.drop_table('subscription_purchase_mappings')
