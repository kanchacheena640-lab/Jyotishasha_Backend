"""add notification_logs clean"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '241a028dadcd'
down_revision = 'fbf348e97946'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notification_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('slot', sa.String(length=20), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'event_id', 'slot', name='unique_user_event_slot')
    )


def downgrade():
    op.drop_table('notification_logs')