"""Real-app regression for the retired public paid-report bypass.

No database, payment network, AI, PDF, or SMTP work is needed by these tests.
Run: python -m unittest test_legacy_report_endpoint_security -v
"""

from contextlib import ExitStack
import os
import sys
import unittest
from unittest.mock import patch

from test_worker_boot_lazy_clients import _clean_worker_env

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class LegacyReportEndpointSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(os.environ, _clean_worker_env(
            "postgresql://unused:unused@localhost:5432/jyotishasha_local"
        ))
        cls.environment.start()
        cls.addClassCleanup(cls.environment.stop)
        from app import app
        cls.app = app

    def test_direct_generation_is_unavailable_without_side_effects(self):
        from extensions import db
        from models import Order
        import routes.generate_report as legacy

        payload = {
            "name": "Security Gate", "email": "security-gate@example.com",
            "product": "startup_suggestion_report", "dob": "1990-01-01",
            "tob": "10:00", "pob": "Delhi", "latitude": 28.6,
            "longitude": 77.2, "language": "en",
        }
        with self.app.app_context(), ExitStack() as stack:
            sentinels = {}
            for name in (
                "calculate_full_kundali", "get_current_positions",
                "get_all_planets_next_12", "build_transit_summary_text",
                "build_prompt_from_product", "get_openai_response",
                "generate_pdf_and_email",
            ):
                sentinels[name] = stack.enter_context(patch.object(legacy, name))
            for target in (
                "tasks.generate_and_send_report",
                "report_writer.get_openai_response",
                "report_writer.generate_pdf_and_email",
                "report_writer.send_email_with_attachment",
                "email_utils.send_email", "smtplib.SMTP",
                "modules.payments.report_generation_dispatcher."
                "ReportGenerationDispatcher.dispatch_if_pending",
                "modules.payments.order_service.OrderService.create_pending_order",
                "modules.payments.order_service.OrderService.create_paid_report_order",
            ):
                sentinels[target] = stack.enter_context(patch(target))
            sentinels["Order construction"] = stack.enter_context(
                patch.object(Order, "__init__", return_value=None)
            )
            # Fail closed if any request attempts SQL, including raw INSERTs.
            sentinels["database connection"] = stack.enter_context(
                patch.object(db.engine, "connect", side_effect=AssertionError(
                    "Retired endpoint must not access the database"
                ))
            )
            client = self.app.test_client()
            for body in (payload, {**payload, "order_id": 1,
                                   "payment_status": "PAID", "status": "PAID"}):
                with self.subTest(body=body):
                    response = client.post("/api/generate-report", json=body)
                    self.assertEqual(response.status_code, 404)
            for name, sentinel in sentinels.items():
                with self.subTest(boundary=name):
                    sentinel.assert_not_called()

    def test_legacy_route_is_absent_from_production_url_map(self):
        self.assertNotIn("generate_report", self.app.blueprints)
        self.assertFalse(any(
            rule.rule.rstrip("/") == "/api/generate-report"
            for rule in self.app.url_map.iter_rules()
        ))
        client = self.app.test_client()
        for method in ("GET", "POST", "OPTIONS"):
            for path in ("/api/generate-report", "/api/generate-report/"):
                with self.subTest(method=method, path=path):
                    self.assertEqual(client.open(path, method=method).status_code, 404)

    def test_canonical_paid_routes_still_resolve_to_real_handlers(self):
        adapter = self.app.url_map.bind("localhost")
        for path, expected in (
            ("/api/razorpay-order", "create_razorpay_order"),
            ("/webhook", "webhook"),
        ):
            with self.subTest(path=path):
                endpoint, arguments = adapter.match(path, method="POST")
                self.assertEqual(endpoint, expected)
                self.assertEqual(arguments, {})
                self.assertEqual(self.app.view_functions[endpoint].__module__, "app")


if __name__ == "__main__":
    unittest.main()
