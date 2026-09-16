"""Focused, database-free DOB validation checks for both paid-order boundaries."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")

from modules.payments.order_service import OrderService, OrderValidationError, _validate_dob


def standard(dob="1990-11-03"):
    return dict(product="career_report", name="Test", email="test@example.invalid",
                phone="9999999999", dob=dob, tob="10:00", pob="Delhi",
                latitude="28.6", longitude="77.2")


def relationship(primary="1990-11-03", partner="2024-02-29"):
    payload = standard(primary)
    payload["product"] = "relationship_future_report"
    payload["partner"] = dict(name="Partner", dob=partner, tob="11:00",
                              pob="Delhi", latitude="28.6", longitude="77.2")
    return payload


class PaidReportDobValidationTests(unittest.TestCase):
    def setUp(self):
        self.query = MagicMock()
        self.db = MagicMock()
        self.patches = [
            patch("modules.payments.order_service.ReportProduct", SimpleNamespace(query=self.query)),
            patch("modules.payments.order_service.db", self.db),
            patch("modules.payments.order_service.Order", lambda **fields: SimpleNamespace(**{"id": 1, "report_stage": "Pending", **fields})),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_strict_calendar_dates(self):
        for value in ("1990-11-03", "2024-02-29"):
            with self.subTest(value=value):
                _validate_dob(value, "dob")
        for value in ("03/11/1990", "11/03/1990", "1990/11/03",
                      "1990-13-03", "1990-02-30", "2023-02-29", "",
                      None, "1990-11-03T00:00:00Z"):
            with self.subTest(value=value):
                with self.assertRaises(OrderValidationError):
                    _validate_dob(value, "dob")

    def test_pending_standard_primary_and_partner(self):
        self.query.get.return_value = SimpleNamespace(active=True, generator="standard_v1", price=51)
        order = OrderService().create_pending_order(standard())
        self.assertEqual(order.dob, "1990-11-03")
        self.assertEqual(self.db.session.add.call_count, 1)
        for invalid in ("03/11/1990", "1990-02-30", "1990-11-03T00:00:00Z", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(OrderValidationError):
                    OrderService().create_pending_order(standard(invalid))
        self.assertEqual(self.db.session.add.call_count, 1)

    def test_pending_relationship_primary_and_partner(self):
        self.query.get.return_value = SimpleNamespace(report_slug="relationship_future_report", active=True, generator="love_premium_v1", price=199)
        order = OrderService().create_pending_order(relationship())
        self.assertEqual(order.dob, "1990-11-03")
        self.assertEqual(order.partner_payload["dob"], "2024-02-29")
        for payload in (relationship(primary="2023-02-29"),
                        relationship(partner="11/03/1990"),
                        relationship(partner="1990-11-03T00:00:00Z")):
            with self.assertRaises(OrderValidationError):
                OrderService().create_pending_order(payload)
        self.assertEqual(self.db.session.add.call_count, 1)

    def test_direct_paid_boundary_primary_and_partner(self):
        service = OrderService()
        with patch.object(service, "_dispatch_report_generation", return_value=None):
            with self.assertRaises(OrderValidationError):
                service.create_paid_report_order(standard("1990-02-30"))
            with self.assertRaises(OrderValidationError):
                service.create_paid_report_order(relationship(partner="2023-02-29"))
            self.assertEqual(self.db.session.add.call_count, 0)
            order = service.create_paid_report_order(relationship())
            self.assertTrue(order.dispatched)
            self.assertEqual(self.db.session.add.call_count, 1)


if __name__ == "__main__":
    unittest.main()
