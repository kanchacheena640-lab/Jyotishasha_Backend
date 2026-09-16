"""Focused, database-free Google paid-report product authority checks."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from flask import Flask

os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")

from modules.payments.order_service import OrderService, OrderValidationError
from modules.payments.payment_models import (
    PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus,
    PaymentVerificationResult,
)
from modules.payments.payment_service import PaymentService
from routes.routes_google_report_confirm import routes_google_report_confirm
from config.google_play_report_products import (
    RELATIONSHIP_REPORT_PRODUCT_ID, STANDARD_REPORT_PRODUCT_ID,
)


def payload(product="career_report", **extra):
    data = dict(product=product, name="Test", email="test@example.invalid",
                phone="9999999999", dob="1990-11-03", tob="10:00",
                pob="Delhi", latitude="28.6", longitude="77.2")
    data.update(extra)
    return data


class GoogleReportProductAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.query = MagicMock()
        self.db = MagicMock()
        self.order = MagicMock(side_effect=lambda **fields: SimpleNamespace(
            **{"id": 1, "report_stage": "Pending", **fields}))
        self.patches = [
            patch("modules.payments.order_service.ReportProduct", SimpleNamespace(query=self.query)),
            patch("modules.payments.order_service.db", self.db),
            patch("modules.payments.order_service.Order", self.order),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def _create(self, requested, registered, **extra):
        self.query.get.return_value = registered
        service = OrderService()
        with patch.object(service, "_dispatch_report_generation", return_value=None):
            service.create_paid_report_order(payload(requested, amount_paise=1, **extra))
        return self.order.call_args.kwargs

    def test_active_standard_uses_canonical_product_and_registry_price(self):
        fields = self._create("  CAREER_REPORT  ", SimpleNamespace(
            report_slug="career_report", active=True, price=51))
        self.assertEqual(fields["product"], "career_report")
        self.assertEqual(fields["amount_paise"], 5100)

    def test_active_relationship_is_accepted(self):
        partner = dict(name="Partner", dob="1991-12-04", tob="11:00",
                       pob="Delhi", latitude="28.6", longitude="77.2")
        fields = self._create("relationship_future_report", SimpleNamespace(
            report_slug="relationship_future_report", active=True, price=199), partner=partner)
        # Registry acceptance is independent of the Play SKU price decision.
        self.assertEqual(fields["product"], "relationship_future_report")
        self.assertEqual(fields["amount_paise"], 19900)

    def test_unknown_and_inactive_create_no_order(self):
        service = OrderService()
        for registered in (None, SimpleNamespace(report_slug="career_report", active=False, price=51)):
            self.query.get.return_value = registered
            with self.subTest(registered=registered):
                with self.assertRaises(OrderValidationError):
                    service.create_paid_report_order(payload())
        self.order.assert_not_called()
        self.db.session.add.assert_not_called()

    def test_invalid_product_is_rejected_before_token_claim(self):
        provider = MagicMock()
        provider.verify.return_value = PaymentVerificationResult(
            status=PaymentStatus.VERIFIED, provider=PaymentProviderType.GOOGLE_PLAY,
            reference="token", verified=True)
        registry = MagicMock()
        registry.resolve.return_value = provider
        order_service = MagicMock()
        order_service.resolve_paid_report_product.side_effect = OrderValidationError("Unknown report product")
        service = PaymentService(provider_registry=registry, order_service=order_service)
        request = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY,
            purpose=PaymentPurpose.REPORT_PURCHASE, reference="token",
            payment_id="token", order_payload=payload("unknown"))
        with patch.object(service, "_find_processed_payment_logged", return_value=None), \
             patch.object(service, "_try_claim") as claim:
            with self.assertRaises(OrderValidationError):
                service.process_payment(request)
        claim.assert_not_called()
        order_service.create_paid_report_order.assert_not_called()

    def test_existing_duplicate_keeps_idempotent_retry_path(self):
        provider = MagicMock()
        provider.verify.return_value = PaymentVerificationResult(
            status=PaymentStatus.VERIFIED, provider=PaymentProviderType.GOOGLE_PLAY,
            reference="token", verified=True)
        registry = MagicMock()
        registry.resolve.return_value = provider
        order_service = MagicMock()
        service = PaymentService(provider_registry=registry, order_service=order_service)
        request = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY,
            purpose=PaymentPurpose.REPORT_PURCHASE, reference="token",
            payment_id="token", order_payload=payload())
        duplicate = PaymentVerificationResult(
            status=PaymentStatus.DUPLICATE, provider=PaymentProviderType.GOOGLE_PLAY,
            reference="token", verified=True)
        with patch.object(service, "_find_processed_payment_logged", return_value=object()), \
             patch.object(service, "_handle_retry", return_value=duplicate), \
             patch.object(service, "_try_claim") as claim:
            result = service.process_payment(request)
        self.assertIs(result, duplicate)
        claim.assert_not_called()
        order_service.resolve_paid_report_product.assert_not_called()

    def _verified_request(self, report_slug, play_product_id, registry_product):
        provider = MagicMock()
        provider.verify.return_value = PaymentVerificationResult(
            status=PaymentStatus.VERIFIED,
            provider=PaymentProviderType.GOOGLE_PLAY,
            reference="token",
            verified=True,
            raw_payload={"product_id": play_product_id},
        )
        registry = MagicMock()
        registry.resolve.return_value = provider
        order_service = MagicMock()
        order_service.resolve_paid_report_product.return_value = registry_product
        service = PaymentService(provider_registry=registry, order_service=order_service)
        request = PaymentRequest(
            provider=PaymentProviderType.GOOGLE_PLAY,
            purpose=PaymentPurpose.REPORT_PURCHASE,
            reference="token",
            payment_id="token",
            order_payload=payload(report_slug),
            metadata={"product_id": play_product_id},
        )
        return service, order_service, request

    def test_correct_standard_and_relationship_products_reach_token_claim(self):
        cases = (
            ("career_report", STANDARD_REPORT_PRODUCT_ID,
             SimpleNamespace(report_slug="career_report", price=51)),
            ("relationship_future_report", RELATIONSHIP_REPORT_PRODUCT_ID,
             SimpleNamespace(report_slug="relationship_future_report", price=199)),
        )
        for slug, play_id, registered in cases:
            with self.subTest(slug=slug):
                service, _, request = self._verified_request(slug, play_id, registered)
                with patch.object(service, "_find_processed_payment_logged", return_value=None), \
                     patch.object(service, "_try_claim", return_value=False) as claim:
                    result = service.process_payment(request)
                self.assertEqual(result.status, PaymentStatus.DUPLICATE)
                claim.assert_called_once_with(request)

    def test_cross_tier_products_are_rejected_before_claim_or_order(self):
        cases = (
            ("relationship_future_report", STANDARD_REPORT_PRODUCT_ID,
             SimpleNamespace(report_slug="relationship_future_report", price=199)),
            ("career_report", RELATIONSHIP_REPORT_PRODUCT_ID,
             SimpleNamespace(report_slug="career_report", price=51)),
        )
        for slug, play_id, registered in cases:
            with self.subTest(slug=slug, play_id=play_id):
                service, order_service, request = self._verified_request(slug, play_id, registered)
                with patch.object(service, "_find_processed_payment_logged", return_value=None), \
                     patch.object(service, "_try_claim") as claim:
                    with self.assertRaisesRegex(OrderValidationError, "does not match"):
                        service.process_payment(request)
                claim.assert_not_called()
                order_service.create_paid_report_order.assert_not_called()


class GoogleReportProductRouteTests(unittest.TestCase):
    def test_product_validation_error_is_controlled_400(self):
        app = Flask(__name__)
        app.register_blueprint(routes_google_report_confirm)
        body = dict(payload(), purchase_token="token", product_id="reports51")
        with patch("routes.routes_google_report_confirm.PaymentService") as service:
            service.return_value.process_payment.side_effect = OrderValidationError(
                "Unknown report product: 'unknown'")
            body["product"] = "unknown"
            response = app.test_client().post("/api/reports/google/confirm", json=body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown report product", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
