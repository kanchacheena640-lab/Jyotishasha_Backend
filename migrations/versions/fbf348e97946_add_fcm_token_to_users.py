"""
Add fcm_token to users

Revision ID: fbf348e97946
Revises: a4fe16131d4c
Create Date: 2025-12-12 13:51:45.030097
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fbf348e97946'
down_revision = 'a4fe16131d4c'
branch_labels = None
depends_on = None


def upgrade():
    """ONLY add fcm_token to users — nothing else."""

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fcm_token', sa.String(length=500), nullable=True))

    # NOTE:
    # All Strapi and unrelated garbage tables intentionally NOT touched.
    # Clean migration: Only minimal change applied.


def downgrade():
    """Reverse only the fcm_token addition."""

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('fcm_token')
