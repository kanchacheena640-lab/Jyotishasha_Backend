"""Standard (base) reports: Rs51 -> Rs99 (data only)

Revision ID: c5e1d7a9b2f4
Revises: b3d8f1a6c2e9
Create Date: 2026-10-31

Changes report_products.price for the 25 generator='standard_v1' rows only. Focused reports (focused_v1 /
focused_dual_v1, Rs51) and relationship_future_report (love_premium_v1, Rs199) are untouched and verified so.
Existing orders keep their own Order.amount_paise snapshot, so paid and pending orders are unaffected.
Guarded: refuses unless exactly 25 standard rows exist, each at Rs51 (upgrade) or Rs99 (downgrade).
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e1d7a9b2f4"
down_revision = "b3d8f1a6c2e9"
branch_labels = None
depends_on = None

STANDARD_COUNT = 25


def _switch(old_price: int, new_price: int) -> None:
    conn = op.get_bind()
    count = lambda sql: conn.execute(sa.text(sql)).scalar()
    others_before = conn.execute(sa.text(
        "SELECT report_slug, price FROM report_products WHERE generator <> 'standard_v1' ORDER BY report_slug")).fetchall()
    standard = count("SELECT count(*) FROM report_products WHERE generator = 'standard_v1'")
    at_old = count(f"SELECT count(*) FROM report_products WHERE generator = 'standard_v1' AND price = {old_price}")
    if standard != STANDARD_COUNT or at_old != STANDARD_COUNT:
        raise RuntimeError(f"Refusing price change: expected {STANDARD_COUNT} standard reports at Rs{old_price}, "
                           f"found {standard} standard rows ({at_old} at Rs{old_price}).")
    updated = conn.execute(sa.text(
        f"UPDATE report_products SET price = {new_price} WHERE generator = 'standard_v1' AND price = {old_price}")).rowcount
    others_after = conn.execute(sa.text(
        "SELECT report_slug, price FROM report_products WHERE generator <> 'standard_v1' ORDER BY report_slug")).fetchall()
    if updated != STANDARD_COUNT or others_after != others_before:
        raise RuntimeError(f"Price change verification failed (updated {updated}); transaction rolled back.")


def upgrade():
    _switch(51, 99)


def downgrade():
    _switch(99, 51)
