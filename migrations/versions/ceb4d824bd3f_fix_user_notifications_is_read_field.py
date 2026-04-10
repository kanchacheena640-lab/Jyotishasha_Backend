from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'ceb4d824bd3f'
down_revision = 'c0258816b77b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_notifications', schema=None) as batch_op:
        batch_op.alter_column(
            'is_read',
            existing_type=sa.Boolean(),
            nullable=False
        )


def downgrade():
    with op.batch_alter_table('user_notifications', schema=None) as batch_op:
        batch_op.alter_column(
            'is_read',
            existing_type=sa.Boolean(),
            nullable=True
        )