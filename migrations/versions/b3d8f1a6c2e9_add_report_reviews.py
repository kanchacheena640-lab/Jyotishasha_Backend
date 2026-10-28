"""F10-P15: verified-purchaser report reviews. Additive only. NOT applied to production.

Creates one new table, report_reviews. No existing table, column or row is
altered; downgrade drops only this table (and its indexes/constraints).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3d8f1a6c2e9'
down_revision = 'f18b2c7d903a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'report_reviews',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product', sa.String(100), nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('display_name', sa.String(40), nullable=False),
        sa.Column('language', sa.String(10), nullable=False, server_default='en'),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('auto_flags', sa.String(200), nullable=True),
        sa.Column('moderation_reason', sa.String(40), nullable=True),
        sa.Column('moderated_at', sa.DateTime(), nullable=True),
        sa.Column('edit_count', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('order_id', name='uq_report_reviews_order_id'),
        sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_report_reviews_rating_1_5'),
        sa.CheckConstraint("status IN ('PUBLISHED','PENDING','REJECTED')", name='ck_report_reviews_status'),
        schema='public',
    )
    op.create_index('ix_report_reviews_product', 'report_reviews', ['product'], schema='public')
    op.create_index('ix_report_reviews_status', 'report_reviews', ['status'], schema='public')
    op.create_index('ix_report_reviews_product_status', 'report_reviews', ['product', 'status'], schema='public')


def downgrade():
    op.drop_index('ix_report_reviews_product_status', table_name='report_reviews', schema='public')
    op.drop_index('ix_report_reviews_status', table_name='report_reviews', schema='public')
    op.drop_index('ix_report_reviews_product', table_name='report_reviews', schema='public')
    op.drop_table('report_reviews', schema='public')
