"""Q5.9 -- relationship_future_report: birth coordinates are validated BEFORE any paid order exists.

Defect: the paid relationship order only checked that latitude/longitude were PRESENT (0 counts as present), so a
customer who typed a birth place without picking a suggestion could pay for a report computed at (0, 0). The frontend
now blocks that, but a browser check is not a data-integrity boundary.

Boundary: OrderService.create_pending_order() -- the ONE place /api/razorpay-order resolves the product, validates the
payload and persists the Order, entirely BEFORE Razorpay is contacted. Only the love_premium_v1 branch changed.

Database-free and network-free: the registry lookup, the session and the Order model are stubbed, and the Razorpay
client is a mock, so no order row, payment order, Luna call, PDF or e-mail can ever result from this file.
"""
import contextlib
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")

from config.pricing import PRODUCT_PRICES  # noqa: E402
from modules.payments.order_service import OrderService, OrderValidationError  # noqa: E402

LOVE = "relationship_future_report"
STANDARD = "career_report"
BAD_NUMBERS = (float("nan"), float("inf"), float("-inf"), "nan", "NaN", "inf", "-Infinity", "abc", "12,5", "1e999", True, False, [], {})


def relationship(lat=28.6139, lng=77.2090, plat=19.0760, plng=72.8777, **overrides):
    payload = dict(product=LOVE, name="Primary", email="q59@example.invalid", dob="1990-05-01", tob="10:00",
                   pob="Delhi", latitude=lat, longitude=lng, language="en",
                   partner=dict(name="Partner", dob="1992-08-15", tob="06:30", pob="Mumbai", latitude=plat, longitude=plng))
    payload.update(overrides)
    return payload


def standard(slug=STANDARD, lat="26.8467", lng="80.9462", **overrides):
    payload = dict(product=slug, name="Customer", email="q59@example.invalid", phone="9999999999", dob="1990-06-15",
                   tob="14:30", pob="Lucknow", latitude=lat, longitude=lng, language="en")
    payload.update(overrides)
    return payload


def fake_product(slug):
    if slug == LOVE:
        return SimpleNamespace(report_slug=slug, active=True, generator="love_premium_v1", price=199, currency="INR")
    if slug in PRODUCT_PRICES:
        return SimpleNamespace(report_slug=slug, active=True, generator="standard_v1", price=PRODUCT_PRICES[slug], currency="INR")
    return None


class StubbedRegistry(unittest.TestCase):
    def setUp(self):
        self.query = MagicMock()
        self.query.get.side_effect = fake_product
        self.db = MagicMock()
        registry = SimpleNamespace(query=self.query)
        for target, replacement in (
            ("modules.payments.order_service.ReportProduct", registry),
            ("modules.payments.report_product_registry.ReportProduct", registry),
            ("modules.payments.order_service.db", self.db),
            ("modules.payments.order_service.Order", lambda **fields: SimpleNamespace(**{"id": 7, "report_stage": "Pending", **fields})),
        ):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def rows_added(self):
        return self.db.session.add.call_count

    def assert_rejected(self, payload, fragment=None):
        before = self.rows_added()
        with self.assertRaises(OrderValidationError) as caught:
            OrderService().create_pending_order(payload)
        self.assertEqual(self.rows_added(), before, "a rejected payload must never stage an Order row")
        self.assertEqual(self.db.session.commit.call_count, 0)
        if fragment:
            self.assertIn(fragment, str(caught.exception))
        return str(caught.exception)

    def assert_accepted(self, payload):
        before = self.rows_added()
        order = OrderService().create_pending_order(payload)
        self.assertEqual(self.rows_added(), before + 1)
        return order


class OrderServiceCoordinateTests(StubbedRegistry):
    # 1 / 2
    def test_1_primary_zero_zero_is_rejected(self):
        for lat, lng in ((0, 0), (0.0, 0.0), ("0", "0"), ("0.0", " 0 "), (-0.0, 0), (0, "0.00")):
            with self.subTest(lat=lat, lng=lng):
                message = self.assert_rejected(relationship(lat=lat, lng=lng), "latitude/longitude (0, 0)")
                self.assertNotIn("partner.", message)

    def test_2_partner_zero_zero_is_rejected(self):
        for plat, plng in ((0, 0), (0.0, 0.0), ("0", "0"), (-0.0, "0")):
            with self.subTest(plat=plat, plng=plng):
                self.assert_rejected(relationship(plat=plat, plng=plng), "partner.latitude/longitude (0, 0)")

    # 3 / 4 / 5
    def test_3_4_primary_with_one_zero_component_is_accepted(self):
        for lat, lng in ((0, 30), (30, 0), (0.0, -74.006), (-33.86, 0), ("0", "30.5"), ("26.8", "0")):
            with self.subTest(lat=lat, lng=lng):
                order = self.assert_accepted(relationship(lat=lat, lng=lng))
                self.assertEqual((order.latitude, order.longitude), (lat, lng), "coordinates are stored verbatim")

    def test_5_partner_with_one_zero_component_is_accepted(self):
        for plat, plng in ((0, 30), (30, 0), (0, -179.9), ("0", "45")):
            with self.subTest(plat=plat, plng=plng):
                order = self.assert_accepted(relationship(plat=plat, plng=plng))
                self.assertEqual((order.partner_payload["latitude"], order.partner_payload["longitude"]), (plat, plng))

    def test_range_edges_are_valid(self):
        for lat, lng in ((90, 180), (-90, -180), (90, -180), (-90, 180)):
            with self.subTest(lat=lat, lng=lng):
                self.assert_accepted(relationship(lat=lat, lng=lng, plat=lat, plng=lng))

    # 6 / 7
    def test_6_out_of_range_latitude_is_rejected(self):
        for bad in (90.0001, -90.0001, 91, -91, 1000, "91", "-90.5"):
            with self.subTest(bad=bad):
                self.assert_rejected(relationship(lat=bad), "latitude/longitude must be valid")
                self.assert_rejected(relationship(plat=bad), "partner.latitude/longitude must be valid")

    def test_7_out_of_range_longitude_is_rejected(self):
        for bad in (180.0001, -180.0001, 181, -181, 1000, "181", "-200"):
            with self.subTest(bad=bad):
                self.assert_rejected(relationship(lng=bad), "latitude/longitude must be valid")
                self.assert_rejected(relationship(plng=bad), "partner.latitude/longitude must be valid")

    # 8
    def test_8_nan_infinity_and_non_numeric_are_rejected(self):
        for bad in BAD_NUMBERS:
            with self.subTest(bad=repr(bad)):
                self.assert_rejected(relationship(lat=bad))
                self.assert_rejected(relationship(lng=bad))
                self.assert_rejected(relationship(plat=bad))
                self.assert_rejected(relationship(plng=bad))

    # 9
    def test_9_missing_required_coordinates_are_rejected(self):
        for missing in (None, "", "   "):
            with self.subTest(missing=missing):
                self.assert_rejected(relationship(lat=missing))
                self.assert_rejected(relationship(lng=missing))
                self.assert_rejected(relationship(plat=missing))
                self.assert_rejected(relationship(plng=missing))
        for key in ("latitude", "longitude"):
            primary_absent = relationship()
            del primary_absent[key]
            self.assert_rejected(primary_absent, key)
            partner_absent = relationship()
            del partner_absent["partner"][key]
            self.assert_rejected(partner_absent, key)

    # 10
    def test_10_valid_full_relationship_payload_passes_and_is_stored_verbatim(self):
        payload = relationship()
        order = self.assert_accepted(payload)
        self.assertEqual(order.product, LOVE)
        self.assertEqual(order.amount_paise, 19900)
        self.assertEqual((order.latitude, order.longitude), (28.6139, 77.2090))
        self.assertEqual(order.partner_payload, payload["partner"])
        string_payload = relationship(lat="28.6139", lng="77.2090", plat="19.076", plng="72.8777")
        order = self.assert_accepted(string_payload)
        self.assertEqual((order.latitude, order.longitude), ("28.6139", "77.2090"), "numeric strings still pass, unchanged")

    def test_partner_details_are_still_required_for_the_paid_flow(self):
        without_partner = relationship()
        del without_partner["partner"]
        self.assert_rejected(without_partner, "partner details are required")
        self.assert_rejected(relationship(partner={"name": "Partner", "dob": "1992-08-15"}), "Missing required partner field")

    # 12
    def test_12_every_standard_51_report_is_unchanged(self):
        standard_slugs = [slug for slug in PRODUCT_PRICES if slug != LOVE]
        self.assertEqual(len(standard_slugs), 24)
        for slug in standard_slugs:
            with self.subTest(slug=slug):
                self.assertEqual(PRODUCT_PRICES[slug], 51)
                order = self.assert_accepted(standard(slug))
                self.assertEqual((order.product, order.amount_paise), (slug, 5100))
                # the frozen standard contract only requires coordinates to be PRESENT, exactly as before
                order = self.assert_accepted(standard(slug, lat=0, lng=0))
                self.assertEqual((order.latitude, order.longitude), (0, 0))
        self.assertEqual(PRODUCT_PRICES[LOVE], 199)

    def test_12b_standard_partner_payload_is_still_stored_verbatim_and_never_coordinate_checked(self):
        partner = dict(name="P", dob="1992-08-15", latitude=0, longitude=0)
        order = self.assert_accepted(standard(partner=partner))
        self.assertEqual(order.partner_payload, partner)

    def test_12c_standard_missing_field_rules_are_unchanged(self):
        self.assert_rejected(standard(lat=None), "Missing required field(s): latitude")
        payload = standard()
        del payload["phone"]
        self.assert_rejected(payload, "phone")

    # 11
    def test_11_dob_only_partner_analysis_still_works_outside_the_paid_order_contract(self):
        """The compatibility collector (unpaid / internal / partial analysis) is untouched: a partner with only name + DOB,
        or an unusable (0, 0) partner place, still produces a report payload -- it is the PAID order that now demands
        full, valid birth data."""
        from modules.love import love_data_collector as collector

        self.assertNotIn("lat", collector._with_engine_coordinates({"name": "P", "dob": "1992-08-15"}))
        self.assertNotIn("lat", collector._with_engine_coordinates({"name": "P", "dob": "1992-08-15", "latitude": 0, "longitude": 0}))
        usable = collector._with_engine_coordinates({"name": "P", "dob": "1992-08-15", "latitude": 0, "longitude": 30})
        self.assertEqual((usable["lat"], usable["lng"]), (0, 30))

        from full_kundali_api import calculate_full_kundali
        with contextlib.redirect_stdout(io.StringIO()):
            kundali = calculate_full_kundali(name="A", dob="1990-06-15", tob="14:30", lat=26.8467, lon=80.9462, language="en")
            for partner in ({"name": "B", "dob": "1992-08-15"},
                            {"name": "B", "dob": "1992-08-15", "tob": "06:30", "pob": "Mumbai", "latitude": 0, "longitude": 0}):
                order = dict(name="A", dob="1990-06-15", tob="14:30", pob="Lucknow", latitude=26.8467, longitude=80.9462,
                             language="en", partner=partner)
                payload = collector.collect_love_report_data(order, kundali, "en")
                self.assertIn("compatibility", payload)


# --------------------------------------------------------------------------------------------------------------------
# The REAL POST /api/razorpay-order route: invalid coordinates never reach the (mocked) Razorpay order-creation call.
# --------------------------------------------------------------------------------------------------------------------
try:
    os.environ["DATABASE_URL"] = "postgresql://sample:unused@localhost:5432/jyotishasha_local"  # never connected: everything is stubbed
    os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
    import app as app_module  # noqa: E402
    APP_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment without the app's own required settings
    app_module = None
    APP_IMPORT_ERROR = repr(exc)


@unittest.skipIf(app_module is None, f"Flask app could not be imported in this environment: {APP_IMPORT_ERROR}")
class RazorpayOrderRouteTests(StubbedRegistry):
    def setUp(self):
        super().setUp()
        self.razorpay = MagicMock()
        self.razorpay.order.create.return_value = {"id": "order_stub_1", "currency": "INR"}
        for target, replacement in (("app.razorpay_client", self.razorpay), ("app.db", MagicMock())):
            patcher = patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app_module.app.test_client()

    def post(self, payload):
        # json.dumps writes NaN/Infinity literals, which Flask's JSON parser accepts -- the realistic worst case
        return self.client.post("/api/razorpay-order", data=json.dumps(payload), content_type="application/json")

    def assert_blocked_before_razorpay(self, payload):
        response = self.post(payload)
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(set(body), {"error", "message"}, "same 4xx shape the frontend already receives for other validation errors")
        self.assertEqual(body["error"], "invalid_request")
        self.assertIn("latitude", body["message"])  # the invalid-coordinate wording, or the existing "Missing required field(s): latitude"
        self.assertEqual(self.razorpay.order.create.call_count, 0, "Razorpay order creation must never be reached")
        self.assertEqual(self.rows_added(), 0, "no internal order may be created")
        return body

    def test_invalid_relationship_coordinates_never_reach_razorpay(self):
        cases = {
            "primary (0,0)": relationship(lat=0, lng=0),
            "partner (0,0)": relationship(plat=0, plng=0),
            "primary lat out of range": relationship(lat=91),
            "primary lng out of range": relationship(lng=181),
            "partner lat out of range": relationship(plat=-91),
            "partner lng out of range": relationship(plng=-181),
            "primary NaN": relationship(lat=float("nan")),
            "primary Infinity": relationship(lng=float("inf")),
            "partner NaN": relationship(plat=float("nan")),
            "primary non-numeric": relationship(lat="abc"),
            "partner non-numeric": relationship(plng="north"),
            "primary missing": relationship(lat=None),
            "partner missing": relationship(plat=""),
        }
        for label, payload in cases.items():
            with self.subTest(case=label):
                self.assert_blocked_before_razorpay(payload)

    def test_partner_zero_zero_message_names_the_partner(self):
        body = self.assert_blocked_before_razorpay(relationship(plat=0, plng=0))
        self.assertIn("partner.latitude/longitude (0, 0)", body["message"])

    def test_valid_relationship_orders_still_reach_razorpay_at_199(self):
        for lat, lng, plat, plng in ((28.6139, 77.209, 19.076, 72.8777), (0, 30, 30, 0), (26.8467, 80.9462, 40.7128, -74.006)):
            with self.subTest(lat=lat, lng=lng, plat=plat, plng=plng):
                self.razorpay.order.create.reset_mock()
                response = self.post(relationship(lat=lat, lng=lng, plat=plat, plng=plng))
                self.assertEqual(response.status_code, 200)
                body = response.get_json()
                self.assertEqual((body["order_id"], body["amount"], body["product"]), ("order_stub_1", 19900, LOVE))
                self.assertEqual(self.razorpay.order.create.call_count, 1)
                self.assertEqual(self.razorpay.order.create.call_args[0][0]["amount"], 19900)

    def test_standard_51_route_is_unchanged(self):
        for slug in ("career_report", "startup_suggestion_report", "sadhesati_report"):
            for lat, lng in (("26.8467", "80.9462"), (0, 0)):
                with self.subTest(slug=slug, lat=lat, lng=lng):
                    self.razorpay.order.create.reset_mock()
                    response = self.post(standard(slug, lat=lat, lng=lng))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json()["amount"], 5100)
                    self.assertEqual(self.razorpay.order.create.call_count, 1)
                    self.assertEqual(self.razorpay.order.create.call_args[0][0]["amount"], 5100)


if __name__ == "__main__":
    unittest.main()
