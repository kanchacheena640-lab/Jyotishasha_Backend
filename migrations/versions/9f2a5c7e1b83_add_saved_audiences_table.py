"""add saved_audiences table

Revision ID: 9f2a5c7e1b83
Revises: 37fd90bfdfd5
Create Date: 2026-09-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '9f2a5c7e1b83'
down_revision = '37fd90bfdfd5'
branch_labels = None
depends_on = None


def upgrade():
    # U6A -- Saved Audience backend foundation. Purely additive: new
    # table only, no existing table touched. See
    # modules/models_saved_audience.py for the full design rationale
    # (dynamic/criteria-based, users.id-scoped, no membership
    # persistence -- deliberately no member_ids/last_member_count/
    # last_resolved_at/notification_job_id columns).
    op.create_table(
        'saved_audiences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('saved_audiences')
