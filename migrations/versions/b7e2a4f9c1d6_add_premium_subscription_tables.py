"""add premium subscription tables (current_entitlements, subscription_events)

Revision ID: b7e2a4f9c1d6
Revises: a1c4e9f7d2b3
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b7e2a4f9c1d6'
down_revision = 'a1c4e9f7d2b3'
branch_labels = None
depends_on = None


def upgrade():
    # subscription_events created first -- current_entitlements.last_event_id
    # references it.
    op.create_table(
        'subscription_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('app_users.id'), nullable=False),
        sa.Column('event_type', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('plan', sa.String(length=30), nullable=True),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('store', sa.String(length=20), nullable=True),
        sa.Column('purchase_token', sa.String(length=255), nullable=True),
        sa.Column('transaction_id', sa.String(length=255), nullable=True),
        sa.Column('receipt_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_subscription_events_profile_id', 'subscription_events', ['profile_id'])
    op.create_index('ix_subscription_events_event_type', 'subscription_events', ['event_type'])
    op.create_index('ix_subscription_events_created_at', 'subscription_events', ['created_at'])

    op.create_table(
        'current_entitlements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('app_users.id'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('plan', sa.String(length=30), nullable=True),
        sa.Column('trial_started_at', sa.DateTime(), nullable=True),
        sa.Column('trial_expires_at', sa.DateTime(), nullable=True),
        sa.Column('subscription_started_at', sa.DateTime(), nullable=True),
        sa.Column('subscription_expires_at', sa.DateTime(), nullable=True),
        sa.Column('store', sa.String(length=20), nullable=True),
        sa.Column('purchase_token', sa.String(length=255), nullable=True),
        sa.Column('auto_renew', sa.Boolean(), nullable=True),
        sa.Column('last_event_id', sa.Integer(), sa.ForeignKey('subscription_events.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('profile_id', name='uq_current_entitlements_profile_id'),
    )
    op.create_index('ix_current_entitlements_profile_id', 'current_entitlements', ['profile_id'])
    op.create_index(
        'ix_current_entitlements_subscription_expires_at',
        'current_entitlements', ['subscription_expires_at'],
    )


def downgrade():
    op.drop_index('ix_current_entitlements_subscription_expires_at', table_name='current_entitlements')
    op.drop_index('ix_current_entitlements_profile_id', table_name='current_entitlements')
    op.drop_table('current_entitlements')

    op.drop_index('ix_subscription_events_created_at', table_name='subscription_events')
    op.drop_index('ix_subscription_events_event_type', table_name='subscription_events')
    op.drop_index('ix_subscription_events_profile_id', table_name='subscription_events')
    op.drop_table('subscription_events')
