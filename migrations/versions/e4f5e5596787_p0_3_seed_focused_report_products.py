"""P0.3 seed 63 focused ReportProduct rows (inactive)

Focused Reports ₹51 Payment Bridge -- P0.3 (Registry Migration).

Populates `report_products` (existing table, R1/R2 -- unchanged here)
with the 63 focused-report products, additive to the 25 rows R2 already
seeded. Every value below was DERIVED, never invented, from direct
inspection of:

  - modules/intents/question_catalog.py::QUESTIONS -- the ONE
    authoritative catalog. 63 entries confirmed (54 person_mode="single",
    9 person_mode="dual"); each `question_key` becomes this migration's
    `report_slug`, matching the SAME identity the focused dispatcher
    (modules/focused_reports/dispatcher.py::resolve_focused_handler)
    already resolves a report by -- no new identity scheme introduced.
  - modules/focused_reports/prompt_specs.py::PROMPT_SPECS -- `title.en`
    used verbatim as `name` below (none derived/guessed from a slug),
    the same source `pdf_adapter.py` already uses for the PDF's own
    product title.

`generator`: "focused_v1" for every SELF (single) product, "focused_dual_v1"
for every DUAL (relationship-family) product -- two values, not one,
because OrderService.create_pending_order() (P0.3) selects its required-
field/coordinate-validation shape purely from this column, exactly as it
already does for "love_premium_v1" vs. every other value; a single shared
generator could not signal which of the two shapes 54 SELF vs. 9 DUAL
products need. Both values route to the SAME dispatch entry point
(modules/payments/report_generation_dispatcher.py) -- no new Celery task
is introduced, mirroring exactly how "standard_v1" and "love_premium_v1"
already share one entry point today.

`price` = 51, `currency` = "INR" for all 63 -- the one price every
focused report has (modules/intents/intent_registry.py::
INTENT_REPORT_PRICE_RUPEES = 51, enforced there by IntentContract's own
__post_init__ for every one of the 14 core intents).

`active` = False for ALL 63, explicitly (overriding the column's own
`default=True`) -- P0.2's approved design, amended by this task's own
rollout instruction: registering these products must not make ANY of
them purchasable. Activation (including major_kundali_obstacles /
major_kundali_strengths) is an explicit, separate, later action, gated
on frontend readiness and production preflight approval -- never a side
effect of this migration.

`model` is NULL for every row, matching R2's own explicit lock -- Luna
model selection remains entirely in app_config.py::PAID_REPORT_AI_MODEL
/ modules/payments/report_ai_client.py; nothing here reads this column.

`prompt_template_id` = report_slug for every row, matching R2's own
convention -- but reported explicitly (not assumed) that focused reports
do NOT use the `.txt`-file + `.format()` mechanism prompt_template_id
named for the 25 standard products (tasks.py's `prompts/{slug}_{lang}.txt`
convention). Focused prompts are assembled dynamically by
modules/focused_reports/prompt_assembler.py from PROMPT_SPECS; nothing
reads this column for a focused product today. Set only to satisfy the
column's NOT NULL constraint with a stable, non-misleading identifier
(the product's own slug), exactly as R2 already did for love_premium_v1
(which also never used the .txt-file convention for its own generation).

`required_input_schema` is NULL for every row, matching R2's own lock --
no consuming code anywhere reads this column yet.

IDEMPOTENCY: every INSERT uses ON CONFLICT (report_slug) DO NOTHING, the
SAME idiom R2 already uses -- re-running upgrade() after a manual partial
apply never raises a duplicate-key error and never overwrites a row a
later, human-made edit may have changed (in particular: never silently
re-activates a product an operator has since flipped).

NOT TOUCHED: the 25 existing rows R2 seeded (matched on report_slug --
disjoint from all 63 focused question_keys, confirmed: no focused
question_key collides with any of the 25 existing report_slug values or
with "relationship_future_report"). No existing row's generator, price,
active flag, or any other column is read, written, or otherwise affected
by this migration.

DOWNGRADE: deletes ONLY the explicit 63 report_slug values this
migration itself inserts -- never a blanket `DELETE FROM report_products`,
never touching the 25 pre-existing rows. The table itself (created in R1)
is never dropped here.

Revision ID: e4f5e5596787
Revises: 0518660f81fc
Create Date: 2026-09-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert


# revision identifiers, used by Alembic.
revision = 'e4f5e5596787'
down_revision = '0518660f81fc'
branch_labels = None
depends_on = None


# question_key -> (title.en, price) -- both from modules/focused_reports/
# prompt_specs.py::PROMPT_SPECS, cross-checked against modules/intents/
# question_catalog.py::QUESTIONS for person_mode. 54 SELF (single).
_FOCUSED_SELF_PRODUCTS = [
    ("promotion_timing", "Promotion Report", 51),
    ("career_improvement_timing", "Career Improvement", 51),
    ("career_growth_delay_reason", "Career Growth Delays", 51),
    ("next_strong_career_period", "Next Career Opportunity", 51),
    ("salary_growth_timing", "Salary Growth", 51),
    ("work_recognition_timing", "Work Recognition", 51),
    ("best_career_years", "Career Growth Years", 51),
    ("job_change_now", "Job Change Timing", 51),
    ("new_job_timing", "New Job Opportunities", 51),
    ("best_period_to_switch", "Job Switch Windows", 51),
    ("job_search_start_timing", "Job Search Timing", 51),
    ("job_gap_easing", "Employment Gap", 51),
    ("financial_improvement_timing", "Financial Improvement", 51),
    ("income_increase_timing", "Income Growth", 51),
    ("money_growth_periods", "Financial Growth Windows", 51),
    ("financial_pressure_easing", "Financial Pressure", 51),
    ("debt_pressure_easing", "Debt Pressure", 51),
    ("business_start_timing", "Starting a Business", 51),
    ("business_growth_timing", "Business Growth", 51),
    ("best_business_periods", "Business Opportunity Windows", 51),
    ("business_expansion_timing", "Business Expansion", 51),
    ("business_slowdown_easing", "Business Slowdown", 51),
    ("new_venture_partnership_timing", "New Venture or Partnership", 51),
    ("strongest_marriage_periods", "Marriage Windows", 51),
    ("marriage_chances_timing", "Marriage Prospects", 51),
    ("marriage_delay_reason", "Marriage Delays", 51),
    ("marriage_delay_easing", "Easing Marriage Delays", 51),
    ("marriage_talks_current_period", "Marriage Discussions", 51),
    ("relationship_to_marriage_window", "Relationship Towards Marriage", 51),
    ("going_abroad_timing", "Going Abroad", 51),
    ("foreign_work_timing", "Working Abroad", 51),
    ("study_abroad", "Study Abroad", 51),
    ("foreign_settlement_timing", "Settling Abroad", 51),
    ("relocation_timing", "Relocation Timing", 51),
    ("foreign_plans_delay_reason", "Overseas Plans Delayed", 51),
    ("study_strong_period", "Study Support", 51),
    ("exam_preparation_period", "Exam Preparation", 51),
    ("higher_education_timing", "Higher Education", 51),
    ("study_progress_improvement", "Study Progress", 51),
    ("property_purchase_timing", "Property Purchase Timing", 51),
    ("property_current_period", "Property Readiness Now", 51),
    ("property_strongest_period", "Property Opportunity Windows", 51),
    ("property_delay_reason", "Property Purchase Delays", 51),
    ("own_home_timing", "A Home of Your Own", 51),
    ("major_turning_points", "Major Life Phases", 51),
    ("next_life_change_period", "Next Phase Change", 51),
    ("important_years_ahead", "Important Years Ahead", 51),
    ("current_phase_meaning", "Understanding Your Current Phase", 51),
    ("areas_needing_attention", "Areas Needing Attention", 51),
    ("natural_strengths", "Natural Strengths", 51),
    ("life_direction", "Life Direction", 51),
    ("focus_to_use_strengths", "Putting Strengths to Work", 51),
    ("major_kundali_obstacles", "Major Obstacles in Your Kundali", 51),
    ("major_kundali_strengths", "Major Strengths in Your Kundali", 51),
]

# 9 DUAL (relationship-family) products.
_FOCUSED_DUAL_PRODUCTS = [
    ("relationship_lead_to_marriage", "Relationship and Marriage", 51),
    ("long_term_compatibility", "Long-Term Compatibility", 51),
    ("kundali_match_for_marriage", "Kundali Match for Marriage", 51),
    ("right_time_to_consider_marriage", "Considering Marriage Together", 51),
    ("relationship_strengths_risks", "Relationship Strengths and Challenges", 51),
    ("conflict_areas", "Understanding Conflict", 51),
    ("emotional_communication_fit", "Emotional and Communication Fit", 51),
    ("strengthen_relationship", "Strengthening Your Relationship", 51),
    ("relationship_care_periods", "Relationship Care Periods", 51),
]

_ALL_FOCUSED_SLUGS = [slug for slug, _, _ in _FOCUSED_SELF_PRODUCTS] + \
    [slug for slug, _, _ in _FOCUSED_DUAL_PRODUCTS]


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
    table = _report_products_table()
    rows = [
        {
            "report_slug": slug, "name": name, "price": price, "currency": "INR",
            "active": False, "generator": "focused_v1", "prompt_template_id": slug,
        }
        for slug, name, price in _FOCUSED_SELF_PRODUCTS
    ] + [
        {
            "report_slug": slug, "name": name, "price": price, "currency": "INR",
            "active": False, "generator": "focused_dual_v1", "prompt_template_id": slug,
        }
        for slug, name, price in _FOCUSED_DUAL_PRODUCTS
    ]

    stmt = pg_insert(table).values(rows).on_conflict_do_nothing(index_elements=["report_slug"])
    op.get_bind().execute(stmt)


def downgrade():
    table = _report_products_table()
    op.get_bind().execute(
        table.delete().where(table.c.report_slug.in_(_ALL_FOCUSED_SLUGS))
    )
