"""add fcm_token

Revision ID: 5398df4940c9
Revises: 15517af13390
Create Date: 2026-03-30 19:28:25.872838

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5398df4940c9'
down_revision = '15517af13390'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('app_users') as batch_op:
        batch_op.add_column(sa.Column('fcm_token', sa.String(length=255), nullable=True))    # ### end Alembic commands ###

def downgrade():
    with op.batch_alter_table('app_users') as batch_op:
        batch_op.drop_column('fcm_token')