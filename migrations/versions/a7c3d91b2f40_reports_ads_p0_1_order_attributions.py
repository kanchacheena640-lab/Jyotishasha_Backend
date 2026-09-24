"""Reports Ads P0.1: add order_attributions (1:1 with orders)

Adds ONE new table, `order_attributions`, holding the sanitized advertising
attribution (utm_source/medium/campaign/content/term, gclid/gbraid/wbraid/
fbclid, landing_page, referrer, a first-touch snapshot, and a non-PII consent
snapshot) captured by the browser and persisted against the internal Order
at order-creation time. See modules/payments/order_attribution.py.

PURELY ADDITIVE / NON-DESTRUCTIVE:
  - creates a new table only; no existing table, column, row or index is
    read, altered or dropped -- every existing Order is untouched and simply
    has no attribution row (which is exactly what "captured nothing / older
    client" means);
  - `order_id` is UNIQUE (one attribution record per Order) with a foreign
    key to orders.id ON DELETE CASCADE, so the row can never outlive or
    block deletion of its Order;
  - guarded with an existence check so re-running it against a database in
    which the table already exists (e.g. one built earlier by create_all())
    is a safe no-op instead of an error.

NO PII: there is no name/email/phone/birth-data column here by design.

DOWNGRADE drops only this table.

Revision ID: a7c3d91b2f40
Revises: e4f5e5596787
Create Date: 2026-09-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3d91b2f40'
down_revision = 'e4f5e5596787'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("order_attributions"):
        return

    op.create_table(
        "order_attributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("attribution_type", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("utm_source", sa.String(length=256), nullable=True),
        sa.Column("utm_medium", sa.String(length=256), nullable=True),
        sa.Column("utm_campaign", sa.String(length=256), nullable=True),
        sa.Column("utm_content", sa.String(length=256), nullable=True),
        sa.Column("utm_term", sa.String(length=256), nullable=True),
        sa.Column("gclid", sa.String(length=256), nullable=True),
        sa.Column("gbraid", sa.String(length=256), nullable=True),
        sa.Column("wbraid", sa.String(length=256), nullable=True),
        sa.Column("fbclid", sa.String(length=256), nullable=True),
        sa.Column("landing_page", sa.String(length=256), nullable=True),
        sa.Column("referrer", sa.String(length=256), nullable=True),
        sa.Column("first_touch", sa.JSON(), nullable=True),
        sa.Column("consent_geo_policy", sa.String(length=20), nullable=True),
        sa.Column("consent_analytics", sa.Boolean(), nullable=True),
        sa.Column("consent_advertising", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_order_attributions_order_id", ondelete="CASCADE"),
        sa.UniqueConstraint("order_id", name="uq_order_attributions_order_id"),
    )


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("order_attributions"):
        op.drop_table("order_attributions")
