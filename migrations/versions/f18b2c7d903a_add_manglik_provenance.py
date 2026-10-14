"""Independent Manglik provenance; no backfill or defaults. NOT applied."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f18b2c7d903a'
down_revision = 'ec4f2103b154'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('app_users', sa.Column('manglik_calculation_version', sa.SmallInteger(), nullable=True), schema='public')
    op.add_column('app_users', sa.Column('manglik_calculated_at', sa.DateTime(timezone=True), nullable=True), schema='public')
    op.add_column('app_users', sa.Column('manglik_input_digest', sa.String(64), nullable=True), schema='public')
    op.add_column('app_users', sa.Column('manglik_correction_run_id', postgresql.UUID(as_uuid=True), nullable=True), schema='public')


def downgrade():
    for name in ('manglik_correction_run_id', 'manglik_input_digest', 'manglik_calculated_at', 'manglik_calculation_version'):
        op.drop_column('app_users', name, schema='public')
