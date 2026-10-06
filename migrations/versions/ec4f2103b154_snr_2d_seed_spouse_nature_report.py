"""SNR-2D seed spouse_nature_report ReportProduct row

Spouse Nature Report (rep_026) -- the 26th original (Main) report.

Adds exactly ONE row to `report_products` (table from R1; the 25 original
rows from R2 and the 63 focused rows from P0.3 are untouched). R2's own
seed migration is NOT edited: it is already applied wherever this table
exists, so a new product needs its own additive revision.

Values mirror config/pricing.py::PRODUCT_PRICES and the other Rs51 Main
Reports seeded by R2:
  report_slug        "spouse_nature_report" (canonical slug, no alias)
  name               "Spouse Nature Report"
  price / currency   51 / "INR"
  active             True (same as every original Main Report)
  generator          "standard_v1" -- tasks.py's spouse branch builds the
                     deterministic spouse_evidence_v1 payload before the
                     shared report AI client is called
  prompt_template_id "spouse_nature_report" -> prompts/spouse_nature_report_{en,hi}.txt
  model / required_input_schema  NULL (R2's own lock)

IDEMPOTENCY: ON CONFLICT (report_slug) DO NOTHING, the same idiom R2 and
P0.3 use -- re-running never raises and never overwrites a later manual
edit (e.g. an operator deactivating the product).

DOWNGRADE: deletes ONLY this one report_slug.

Revision ID: ec4f2103b154
Revises: a7c3d91b2f40
Create Date: 2026-10-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


# revision identifiers, used by Alembic.
revision = 'ec4f2103b154'
down_revision = 'a7c3d91b2f40'
branch_labels = None
depends_on = None


_SPOUSE_NATURE_PRODUCT = ("spouse_nature_report", "Spouse Nature Report", 51)


def _report_products_table():
    return sa.table(
        "report_products",
        sa.column("report_slug", sa.String),
        sa.column("name", sa.String),
        sa.column("price", sa.Integer),
        sa.column("currency", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("generator", sa.String),
        sa.column("prompt_template_id", sa.String),
    )


def upgrade():
    slug, name, price = _SPOUSE_NATURE_PRODUCT
    stmt = pg_insert(_report_products_table()).values([{
        "report_slug": slug, "name": name, "price": price, "currency": "INR",
        "active": True, "generator": "standard_v1", "prompt_template_id": slug,
    }]).on_conflict_do_nothing(index_elements=["report_slug"])
    op.get_bind().execute(stmt)


def downgrade():
    table = _report_products_table()
    op.get_bind().execute(
        table.delete().where(table.c.report_slug == _SPOUSE_NATURE_PRODUCT[0])
    )
