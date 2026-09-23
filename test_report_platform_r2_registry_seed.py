"""
test_report_platform_r2_registry_seed.py
-------------------------------------------------
Paid Report Platform v1.0 -- R2 (Product Registry Seed & Validation).

Proves migration 65bed70e2520 seeds `report_products` to exactly and
only match the real, existing purchasable catalog -- no invented slug,
price, generator, or prompt id. Every expected value below is derived
from the SAME sources the migration itself documents deriving from
(config/pricing.py::PRODUCT_PRICES, jyotishasha-frontend/app/data/
reportsData.ts, modules/love/love_report_router.py, prompts/*.txt) --
never re-typed independently, so a genuine drift in either the
migration or this test's own expectations cannot silently agree with
itself.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No application code (routes, PaymentService,
OrderService, tasks.py) is touched or exercised here.
"""

import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from config.pricing import PRODUCT_PRICES  # noqa: E402
from modules.payments.report_product_registry import ReportProduct  # noqa: E402

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


LOVE_PREMIUM_SLUG = "relationship_future_report"


def run_flask_db(*args):
    result = subprocess.run(
        [sys.executable, "-m", "flask", "db", *args],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=os.environ.copy(),
        capture_output=True, text=True,
    )
    return result


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        # ==============================================================
        print("\n=== 1/2: exactly one row per PRODUCT_PRICES entry, no unexpected extras ===")
        # ==============================================================
        seeded = {p.report_slug: p for p in ReportProduct.query.all()}
        # P0.3 -- report_products now also carries 63 focused-report rows from a
        # separate, later, additive migration this file does not own (generator
        # in {focused_v1, focused_dual_v1}). This file's own assertions stay
        # scoped to the 25 rows R2 itself is responsible for -- whether some
        # OTHER, later migration also added disjoint rows to the same shared
        # table is out of scope here and covered by that migration's own test.
        r2_seeded = {slug: p for slug, p in seeded.items() if p.generator not in ("focused_v1", "focused_dual_v1")}
        check("1: PRODUCT_PRICES has exactly 25 entries (sanity, not assumed)", len(PRODUCT_PRICES) == 25)
        check("1: report_products has exactly 25 non-focused (R2-owned) rows", len(r2_seeded) == 25)
        check("1: every PRODUCT_PRICES slug has exactly one report_products row", set(PRODUCT_PRICES.keys()) == set(r2_seeded.keys()))
        check("2: no non-focused report_products row exists outside PRODUCT_PRICES's own slugs", set(r2_seeded.keys()) - set(PRODUCT_PRICES.keys()) == set())

        # ==============================================================
        print("\n=== 3: price matches PRODUCT_PRICES exactly, for every product ===")
        # ==============================================================
        mismatches = [slug for slug, price in PRODUCT_PRICES.items() if seeded[slug].price != price]
        check("3: every seeded price matches PRODUCT_PRICES exactly", mismatches == [])

        # ==============================================================
        print("\n=== 4/5/6: active / currency / model for every product ===")
        # ==============================================================
        check("4: every R2-owned seeded product is active", all(p.active is True for p in r2_seeded.values()))
        check("5: currency is INR for every R2-owned seeded product", all(p.currency == "INR" for p in r2_seeded.values()))
        check("6: model is NULL for every R2-owned seeded product (locked -- Luna selection untouched)", all(p.model is None for p in r2_seeded.values()))

        # ==============================================================
        print("\n=== 7: generator mapping matches modules/love/love_report_router.py exactly ===")
        # ==============================================================
        check(
            "7: relationship_future_report -> love_premium_v1",
            seeded[LOVE_PREMIUM_SLUG].generator == "love_premium_v1",
        )
        non_love_generators = {slug: p.generator for slug, p in r2_seeded.items() if slug != LOVE_PREMIUM_SLUG}
        check(
            "7: every OTHER R2-owned product -> standard_v1 (matches route_report_generation()'s own fallback)",
            all(g == "standard_v1" for g in non_love_generators.values()),
        )

        # ==============================================================
        print("\n=== 8: prompt_template_id matches the real prompts/{slug}_{lang}.txt convention ===")
        # ==============================================================
        prompts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
        prompt_mismatches = []
        for slug, product in r2_seeded.items():
            if product.prompt_template_id != slug:
                prompt_mismatches.append((slug, "prompt_template_id != report_slug"))
                continue
            expected_file = os.path.join(prompts_dir, f"{slug}_en.txt")
            if not os.path.isfile(expected_file):
                prompt_mismatches.append((slug, f"missing {expected_file}"))
        check("8: prompt_template_id == report_slug, and prompts/{slug}_en.txt exists, for every product", prompt_mismatches == [])
        if prompt_mismatches:
            print("   mismatches:", prompt_mismatches)

        # ==============================================================
        print("\n=== 9: relationship_future_report tested separately, since it is genuinely special ===")
        # ==============================================================
        love = seeded[LOVE_PREMIUM_SLUG]
        check("9: relationship_future_report price is 199, not the standard 51", love.price == 199)
        check("9: relationship_future_report delivery_type still EMAIL_PDF (no delivery-type divergence found)", love.delivery_type == "EMAIL_PDF")
        # required_input_schema is deliberately left NULL even for this
        # product -- see the migration's own docstring for why a proven
        # partner-payload requirement was reported, not invented into a
        # schema shape. This test documents that as a CURRENT fact, not
        # an endorsement -- it must be revisited once required_input_
        # schema has a real reader/format.
        check("9: relationship_future_report required_input_schema is still NULL (reported, not yet encoded -- see migration docstring)", love.required_input_schema is None)

    # ==================================================================
    print("\n=== 10/11: downgrade removes ONLY R2 seed rows; re-upgrade restores them ===")
    # ==================================================================
    # Explicitly targets R2's OWN down_revision (R1's head) rather than
    # a bare one-step `downgrade`, so this test keeps testing exactly
    # R2's round-trip even once a future R3 is chained on top of it --
    # same robustness fix applied to test_report_platform_r1_schema.py.
    R2_DOWN_REVISION = "7064abce6f23"
    down = run_flask_db("downgrade", R2_DOWN_REVISION)
    check("10: flask db downgrade to R2's own down_revision succeeded", down.returncode == 0)
    if down.returncode != 0:
        print(down.stdout[-2000:], down.stderr[-2000:])

    with app.app_context():
        remaining = ReportProduct.query.count()
        check("10: report_products table still exists and is now empty (R2 downgrade removed exactly its own rows)", remaining == 0)
        table_exists = db.session.execute(
            text("SELECT to_regclass('report_products')")
        ).scalar()
        check("10: report_products TABLE itself was NOT dropped by the R2 downgrade", table_exists is not None)

    up = run_flask_db("upgrade")
    check("11: flask db upgrade (re-apply R2) succeeded", up.returncode == 0)
    if up.returncode != 0:
        print(up.stdout[-2000:], up.stderr[-2000:])

    with app.app_context():
        # A bare `flask db upgrade` re-applies every migration up to the
        # CURRENT head, not just R2 -- P0.3's own 63-row migration (if
        # present in this chain) re-applies here too. Scope this
        # assertion to R2's own 25 rows, exactly like checks 1/2/4-8 above.
        restored_all = {p.report_slug: p for p in ReportProduct.query.all()}
        restored = {slug: p for slug, p in restored_all.items() if p.generator not in ("focused_v1", "focused_dual_v1")}
        check("11: re-upgrade restores exactly R2's own 25 rows", set(restored.keys()) == set(PRODUCT_PRICES.keys()))
        check("11: re-upgrade restores correct prices", all(restored[slug].price == price for slug, price in PRODUCT_PRICES.items()))

        cur = run_flask_db("current")
        # Asserts "at or past R2," never a hardcoded specific head --
        # remains correct once a future R3 is chained on top.
        check("11: flask db current is no longer R2's own down_revision", R2_DOWN_REVISION not in (cur.stdout or "")
              and cur.returncode == 0)

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
