"""add ask now intent history

Revision ID: fc796ea78183
Revises: 28994a85b1b9
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fc796ea78183'
down_revision = '28994a85b1b9'
branch_labels = None
depends_on = None


def upgrade():
    # Purely additive: new table only, no existing table touched. See
    # modules/models_ask_now_intent_history.py for the full design
    # rationale (per-question history, not a per-user overwritten
    # column; user_id = users.id, no FK constraint, matching this
    # codebase's own free_daily_questions/chat_packs convention).
    # Category Length Alignment fix: concern_category is String(100),
    # matching ask_now_concern_categories.name's own VARCHAR(100) exactly
    # (migration 0e2036a0b4b7) -- both migrations were still uncommitted
    # when this was corrected, so no separate ALTER migration was needed;
    # this file's own original String(50) is fixed in place here.
    op.create_table(
        'ask_now_intent_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('concern_category', sa.String(length=100), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ask_now_intent_history', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_ask_now_intent_history_user_id'), ['user_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_ask_now_intent_history_created_at'), ['created_at'], unique=False
        )


def downgrade():
    with op.batch_alter_table('ask_now_intent_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ask_now_intent_history_created_at'))
        batch_op.drop_index(batch_op.f('ix_ask_now_intent_history_user_id'))

    op.drop_table('ask_now_intent_history')
