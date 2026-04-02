"""add user dasha timeline

Revision ID: 15517af13390
Revises: 241a028dadcd
Create Date: 2026-03-29 23:26:49.728749

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '15517af13390'
down_revision = '241a028dadcd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_dasha_timeline',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('mahadasha', sa.String(length=20), nullable=False),
        sa.Column('antardasha', sa.String(length=20), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True)
    )

def downgrade():
    op.drop_table('user_dasha_timeline')

    
    # ### end Alembic commands ###
