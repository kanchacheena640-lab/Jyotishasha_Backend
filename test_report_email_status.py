"""
test_report_email_status.py
-------------------------------------------------
Task 17B: proves the paid-report email delivery-truth fix --

  A. email_utils.py::send_email() no longer swallows a send failure --
     it raises on failure, returns normally on success (Task 17A's own
     root-cause finding for the report-email observability gap).

  B. tasks.py::_generate_and_send_report_core() records that outcome
     durably and truthfully on Order.email_status/email_last_attempt_at/
     email_sent_at/email_error, via its OWN dedicated try/except --
     completely separate from report_stage, which continues to mean
     ONLY "was the PDF generated," never "was the email delivered."

  C. A pre-email report-generation failure still behaves exactly as
     before (report_stage="Failed", report_generation_failed emitted) --
     and email_status correctly stays "NOT_ATTEMPTED", since the email
     step is never reached at all in that case.

  D/E. A resend (re-invoking the SAME shared _generate_and_send_report_
     core() function against an existing order_id -- what OrderService.
     redispatch_report_generation()/admin_orders.py's resend_order()
     both ultimately dispatch to) updates email_status truthfully on
     each new attempt, independent of what a prior attempt recorded.
     NOTE: admin_orders.py's own resend_order() calls
     generate_and_send_report.delay(order_id), which assumes Celery
     (USE_CELERY=True); this repo's local dev checkpoint has
     USE_CELERY=False (app_config.py), under which `generate_and_send_
     report` is a plain function with no .delay() at all -- an existing,
     unrelated, out-of-scope quirk, not something this task fixes.
     Exercising _generate_and_send_report_core() directly a second time
     against the same order_id is the correct and sufficient way to
     prove resend's email-status truth, since that is the exact shared
     function both the fresh-purchase path and any real resend dispatch
     (Celery or thread) ultimately call.

  F. send_email()'s own contract, directly: a mocked successful SMTP
     interaction completes without raising; a mocked failed SMTP
     interaction (login raises) propagates to the caller instead of
     being caught and printed.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real OpenAI/kundali/PDF/SMTP call is ever
made -- every external/expensive call inside the Order pipeline is
monkeypatched to a deterministic fake, matching the exact convention
test_report_activity_events.py already established (apply_tasks_mocks/
restore_tasks_mocks). All test rows are created with dedicated markers
and deleted in a finally block, keyed by their own ids -- never a broad
DELETE.
"""

import os
import sys
import tempfile
import uuid
from types import SimpleNamespace
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

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


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text

    from models import Order
    import tasks as tasks_module
    import email_utils as email_utils_module

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"REFUSING to run against {current_db!r} -- local only."
        )

        created_order_ids = []
        created_event_ids = []

        def new_order(product="career_report"):
            o = Order(
                name="Phase17B Test", email=f"phase17b-{uuid.uuid4().hex[:8]}@example.com",
                phone="9999999999", product=product,
                dob="1990-01-01", tob="10:00", pob="Delhi, India",
                language="en", status="PAID",
                latitude="28.6139", longitude="77.2090",
            )
            db.session.add(o)
            db.session.commit()
            created_order_ids.append(o.id)
            return o.id

        def track_all(rows):
            for r in rows:
                created_event_ids.append(str(r.event_id))
            return rows

        def rows_for_entity(entity_type, entity_id, event_name=None):
            if event_name:
                return db.session.execute(
                    text(
                        "SELECT * FROM activity_events WHERE entity_type = :et "
                        "AND entity_id = :eid AND event_name = :en ORDER BY recorded_at"
                    ),
                    {"et": entity_type, "eid": str(entity_id), "en": event_name},
                ).fetchall()
            return db.session.execute(
                text(
                    "SELECT * FROM activity_events WHERE entity_type = :et "
                    "AND entity_id = :eid ORDER BY recorded_at"
                ),
                {"et": entity_type, "eid": str(entity_id)},
            ).fetchall()

        # ------------------------------------------------------------
        # Same mocking convention as test_report_activity_events.py's
        # own "ORDER GENERAL PIPELINE" section.
        # ------------------------------------------------------------
        def fake_kundali(**kwargs):
            return {"lagna_rashi": "Aries", "planets": {}}

        def fake_transit():
            return {}

        def fake_summary_blocks(kundali, transit):
            return {
                "birth_chart_summary": "x", "current_transit_summary": "x",
                "mahadasha_summary": "x",
            }

        def fake_drawing(**kwargs):
            return "fake_drawing"

        def fake_pdf(**kwargs):
            return None

        def fake_send_email_success(*a, **k):
            return None

        def fake_send_email_failure(*a, **k):
            raise RuntimeError("simulated SMTP send failure (mocked, no real network)")

        class _FakeCompletions:
            def __init__(self, content):
                self._content = content

            def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
                )

        class _FakeOpenAIClient:
            def __init__(self, content="Fake generated report body."):
                self.chat = SimpleNamespace(completions=_FakeCompletions(content))

        def apply_tasks_mocks(send_email_fn, openai_content="Fake generated report body."):
            tasks_module.calculate_full_kundali = fake_kundali
            tasks_module.get_current_positions = fake_transit
            tasks_module.build_summary_blocks_with_transit = fake_summary_blocks
            tasks_module.generate_kundali_drawing = fake_drawing
            tasks_module.generate_pdf_report = fake_pdf
            tasks_module.send_email = send_email_fn
            tasks_module.openai_client = _FakeOpenAIClient(openai_content)

        real_tasks_attrs = {
            name: getattr(tasks_module, name) for name in (
                "calculate_full_kundali", "get_current_positions",
                "build_summary_blocks_with_transit", "generate_kundali_drawing",
                "generate_pdf_report", "send_email", "openai_client",
            )
        }

        def restore_tasks_mocks():
            for name, value in real_tasks_attrs.items():
                setattr(tasks_module, name, value)

        try:
            # ==========================================================
            print("\n=== A: successful generation + successful mocked email ===")
            # ==========================================================
            order_a_id = new_order(product="career_report")
            apply_tasks_mocks(fake_send_email_success)
            try:
                tasks_module._generate_and_send_report_core(order_a_id)
            finally:
                restore_tasks_mocks()
            track_all(rows_for_entity("order", order_a_id))
            row_a = Order.query.get(order_a_id)
            check("A: report_stage == Ready", row_a.report_stage == "Ready")
            check("A: email_status == SENT", row_a.email_status == "SENT")
            check("A: email_sent_at is set", row_a.email_sent_at is not None)
            check("A: email_last_attempt_at is set", row_a.email_last_attempt_at is not None)
            check("A: email_sent_at == email_last_attempt_at (same attempt)", row_a.email_sent_at == row_a.email_last_attempt_at)
            check("A: email_error is None (no failure recorded)", row_a.email_error is None)

            # ==========================================================
            print("\n=== B: successful generation + FAILED mocked email ===")
            # ==========================================================
            order_b_id = new_order(product="career_report")
            apply_tasks_mocks(fake_send_email_failure)
            try:
                tasks_module._generate_and_send_report_core(order_b_id)
            finally:
                restore_tasks_mocks()
            track_all(rows_for_entity("order", order_b_id))
            row_b = Order.query.get(order_b_id)
            check("B: report_stage STILL Ready despite email failure (Step 5 -- must not corrupt each other)", row_b.report_stage == "Ready")
            check("B: email_status == FAILED", row_b.email_status == "FAILED")
            check("B: email_error is observable (non-empty)", bool(row_b.email_error))
            check("B: email_error is the simulated failure text, bounded", "simulated SMTP send failure" in row_b.email_error and len(row_b.email_error) <= 500)
            check("B: email_last_attempt_at is set", row_b.email_last_attempt_at is not None)
            check("B: email_sent_at is NOT set (never actually succeeded)", row_b.email_sent_at is None)
            check("B: pdf_url still present -- the report itself remains available", bool(row_b.pdf_url))
            check("B: no credentials leaked into email_error", "SENDER_PASSWORD" not in row_b.email_error and "smtp.gmail.com" not in row_b.email_error)
            check("B: no report_generation_failed row was emitted for an email-only failure", len(rows_for_entity("order", order_b_id, "report_generation_failed")) == 0)
            check("B: report_generation_completed WAS still emitted (report itself succeeded)", len(rows_for_entity("order", order_b_id, "report_generation_completed")) == 1)

            # ==========================================================
            print("\n=== C: report/PDF generation failure BEFORE email is ever reached ===")
            # ==========================================================
            order_c_id = new_order(product="a-product-with-no-real-prompt-template-17b")
            apply_tasks_mocks(fake_send_email_success)  # irrelevant -- must never be reached
            try:
                tasks_module._generate_and_send_report_core(order_c_id)
            finally:
                restore_tasks_mocks()
            track_all(rows_for_entity("order", order_c_id))
            row_c = Order.query.get(order_c_id)
            check("C: existing report-generation failure behavior preserved -- report_stage == Failed", row_c.report_stage == "Failed")
            check("C: report_generation_failed WAS emitted (existing behavior unchanged)", len(rows_for_entity("order", order_c_id, "report_generation_failed")) == 1)
            check("C: email_status remains NOT_ATTEMPTED -- the email step was never reached", row_c.email_status == "NOT_ATTEMPTED")
            check("C: email_sent_at is None", row_c.email_sent_at is None)
            check("C: email_last_attempt_at is None", row_c.email_last_attempt_at is None)
            check("C: email_error is None", row_c.email_error is None)

            # ==========================================================
            print("\n=== D: resend (re-invocation) after a FAILED email -> SENT ===")
            # ==========================================================
            # order_b's prior state: email_status == FAILED (from Test B).
            # A resend re-runs the SAME shared core function against the
            # SAME order_id -- see this file's own module docstring for
            # why this is the correct way to exercise resend's email-
            # status truth in this local, USE_CELERY=False checkpoint.
            apply_tasks_mocks(fake_send_email_success)
            try:
                tasks_module._generate_and_send_report_core(order_b_id)
            finally:
                restore_tasks_mocks()
            row_d = Order.query.get(order_b_id)
            check("D: resend success -> email_status becomes SENT (overwrites prior FAILED)", row_d.email_status == "SENT")
            check("D: resend success -> email_sent_at updated to this attempt", row_d.email_sent_at is not None and row_d.email_sent_at == row_d.email_last_attempt_at)
            check("D: resend success -> email_error cleared", row_d.email_error is None)
            check("D: report_stage remains Ready throughout resend", row_d.report_stage == "Ready")

            # ==========================================================
            print("\n=== E: resend (re-invocation) that ALSO fails ===")
            # ==========================================================
            # order_a's prior state: email_status == SENT (from Test A).
            # Force a failing resend and confirm the new FAILED outcome
            # correctly overwrites it, while report_stage is untouched.
            apply_tasks_mocks(fake_send_email_failure)
            try:
                tasks_module._generate_and_send_report_core(order_a_id)
            finally:
                restore_tasks_mocks()
            row_e = Order.query.get(order_a_id)
            check("E: resend failure -> email_status becomes FAILED (overwrites prior SENT)", row_e.email_status == "FAILED")
            check("E: resend failure -> email_error observable", bool(row_e.email_error))
            check("E: resend failure -> report_stage remains unchanged (still Ready)", row_e.report_stage == "Ready")

            # ==========================================================
            print("\n=== F: send_email() itself -- real contract, mocked smtplib only ===")
            # ==========================================================
            tmp_pdf_fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
            with os.fdopen(tmp_pdf_fd, "wb") as f:
                f.write(b"%PDF-1.4 fake test pdf content")

            try:
                # F1: successful mocked SMTP interaction.
                with patch("smtplib.SMTP") as mock_smtp_cls_ok:
                    mock_server_ok = mock_smtp_cls_ok.return_value
                    email_utils_module.send_email(
                        "test-recipient@example.com", "Test Subject", "Test body", tmp_pdf_path,
                    )
                    check("F1: successful mocked SMTP call completes without raising", True)
                    check("F1: starttls/login/send_message were all called", (
                        mock_server_ok.starttls.called
                        and mock_server_ok.login.called
                        and mock_server_ok.send_message.called
                    ))

                # F2: failed mocked SMTP interaction -- MUST propagate now
                # (Task 17B's own contract change), never be swallowed.
                with patch("smtplib.SMTP") as mock_smtp_cls_fail:
                    mock_server_fail = mock_smtp_cls_fail.return_value
                    mock_server_fail.login.side_effect = RuntimeError("simulated auth failure (mocked)")
                    raised = False
                    raised_message = None
                    try:
                        email_utils_module.send_email(
                            "test-recipient@example.com", "Test Subject", "Test body", tmp_pdf_path,
                        )
                    except Exception as exc:
                        raised = True
                        raised_message = str(exc)
                    check("F2: failed mocked SMTP call PROPAGATES to the caller (no longer swallowed)", raised)
                    check("F2: the real exception reaches the caller unmodified", raised_message == "simulated auth failure (mocked)")
            finally:
                os.remove(tmp_pdf_path)

            # ==========================================================
            print("\n=== G: security -- no credentials anywhere in ledger rows touched above ===")
            # ==========================================================
            forbidden_substrings = ["SENDER_PASSWORD", "smtp.gmail.com"]
            leak_found = False
            for eid in dict.fromkeys(created_event_ids):
                row = db.session.execute(text("SELECT * FROM activity_events WHERE event_id = :id"), {"id": eid}).fetchone()
                if row is None:
                    continue
                serialized = str(row.properties) + str(row.entity_id) + str(row.dedupe_key)
                for term in forbidden_substrings:
                    if term in serialized:
                        leak_found = True
                        print(f"  LEAK: {term!r} found in row {eid}")
            check("G: no SMTP credentials/host text found in any activity_events row", leak_found is False)

        finally:
            # ----------------------------------------------------------
            # Cleanup -- precise, per-row, never a broad DELETE.
            # ----------------------------------------------------------
            for eid in dict.fromkeys(created_event_ids):
                db.session.execute(text("DELETE FROM activity_events WHERE event_id = :id"), {"id": eid})
            db.session.commit()

            for oid in dict.fromkeys(created_order_ids):
                db.session.execute(text("DELETE FROM orders WHERE id = :id"), {"id": oid})
            db.session.commit()

            remaining_orders = Order.query.filter(Order.id.in_(created_order_ids or [-1])).count()
            check("cleanup: all Task-17B Order fixtures removed", remaining_orders == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
