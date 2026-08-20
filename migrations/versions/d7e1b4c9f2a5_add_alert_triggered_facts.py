"""add triggered_facts to alert_micro_events

Revision ID: d7e1b4c9f2a5
Revises: c2f8a6d1e3b7
Create Date: 2026-08-20

Architectural gate fix: AI generation was moved from detection time
(before selection/cooldown/suppression narrows the detected set down
to the final delivered alert(s)) to AFTER selection -- see
modules/alerts/alert_ai_content_service.py::
ensure_ai_content_for_selected_rows()'s own docstring. This requires
persisting the plain-English facts a genuinely later, separate
generation step needs, since the live detection-time objects
(PlannedMicroEvent/EvaluationContext) no longer exist by the time
selection (and therefore generation) runs.

Purely additive -- one new nullable JSON column, no existing column
altered, no data migrated. NULL on every existing row means "no facts
computed yet for this row" (harmless -- the next detection run for
that profile/event_id populates it, cheaply, with no OpenAI cost).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd7e1b4c9f2a5'
down_revision = 'c2f8a6d1e3b7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alert_micro_events', sa.Column('triggered_facts', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('alert_micro_events', 'triggered_facts')
