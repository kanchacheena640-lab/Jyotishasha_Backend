"""widen processed_payments.payment_id/reference to fit Google Play purchase tokens

Revision ID: 9f4d2a7e1c6b
Revises: 7b3f1c9a4d5e
Create Date: 2026-08-19

Root-cause fix for a silent HTTP 500 in POST /api/reports/google/confirm
(and any other GOOGLE_PLAY payment routed through PaymentService.
process_payment()): ProcessedPayment.payment_id/.reference were sized
at VARCHAR(120), a bound copied from the Razorpay payment_id example in
this table's own original docstring/comment -- Razorpay identifiers are
short. A real Google Play purchase_token is commonly 150-190+
characters. Inserting one raised psycopg2.errors.StringDataRightTruncation
(SQLAlchemy DataError) -- a DIFFERENT exception class from the
IntegrityError PaymentService._try_claim() already handles for its own,
unrelated purpose (a genuine concurrent-claim race) -- so it was never
caught there, and propagated silently past every log_payment_event()
call in process_payment() to the caller's generic except-Exception-500,
with zero trace in the logs.

Widened to VARCHAR(255), matching every other Google Play purchase-token
column already in this codebase (SubscriptionPurchaseMapping.
purchase_token, CurrentEntitlement.purchase_token, SubscriptionEvent.
purchase_token -- all String(255)), not a new convention.

Purely additive -- VARCHAR widening never touches existing row data or
requires a table rewrite in Postgres.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9f4d2a7e1c6b'
down_revision = '7b3f1c9a4d5e'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'processed_payments', 'payment_id',
        existing_type=sa.String(length=120),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.alter_column(
        'processed_payments', 'reference',
        existing_type=sa.String(length=120),
        type_=sa.String(length=255),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'processed_payments', 'reference',
        existing_type=sa.String(length=255),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
    op.alter_column(
        'processed_payments', 'payment_id',
        existing_type=sa.String(length=255),
        type_=sa.String(length=120),
        existing_nullable=False,
    )
