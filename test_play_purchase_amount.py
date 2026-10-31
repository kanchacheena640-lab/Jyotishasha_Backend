"""A verified Google Play report purchase records what Google charged for its product, never the registry price.

reports51 -> 5100, reports99 -> 9900, relationship_report199 -> 19900, at either standard registry price (Rs51 / Rs99).
Database-free: the real PaymentService and OrderService.create_paid_report_order run with Order/db/dispatch stubbed.
"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")

from config.google_play_report_products import PLAY_PRODUCT_AMOUNT_PAISE
from modules.payments import order_service as order_module
from modules.payments.order_service import OrderService, OrderValidationError
from modules.payments.payment_models import (
    PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus, PaymentVerificationResult,
)
from modules.payments.payment_service import PaymentService


def payload(product="career_report", **extra):
    data = dict(product=product, name="Play Buyer", email="play@example.invalid", phone="9999999999",
                dob="1990-11-03", tob="10:00", pob="Delhi", latitude=28.6, longitude=77.2, language="en")
    if product == "relationship_future_report":
        data["partner"] = dict(name="Partner", dob="1991-12-04", tob="11:00", pob="Delhi", latitude=28.6, longitude=77.2)
    data.update(extra)
    return data


def registry(slug, price):
    generator = "love_premium_v1" if slug == "relationship_future_report" else "standard_v1"
    return SimpleNamespace(report_slug=slug, active=True, generator=generator, price=price, currency="INR")


def verified(product_id, provider=PaymentProviderType.GOOGLE_PLAY):
    return PaymentVerificationResult(status=PaymentStatus.VERIFIED, provider=provider, reference="token",
                                     verified=True, raw_payload={"product_id": product_id})


class PlayPurchaseAmountTests(unittest.TestCase):
    def create(self, slug, db_price, verification, provider=PaymentProviderType.GOOGLE_PLAY, client_product_id=None):
        """Run the real business effect; return the amount_paise the Order was created with."""
        seen = {}

        def make_order(**fields):
            seen.update(fields)
            return SimpleNamespace(**{"status": "PAID", "report_stage": "Pending", **fields, "id": 7})

        request = PaymentRequest(provider=provider, purpose=PaymentPurpose.REPORT_PURCHASE, reference="token",
                                 payment_id="token", order_payload=payload(slug),
                                 metadata={"product_id": client_product_id} if client_product_id else None)
        with patch.object(order_module, "ReportProduct") as products, patch.object(order_module, "db"), \
             patch.object(order_module, "Order", side_effect=make_order), \
             patch.object(OrderService, "_dispatch_report_generation", return_value=None):
            products.query.get.return_value = registry(slug, db_price)
            service = PaymentService(provider_registry=MagicMock(), order_service=OrderService())
            service._apply_business_effect(request, verification)
        return seen["amount_paise"]

    def test_the_four_standard_combinations_record_the_amount_google_charged(self):
        for db_price, play_id, expected in ((51, "reports51", 5100), (99, "reports51", 5100),
                                            (51, "reports99", 9900), (99, "reports99", 9900)):
            with self.subTest(db_price=db_price, play_id=play_id):
                self.assertEqual(self.create("career_report", db_price, verified(play_id)), expected)

    def test_relationship_records_19900(self):
        self.assertEqual(self.create("relationship_future_report", 199, verified("relationship_report199")), 19900)

    def test_the_google_verified_product_wins_over_a_client_supplied_one(self):
        # Client claims reports99, Google verified the token as reports51 -> recorded as the Rs51 Google charged.
        self.assertEqual(self.create("career_report", 99, verified("reports51"), client_product_id="reports99"), 5100)

    def test_a_verified_product_without_a_configured_amount_creates_no_order(self):
        with self.assertRaises(OrderValidationError):
            self.create("career_report", 99, verified("reports999"))

    def test_razorpay_and_other_providers_keep_the_registry_price(self):
        self.assertEqual(self.create("career_report", 99, verified("anything", PaymentProviderType.RAZORPAY),
                                     provider=PaymentProviderType.RAZORPAY), 9900)
        self.assertEqual(self.create("career_report", 51, verified("anything", PaymentProviderType.RAZORPAY),
                                     provider=PaymentProviderType.RAZORPAY), 5100)

    def test_amount_map_is_exactly_the_three_play_products(self):
        self.assertEqual(PLAY_PRODUCT_AMOUNT_PAISE, {"reports51": 5100, "reports99": 9900, "relationship_report199": 19900})


class PlayPurchaseGuardTests(unittest.TestCase):
    def service_for(self, play_id, registered):
        provider = MagicMock()
        provider.verify.return_value = verified(play_id)
        providers = MagicMock()
        providers.resolve.return_value = provider
        orders = MagicMock()
        orders.resolve_paid_report_product.return_value = registered
        service = PaymentService(provider_registry=providers, order_service=orders)
        request = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                                 reference="token", payment_id="token", order_payload=payload(registered.report_slug),
                                 metadata={"product_id": play_id})
        return service, orders, request

    def test_forged_or_cross_tier_product_ids_are_rejected_before_claim_or_order(self):
        for play_id, registered in (("relationship_report199", registry("career_report", 99)),
                                    ("reports99", registry("relationship_future_report", 199)),
                                    ("reports51", registry("relationship_future_report", 199)),
                                    ("reports999", registry("career_report", 99))):
            with self.subTest(play_id=play_id, slug=registered.report_slug):
                service, orders, request = self.service_for(play_id, registered)
                with patch.object(service, "_find_processed_payment_logged", return_value=None), \
                     patch.object(service, "_try_claim") as claim:
                    with self.assertRaisesRegex(OrderValidationError, "does not match"):
                        service.process_payment(request)
                claim.assert_not_called()
                orders.create_paid_report_order.assert_not_called()

    def test_a_duplicate_purchase_takes_the_idempotent_retry_path_and_creates_no_new_order(self):
        for play_id in ("reports51", "reports99"):
            with self.subTest(play_id=play_id):
                service, orders, request = self.service_for(play_id, registry("career_report", 99))
                duplicate = PaymentVerificationResult(status=PaymentStatus.DUPLICATE, provider=PaymentProviderType.GOOGLE_PLAY,
                                                      reference="token", verified=True)
                with patch.object(service, "_find_processed_payment_logged", return_value=object()), \
                     patch.object(service, "_handle_retry", return_value=duplicate) as retry, \
                     patch.object(service, "_try_claim") as claim:
                    self.assertIs(service.process_payment(request), duplicate)
                retry.assert_called_once()
                claim.assert_not_called()
                orders.create_paid_report_order.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
