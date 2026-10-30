"""Regression tests for F12-P3.7: the buyer's explicit bride/groom role for the 9 two-person focused reports.

Checkout must name the buyer's role (never assumed), the paid router must pass it through as boy_is_user, and the
frozen Ashtakoot engine must receive the bride/groom Moons in that order. No database, network, AI, payment or email.
"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_focused_promotion_prototype import frozen_clock, FIXTURE
from modules.focused_reports import paid_report_router as router
from modules.focused_reports import relationship_evidence as collector
from modules.focused_reports.relationship_keys import RELATIONSHIP_QUESTION_KEYS as KEYS, RELATIONSHIP_SELECTIONS, ALL_KOOTAS
from modules.focused_reports.relationship_reports import build_relationship_report_prompt
from modules.intents.question_catalog import QUESTIONS
from modules.love.ashtakoot_love import compute_ashtakoot
from modules.payments import order_service

# Buyer Moon: Aquarius (Shudra varna). Partner Moon: Aries (Kshatriya varna). Varna is asymmetric for this pair,
# so the roles visibly change the frozen engine's result: buyer as bride -> Varna 1, 24.5/36; as groom -> 0, 23.5/36.
BUYER = {**FIXTURE, "lng": FIXTURE["lon"]}
PARTNER = {**BUYER, "name": "Partner Fixture", "dob": "1992-08-20", "tob": "09:15"}
ROLE_LABELS = {"bride": "Groom role: Partner; bride role: Primary person",
               "groom": "Groom role: Primary person; bride role: Partner"}
GOLDEN_MATCH = {"bride": (1, 24.5), "groom": (0, 23.5)}


def order_payload(product, **extra):
    return {"product": product, "name": BUYER["name"], "email": "p37@example.invalid", "phone": "9999999999",
            "dob": BUYER["dob"], "tob": BUYER["tob"], "pob": BUYER["pob"], "latitude": "26.8467",
            "longitude": "80.9462", "language": "en",
            "partner": {"name": PARTNER["name"], "dob": PARTNER["dob"], "tob": PARTNER["tob"], "pob": PARTNER["pob"],
                        "latitude": "26.8467", "longitude": "80.9462"}, **extra}


class CatalogTests(unittest.TestCase):
    def test_the_nine_two_person_products_are_the_relationship_keys(self):
        duals = {q.question_key for q in QUESTIONS if q.person_mode == "dual"}
        self.assertEqual(len(duals), 9)
        self.assertEqual(duals, set(KEYS))


class CheckoutRoleTests(unittest.TestCase):
    def create(self, payload, generator="focused_dual_v1"):
        product = SimpleNamespace(active=True, generator=generator, price=51)
        with patch.object(order_service, "ReportProduct") as products, \
             patch.object(order_service, "db") as db, \
             patch.object(order_service, "Order", side_effect=lambda **kw: SimpleNamespace(**kw)):
            products.query.get.return_value = product
            order = order_service.OrderService().create_pending_order(payload)
        return order, db

    def test_role_validator(self):
        for raw, role in (("bride", "bride"), ("groom", "groom"), (" Bride ", "bride"), ("GROOM", "groom")):
            self.assertEqual(order_service._validate_buyer_role(raw), role)
        for bad in (None, "", "  ", "boy", "girl", "male", "female", "husband", True, 1, ["bride"]):
            with self.assertRaises(order_service.OrderValidationError):
                order_service._validate_buyer_role(bad)

    def test_all_nine_products_refuse_a_missing_or_ambiguous_role_before_any_order_exists(self):
        for key in KEYS:
            for extra in ({}, {"buyer_role": None}, {"buyer_role": "boy"}, {"boy_is_user": True}):
                with self.subTest(key=key, extra=extra), self.assertRaises(order_service.OrderValidationError) as ctx:
                    self.create(order_payload(key, **extra))
                self.assertIn("buyer_role", str(ctx.exception))

    def test_all_nine_products_store_the_role_and_keep_both_identities(self):
        for key in KEYS:
            for role in ("bride", "groom"):
                payload = order_payload(key, buyer_role=role.upper())
                original_partner = copy.deepcopy(payload["partner"])
                order, db = self.create(payload)
                self.assertEqual(order.partner_payload, {**original_partner, "buyer_role": role}, key)
                self.assertEqual((order.name, order.dob, order.tob), (BUYER["name"], BUYER["dob"], BUYER["tob"]))
                self.assertEqual(payload["partner"], original_partner, "caller payload must not be mutated")
                db.session.add.assert_called_once()

    def test_love_premium_and_single_person_orders_are_unchanged(self):
        order, _ = self.create(order_payload("relationship_future_report"), generator="love_premium_v1")
        self.assertNotIn("buyer_role", order.partner_payload)
        single = order_payload("promotion_timing")
        single.pop("partner")
        order, _ = self.create(single, generator="focused_v1")
        self.assertIsNone(order.partner_payload)


class PaidRouterRoleTests(unittest.TestCase):
    def route(self, key, partner_payload):
        order = SimpleNamespace(id=7, product=key, name=BUYER["name"], dob=BUYER["dob"], tob=BUYER["tob"],
                                pob=BUYER["pob"], latitude=26.8467, longitude=80.9462, language="en",
                                partner_payload=partner_payload, report_stage="Queued", processing_started_at=None,
                                pdf_url=None)
        product = SimpleNamespace(generator="focused_dual_v1" if key in KEYS else "focused_v1")
        generate = MagicMock(return_value={})
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(router, "Order") as orders, patch.object(router, "ReportProduct") as products, \
             patch.object(router, "db"), patch.object(router, "generate_focused_report", generate), \
             patch.object(router, "calculate_full_kundali", return_value={"kundali": "self"}) as kundali, \
             patch.object(router, "render_focused_report_pdf", return_value=tmp + "/r.pdf"), \
             patch.object(router, "deliver_generated_report"), \
             patch.object(router, "report_output_path", side_effect=lambda name: tmp + "/" + name):
            orders.query.get.return_value = order
            products.query.get.return_value = product
            error = None
            try:
                router.route_focused_report_generation(order.id)
            except router.FocusedReportRoutingError as exc:
                error = exc
        return order, generate, kundali, error

    def test_all_nine_products_pass_the_buyer_role_through(self):
        for key in KEYS:
            for role, boy_is_user in (("bride", False), ("groom", True)):
                partner = {"name": PARTNER["name"], "dob": PARTNER["dob"], "tob": PARTNER["tob"],
                           "pob": PARTNER["pob"], "latitude": 26.8467, "longitude": 80.9462, "buyer_role": role}
                order, generate, _, error = self.route(key, partner)
                self.assertIsNone(error, key)
                sent = generate.call_args.args[1]
                self.assertIs(sent["boy_is_user"], boy_is_user, f"{key}/{role}")
                self.assertEqual((sent["user"]["name"], sent["partner"]["name"]), (BUYER["name"], PARTNER["name"]))
                self.assertNotIn("buyer_role", sent["partner"])
                self.assertEqual(order.report_stage, "Ready")

    def test_missing_or_invalid_role_fails_closed_without_assuming_groom(self):
        for key in KEYS:
            for partner in ({"name": PARTNER["name"]}, {"name": PARTNER["name"], "buyer_role": None},
                            {"name": PARTNER["name"], "buyer_role": "Groom"}, {"name": PARTNER["name"], "buyer_role": True},
                            None):
                order, generate, kundali, error = self.route(key, partner)
                self.assertIsInstance(error, router.FocusedReportRoutingError, key)
                self.assertIn("buyer_role", str(error))
                generate.assert_not_called()
                kundali.assert_not_called()
                self.assertEqual(order.report_stage, "Failed")

    def test_single_person_reports_need_no_role(self):
        order, generate, kundali, error = self.route("promotion_timing", None)
        self.assertIsNone(error)
        kundali.assert_called_once()
        self.assertEqual(generate.call_args.args[1], {"kundali": "self"})


class EvidenceAndPromptRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.charts = {}
        with contextlib.redirect_stdout(io.StringIO()), frozen_clock():
            for p in (BUYER, PARTNER):
                cls.charts[p["name"]] = collector.calculate_full_kundali(
                    name=p["name"], dob=p["dob"], tob=p["tob"], lat=p["lat"], lon=p["lng"], language="en")
            cls.transits = {c["lagna_sign"]: collector.build_promotion_transit_evidence(
                c["lagna_sign"], horizon_months=12, selected_planets=("Jupiter", "Saturn")) for c in cls.charts.values()}
        cls.moons = {name: collector._extract_moon(chart) for name, chart in cls.charts.items()}

    def setUp(self):
        for target, side_effect in (
            ("calculate_full_kundali", lambda **kw: copy.deepcopy(self.charts[kw["name"]])),
            ("build_promotion_transit_evidence", lambda lagna, **kw: copy.deepcopy(self.transits[lagna])),
        ):
            patcher = patch.object(collector, target, side_effect=side_effect)
            patcher.start()
            self.addCleanup(patcher.stop)

    def expected_match(self, role):
        buyer, partner = self.moons[BUYER["name"]], self.moons[PARTNER["name"]]
        if role == "bride":
            return compute_ashtakoot(bride_moon=buyer, groom_moon=partner)
        return compute_ashtakoot(bride_moon=partner, groom_moon=buyer)

    def build(self, key, role, language):
        payload = {"user": BUYER, "partner": PARTNER, "boy_is_user": role == "groom"}
        with contextlib.redirect_stdout(io.StringIO()), frozen_clock():
            return build_relationship_report_prompt(key, payload, language)

    def test_fixture_pair_is_role_sensitive_in_the_frozen_engine(self):
        for role, (varna, total) in GOLDEN_MATCH.items():
            match = self.expected_match(role)
            self.assertEqual((match["kootas"]["varna"]["score"], match["total_score"], match["max_score"]), (varna, total, 36))

    def test_all_nine_products_label_both_roles_and_use_the_matching_engine_order_in_en_and_hi(self):
        for key in KEYS:
            components = RELATIONSHIP_SELECTIONS[key][1]
            for role in ("bride", "groom"):
                expected = self.expected_match(role)
                for language in ("en", "hi"):
                    with self.subTest(key=key, role=role, language=language):
                        built = self.build(key, role, language)
                        facts_text = built.evidence.sections["compatibility_facts"]
                        self.assertIn(ROLE_LABELS[role], facts_text)
                        self.assertIn(ROLE_LABELS[role], built.prompt)
                        facts = json.loads(facts_text[facts_text.index("{"):])
                        for component in components:
                            self.assertEqual(facts[component], expected["kootas"][component], component)

    def test_kundali_match_varna_and_total_follow_the_buyer_role(self):
        for role, (varna, total) in GOLDEN_MATCH.items():
            for language in ("en", "hi"):
                built = self.build("kundali_match_for_marriage", role, language)
                text = built.evidence.sections["compatibility_facts"]
                facts = json.loads(text[text.index("{"):])
                self.assertEqual(set(facts) - {"total_score", "max_score"}, set(ALL_KOOTAS))
                self.assertEqual((facts["varna"]["score"], facts["total_score"], facts["max_score"]), (varna, total, 36))
                self.assertIn(f"{total}", built.prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
