"""add user_notifications table

Revision ID: c0258816b77b
Revises: 5398df4940c9
Create Date: 2026-04-05 13:32:20.191414

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c0258816b77b'
down_revision = '5398df4940c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_notifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(255)),
        sa.Column('body', sa.Text()),
        sa.Column('data', sa.JSON()),
        sa.Column('is_read', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

def downgrade():
    op.drop_table('user_notifications')
    # ### end Alembic commands ###
