"""add lang to app_users

Revision ID: 7b3f1c9a4d5e
Revises: 60982e2e358a
Create Date: 2026-08-15 00:00:00.000000

N3 (Personalized Planetary Transit + Dasha Verification) -- adds a single
nullable content-language-preference column to app_users. Populated going
forward from the `lang` value the Flutter app already sends on every
/api/user/bootstrap call (previously received and used only transiently to
render calculate_full_kundali(), never persisted -- see
routes/routes_profile_bootstrap.py) and, for symmetry, from
modules/user_service.py::register_or_update_user(). No backfill for existing
rows: they simply read NULL until that user's next bootstrap/profile save,
and every reader treats NULL as "unknown, default to en" rather than this
migration guessing a value.

Does not touch any other column, index, or table.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7b3f1c9a4d5e'
down_revision = '60982e2e358a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('app_users', sa.Column('lang', sa.String(length=5), nullable=True))


def downgrade():
    op.drop_column('app_users', 'lang')
