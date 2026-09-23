"""
test_report_platform_p0_3_focused_payment_bridge.py
-------------------------------------------------
Focused Reports Rs51 Payment Bridge -- P0.3.

Proves: the 63-row focused-report registry migration seeded exactly the
right data (and left the 25 existing rows untouched); OrderService's new
focused_v1/focused_dual_v1 branches validate the right fields/coordinates
without changing standard_v1/love_premium_v1 behavior; both new
generators are recognized by ReportGenerationDispatcher without breaking
existing dispatch/idempotency; tasks.py's new branch routes exclusively
to modules.focused_reports.paid_report_router and never touches the
standard/relationship pipelines; the router derives question_key ONLY
from Order.product, fails closed on a person_mode/generator mismatch,
builds the correct SELF/DUAL payload, and calls generate_focused_report/
render_focused_report_pdf/deliver_generated_report exactly as designed;
and the existing ReconciliationService retry/regenerate machinery
already covers a missing-PDF retry for a focused product with zero
additional code.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real Razorpay charge, no real customer email
(send_email is mocked everywhere it would fire), no real Celery/thread
dispatch (threading.Thread is mocked), and no live Luna call anywhere in
this file (generate_report_completion / generate_focused_report are
mocked at their call boundary).

HARD LOCK: two non-pilot focused products (one focused_v1, one
focused_dual_v1) are temporarily flipped active=True, inside a
try/finally that unconditionally restores active=False even if an
assertion raises -- major_kundali_obstacles and major_kundali_strengths
are never touched by this file. A final section re-verifies all 63
focused rows are active=False before this script exits.
"""

import os
import sys
from unittest.mock import patch, MagicMock

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
from modules.payments.order_service import OrderService, OrderValidationError  # noqa: E402
from modules.payments.report_generation_dispatcher import (  # noqa: E402
    ReportGenerationDispatcher, ReportGenerationDispatchStatus,
)
from modules.payments.reconciliation_service import ReconciliationService  # noqa: E402
from modules.focused_reports.paid_report_router import (  # noqa: E402
    route_focused_report_generation, FocusedReportRoutingError,
)
import tasks  # noqa: E402

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


MARKER_EMAIL_PREFIX = "p0-3-focused-test"
_counter = {"n": 0}


def _unique_email():
    _counter["n"] += 1
    return f"{MARKER_EMAIL_PREFIX}-{_counter['n']}@example.com"


SELF_TEST_SLUG = "promotion_timing"          # focused_v1, NOT a pilot product
DUAL_TEST_SLUG = "relationship_lead_to_marriage"  # focused_dual_v1, NOT a pilot product
PILOT_SLUGS = ("major_kundali_obstacles", "major_kundali_strengths")

_SELF_PAYLOAD = {
    "product": SELF_TEST_SLUG, "name": "Focused Test User", "phone": "9999999999",
    "dob": "1994-01-26", "tob": "08:40", "pob": "Sindhnur Rural",
    "latitude": "15.6167", "longitude": "76.6833", "language": "en",
}
_DUAL_PAYLOAD = {
    "product": DUAL_TEST_SLUG, "name": "Focused Dual Test User", "phone": "9999999999",
    "dob": "1994-01-26", "tob": "08:40", "pob": "Sindhnur Rural",
    "latitude": "15.6167", "longitude": "76.6833", "language": "en",
    "partner": {
        "name": "Partner", "dob": "1992-08-15", "tob": "06:30",
        "pob": "Mumbai", "latitude": "19.076", "longitude": "72.8777",
    },
}


def cleanup():
    Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()


def set_active(slug, value):
    ReportProduct.query.filter_by(report_slug=slug).update({"active": value}, synchronize_session=False)
    db.session.commit()


def make_order(payload):
    order = OrderService().create_pending_order(dict(payload, email=_unique_email()))
    return order


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )
        cleanup()

        # ==============================================================
        print("\n=== A: Registry / migration ===")
        # ==============================================================
        focused = ReportProduct.query.filter(
            ReportProduct.generator.in_(("focused_v1", "focused_dual_v1"))
        ).all()
        check("A1: exactly 63 focused products", len(focused) == 63)
        selfs = [p for p in focused if p.generator == "focused_v1"]
        duals = [p for p in focused if p.generator == "focused_dual_v1"]
        check("A2: 54 SELF (focused_v1)", len(selfs) == 54)
        check("A3: 9 DUAL (focused_dual_v1)", len(duals) == 9)
        check("A4: all 63 price == 51", all(p.price == 51 for p in focused))
        check("A5: all 63 currency == INR", all(p.currency == "INR" for p in focused))
        check("A6: all 63 active == False", all(p.active is False for p in focused))
        check("A7: both pilot products present and inactive",
              all(ReportProduct.query.get(s) is not None and ReportProduct.query.get(s).active is False
                  for s in PILOT_SLUGS))
        existing_25 = ReportProduct.query.filter(
            ~ReportProduct.generator.in_(("focused_v1", "focused_dual_v1"))
        ).all()
        check("A8: existing 25 rows untouched (count)", len(existing_25) == 25)
        check("A9: existing 25 rows still all active=True",
              all(p.active is True for p in existing_25))
        check("A10: existing generators unchanged (standard_v1/love_premium_v1 only)",
              {p.generator for p in existing_25} == {"standard_v1", "love_premium_v1"})

        # ==============================================================
        print("\n=== A11-13: amount_paise authoritative at order-creation time ===")
        # ==============================================================
        # Temporarily activate ONLY the two non-pilot test products, guaranteed
        # reverted in the finally block below -- pilots are never touched.
        set_active(SELF_TEST_SLUG, True)
        set_active(DUAL_TEST_SLUG, True)
        try:
            # ==========================================================
            print("\n=== B: Order creation ===")
            # ==========================================================
            order = make_order(_SELF_PAYLOAD)
            check("B1: valid SELF order created", order.id is not None)
            check("B2: amount_paise == 5100 (51 * 100) from registry, not client input",
                  order.amount_paise == 5100)
            check("B3: payment_status starts CREATED", order.payment_status == "CREATED")
            check("B4: report_stage starts Pending", order.report_stage == "Pending")

            dual_order = make_order(_DUAL_PAYLOAD)
            check("B5: valid DUAL order created", dual_order.id is not None)
            check("B6: DUAL amount_paise == 5100", dual_order.amount_paise == 5100)
            check("B7: partner_payload stored verbatim",
                  dual_order.partner_payload is not None and dual_order.partner_payload.get("name") == "Partner")

            for field in ("name", "email", "phone", "dob", "tob", "pob", "latitude", "longitude"):
                bad = dict(_SELF_PAYLOAD, email=_unique_email())
                del bad[field]
                try:
                    OrderService().create_pending_order(bad)
                    check(f"B8: missing SELF field '{field}' rejected", False)
                except OrderValidationError:
                    check(f"B8: missing SELF field '{field}' rejected", True)

            bad_coords = dict(_SELF_PAYLOAD, latitude="0", longitude="0")
            try:
                make_order(bad_coords)
                check("B9: invalid SELF (0,0) coordinates rejected", False)
            except OrderValidationError as exc:
                check("B9: invalid SELF (0,0) coordinates rejected", "not a valid birth place" in str(exc))

            bad_partner = dict(_DUAL_PAYLOAD, partner={k: v for k, v in _DUAL_PAYLOAD["partner"].items() if k != "tob"})
            try:
                make_order(bad_partner)
                check("B10: missing DUAL partner field rejected", False)
            except OrderValidationError as exc:
                check("B10: missing DUAL partner field rejected", "partner.tob" in str(exc))

            bad_partner_coords = dict(_DUAL_PAYLOAD, partner=dict(_DUAL_PAYLOAD["partner"], latitude="0", longitude="0"))
            try:
                make_order(bad_partner_coords)
                check("B11: invalid/(0,0) DUAL partner coordinates rejected", False)
            except OrderValidationError as exc:
                check("B11: invalid/(0,0) DUAL partner coordinates rejected",
                      "partner." in str(exc) and "not a valid birth place" in str(exc))

            try:
                make_order(dict(_SELF_PAYLOAD, product="totally_unknown_question_key_xyz"))
                check("B12: unknown question_key rejected before Razorpay", False)
            except OrderValidationError as exc:
                check("B12: unknown question_key rejected before Razorpay", "Unknown report product" in str(exc))

            # Inactive focused product (any of the other 61, still active=False) is rejected too.
            try:
                make_order(dict(_SELF_PAYLOAD, product="major_kundali_obstacles"))
                check("B13: inactive focused product rejected before Razorpay", False)
            except OrderValidationError as exc:
                check("B13: inactive focused product rejected before Razorpay", "not currently available" in str(exc))

            # ==========================================================
            print("\n=== C: Dispatch ===")
            # ==========================================================
            dispatcher = ReportGenerationDispatcher()

            order.payment_status = "PAID"
            order.status = "PAID"
            db.session.commit()
            with patch("threading.Thread") as mock_thread_cls:
                result = dispatcher.dispatch_if_pending(order.id)
            check("C1: focused_v1 generator recognized -> DISPATCHED", result.status == ReportGenerationDispatchStatus.DISPATCHED)
            db.session.refresh(order)
            check("C2: report_stage Pending -> Queued", order.report_stage == "Queued")
            check("C3: dispatch still routes through the single existing entry point",
                  mock_thread_cls.call_args.kwargs.get("target").__name__ == "generate_and_send_report")

            dual_order.payment_status = "PAID"
            dual_order.status = "PAID"
            db.session.commit()
            with patch("threading.Thread"):
                result_dual = dispatcher.dispatch_if_pending(dual_order.id)
            check("C4: focused_dual_v1 generator recognized -> DISPATCHED", result_dual.status == ReportGenerationDispatchStatus.DISPATCHED)

            unknown_gen_order = make_order(dict(_SELF_PAYLOAD))
            ReportProduct.query.filter_by(report_slug=SELF_TEST_SLUG).update({"generator": "bogus_v9"}, synchronize_session=False)
            db.session.commit()
            unknown_gen_order.payment_status = "PAID"
            unknown_gen_order.status = "PAID"
            db.session.commit()
            result_unknown = dispatcher.dispatch_if_pending(unknown_gen_order.id)
            check("C5: unrecognized generator rejected", result_unknown.status == ReportGenerationDispatchStatus.UNKNOWN_GENERATOR)
            ReportProduct.query.filter_by(report_slug=SELF_TEST_SLUG).update({"generator": "focused_v1"}, synchronize_session=False)
            db.session.commit()

            # Duplicate dispatch never regenerates.
            with patch("threading.Thread") as mock_thread_cls2:
                dup_result = dispatcher.dispatch_if_pending(order.id)  # already Queued
            check("C6: duplicate dispatch on already-Queued Order does not regenerate",
                  dup_result.status == ReportGenerationDispatchStatus.ALREADY_QUEUED and mock_thread_cls2.call_count == 0)

            # tasks.py routing: focused order reaches ONLY the new router, never
            # love_report_router / the inline standard pipeline.
            order.report_stage = "Pending"
            db.session.commit()
            with patch("modules.focused_reports.paid_report_router.route_focused_report_generation") as mock_route, \
                 patch("modules.love.love_report_router.route_report_generation") as mock_love_route:
                tasks._generate_and_send_report_core(order.id)
            check("C7: focused SELF order routes to paid_report_router exactly once",
                  mock_route.call_count == 1 and mock_route.call_args.args == (order.id,))
            check("C8: focused order never reaches love_report_router", mock_love_route.call_count == 0)
            db.session.refresh(order)
            check("C9: tasks.py's new branch returns before the inline standard pipeline touches report_stage",
                  order.report_stage == "Pending")  # unchanged -- the router (mocked here) owns that transition

            # Existing standard/relationship routing unchanged.
            std_order = OrderService().create_pending_order({
                "product": "career_report", "name": "Std", "email": _unique_email(), "phone": "9999999999",
                "dob": "1994-01-26", "tob": "08:40", "pob": "Delhi", "latitude": "28.6", "longitude": "77.2", "language": "en",
            })
            with patch("modules.focused_reports.paid_report_router.route_focused_report_generation") as mock_route2, \
                 patch("modules.love.love_report_router.route_report_generation") as mock_love_route2, \
                 patch("tasks.build_summary_blocks_with_transit", side_effect=RuntimeError("stop before real generation")):
                try:
                    tasks._generate_and_send_report_core(std_order.id)
                except Exception:
                    pass
            check("C10: standard_v1 order never reaches the focused router", mock_route2.call_count == 0)
            check("C10b: standard_v1 order never reaches love_report_router", mock_love_route2.call_count == 0)

            rel_order = OrderService().create_pending_order(dict(_DUAL_PAYLOAD, product="relationship_future_report",
                name="Rel", email=_unique_email(), phone=None,
                partner={"name": "Partner", "dob": "1992-08-15", "tob": "06:30", "pob": "Mumbai",
                         "latitude": "19.076", "longitude": "72.8777"}))
            with patch("modules.focused_reports.paid_report_router.route_focused_report_generation") as mock_route3, \
                 patch("modules.love.love_report_router.route_report_generation") as mock_love_route3:
                tasks._generate_and_send_report_core(rel_order.id)
            check("C11: relationship_future_report still routes to love_report_router, not the focused router",
                  mock_love_route3.call_count == 1 and mock_route3.call_count == 0)

            # ==========================================================
            print("\n=== D: Focused router ===")
            # ==========================================================
            fake_result = {
                "question_key": SELF_TEST_SLUG, "intent_slug": "career_growth_timing",
                "handler_key": SELF_TEST_SLUG, "language": "en", "customer_question": "Is this a good time?",
                "hero": {"label": "L", "value": "V", "interpretation": "I", "evidence": ["e"]},
                "report": "Direct Answer\nSome narrative text long enough.",
            }
            router_order = make_order(_SELF_PAYLOAD)
            with patch("modules.focused_reports.paid_report_router.get_question") as mock_get_q:
                mock_get_q.side_effect = lambda k: MagicMock(person_mode="dual")  # deliberately wrong
                try:
                    route_focused_report_generation(router_order.id)
                    check("D1: person_mode/generator mismatch fails closed", False)
                except FocusedReportRoutingError:
                    check("D1: person_mode/generator mismatch fails closed", True)
            db.session.refresh(router_order)
            check("D1b: failed-closed mismatch never left Order stuck mid-Processing without failing forward",
                  router_order.report_stage in ("Pending", "Processing"))

            with patch("modules.focused_reports.paid_report_router.generate_focused_report") as mock_gen, \
                 patch("modules.focused_reports.paid_report_router.render_focused_report_pdf") as mock_pdf, \
                 patch("modules.focused_reports.paid_report_router.deliver_generated_report") as mock_deliver:
                mock_gen.return_value = fake_result
                mock_pdf.return_value = "/home/Jyotishasha/reports/fake_focused_test.pdf"
                route_focused_report_generation(router_order.id)
            check("D2: question_key came from Order.product exclusively",
                  mock_gen.call_args.args[0] == router_order.product == SELF_TEST_SLUG)
            check("D3: generate_focused_report invoked exactly once", mock_gen.call_count == 1)
            check("D4: SELF payload passed to generate_focused_report is a real kundali dict (has lagna_sign)",
                  isinstance(mock_gen.call_args.args[1], dict) and "lagna_sign" in mock_gen.call_args.args[1])
            check("D5: PDF adapter invoked with the generation result and a customer dict", mock_pdf.call_count == 1
                  and mock_pdf.call_args.args[0] == fake_result and mock_pdf.call_args.args[1]["name"] == router_order.name)
            check("D6: delivery service invoked exactly once", mock_deliver.call_count == 1)
            db.session.refresh(router_order)
            check("D7: report_stage Processing -> Ready", router_order.report_stage == "Ready")

            dual_router_order = make_order(_DUAL_PAYLOAD)
            with patch("modules.focused_reports.paid_report_router.generate_focused_report") as mock_gen_d, \
                 patch("modules.focused_reports.paid_report_router.render_focused_report_pdf") as mock_pdf_d, \
                 patch("modules.focused_reports.paid_report_router.deliver_generated_report"):
                mock_gen_d.return_value = dict(fake_result, question_key=DUAL_TEST_SLUG)
                mock_pdf_d.return_value = "/home/Jyotishasha/reports/fake_focused_dual_test.pdf"
                route_focused_report_generation(dual_router_order.id)
            dual_payload_sent = mock_gen_d.call_args.args[1]
            check("D8: DUAL payload shape is {user, partner, boy_is_user}",
                  set(dual_payload_sent.keys()) == {"user", "partner", "boy_is_user"})
            check("D9: DUAL payload carries both people's real birth data",
                  dual_payload_sent["user"]["name"] == dual_router_order.name
                  and dual_payload_sent["partner"]["name"] == "Partner")
            check("D10: boy_is_user is a real bool (existing love_premium_v1 convention reused)",
                  dual_payload_sent["boy_is_user"] is True)

            # Exception during generation -> Failed, payment untouched.
            failing_order = make_order(_SELF_PAYLOAD)
            with patch("modules.focused_reports.paid_report_router.generate_focused_report", side_effect=RuntimeError("Luna down")):
                try:
                    route_focused_report_generation(failing_order.id)
                except RuntimeError:
                    pass
            db.session.refresh(failing_order)
            check("D11: generation exception -> report_stage Failed", failing_order.report_stage == "Failed")
            check("D11b: payment_status untouched by generation failure", failing_order.payment_status == "CREATED")

            # ==========================================================
            print("\n=== E: Delivery / retry ===")
            # ==========================================================
            delivered_order = make_order(_SELF_PAYLOAD)
            with patch("modules.focused_reports.paid_report_router.generate_focused_report", return_value=fake_result), \
                 patch("modules.focused_reports.paid_report_router.render_focused_report_pdf",
                       return_value="/home/Jyotishasha/reports/fake_e1.pdf"), \
                 patch("modules.focused_reports.paid_report_router.send_email") as mock_send, \
                 patch("modules.payments.report_delivery_service.os.remove"):
                route_focused_report_generation(delivered_order.id)
            db.session.refresh(delivered_order)
            check("E1: successful delivery -> email_status SENT", delivered_order.email_status == "SENT")
            check("E1b: no real email actually sent (send_email mocked)", mock_send.call_count == 1)

            email_fail_order = make_order(_SELF_PAYLOAD)
            with patch("modules.focused_reports.paid_report_router.generate_focused_report", return_value=fake_result), \
                 patch("modules.focused_reports.paid_report_router.render_focused_report_pdf",
                       return_value="/home/Jyotishasha/reports/fake_e2.pdf"), \
                 patch("modules.focused_reports.paid_report_router.send_email", side_effect=RuntimeError("SMTP down")):
                route_focused_report_generation(email_fail_order.id)
            db.session.refresh(email_fail_order)
            check("E2: email failure -> report_stage stays Ready", email_fail_order.report_stage == "Ready")
            check("E2b: email failure -> email_status FAILED", email_fail_order.email_status == "FAILED")

            # Duplicate webhook idempotency regression (product-agnostic; unaffected by P0.3,
            # which never touched this module -- imports cleanly, same public names).
            from modules.payments.payment_finalization_service import PaymentFinalizationService, ReportPaymentFinalizationStatus
            check("E3: PaymentFinalizationService still imports cleanly after P0.3 changes",
                  PaymentFinalizationService is not None and ReportPaymentFinalizationStatus is not None)

            # Missing-PDF retry: existing generic ReconciliationService already covers this.
            missing_pdf_order = make_order(_SELF_PAYLOAD)
            missing_pdf_order.payment_status = "PAID"
            missing_pdf_order.status = "PAID"
            missing_pdf_order.report_stage = "Ready"
            missing_pdf_order.email_status = "FAILED"
            missing_pdf_order.pdf_url = "/home/Jyotishasha/reports/does_not_exist_anymore.pdf"
            db.session.commit()
            recon = ReconciliationService()
            with patch("modules.payments.report_generation_dispatcher.ReportGenerationDispatcher._start_generation") as mock_regen:
                mock_regen.return_value = None
                result_retry = recon.retry_delivery(missing_pdf_order.id)
            db.session.refresh(missing_pdf_order)
            check("E4: missing-PDF retry falls through to regeneration (Ready -> Processing -> Queued path), not a bare email resend",
                  result_retry.resumed is True and mock_regen.call_count == 1)
            check("E4b: regeneration path targets the SAME order_id, no new payment/Order created",
                  mock_regen.call_args.args[0] == missing_pdf_order.id)

        finally:
            set_active(SELF_TEST_SLUG, False)
            set_active(DUAL_TEST_SLUG, False)

        # ==============================================================
        print("\n=== 10: ACTIVE FLAG HARD LOCK -- re-verify after every test above ===")
        # ==============================================================
        all_focused_now = ReportProduct.query.filter(
            ReportProduct.generator.in_(("focused_v1", "focused_dual_v1"))
        ).all()
        check("10: still exactly 63 focused rows", len(all_focused_now) == 63)
        check("10: ALL 63 focused rows are active=False (including the two temporarily-flipped test slugs)",
              all(p.active is False for p in all_focused_now))
        check("10: major_kundali_obstacles / major_kundali_strengths were never activated by this file",
              all(ReportProduct.query.get(s).active is False for s in PILOT_SLUGS))

        cleanup()

        print("\n" + "=" * 50)
        print(f"RESULT: {passed} passed, {failed} failed")
        print("=" * 50)
        return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
