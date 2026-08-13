"""add alert_micro_events table

Revision ID: 5e64a21e77aa
Revises: d4c8b2f7e9a3
Create Date: 2026-08-13 00:00:00.000000

Alerts Engine -- Phase 1 (persistence only). Adds the ONLY table the
Micro Event Engine uses. See modules/alerts/persistence_models.py and
modules/alerts/persistence_repository.py for the full design reasoning
(in particular: why the UNIQUE constraint is (profile_id, event_id),
not (profile_id, event_id, active_from)).

Does not touch any existing table -- additive only. `profile_id`
references app_users.id, the same foreign key
modules/models_ai_reports.py's own "add_ai_reports_table" migration
already uses for the identical reason (no dedicated Profile table
exists yet).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5e64a21e77aa'
down_revision = 'd4c8b2f7e9a3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'alert_micro_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('app_users.id'), nullable=False),
        sa.Column('event_id', sa.String(length=64), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('state', sa.String(length=10), nullable=False),
        sa.Column('priority', sa.String(length=10), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('active_from', sa.Date(), nullable=False),
        sa.Column('active_until', sa.Date(), nullable=False),
        sa.Column('first_detected_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_evaluated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            'profile_id', 'event_id',
            name='uq_alert_micro_events_profile_event',
        ),
    )

    # THE idempotency/concurrency guarantee -- see
    # persistence_repository.py's module docstring for why this is
    # (profile_id, event_id), not (..., active_from). Its own backing
    # index also serves per-profile lookups (profile_id is the leading
    # column of a UNIQUE constraint's index), so no separate
    # single-column profile_id index is added here.

    # Serves "active alerts for one profile" (filtered further by
    # profile_id from the tiny per-profile row set), "alerts by
    # state/time", and "scheduler processing" (scan by state, ordered/
    # filtered by evaluation recency) -- the three read patterns this
    # phase's brief names, in one composite index rather than two
    # separate, partially-redundant ones.
    op.create_index(
        'ix_alert_micro_events_state_last_evaluated_at',
        'alert_micro_events',
        ['state', 'last_evaluated_at'],
    )


def downgrade():
    op.drop_index('ix_alert_micro_events_state_last_evaluated_at', table_name='alert_micro_events')
    op.drop_table('alert_micro_events')
