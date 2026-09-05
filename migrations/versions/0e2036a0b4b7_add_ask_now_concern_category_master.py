"""add ask now concern category master

Revision ID: 0e2036a0b4b7
Revises: fc796ea78183
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = '0e2036a0b4b7'
down_revision = 'fc796ea78183'
branch_labels = None
depends_on = None


# Ask Now Category Architecture v1 -- FINAL PRODUCT DECISION: a small,
# controlled master list (NOT the 36-item granular taxonomy, NOT
# model-invented categories). Seeded once here; from this point on the
# master is managed via modules/services/asknow_category_service.py
# (and, later, an Admin Dashboard) -- never by editing this list again.
INITIAL_CATEGORIES = [
    "Love & Relationship",
    "Breakup",
    "Marriage / Marriage Delay",
    "Marital Conflict / Divorce",
    "Job & Career",
    "Business",
    "Money / Debt",
    "Property",
    "Childbirth / Children",
    "Health & Mental Wellbeing",
    "Education / Foreign Career & Settlement",
    "Spiritual / Dosh / Remedies",
    "Other",
]


def upgrade():
    # Purely additive: new table only, no existing table touched.
    op.create_table(
        'ask_now_concern_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ask_now_concern_categories', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_ask_now_concern_categories_name', ['name']
        )

    # Data seed -- plain sa.table()/Core insert (not the ORM model), the
    # standard Alembic pattern for migration-owned seed data so this
    # migration never depends on the model class's own definition
    # drifting in the future.
    categories_table = sa.table(
        'ask_now_concern_categories',
        sa.column('name', sa.String),
        sa.column('is_active', sa.Boolean),
        sa.column('created_at', sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(
        categories_table,
        [{"name": name, "is_active": True, "created_at": now} for name in INITIAL_CATEGORIES],
    )


def downgrade():
    with op.batch_alter_table('ask_now_concern_categories', schema=None) as batch_op:
        batch_op.drop_constraint('uq_ask_now_concern_categories_name', type_='unique')

    op.drop_table('ask_now_concern_categories')
