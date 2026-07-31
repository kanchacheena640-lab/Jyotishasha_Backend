"""add ai_reports table

Revision ID: a1c4e9f7d2b3
Revises: d3a9f1b2c7e4
Create Date: 2026-07-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1c4e9f7d2b3'
down_revision = 'd3a9f1b2c7e4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('app_users.id'), nullable=False),
        sa.Column('segment', sa.String(length=20), nullable=False),
        sa.Column('report_type', sa.String(length=30), nullable=False),
        sa.Column('language', sa.String(length=10), nullable=False, server_default='en'),
        sa.Column('content_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('model_version', sa.String(length=50), nullable=True),
        sa.Column('prompt_version', sa.String(length=50), nullable=True),
        sa.Column('generator_version', sa.String(length=50), nullable=True),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            'profile_id', 'segment', 'report_type', 'language',
            name='uq_ai_reports_profile_segment_type_language',
        ),
    )

    # Single-column indexes (kept from Phase 1 -- unaffected by the
    # cache-strategy revision).
    op.create_index('ix_ai_reports_profile_id', 'ai_reports', ['profile_id'])
    op.create_index('ix_ai_reports_segment', 'ai_reports', ['segment'])
    op.create_index('ix_ai_reports_report_type', 'ai_reports', ['report_type'])
    op.create_index('ix_ai_reports_expires_at', 'ai_reports', ['expires_at'])

    # NOTE: no separate composite lookup index -- the UNIQUE constraint
    # above already creates one covering (profile_id, segment,
    # report_type, language), so a duplicate index would be pure waste.


def downgrade():
    op.drop_index('ix_ai_reports_expires_at', table_name='ai_reports')
    op.drop_index('ix_ai_reports_report_type', table_name='ai_reports')
    op.drop_index('ix_ai_reports_segment', table_name='ai_reports')
    op.drop_index('ix_ai_reports_profile_id', table_name='ai_reports')
    op.drop_table('ai_reports')
