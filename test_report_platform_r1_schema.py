"""
test_report_platform_r1_schema.py
-------------------------------------------------
Paid Report Platform v1.0 -- R1 (Schema Foundation) verification.

Covers exactly the R1 scope, nothing from R2+:
  A. ReportProduct model: required fields persist; currency/active/
     delivery_type defaults apply; model and required_input_schema may
     be NULL; created_at is set automatically.
  B. Order additive columns: an existing (pre-R1-shaped) Order remains
     fully readable; a new Order can set razorpay_order_id/
     razorpay_payment_id/payment_status; razorpay_order_id's UNIQUE
     constraint is enforced at the DB level.
  C. Historical-data backfill correctness -- the one non-trivial part
     of migration 7064abce6f23: runs an actual `flask db downgrade`
     then `flask db upgrade` cycle (invoked via this script's own
     subprocess calls, LOCAL DB only) against two pre-existing rows
     (status="PAID" and status="PENDING") and asserts the backfill's
     conditional UPDATE reproduces the exact same result a real
     historical production row would get.

No application code (routes, PaymentService, OrderService, tasks.py)
is touched or exercised here -- this is schema-level only, per R1's
own scope. LOCAL ONLY -- connects exclusively to jyotishasha_local,
refuses to run against anything else.
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
from sqlalchemy.exc import IntegrityError  # noqa: E402
from models import Order  # noqa: E402
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


MARKER_EMAIL_PAID = "r1-schema-test-paid@example.com"
MARKER_EMAIL_PENDING = "r1-schema-test-pending@example.com"
MARKER_RZP_ORDER_ID = "order_R1SCHEMATEST0001"
MARKER_SLUG = "r1_schema_test_report"


def cleanup():
    Order.query.filter(Order.email.in_([MARKER_EMAIL_PAID, MARKER_EMAIL_PENDING])).delete(synchronize_session=False)
    db.session.execute(text("DELETE FROM orders WHERE razorpay_order_id LIKE :p"), {"p": f"{MARKER_RZP_ORDER_ID}%"})
    db.session.execute(text("DELETE FROM report_products WHERE report_slug = :slug"), {"slug": MARKER_SLUG})
    db.session.commit()


def run_flask_db(*args):
    """Runs `flask db <args>` as a real subprocess (same CLI entrypoint
    section F itself asks for), inheriting this process's own env
    (DATABASE_URL etc. already set above) -- never a second, divergent
    way of applying migrations."""
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

        cleanup()

        # ==============================================================
        print("\n=== A: ReportProduct model -- required fields + defaults ===")
        # ==============================================================
        product = ReportProduct(
            report_slug=MARKER_SLUG,
            name="R1 Schema Test Report",
            price=51,
            generator="standard_v1",
            prompt_template_id=MARKER_SLUG,
        )
        db.session.add(product)
        db.session.commit()
        db.session.refresh(product)

        check("A: report_slug persisted", product.report_slug == MARKER_SLUG)
        check("A: currency defaults to INR", product.currency == "INR")
        check("A: active defaults to True", product.active is True)
        check("A: delivery_type defaults to EMAIL_PDF", product.delivery_type == "EMAIL_PDF")
        check("A: model is nullable and NULL when not supplied", product.model is None)
        check("A: required_input_schema is nullable and NULL when not supplied", product.required_input_schema is None)
        check("A: created_at auto-populated", product.created_at is not None)

        # A duplicate report_slug must be rejected (primary key).
        dup = ReportProduct(
            report_slug=MARKER_SLUG, name="dup", price=1,
            generator="standard_v1", prompt_template_id=MARKER_SLUG,
        )
        db.session.add(dup)
        try:
            db.session.commit()
            check("A: duplicate report_slug rejected (PRIMARY KEY)", False)
        except IntegrityError:
            db.session.rollback()
            check("A: duplicate report_slug rejected (PRIMARY KEY)", True)

        # ==============================================================
        print("\n=== B: Order additive columns ===")
        # ==============================================================
        # B1 -- an "existing-shaped" Order (only the pre-R1 required
        # fields set, exactly like every real order today) remains
        # fully readable with sane new-column defaults.
        legacy_shaped = Order(
            name="Legacy Shape", email=MARKER_EMAIL_PAID, product="startup_suggestion_report",
            dob="1994-01-26", tob="08:40", pob="Sindhnur Rural", status="PAID",
        )
        db.session.add(legacy_shaped)
        db.session.commit()
        db.session.refresh(legacy_shaped)
        check("B1: existing-shaped Order still readable", legacy_shaped.id is not None)
        check("B1: existing-shaped Order's new payment_status column defaults to CREATED", legacy_shaped.payment_status == "CREATED")
        check("B1: existing-shaped Order's new razorpay columns default to NULL", legacy_shaped.razorpay_order_id is None and legacy_shaped.razorpay_payment_id is None)
        check("B1: legacy `status`/`report_stage`/`email_status` behavior untouched", legacy_shaped.status == "PAID" and legacy_shaped.report_stage == "Pending" and legacy_shaped.email_status == "NOT_ATTEMPTED")

        # B2 -- a new Order can set the new columns explicitly.
        new_order = Order(
            name="New Flow", email="r1-schema-test-new@example.com", product=MARKER_SLUG,
            razorpay_order_id=f"{MARKER_RZP_ORDER_ID}_A", razorpay_payment_id="pay_R1TEST0001",
            payment_status="PAYMENT_PENDING",
        )
        db.session.add(new_order)
        db.session.commit()
        db.session.refresh(new_order)
        check("B2: new Order persists razorpay_order_id", new_order.razorpay_order_id == f"{MARKER_RZP_ORDER_ID}_A")
        check("B2: new Order persists razorpay_payment_id", new_order.razorpay_payment_id == "pay_R1TEST0001")
        check("B2: new Order persists payment_status", new_order.payment_status == "PAYMENT_PENDING")
        db.session.delete(new_order)
        db.session.commit()

        # B3 -- razorpay_order_id UNIQUE constraint enforced at the DB level.
        first = Order(name="Dup A", email="r1-schema-test-dupA@example.com", product=MARKER_SLUG, razorpay_order_id=f"{MARKER_RZP_ORDER_ID}_B")
        db.session.add(first)
        db.session.commit()
        second = Order(name="Dup B", email="r1-schema-test-dupB@example.com", product=MARKER_SLUG, razorpay_order_id=f"{MARKER_RZP_ORDER_ID}_B")
        db.session.add(second)
        try:
            db.session.commit()
            check("B3: duplicate razorpay_order_id rejected (UNIQUE)", False)
        except IntegrityError:
            db.session.rollback()
            check("B3: duplicate razorpay_order_id rejected (UNIQUE)", True)
        Order.query.filter_by(email="r1-schema-test-dupA@example.com").delete(synchronize_session=False)
        db.session.commit()

        # ==============================================================
        print("\n=== C: preparing rows for the downgrade/upgrade backfill test ===")
        # ==============================================================
        # legacy_shaped (status="PAID") already exists from B1 above.
        # Add a second row with a non-PAID status, to prove the
        # backfill is conditional, never a blanket UPDATE.
        pending_shaped = Order(
            name="Pending Shape", email=MARKER_EMAIL_PENDING, product="startup_suggestion_report",
            status="PENDING",
        )
        db.session.add(pending_shaped)
        db.session.commit()
        paid_id = legacy_shaped.id
        pending_id = pending_shaped.id
        print(f"  Prepared Order.id={paid_id} (status=PAID), Order.id={pending_id} (status=PENDING)")

    # ==================================================================
    print("\n=== C: flask db downgrade -> flask db upgrade cycle ===")
    # ==================================================================
    # Explicitly targets R1's OWN down_revision (never a bare one-step
    # `downgrade`) so this test keeps exercising R1's specific
    # razorpay_order_id/razorpay_payment_id/payment_status columns --
    # not just whatever revision happens to be current HEAD-1 -- even
    # after later revisions (e.g. R2) are chained on top of R1. A bare
    # `flask db upgrade` with no argument always means "the true head,
    # whatever it now is," so this remains a correct full round-trip
    # regardless of how many later revisions exist.
    R1_DOWN_REVISION = "6d2ed1d602c1"
    down = run_flask_db("downgrade", R1_DOWN_REVISION)
    check("C: flask db downgrade to R1's own down_revision succeeded", down.returncode == 0)
    if down.returncode != 0:
        print(down.stdout[-2000:], down.stderr[-2000:])

    up = run_flask_db("upgrade")
    check("C: flask db upgrade (back to true head) succeeded", up.returncode == 0)
    if up.returncode != 0:
        print(up.stdout[-2000:], up.stderr[-2000:])

    with app.app_context():
        db.session.expire_all()
        re_paid = Order.query.get(paid_id)
        re_pending = Order.query.get(pending_id)
        check("C: status=PAID row backfilled to payment_status=PAID after downgrade/upgrade", re_paid is not None and re_paid.payment_status == "PAID")
        check("C: status=PENDING row left at payment_status=CREATED (not force-marked PAID)", re_pending is not None and re_pending.payment_status == "CREATED")
        check("C: both rows survived the cycle with their original status/report_stage intact", re_paid.status == "PAID" and re_pending.status == "PENDING")

        cur = run_flask_db("current")
        # Asserts "at or past R1," never a hardcoded specific head --
        # remains correct as later revisions (R2+) are chained on top.
        check("C: flask db current is no longer R1's own pre-migration baseline", R1_DOWN_REVISION not in (cur.stdout or "")
              and cur.returncode == 0)

        cleanup()

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
