"""Focused, database-free checks for paid-report recovery and admin regeneration."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.payments.reconciliation_models import ReconciliationAction
from modules.payments.reconciliation_service import ReconciliationService
from modules.payments.report_generation_dispatcher import (
    ReportGenerationDispatcher,
    ReportGenerationDispatchResult,
    ReportGenerationDispatchStatus,
)


def order(stage, age_seconds=0, **overrides):
    now = datetime.utcnow()
    values = dict(
        id=42, product="career_report", status="PAID", payment_status="PAID",
        report_stage=stage, processing_started_at=now - timedelta(seconds=age_seconds),
        created_at=now - timedelta(seconds=age_seconds),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class RecoveryInspectionTests(unittest.TestCase):
    def _inspect(self, value):
        query = MagicMock()
        query.get.return_value = value
        with patch("modules.payments.reconciliation_service.Order", SimpleNamespace(query=query)):
            return ReconciliationService().inspect(value.id)

    def test_fresh_queued_is_not_reclaimed(self):
        decision = self._inspect(order("Queued", age_seconds=60))
        self.assertEqual(decision.action, ReconciliationAction.ALREADY_RUNNING)

    def test_stale_queued_paid_is_recoverable(self):
        decision = self._inspect(order("Queued", age_seconds=301))
        self.assertEqual(decision.action, ReconciliationAction.RESUME_ALLOWED)

    def test_legacy_stale_queued_uses_created_at_fallback(self):
        decision = self._inspect(order(
            "Queued", age_seconds=301, processing_started_at=None,
        ))
        self.assertEqual(decision.action, ReconciliationAction.RESUME_ALLOWED)

    def test_existing_stale_processing_recovery_remains(self):
        decision = self._inspect(order("Processing", age_seconds=2401))
        self.assertEqual(decision.action, ReconciliationAction.RESUME_ALLOWED)

    def test_pending_and_failed_semantics_remain(self):
        self.assertEqual(
            self._inspect(order("Pending")).action,
            ReconciliationAction.NO_ACTION,
        )
        self.assertEqual(
            self._inspect(order("Failed")).action,
            ReconciliationAction.RESUME_ALLOWED,
        )

    def test_unpaid_order_is_ineligible(self):
        decision = self._inspect(order("Failed", payment_status="CREATED"))
        self.assertEqual(decision.action, ReconciliationAction.INVALID_STATE)


class RecoveryDispatchTests(unittest.TestCase):
    def test_atomic_stale_claim_allows_only_one_winner(self):
        filtered = MagicMock()
        filtered.update.side_effect = [1, 0]
        fake_order = MagicMock()
        fake_order.processing_started_at.__lt__.return_value = MagicMock()
        fake_order.created_at.__lt__.return_value = MagicMock()
        fake_order.query.filter.return_value = filtered
        fake_db = MagicMock()
        service = ReconciliationService(dispatcher=MagicMock())
        with patch("modules.payments.reconciliation_service.Order", fake_order), \
             patch("modules.payments.reconciliation_service.db", fake_db):
            self.assertTrue(service._try_acquire_resume_ownership(42))
            self.assertFalse(service._try_acquire_resume_ownership(42))
        self.assertEqual(filtered.update.call_count, 2)

    def test_only_one_recovery_attempt_dispatches(self):
        dispatcher = MagicMock()
        dispatcher.dispatch_claimed.return_value = ReportGenerationDispatchResult(
            status=ReportGenerationDispatchStatus.DISPATCHED, order_id=42,
        )
        service = ReconciliationService(dispatcher=dispatcher)
        allowed = SimpleNamespace(
            order_id=42, report_stage="Queued",
            action=ReconciliationAction.RESUME_ALLOWED, reason="stale",
        )
        with patch.object(service, "inspect", return_value=allowed), \
             patch.object(service, "_try_acquire_resume_ownership", side_effect=[True, False]):
            first = service.resume(42)
            second = service.resume(42)
        self.assertTrue(first.resumed)
        self.assertFalse(second.resumed)
        dispatcher.dispatch_claimed.assert_called_once_with(42)

    def test_admin_ready_regeneration_is_claimed_and_dispatched_once(self):
        dispatcher = MagicMock()
        dispatcher.dispatch_claimed.return_value = ReportGenerationDispatchResult(
            status=ReportGenerationDispatchStatus.DISPATCHED, order_id=42,
        )
        service = ReconciliationService(dispatcher=dispatcher)
        paid = order("Ready")
        query = MagicMock()
        query.get.return_value = paid
        with patch("modules.payments.reconciliation_service.Order", SimpleNamespace(query=query)), \
             patch.object(service, "_try_acquire_regeneration_ownership", return_value=True):
            result = service.regenerate(42)
        self.assertTrue(result.resumed)
        dispatcher.dispatch_claimed.assert_called_once_with(42)
        self.assertEqual(paid.payment_status, "PAID")
        self.assertEqual(paid.status, "PAID")

    def test_busy_admin_regeneration_is_rejected(self):
        dispatcher = MagicMock()
        service = ReconciliationService(dispatcher=dispatcher)
        busy = order("Processing", age_seconds=60)
        query = MagicMock()
        query.get.return_value = busy
        with patch("modules.payments.reconciliation_service.Order", SimpleNamespace(query=query)):
            result = service.regenerate(42)
        self.assertFalse(result.resumed)
        self.assertEqual(result.decision.action, ReconciliationAction.ALREADY_RUNNING)
        dispatcher.dispatch_claimed.assert_not_called()

    def test_direct_mode_uses_thread_and_never_delay(self):
        generation = MagicMock()
        fake_tasks = SimpleNamespace(generate_and_send_report=generation)
        with patch.dict(sys.modules, {"tasks": fake_tasks}), \
             patch("app_config.USE_CELERY", False), \
             patch("modules.payments.report_generation_dispatcher.threading.Thread") as thread:
            task_id = ReportGenerationDispatcher._start_generation(42)
        self.assertIsNone(task_id)
        thread.assert_called_once()
        generation.delay.assert_not_called()

    def test_admin_route_contains_no_direct_delay_or_new_stage(self):
        source = Path("routes/admin_orders.py").read_text(encoding="utf-8")
        resend = source.split("def resend_order", 1)[1].split(
            "# ------------------- UPDATE ORDER", 1
        )[0]
        self.assertIn("ReconciliationService().retry_delivery(order_id)", resend)
        self.assertNotIn(".delay(", resend)
        self.assertNotIn("Regenerating", resend)

    def test_recovery_does_not_create_order_or_processed_payment(self):
        source = Path("modules/payments/reconciliation_service.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("models_processed_payments", source)
        self.assertNotIn("db.session.add", source)


class NormalPendingDispatchTests(unittest.TestCase):
    def test_pending_dispatch_still_claims_queued_and_hands_off_once(self):
        paid = order("Pending")
        filtered = MagicMock()
        filtered.update.return_value = 1
        order_query = MagicMock()
        order_query.get.return_value = paid
        order_query.filter_by.return_value = filtered
        product_query = MagicMock()
        product_query.get.return_value = SimpleNamespace(active=True, generator="standard_v1")
        fake_order = SimpleNamespace(query=order_query)
        fake_product = SimpleNamespace(query=product_query)
        fake_db = MagicMock()
        dispatcher = ReportGenerationDispatcher()
        with patch("modules.payments.report_generation_dispatcher.Order", fake_order), \
             patch("modules.payments.report_generation_dispatcher.ReportProduct", fake_product), \
             patch("modules.payments.report_generation_dispatcher.db", fake_db), \
             patch.object(dispatcher, "_start_generation", return_value=None) as start:
            result = dispatcher.dispatch_if_pending(42)
        self.assertEqual(result.status, ReportGenerationDispatchStatus.DISPATCHED)
        start.assert_called_once_with(42)
        update_values = filtered.update.call_args.args[0]
        self.assertEqual(update_values["report_stage"], "Queued")
        self.assertIsInstance(update_values["processing_started_at"], datetime)


if __name__ == "__main__":
    unittest.main()
