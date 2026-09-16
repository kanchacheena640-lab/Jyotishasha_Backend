import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import email_utils
from modules.payments.reconciliation_models import ReconciliationAction, ReconciliationDecision, ReconciliationResumeResult
from modules.payments.report_delivery_service import deliver_generated_report
from modules.payments.reconciliation_service import ReconciliationService


def order(**overrides):
    values = dict(
        id=42, name="Delivery Test", email="delivery@example.com",
        product="career_report", payment_status="PAID", status="PAID",
        report_stage="Ready", email_status="FAILED", email_error="old",
        email_last_attempt_at=None, email_sent_at=None, pdf_url=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class StrictAttachmentTests(unittest.TestCase):
    def _path(self, content):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        handle.write(content)
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.remove(handle.name))
        return handle.name

    def test_valid_pdf_and_smtp_success_attaches_pdf(self):
        path = self._path(b"%PDF-1.7\nreport")
        with patch("email_utils.smtplib.SMTP") as smtp:
            email_utils.send_email("x@example.com", "subject", "body", path)
        smtp.return_value.send_message.assert_called_once()
        message = smtp.return_value.send_message.call_args.args[0]
        self.assertEqual(len(message.get_payload()), 2)

    def test_missing_empty_and_unreadable_pdf_never_open_smtp(self):
        empty = self._path(b"")
        valid = self._path(b"%PDF-1.7\nreport")
        for path, opener in (
            ("missing.pdf", None),
            (empty, None),
            (valid, OSError("unreadable")),
        ):
            with self.subTest(path=path), patch("email_utils.smtplib.SMTP") as smtp:
                context = patch("builtins.open", side_effect=opener) if opener else _NullContext()
                with context:
                    with self.assertRaises((FileNotFoundError, ValueError, OSError)):
                        email_utils.send_email("x@example.com", "subject", "body", path)
                smtp.assert_not_called()


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DeliveryStateTests(unittest.TestCase):
    def test_both_generators_use_shared_delivery_state_service(self):
        standard = Path("tasks.py").read_text(encoding="utf-8")
        relationship = Path("modules/love/love_premium_task.py").read_text(encoding="utf-8")
        self.assertIn("deliver_generated_report(order_id, output_path", standard)
        self.assertIn("deliver_generated_report(order_id, output_path", relationship)

    def _run(self, report_order, send):
        fake_order_model = SimpleNamespace(query=SimpleNamespace(get=MagicMock(return_value=report_order)))
        fake_db = MagicMock()
        with patch("modules.payments.report_delivery_service.Order", fake_order_model), \
             patch("modules.payments.report_delivery_service.db", fake_db):
            deliver_generated_report(report_order.id, report_order.pdf_url, send_email_fn=send)
        return fake_db

    def test_success_sets_sent_clears_pointer_and_cleans_temporary_pdf(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as artifact:
            artifact.write(b"%PDF-1.7\nreport")
            path = artifact.name
        report_order = order(pdf_url=path)
        self._run(report_order, MagicMock())
        self.assertEqual(report_order.email_status, "SENT")
        self.assertIsNone(report_order.pdf_url)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(report_order.payment_status, "PAID")

    def test_smtp_failure_sets_failed_and_retains_artifact(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as artifact:
            artifact.write(b"%PDF-1.7\nreport")
            path = artifact.name
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        report_order = order(pdf_url=path)
        send = MagicMock(side_effect=RuntimeError("smtp unavailable"))
        with self.assertRaisesRegex(RuntimeError, "smtp unavailable"):
            self._run(report_order, send)
        self.assertEqual(report_order.email_status, "FAILED")
        self.assertIn("smtp unavailable", report_order.email_error)
        self.assertEqual(report_order.pdf_url, path)
        self.assertEqual(report_order.payment_status, "PAID")

    def test_missing_empty_and_unreadable_artifacts_set_failed_without_smtp(self):
        missing = tempfile.mktemp(suffix=".pdf")
        empty = tempfile.mktemp(suffix=".pdf")
        Path(empty).write_bytes(b"")
        self.addCleanup(lambda: os.path.exists(empty) and os.remove(empty))
        unreadable = tempfile.mktemp(suffix=".pdf")
        Path(unreadable).write_bytes(b"%PDF-1.7\nreport")
        self.addCleanup(lambda: os.path.exists(unreadable) and os.remove(unreadable))

        for path, open_error in ((missing, None), (empty, None), (unreadable, OSError("denied"))):
            with self.subTest(path=path):
                report_order = order(pdf_url=path)
                smtp = MagicMock()
                patches = [patch("email_utils.smtplib.SMTP", smtp)]
                if open_error:
                    patches.append(patch("builtins.open", side_effect=open_error))
                with patches[0]:
                    context = patches[1] if len(patches) == 2 else _NullContext()
                    with context, self.assertRaises((FileNotFoundError, ValueError, OSError)):
                        self._run(report_order, email_utils.send_email)
                self.assertEqual(report_order.email_status, "FAILED")
                self.assertTrue(report_order.email_error)
                smtp.assert_not_called()

    def test_relationship_success_and_failure_use_same_email_state_contract(self):
        for succeeds in (True, False):
            with self.subTest(succeeds=succeeds):
                path = tempfile.mktemp(suffix=".pdf")
                Path(path).write_bytes(b"%PDF-1.7\nrelationship")
                self.addCleanup(lambda p=path: os.path.exists(p) and os.remove(p))
                report_order = order(product="relationship_future_report", pdf_url=path)
                send = MagicMock() if succeeds else MagicMock(side_effect=RuntimeError("relationship smtp failure"))
                if succeeds:
                    self._run(report_order, send)
                    self.assertEqual(report_order.email_status, "SENT")
                else:
                    with self.assertRaises(RuntimeError):
                        self._run(report_order, send)
                    self.assertEqual(report_order.email_status, "FAILED")
                self.assertEqual(report_order.payment_status, "PAID")


class DeliveryRetryTests(unittest.TestCase):
    def test_existing_pdf_uses_email_only_retry(self):
        existing = order(pdf_url="temporary.pdf")
        query = SimpleNamespace(get=MagicMock(return_value=existing))
        service = ReconciliationService(dispatcher=MagicMock())
        with patch("modules.payments.reconciliation_service.Order", SimpleNamespace(query=query)), \
             patch.object(service, "_try_acquire_delivery_ownership", return_value=True), \
             patch("modules.payments.reconciliation_service.pdf_artifact_is_usable", return_value=True), \
             patch("modules.payments.reconciliation_service.deliver_generated_report") as deliver, \
             patch.object(service, "regenerate") as regenerate:
            result = service.retry_delivery(42)
        self.assertTrue(result.resumed)
        deliver.assert_called_once_with(42, "temporary.pdf")
        regenerate.assert_not_called()

    def test_missing_pdf_uses_existing_regeneration_path(self):
        existing = order(pdf_url="gone.pdf")
        filtered = MagicMock()
        fake_query = MagicMock()
        fake_query.get.return_value = existing
        fake_query.filter_by.return_value = filtered
        regenerated = ReconciliationResumeResult(
            order_id=42, resumed=True,
            decision=ReconciliationDecision(42, "Ready", ReconciliationAction.RESUME_ALLOWED, "regenerated"),
        )
        service = ReconciliationService(dispatcher=MagicMock())
        with patch("modules.payments.reconciliation_service.Order", SimpleNamespace(query=fake_query)), \
             patch("modules.payments.reconciliation_service.db", MagicMock()), \
             patch.object(service, "_try_acquire_delivery_ownership", return_value=True), \
             patch("modules.payments.reconciliation_service.pdf_artifact_is_usable", return_value=False), \
             patch.object(service, "regenerate", return_value=regenerated) as regenerate, \
             patch("modules.payments.reconciliation_service.deliver_generated_report") as deliver:
            result = service.retry_delivery(42)
        self.assertTrue(result.resumed)
        regenerate.assert_called_once_with(42)
        deliver.assert_not_called()
        self.assertEqual(existing.payment_status, "PAID")

    def test_concurrent_retry_loser_does_nothing(self):
        existing = order(pdf_url="temporary.pdf")
        service = ReconciliationService(dispatcher=MagicMock())
        with patch("modules.payments.reconciliation_service.Order", SimpleNamespace(query=SimpleNamespace(get=MagicMock(return_value=existing)))), \
             patch.object(service, "_try_acquire_delivery_ownership", return_value=False), \
             patch("modules.payments.reconciliation_service.deliver_generated_report") as deliver:
            result = service.retry_delivery(42)
        self.assertFalse(result.resumed)
        deliver.assert_not_called()

    def test_no_business_rows_are_created(self):
        source = Path("modules/payments/reconciliation_service.py").read_text(encoding="utf-8")
        retry_source = source.split("def retry_delivery", 1)[1].split("def _try_acquire_resume_ownership", 1)[0]
        self.assertNotIn("db.session.add", retry_source)
        self.assertNotIn("ProcessedPayment", retry_source)


class DownloadSecurityTests(unittest.TestCase):
    def test_download_route_uses_existing_admin_bridge_guard(self):
        source = Path("app.py").read_text(encoding="utf-8")
        route = source.split('@app.route("/admin/download/<int:order_id>")', 1)[1].split(
            "# ------------------- KUNDALI API", 1
        )[0]
        self.assertIn("@admin_or_bridge_required", route)


if __name__ == "__main__":
    unittest.main()
