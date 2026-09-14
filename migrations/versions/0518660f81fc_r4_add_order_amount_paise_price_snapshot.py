"""R4 add Order.amount_paise price snapshot

Paid Report Platform v1.0 -- R4 (Payment Finalization & Idempotency
Core), Section A.

Adds ONE additive, nullable column: orders.amount_paise. Confirmed by
direct inspection (R3's own audit, re-confirmed here) that no existing
field or table already provides a durable, immutable, per-order
expected-amount snapshot:
  - `orders` itself has no amount/price column of any kind.
  - modules/models_processed_payments.py::ProcessedPayment has no
    amount column either -- it stores provider/payment_id/reference/
    order_id/response_payload only.
  - config/pricing.py::PRODUCT_PRICES and report_products.price (R2)
    are both keyed by report_slug, not by a specific Order -- neither
    is immutable PER TRANSACTION (a future price change would silently
    change what an in-flight, not-yet-paid legacy Order "should" have
    cost, with nothing pinning the actual price quoted to that specific
    customer at Order-creation time).

INTEGER, paise (never a float) -- Razorpay's own API and this
codebase's existing PaymentRequest.amount field (modules/payments/
payment_models.py, "smallest currency unit (e.g. paise), if known")
already use exactly this representation; storing rupees-as-float here
would introduce a rounding-comparison risk this migration exists to
avoid.

NULLABLE, deliberately: this migration does not and cannot know the
exact historical amount_paise for any pre-existing Order (R1's own
Order rows were never even validated against ReportProduct.price to
begin with, and prices may have changed over time) -- no backfill is
attempted here, matching this phase's own explicit instruction. Every
NEW Order created via OrderService.create_pending_order() (R3, updated
in this same phase to populate this column from
ReportProduct.price * 100) always has amount_paise populated; a NULL
value going forward means only "a legacy, pre-R4 Order," never
"unknown for a new-platform Order."

Once set by create_pending_order(), no other code path in this
migration's own scope writes to this column -- PaymentFinalizationService
(this same phase, modules/payments/payment_finalization_service.py)
only ever READS it for comparison against a payment's captured amount;
it is never reassigned by a payment callback.

Revision ID: 0518660f81fc
Revises: 65bed70e2520
Create Date: (see file mtime)

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0518660f81fc'
down_revision = '65bed70e2520'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orders', sa.Column('amount_paise', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('orders', 'amount_paise')
