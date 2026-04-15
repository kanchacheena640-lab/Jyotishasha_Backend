from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f32c4878fcf0'
down_revision = 'ceb4d824bd3f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_notifications', schema=None) as batch_op:
        batch_op.add_column(sa.Column('data', postgresql.JSON(astext_type=sa.Text()), nullable=True))
        batch_op.add_column(sa.Column('read_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user_notifications', schema=None) as batch_op:
        batch_op.drop_column('read_at')
        batch_op.drop_column('data')