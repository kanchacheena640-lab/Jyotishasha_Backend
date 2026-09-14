"""R2 seed report_products from PRODUCT_PRICES catalog

Paid Report Platform v1.0 -- R2 (Product Registry Seed & Validation).

Populates `report_products` (added, empty, in R1) with the exact
currently-purchasable paid-report catalog. Every value below was
DERIVED, never invented, from direct inspection of:

  - config/pricing.py::PRODUCT_PRICES -- 25 entries, the sole source of
    truth app.py::create_razorpay_order() actually validates a
    `product` slug and price against today.
  - jyotishasha-frontend/app/data/reportsData.ts -- the SAME 25 slugs
    (cross-checked one-for-one) with the SAME prices, and the only
    existing place a human-readable `title.en` is stored for each
    report -- used verbatim as `name` below (none derived/guessed from
    a slug; every product already had a real title).
  - prompts/*.txt -- confirmed one `{report_slug}_en.txt` file exists
    for every one of the 25 slugs, proving prompt_template_id ==
    report_slug is the real, already-used convention (tasks.py's own
    `template_path = f"prompts/{product_slug}_{language}.txt"`), not
    an assumption.
  - modules/love/love_report_router.py::route_report_generation() --
    read directly, not assumed: exactly ONE product
    ("relationship_future_report") is routed to
    generate_love_premium_report() (generator="love_premium_v1"
    below); every other product falls through to the existing
    generate_and_send_report() (generator="standard_v1" below). No
    other special-cased product was found anywhere in that router or
    in tasks.py.

`model` is NULL for every row (per this phase's explicit lock) --
tasks.py/love_premium_task.py continue selecting their own currently-
configured Luna model exactly as today; nothing in R1 or R2 reads this
column.

`required_input_schema` is NULL for every row. Note (reported, not
encoded): jyotishasha-frontend/app/[locale]/love/report/
relationship_future_report/RelationshipFutureReportForm.tsx proves
"relationship_future_report" genuinely requires an additional
`partner` payload (name/dob/tob/pob/lat/lng -- matching the existing,
already-present Order.partner_payload column) beyond the universal
name/email/phone/dob/tob/pob/lat/long set every other product uses.
This migration does not encode that into required_input_schema: no
consuming code anywhere yet defines what shape/format that column is
read as, and inventing one now (rather than deriving it from an
existing, already-used convention) would violate this phase's own
"do not invent" instruction. Left NULL, with this fact reported
explicitly for a later phase to encode once required_input_schema has
a real reader.

IDEMPOTENCY: every INSERT uses ON CONFLICT (report_slug) DO NOTHING,
so re-running this migration's upgrade() (e.g. after a manual partial
apply) never raises a duplicate-key error and never overwrites a row
some later, human-made edit may have changed.

DOWNGRADE: deletes ONLY the 25 report_slug values this migration
itself inserts (an explicit literal list, never a blanket `DELETE FROM
report_products`) -- the table itself (created in R1) is never
dropped here.

Revision ID: 65bed70e2520
Revises: 7064abce6f23
Create Date: 2026-09-14 01:03:34.274882

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


# revision identifiers, used by Alembic.
revision = '65bed70e2520'
down_revision = '7064abce6f23'
branch_labels = None
depends_on = None


# report_slug -> (name, price) -- name from reportsData.ts::title.en,
# price from config/pricing.py::PRODUCT_PRICES. Both sources agree
# exactly on all 25 entries (cross-checked, no discrepancy found).
_STANDARD_PRODUCTS = [
    ("sadhesati_report", "Sadhesati Report", 51),
    ("financial_report", "Financial Report", 51),
    ("love_relationship_report", "Love & Relationship Report", 51),
    ("marriage_report", "Marriage Report", 51),
    ("startup_suggestion_report", "Startup Suggestion Report", 51),
    ("love_marriage_report", "Love Marriage Report", 51),
    ("government_job_report", "Government Job Report", 51),
    ("foreign_travel_report", "Foreign Travel Report", 51),
    ("business_report", "Business Report", 51),
    ("career_report", "Career Report", 51),
    ("gemstone_consultation", "Gemstone Consultation", 51),
    ("children_parenting_report", "Children Parenting Report", 51),
    ("delay_in_marriage_report", "Delay in Marriage Report", 51),
    ("financial_stability_report", "Financial Stability Report", 51),
    ("jupiter_transit_report", "Jupiter Transit Report", 51),
    ("lifestyle_analysis_report", "Lifestyle Analysis Report", 51),
    ("love_disappointment_report", "Love Disappointment Report", 51),
    ("problem_in_marriage_report", "Problem in Marriage Report", 51),
    ("mood_mental_health_report", "Mood & Mental Health Report", 51),
    ("property_report", "Property Report", 51),
    ("saturn_transit_report", "Saturn Transit Report", 51),
    ("second_marriage_report", "Second Marriage Report", 51),
    ("divorce_possibility_report", "Divorce Possibility Report", 51),
    ("legal_disputes_report", "Legal Disputes Report", 51),
]

# The one product confirmed, by direct code read of
# modules/love/love_report_router.py, to route to a different generator.
_LOVE_PREMIUM_PRODUCT = ("relationship_future_report", "Relationship Future Report", 199)

_ALL_SLUGS = [slug for slug, _, _ in _STANDARD_PRODUCTS] + [_LOVE_PREMIUM_PRODUCT[0]]


def _report_products_table():
    return sa.table(
        "report_products",
        sa.column("report_slug", sa.String),
        sa.column("name", sa.String),
        sa.column("price", sa.Integer),
        sa.column("generator", sa.String),
        sa.column("prompt_template_id", sa.String),
    )


def upgrade():
    table = _report_products_table()
    rows = [
        {
            "report_slug": slug, "name": name, "price": price,
            "generator": "standard_v1", "prompt_template_id": slug,
        }
        for slug, name, price in _STANDARD_PRODUCTS
    ]
    slug, name, price = _LOVE_PREMIUM_PRODUCT
    rows.append({
        "report_slug": slug, "name": name, "price": price,
        "generator": "love_premium_v1", "prompt_template_id": slug,
    })

    stmt = pg_insert(table).values(rows).on_conflict_do_nothing(index_elements=["report_slug"])
    op.get_bind().execute(stmt)


def downgrade():
    table = _report_products_table()
    op.get_bind().execute(
        table.delete().where(table.c.report_slug.in_(_ALL_SLUGS))
    )
