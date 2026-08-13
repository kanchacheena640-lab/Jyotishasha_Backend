"""add severity and last_delivered_at to alert_micro_events

Revision ID: 60982e2e358a
Revises: 5e64a21e77aa
Create Date: 2026-08-13 00:00:00.000000

Alerts Engine -- Phase 4 (severity + cooldown policy). Adds the
MINIMUM delivery-policy columns to the existing alert_micro_events
table (created by 5e64a21e77aa, Phase 1) -- both nullable, so every
existing row from Phase 1/2/3 remains valid with no backfill required
(both new columns simply read as NULL for pre-Phase-4 rows).

Does NOT touch (profile_id, event_id) uniqueness, any existing column,
any index, or any other table. Does not edit 5e64a21e77aa.

- severity: LOW/MEDIUM/HIGH/CRITICAL, config-driven (see
  modules/alerts/severity_cooldown_registry.py) -- populated by
  ProfileDetectionService going forward, never derived from confidence.
- last_delivered_at: set ONLY by a future Phase 5 delivery adapter
  after a CONFIRMED successful FCM send. Nothing in Phase 1-4 writes to
  it -- see modules/alerts/persistence_repository.py::synchronize_profile_events()'s
  own docstring for why lifecycle synchronization never touches it.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '60982e2e358a'
down_revision = '5e64a21e77aa'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alert_micro_events', sa.Column('severity', sa.String(length=10), nullable=True))
    op.add_column('alert_micro_events', sa.Column('last_delivered_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('alert_micro_events', 'last_delivered_at')
    op.drop_column('alert_micro_events', 'severity')
