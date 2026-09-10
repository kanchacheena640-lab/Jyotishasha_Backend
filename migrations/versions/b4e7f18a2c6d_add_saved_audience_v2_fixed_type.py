"""Saved Audience V2 -- add audience_type + saved_audience_members (FIXED type)

Revision ID: b4e7f18a2c6d
Revises: c4d8f21a9e05
Create Date: 2026-09-11 00:00:00.000000

Adds the explicit FIXED audience type alongside the existing DYNAMIC/
criteria-based one (see modules/models_saved_audience.py's own module
docstring for the full product rationale):

  - saved_audiences.audience_type (String(10), NOT NULL, default
    'dynamic') -- every EXISTING row backfills to 'dynamic' via the
    server_default, matching its already-required, already-populated
    criteria column exactly. Purely additive for every existing row.
  - saved_audiences.criteria widened to NULLABLE (was NOT NULL) -- a
    FIXED audience has no criteria at all; membership lives in the new
    saved_audience_members table instead.
  - Two CHECK constraints enforce the type/criteria shape never drifts:
    audience_type must be 'dynamic' or 'fixed', and criteria is
    non-NULL iff audience_type='dynamic' (NULL iff 'fixed').
  - New saved_audience_members table: one row per (audience, users.id)
    membership pair, FK'd both ways (ON DELETE CASCADE), with a UNIQUE
    constraint on (saved_audience_id, user_id) so the database itself
    prevents duplicate members -- never relying on application-level
    dedupe alone.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b4e7f18a2c6d'
down_revision = 'c4d8f21a9e05'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'saved_audiences',
        sa.Column('audience_type', sa.String(length=10), nullable=False, server_default='dynamic'),
    )
    op.alter_column('saved_audiences', 'criteria', existing_type=sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    op.create_check_constraint(
        'ck_saved_audiences_audience_type',
        'saved_audiences',
        "audience_type IN ('dynamic', 'fixed')",
    )
    op.create_check_constraint(
        'ck_saved_audiences_criteria_matches_type',
        'saved_audiences',
        "(audience_type = 'dynamic' AND criteria IS NOT NULL) OR "
        "(audience_type = 'fixed' AND criteria IS NULL)",
    )

    op.create_table(
        'saved_audience_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('saved_audience_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['saved_audience_id'], ['saved_audiences.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('saved_audience_id', 'user_id', name='uq_saved_audience_member'),
    )
    op.create_index(
        op.f('ix_saved_audience_members_saved_audience_id'),
        'saved_audience_members', ['saved_audience_id'], unique=False,
    )
    op.create_index(
        op.f('ix_saved_audience_members_user_id'),
        'saved_audience_members', ['user_id'], unique=False,
    )


def downgrade():
    op.drop_index(op.f('ix_saved_audience_members_user_id'), table_name='saved_audience_members')
    op.drop_index(op.f('ix_saved_audience_members_saved_audience_id'), table_name='saved_audience_members')
    op.drop_table('saved_audience_members')

    op.drop_constraint('ck_saved_audiences_criteria_matches_type', 'saved_audiences', type_='check')
    op.drop_constraint('ck_saved_audiences_audience_type', 'saved_audiences', type_='check')
    op.alter_column('saved_audiences', 'criteria', existing_type=sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=False)
    op.drop_column('saved_audiences', 'audience_type')
