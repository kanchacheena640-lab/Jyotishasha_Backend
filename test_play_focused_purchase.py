"""Google Play focused-report purchases: reports51 for all 63, and order fields validated BEFORE the token claim.

A bad form must be refused while the purchase token is still unclaimed; refused after the claim it would leave a
paid purchase that can never become a report. Database-free: ReportProduct/Order/db/dispatch are stubbed and the
real PaymentService + OrderService run.
"""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")

from modules.intents.question_catalog import QUESTIONS
from modules.payments import order_service as order_module
from modules.payments.order_service import OrderService, OrderValidationError
from modules.payments.payment_models import (
    PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus, PaymentVerificationResult,
)
from modules.payments.payment_service import PaymentService

DUAL_KEYS = sorted(q.question_key for q in QUESTIONS if q.person_mode == "dual")
SINGLE_KEYS = sorted(q.question_key for q in QUESTIONS if q.person_mode == "single")


def generator_for(slug):
    if slug in DUAL_KEYS:
        return "focused_dual_v1"
    if slug in SINGLE_KEYS:
        return "focused_v1"
    return "love_premium_v1" if slug == "relationship_future_report" else "standard_v1"


def registry(slug, price):
    return SimpleNamespace(report_slug=slug, active=True, generator=generator_for(slug), price=price, currency="INR")


def person(**extra):
    return {"name": "Partner", "dob": "1991-12-04", "tob": "11:00", "pob": "Delhi", "latitude": 28.6, "longitude": 77.2,
            **extra}


def payload(slug, **extra):
    data = dict(product=slug, name="Play Buyer", email="play@example.invalid", phone="9999999999", dob="1990-11-03",
                tob="10:00", pob="Lucknow", latitude=26.8, longitude=80.9, language="en")
    if slug in DUAL_KEYS or slug == "relationship_future_report":
        data["partner"] = person()
    data.update(extra)
    return data


def verified(product_id):
    return PaymentVerificationResult(status=PaymentStatus.VERIFIED, provider=PaymentProviderType.GOOGLE_PLAY,
                                     reference="token", verified=True, raw_payload={"product_id": product_id})


class PlayCase(unittest.TestCase):
    def process(self, slug, price, play_id, order_payload):
        """Run the real PaymentService.process_payment up to the claim; return (claim mock, created orders)."""
        provider = MagicMock()
        provider.verify.return_value = verified(play_id)
        providers = MagicMock()
        providers.resolve.return_value = provider
        service = PaymentService(provider_registry=providers, order_service=OrderService())
        request = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                                 reference="token", payment_id="token", order_payload=order_payload,
                                 metadata={"product_id": play_id})
        with patch.object(order_module, "ReportProduct") as products, patch.object(order_module, "Order") as orders, \
             patch.object(service, "_find_processed_payment_logged", return_value=None), \
             patch.object(service, "_try_claim", side_effect=RuntimeError("claimed")) as claim:
            products.query.get.return_value = registry(slug, price)
            try:
                service.process_payment(request)
            except RuntimeError as exc:
                self.assertEqual(str(exc), "claimed")
        return claim, orders

    def assert_refused_before_claim(self, slug, order_payload, play_id="reports51", price=51):
        with self.assertRaises(OrderValidationError):
            self.process(slug, price, play_id, order_payload)


class FocusedPlayPurchaseTests(PlayCase):
    def test_catalogue_has_63_focused_reports_9_of_them_two_person(self):
        self.assertEqual(len(QUESTIONS), 63)
        self.assertEqual(len(DUAL_KEYS), 9)

    def test_valid_reports51_purchase_of_every_focused_report_reaches_the_claim(self):
        for slug in SINGLE_KEYS + DUAL_KEYS:
            with self.subTest(slug=slug):
                claim, orders = self.process(slug, 51, "reports51", payload(slug))
                claim.assert_called_once()
                orders.assert_not_called()

    def test_every_focused_report_records_5100_paise(self):
        for slug in SINGLE_KEYS + DUAL_KEYS:
            with self.subTest(slug=slug):
                seen = {}
                with patch.object(order_module, "ReportProduct") as products, patch.object(order_module, "db"), \
                     patch.object(order_module, "Order", side_effect=lambda **f: seen.update(f) or SimpleNamespace(
                         **{"report_stage": "Pending", **f, "id": 1})), \
                     patch.object(OrderService, "_dispatch_report_generation", return_value=None):
                    products.query.get.return_value = registry(slug, 51)
                    request = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY,
                                             purpose=PaymentPurpose.REPORT_PURCHASE, reference="token",
                                             payment_id="token", order_payload=payload(slug))
                    PaymentService(provider_registry=MagicMock(), order_service=OrderService())._apply_business_effect(
                        request, verified("reports51"))
                self.assertEqual(seen["amount_paise"], 5100)
                self.assertEqual(seen["product"], slug)
                if slug in DUAL_KEYS:
                    self.assertEqual(seen["partner_payload"]["name"], "Partner")

    def test_cross_tier_play_products_are_refused_for_focused_reports(self):
        for play_id in ("reports99", "relationship_report199"):
            for slug in ("promotion_timing", "kundali_match_for_marriage"):
                with self.subTest(play_id=play_id, slug=slug):
                    self.assert_refused_before_claim(slug, payload(slug), play_id)

    def test_all_9_two_person_reports_require_complete_partner_details_before_the_claim(self):
        broken_partners = {
            "missing": None,
            "empty": {},
            "no tob": person(tob=""),
            "bad tob": person(tob="7 PM"),
            "bad dob": person(dob="04-12-1991"),
            "no coordinates": person(latitude=None, longitude=None),
            "null island": person(latitude=0, longitude=0),
            "lat/lng keys only": {k: v for k, v in person(lat=28.6, lng=77.2).items() if k not in ("latitude", "longitude")},
        }
        for slug in DUAL_KEYS:
            for label, partner in broken_partners.items():
                with self.subTest(slug=slug, partner=label):
                    data = payload(slug)
                    data.pop("partner")
                    if partner is not None:
                        data["partner"] = partner
                    self.assert_refused_before_claim(slug, data)

    def test_invalid_primary_details_are_refused_before_the_claim(self):
        cases = {
            "no phone (single)": dict(phone=""),
            "bad dob": dict(dob="1990-02-30"),
            "dob not iso": dict(dob="03/11/1990"),
            "hour out of range": dict(tob="25:00"),
            "unpadded time": dict(tob="9:5"),
            "time with seconds": dict(tob="10:00:00"),
            "12-hour time": dict(tob="10:00 AM"),
            "no coordinates": dict(latitude=None, longitude=None),
            "typed place, no coordinates": dict(pob="Somewhere", latitude="", longitude=""),
            "null island": dict(latitude=0, longitude=0),
            "latitude out of range": dict(latitude=95),
            "name too long for Order.name": dict(name="N" * 51),
            "phone too long for Order.phone": dict(phone="9" * 21),
        }
        for slug in ("promotion_timing", "kundali_match_for_marriage"):
            for label, change in cases.items():
                if slug in DUAL_KEYS and label == "no phone (single)":
                    continue
                with self.subTest(slug=slug, case=label):
                    self.assert_refused_before_claim(slug, payload(slug, **change))

    def test_two_person_focused_reports_need_no_phone_matching_the_website(self):
        claim, _ = self.process("kundali_match_for_marriage", 51, "reports51",
                                payload("kundali_match_for_marriage", phone=""))
        claim.assert_called_once()

    def test_a_replayed_token_takes_the_retry_path_before_any_validation(self):
        provider = MagicMock()
        provider.verify.return_value = verified("reports51")
        providers = MagicMock()
        providers.resolve.return_value = provider
        orders = MagicMock()
        service = PaymentService(provider_registry=providers, order_service=orders)
        request = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                                 reference="token", payment_id="token",
                                 order_payload=payload("promotion_timing", tob="bad"), metadata={"product_id": "reports51"})
        duplicate = PaymentVerificationResult(status=PaymentStatus.DUPLICATE, provider=PaymentProviderType.GOOGLE_PLAY,
                                              reference="token", verified=True)
        with patch.object(service, "_find_processed_payment_logged", return_value=object()), \
             patch.object(service, "_handle_retry", return_value=duplicate) as retry, \
             patch.object(service, "_try_claim") as claim:
            self.assertIs(service.process_payment(request), duplicate)
        retry.assert_called_once()
        claim.assert_not_called()
        orders.validate_paid_report_order.assert_not_called()
        orders.create_paid_report_order.assert_not_called()


class ExistingProductsRegressionTests(PlayCase):
    """Older app versions send base and relationship purchases with their existing, looser fields: still accepted."""

    def old_app_payload(self, slug):
        data = dict(product=slug, name="Old App", email="old@example.invalid", dob="1990-11-03", tob="10:00 AM",
                    pob="Typed City")
        if slug == "relationship_future_report":
            data["partner"] = {"name": "P", "dob": "1991-12-04", "tob": "11:00", "pob": "Delhi", "lat": 28.6, "lng": 77.2}
        return data

    def test_base_reports_via_reports99_and_legacy_reports51_still_reach_the_claim(self):
        for price, play_id in ((99, "reports99"), (99, "reports51"), (51, "reports51")):
            with self.subTest(price=price, play_id=play_id):
                claim, _ = self.process("career_report", price, play_id, self.old_app_payload("career_report"))
                claim.assert_called_once()

    def test_relationship_199_still_reaches_the_claim(self):
        claim, _ = self.process("relationship_future_report", 199, "relationship_report199",
                                self.old_app_payload("relationship_future_report"))
        claim.assert_called_once()

    def test_base_report_with_a_bad_dob_is_now_refused_before_the_claim_not_after(self):
        self.assert_refused_before_claim("career_report", dict(self.old_app_payload("career_report"), dob="1990-13-01"),
                                         "reports99", 99)


class WebsitePendingOrderTests(unittest.TestCase):
    """create_pending_order() (website) uses the same shared rules; only focused reports gain the time check."""

    def create(self, slug, **change):
        data = payload(slug, **change)
        with patch.object(order_module, "ReportProduct") as products, patch.object(order_module, "db"), \
             patch.object(order_module, "Order", side_effect=lambda **f: SimpleNamespace(**f)):
            products.query.get.return_value = registry(slug, 99 if generator_for(slug) == "standard_v1" else 51)
            return OrderService().create_pending_order(data)

    def test_focused_orders_validate_birth_time(self):
        for slug in ("promotion_timing", "kundali_match_for_marriage"):
            with self.subTest(slug=slug):
                self.assertEqual(self.create(slug).tob, "10:00")
                with self.assertRaises(OrderValidationError):
                    self.create(slug, tob="25:61")

    def test_two_person_focused_partner_time_is_validated(self):
        with self.assertRaises(OrderValidationError):
            self.create("kundali_match_for_marriage", partner=person(tob="noon"))

    def test_standard_and_relationship_orders_are_unchanged(self):
        self.assertEqual(self.create("career_report", tob="10:00 AM").tob, "10:00 AM")
        self.assertEqual(self.create("relationship_future_report", tob="10:00 AM").tob, "10:00 AM")


if __name__ == "__main__":
    unittest.main(verbosity=2)
