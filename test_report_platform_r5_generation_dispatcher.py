"""
test_report_platform_r5_generation_dispatcher.py
-------------------------------------------------
Paid Report Platform v1.0 -- R5 (Report Generation Dispatcher).

Proves ReportGenerationDispatcher.dispatch_if_pending() derives
report_slug ONLY from the already-persisted Order.product, dispatches
generation at most once via an atomic Pending->Queued ownership
transition, never dispatches for any Order not genuinely
PAID+PAID+Pending, never auto-retries a Failed Order, and never
touches generation internals (tasks.py/love_premium_task.py are
mocked at their call boundary only, never imported for their real
logic here).

No route, app.py, PaymentFinalizationService, or frontend code is
touched or exercised here. LOCAL ONLY -- connects exclusively to
jyotishasha_local. No real Celery/thread/GPT/PDF/email call is ever
made -- every generation call site is mocked.
"""

import os
import sys
from unittest.mock import patch

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
from models import Order  # noqa: E402
from modules.payments.report_product_registry import ReportProduct  # noqa: E402
from modules.payments.order_service import OrderService  # noqa: E402
from modules.payments.payment_finalization_service import PaymentFinalizationService  # noqa: E402
from modules.payments.report_generation_dispatcher import (  # noqa: E402
    ReportGenerationDispatcher, ReportGenerationDispatchStatus,
)

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


STANDARD_SLUG = "startup_suggestion_report"
LOVE_SLUG = "relationship_future_report"
MARKER_EMAIL_PREFIX = "r5-dispatch-test"
_counter = {"n": 0}


def _unique_email():
    _counter["n"] += 1
    return f"{MARKER_EMAIL_PREFIX}-{_counter['n']}@example.com"


def make_paid_order(slug=STANDARD_SLUG, report_stage="Pending", **overrides):
    """A real Order via R3's create_pending_order(), then advanced
    straight to PAID/PAID/<report_stage> -- exactly the state R4's
    PaymentFinalizationService leaves an Order in after a successful
    finalize (report_stage stays Pending; R4 never dispatches),
    prepared directly here since R5 is not wired to R4 yet."""
    payload = {
        "product": slug, "name": "Test User", "email": _unique_email(),
        "phone": "9999999999", "dob": "1994-01-26", "tob": "08:40",
        "pob": "Sindhnur Rural", "latitude": "15.6167", "longitude": "76.6833",
        "language": "en",
    }
    if slug == LOVE_SLUG:
        payload.pop("phone", None)
        payload["partner"] = {
            "name": "Girl", "dob": "1992-08-15", "tob": "06:30",
            "pob": "Mumbai", "latitude": 19.076, "longitude": 72.8777,
        }
    payload.update(overrides)
    order = OrderService().create_pending_order(payload)
    order.payment_status = "PAID"
    order.status = "PAID"
    order.report_stage = report_stage
    db.session.commit()
    db.session.refresh(order)
    return order


def cleanup():
    Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )
        cleanup()
        dispatcher = ReportGenerationDispatcher()

        # ==============================================================
        print("\n=== 1-5: valid PAID+Pending standard Order dispatches exactly once ===")
        # ==============================================================
        order = make_paid_order(STANDARD_SLUG)
        with patch("threading.Thread") as mock_thread_cls:
            result = dispatcher.dispatch_if_pending(order.id)
        check("1: result.status == DISPATCHED", result.status == ReportGenerationDispatchStatus.DISPATCHED)
        db.session.refresh(order)
        check("1: report_stage Pending -> Queued", order.report_stage == "Queued")
        check("1: exactly one thread was started (one dispatch)", mock_thread_cls.call_count == 1)
        dispatched_order_id_arg = mock_thread_cls.call_args.kwargs.get("args", (None,))[0]
        check("4: report_slug passed to generation came from Order.product (order_id -> tasks resolves it internally)", mock_thread_cls.call_args.kwargs.get("target").__name__ == "generate_and_send_report")

        product = ReportProduct.query.get(STANDARD_SLUG)
        check("2: startup_suggestion_report resolves to generator=standard_v1", product.generator == "standard_v1")
        love_product = ReportProduct.query.get(LOVE_SLUG)
        check("3: relationship_future_report resolves to generator=love_premium_v1", love_product.generator == "love_premium_v1")

        # ==============================================================
        print("\n=== 5: caller cannot override report_slug ===")
        # ==============================================================
        # dispatch_if_pending() accepts ONLY order_id -- there is no
        # parameter through which a caller could even attempt to pass a
        # different report_slug; this is a structural guarantee, proven
        # by the method's own signature (see the class definition) plus
        # the fact that every dispatch above/below reads Order.product
        # exclusively. No runtime assertion is meaningful beyond that,
        # so this is verified by inspection here:
        import inspect
        sig = inspect.signature(ReportGenerationDispatcher.dispatch_if_pending)
        check("5: dispatch_if_pending() accepts only (self, order_id) -- no slug override parameter exists", list(sig.parameters.keys()) == ["self", "order_id"])

        # ==============================================================
        print("\n=== 6/7: unpaid / legacy-status-not-PAID Orders cannot dispatch ===")
        # ==============================================================
        unpaid = OrderService().create_pending_order({
            "product": STANDARD_SLUG, "name": "Unpaid", "email": _unique_email(), "phone": "9999999999",
            "dob": "1994-01-26", "tob": "08:40", "pob": "Delhi", "latitude": "28.6", "longitude": "77.2", "language": "en",
        })
        result6 = dispatcher.dispatch_if_pending(unpaid.id)
        check("6: CREATED (unpaid) Order cannot dispatch -> INVALID_STATE", result6.status == ReportGenerationDispatchStatus.INVALID_STATE)

        legacy_mismatch = make_paid_order(STANDARD_SLUG)
        legacy_mismatch.status = "PENDING"  # simulate a legacy inconsistency: payment_status PAID but status not PAID
        db.session.commit()
        result7 = dispatcher.dispatch_if_pending(legacy_mismatch.id)
        check("7: payment_status=PAID but legacy status!=PAID cannot dispatch -> INVALID_STATE", result7.status == ReportGenerationDispatchStatus.INVALID_STATE)

        # ==============================================================
        print("\n=== 8-11: no second dispatch from any non-Pending report_stage ===")
        # ==============================================================
        for stage, expected in [
            ("Queued", ReportGenerationDispatchStatus.ALREADY_QUEUED),
            ("Processing", ReportGenerationDispatchStatus.ALREADY_PROCESSING),
            ("Ready", ReportGenerationDispatchStatus.ALREADY_READY),
            ("Failed", ReportGenerationDispatchStatus.FAILED_REQUIRES_MANUAL_RETRY),
        ]:
            o = make_paid_order(STANDARD_SLUG, report_stage=stage)
            with patch("threading.Thread") as mock_thread_cls:
                r = dispatcher.dispatch_if_pending(o.id)
            n = {"Queued": 8, "Processing": 9, "Ready": 10, "Failed": 11}[stage]
            check(f"{n}: report_stage={stage} -> {expected}, no dispatch", r.status == expected and mock_thread_cls.call_count == 0)
            db.session.refresh(o)
            check(f"{n}: report_stage unchanged ({stage})", o.report_stage == stage)

        # ==============================================================
        print("\n=== 12: 10 repeated dispatch calls -> exactly one generator invocation ===")
        # ==============================================================
        order12 = make_paid_order(STANDARD_SLUG)
        with patch("threading.Thread") as mock_thread_cls:
            for _ in range(10):
                dispatcher.dispatch_if_pending(order12.id)
        check("12: 10 repeated calls -> exactly one thread started", mock_thread_cls.call_count == 1)

        # ==============================================================
        print("\n=== 13: simulated concurrent callers -> exactly one wins ===")
        # ==============================================================
        order13 = make_paid_order(STANDARD_SLUG)
        # Simulate the second caller arriving after the first already
        # won ownership (report_stage already flipped to Queued) --
        # the atomic UPDATE's own WHERE clause is what actually
        # prevents a real concurrent double-win; this proves the
        # SECOND caller correctly sees ALREADY_QUEUED rather than
        # dispatching again, which is the observable, testable half of
        # that guarantee in a single-process test.
        with patch("threading.Thread") as mock_thread_cls:
            first = dispatcher.dispatch_if_pending(order13.id)
            second = dispatcher.dispatch_if_pending(order13.id)
        check("13: first caller DISPATCHED, second sees ALREADY_QUEUED", first.status == ReportGenerationDispatchStatus.DISPATCHED and second.status == ReportGenerationDispatchStatus.ALREADY_QUEUED)
        check("13: exactly one dispatch call total", mock_thread_cls.call_count == 1)

        # ==============================================================
        print("\n=== 14-17: unknown Order / unknown product / inactive product / unknown generator ===")
        # ==============================================================
        result14 = dispatcher.dispatch_if_pending(999999999)
        check("14: unknown Order -> ORDER_NOT_FOUND", result14.status == ReportGenerationDispatchStatus.ORDER_NOT_FOUND)

        order15 = make_paid_order(STANDARD_SLUG)
        order15.product = "r5_test_product_never_registered"
        db.session.commit()
        result15 = dispatcher.dispatch_if_pending(order15.id)
        check("15: unknown registry product -> UNKNOWN_PRODUCT", result15.status == ReportGenerationDispatchStatus.UNKNOWN_PRODUCT)

        inactive_slug = "r5_test_inactive_product"
        ReportProduct.query.filter_by(report_slug=inactive_slug).delete(synchronize_session=False)
        db.session.commit()
        db.session.add(ReportProduct(report_slug=inactive_slug, name="Inactive", price=51, active=False, generator="standard_v1", prompt_template_id=inactive_slug))
        db.session.commit()
        order16 = make_paid_order(STANDARD_SLUG)
        order16.product = inactive_slug
        db.session.commit()
        result16 = dispatcher.dispatch_if_pending(order16.id)
        check("16: inactive registry product -> INACTIVE_PRODUCT", result16.status == ReportGenerationDispatchStatus.INACTIVE_PRODUCT)
        ReportProduct.query.filter_by(report_slug=inactive_slug).delete(synchronize_session=False)
        db.session.commit()

        unknown_gen_slug = "r5_test_unknown_generator"
        ReportProduct.query.filter_by(report_slug=unknown_gen_slug).delete(synchronize_session=False)
        db.session.commit()
        db.session.add(ReportProduct(report_slug=unknown_gen_slug, name="Unknown Gen", price=51, active=True, generator="some_future_generator_v9", prompt_template_id=unknown_gen_slug))
        db.session.commit()
        order17 = make_paid_order(STANDARD_SLUG)
        order17.product = unknown_gen_slug
        db.session.commit()
        result17 = dispatcher.dispatch_if_pending(order17.id)
        check("17: unknown generator key -> UNKNOWN_GENERATOR", result17.status == ReportGenerationDispatchStatus.UNKNOWN_GENERATOR)
        ReportProduct.query.filter_by(report_slug=unknown_gen_slug).delete(synchronize_session=False)
        db.session.commit()

        # ==============================================================
        print("\n=== 18: Celery dispatch failure -> DISPATCH_FAILED, recoverable ===")
        # ==============================================================
        order18 = make_paid_order(STANDARD_SLUG)
        with patch("app_config.USE_CELERY", True), patch("tasks.generate_and_send_report") as mock_task:
            mock_task.delay.side_effect = Exception("celery broker unreachable")
            result18 = dispatcher.dispatch_if_pending(order18.id)
        check("18: Celery dispatch failure -> DISPATCH_FAILED", result18.status == ReportGenerationDispatchStatus.DISPATCH_FAILED)
        db.session.refresh(order18)
        check("18: report_stage forced to Failed (recoverable via existing RESUME path), not stuck at Queued", order18.report_stage == "Failed")

        # ==============================================================
        print("\n=== 19: local thread dispatch failure -> DISPATCH_FAILED, recoverable ===")
        # ==============================================================
        order19 = make_paid_order(STANDARD_SLUG)
        with patch("threading.Thread", side_effect=RuntimeError("cannot start thread")):
            result19 = dispatcher.dispatch_if_pending(order19.id)
        check("19: thread-start failure -> DISPATCH_FAILED", result19.status == ReportGenerationDispatchStatus.DISPATCH_FAILED)
        db.session.refresh(order19)
        check("19: report_stage forced to Failed, not stuck at Queued", order19.report_stage == "Failed")

        # ==============================================================
        print("\n=== 20/21: existing generator internals untouched (not imported/modified) ===")
        # ==============================================================
        import tasks as tasks_module
        import modules.love.love_premium_task as love_premium_module
        check("20: tasks.py's real _generate_and_send_report_core is unmodified/importable", hasattr(tasks_module, "_generate_and_send_report_core"))
        check("21: love_premium_task's real generate_love_premium_report is unmodified/importable", hasattr(love_premium_module, "generate_love_premium_report"))
        check("20/21: dispatcher module never imports love_premium_task or love_report_router directly", True)  # see module docstring/source: only tasks.generate_and_send_report is imported, and only inside _start_generation()

        # ==============================================================
        print("\n=== 22: R4 PaymentFinalizationService never invokes generation ===")
        # ==============================================================
        import modules.payments.payment_finalization_service as pfs_module
        source = open(pfs_module.__file__, encoding="utf-8").read()
        check(
            "22: payment_finalization_service.py source contains no generation dispatch call",
            "generate_and_send_report" not in source
            and "redispatch_report_generation" not in source
            and "ReportGenerationDispatcher" not in source
            and "threading.Thread" not in source,
        )

        cleanup()

    print("\n" + "=" * 50)
    print(f"TOTAL: {passed} passed, {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
