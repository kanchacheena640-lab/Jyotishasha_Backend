"""PH27 seed personalized_horoscope_2027 ReportProduct row

Personalized Horoscope 2027 (rep_027): a one-time standard report.
Adds exactly ONE row to `report_products`; every existing row is untouched.
Same additive pattern as SNR-2D (ec4f2103b154):
  report_slug        "personalized_horoscope_2027"
  name               "Personalized Horoscope 2027"
  price / currency   99 / "INR" -- the actual Razorpay and Google Play charge
                     (Play product reports99, the existing standard tier).
                     The website's crossed-out reference price is display-only
                     and never stored or charged.
  active             True
  generator          "standard_v1" -- tasks.py's horoscope 2027 branch builds
                     the deterministic evidence (natal chart + 2027 transit
                     master) before the shared report AI client is called
  prompt_template_id "personalized_horoscope_2027" -> prompts/personalized_horoscope_2027_{en,hi}.txt
  model / required_input_schema  NULL (R2's own lock)

Runs after c5e1d7a9b2f4 (standard reports Rs51 -> Rs99), so that migration's
25-standard-row guard sees exactly the rows it expects in both directions.

IDEMPOTENCY: ON CONFLICT (report_slug) DO NOTHING -- re-running never raises
and never overwrites a later manual edit (e.g. deactivating the product).
DOWNGRADE: deletes ONLY this one report_slug.

Revision ID: d7a3c9e1f2b4
Revises: c5e1d7a9b2f4
Create Date: 2026-11-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


revision = 'd7a3c9e1f2b4'
down_revision = 'c5e1d7a9b2f4'
branch_labels = None
depends_on = None


_PERSONALIZED_HOROSCOPE_2027_PRODUCT = ("personalized_horoscope_2027", "Personalized Horoscope 2027", 99)


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
    slug, name, price = _PERSONALIZED_HOROSCOPE_2027_PRODUCT
    stmt = pg_insert(_report_products_table()).values([{
        "report_slug": slug, "name": name, "price": price, "currency": "INR",
        "active": True, "generator": "standard_v1", "prompt_template_id": slug,
    }]).on_conflict_do_nothing(index_elements=["report_slug"])
    op.get_bind().execute(stmt)


def downgrade():
    table = _report_products_table()
    op.get_bind().execute(
        table.delete().where(table.c.report_slug == _PERSONALIZED_HOROSCOPE_2027_PRODUCT[0])
    )
