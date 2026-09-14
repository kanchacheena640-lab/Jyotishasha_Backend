"""R1 add report_products table and Order payment fields

Paid Report Platform v1.0 -- R1 (Schema Foundation ONLY).

Purely additive: a new `report_products` table, and three new nullable-
or-defaulted columns on the existing `orders` table. No existing
column is renamed, retyped, or dropped. No application code path
reads or writes any of these new columns yet (that begins at R3+) --
this migration changes zero runtime behavior.

HISTORICAL DATA SAFETY (the one non-trivial decision in this
migration):

`orders.payment_status` is NOT NULL with server_default='CREATED'.
Adding it naively would make Postgres backfill EVERY existing row --
including years of already-completed, already-paid orders -- with
'CREATED', which would misrepresent them as brand-new unpaid orders to
any future reconciliation/query logic (R9). That must not happen.

Verified via direct code inspection (not assumed) that the ONLY
production code path that has ever constructed an `Order` row is
modules/payments/order_service.py::OrderService.create_paid_report_order(),
which unconditionally passes status="PAID" at construction time -- the
model's own status column default ("PENDING") has never actually been
exercised by any real caller (grepped every `Order(` construction site
in the codebase; the only other hits are the unrelated AskNowOrder/
SubscriptionOrder models and test fixtures). Every historical Order
row was therefore created only AFTER a real, successfully verified
payment. Production `orders` data itself was not directly queried for
this migration (no production DB access in this task) -- this
conclusion rests on the code-path proof above, which is unconditional
(no caller-supplied `status` override exists anywhere), not on a
production data sample.

Backfill rule applied below, immediately after adding the column with
its default: `payment_status = 'PAID' WHERE status = 'PAID'`, else left
at the server_default 'CREATED'. This is deliberately conditioned on
the row's own `status` value (never an unconditional blanket UPDATE),
so that IF a historical row somehow does not carry status='PAID' (not
proven to exist, but not disprovable without production access either),
it is left as 'CREATED' rather than being incorrectly force-labeled
'PAID' -- the safer direction for a value neither confirmed nor
contradicted by code. No row is left NULL either way (NOT NULL
default already covers that).

`orders.razorpay_order_id` / `razorpay_payment_id` are left NULL for
every historical row -- genuinely correct, since no existing row has
ever recorded either value (confirmed: `orders` carries no such column
today, and modules/models_processed_payments.py::ProcessedPayment is
the only existing place a razorpay_payment_id is stored, with no FK/
join back to `orders` at all). No backfill is attempted or possible
for these two columns from within this migration; R9's own legacy-
reconciliation task is the intended (separate, human-reviewed) path
for connecting a historical Order to its original Razorpay identifiers
where that is still discoverable.

Revision ID: 7064abce6f23
Revises: 6d2ed1d602c1
Create Date: 2026-09-14 00:53:53.604372

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7064abce6f23'
down_revision = '6d2ed1d602c1'
branch_labels = None
depends_on = None


def upgrade():
    # -----------------------------------------------------------------
    # A. report_products -- the Report/Product Registry (R1: schema
    # only, NOT seeded here -- seeding from config/pricing.py is R2).
    # `model` is deliberately nullable with no server_default: this
    # column must never influence which AI model tasks.py/
    # love_premium_task.py actually call (both remain fully hardcoded,
    # untouched, still selecting Luna exactly as today) until an
    # explicit future phase deliberately wires it up. A NULL model here
    # must always mean "use whatever the generator's own code already
    # uses," never "no model configured."
    # -----------------------------------------------------------------
    op.create_table(
        'report_products',
        sa.Column('report_slug', sa.String(length=100), primary_key=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='INR'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('generator', sa.String(length=50), nullable=False),
        sa.Column('prompt_template_id', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=50), nullable=True),
        sa.Column('delivery_type', sa.String(length=30), nullable=False, server_default='EMAIL_PDF'),
        sa.Column('required_input_schema', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False, server_default=sa.func.now()),
    )

    # -----------------------------------------------------------------
    # B. orders -- additive payment-tracking columns only.
    # -----------------------------------------------------------------
    op.add_column('orders', sa.Column('razorpay_order_id', sa.String(length=64), nullable=True))
    op.add_column('orders', sa.Column('razorpay_payment_id', sa.String(length=64), nullable=True))
    op.add_column(
        'orders',
        sa.Column('payment_status', sa.String(length=20), nullable=False, server_default='CREATED'),
    )

    op.create_index(
        'uq_orders_razorpay_order_id', 'orders', ['razorpay_order_id'], unique=True,
    )
    op.create_index(
        'ix_orders_razorpay_payment_id', 'orders', ['razorpay_payment_id'], unique=False,
    )

    # Historical-data safety backfill -- see module docstring above.
    # Runs AFTER the column exists (with every row already defaulted to
    # 'CREATED' by the ADD COLUMN itself), correcting only the rows
    # whose own `status` already proves a completed payment.
    op.execute("UPDATE orders SET payment_status = 'PAID' WHERE status = 'PAID'")


def downgrade():
    op.drop_index('ix_orders_razorpay_payment_id', table_name='orders')
    op.drop_index('uq_orders_razorpay_order_id', table_name='orders')
    op.drop_column('orders', 'payment_status')
    op.drop_column('orders', 'razorpay_payment_id')
    op.drop_column('orders', 'razorpay_order_id')

    op.drop_table('report_products')
