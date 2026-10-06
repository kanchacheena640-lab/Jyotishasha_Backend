"""Step 3: all catalog products through real local routes and dispatch ownership.

Reuses Step 2's isolated fixture, real services/HMAC and mocked external boundaries.
Run: python -m unittest test_report_platform_product_matrix -v
"""
import ast
import contextlib
import hashlib
import io
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import test_report_platform_suresh_webhook_first as incident
from config.pricing import PRODUCT_PRICES
from modules.payments.report_product_registry import ReportProduct
from modules.payments.report_generation_dispatcher import KNOWN_GENERATORS

EXPECTED = set("""business_report career_report children_parenting_report
delay_in_marriage_report divorce_possibility_report financial_report
financial_stability_report foreign_travel_report gemstone_consultation
government_job_report jupiter_transit_report legal_disputes_report
lifestyle_analysis_report love_disappointment_report love_marriage_report
love_relationship_report marriage_report mood_mental_health_report
problem_in_marriage_report property_report sadhesati_report saturn_transit_report
second_marriage_report startup_suggestion_report relationship_future_report
spouse_nature_report""".split())
LOVE = "relationship_future_report"


class ProductMatrixTests(unittest.TestCase):
    def test_frontend_catalog_parity(self):
        # Cross-repo parity: the frontend catalogue must list exactly the
        # backend original catalogue. SNR-2D registers spouse_nature_report
        # in the backend first, so this stays RED (frontend 25 vs backend 26)
        # until the frontend registration phase -- never skipped or relaxed.
        frontend = Path("../jyotishasha-frontend/app/data/reportsData.ts").read_text(encoding="utf-8")
        pairs = re.findall(r'slug:\s*"([^"]+)"\s*,\s*price:\s*(\d+)', frontend)
        self.assertEqual(len(pairs), len(EXPECTED))
        prices = {slug: int(price) for slug, price in pairs}
        self.assertEqual(set(prices), EXPECTED)
        self.assertEqual(prices, PRODUCT_PRICES)

    def test_catalog_seed_prices_and_resources(self):
        prices = dict(PRODUCT_PRICES)
        self.assertEqual(len(prices), 26)
        self.assertEqual(set(prices), EXPECTED)
        seed = ast.parse(next(Path("migrations/versions").glob("65bed70e2520*.py")).read_text())
        values = {n.targets[0].id: ast.literal_eval(n.value) for n in seed.body
                  if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id in ("_STANDARD_PRODUCTS", "_LOVE_PREMIUM_PRODUCT")}
        # SNR-2D -- spouse_nature_report is seeded by its own additive migration.
        snr = ast.parse(next(Path("migrations/versions").glob("ec4f2103b154*.py")).read_text())
        spouse = next(ast.literal_eval(n.value) for n in snr.body
                      if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                      and n.targets[0].id == "_SPOUSE_NATURE_PRODUCT")
        self.assertEqual({s: p for s, _, p in values["_STANDARD_PRODUCTS"] +
                          [values["_LOVE_PREMIUM_PRODUCT"], spouse]}, prices)
        source = Path("tasks.py").read_text(encoding="utf-8")
        loader = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Try)
                      and any(isinstance(h.type, ast.Name) and h.type.id == "FileNotFoundError"
                              for h in n.handlers)
                      and "template_path" in ast.get_source_segment(source, n))
        with incident.app.app_context():
            # Original catalogue only; focused_v1/focused_dual_v1 rows are a separate population.
            rows = ReportProduct.query.filter(
                ReportProduct.generator.in_(("standard_v1", "love_premium_v1"))).all()
            self.assertEqual({r.report_slug: r.price for r in rows}, prices)
            for row in rows:
                with self.subTest(product=row.report_slug):
                    self.assertTrue(row.active)
                    self.assertEqual(row.currency, "INR")
                    self.assertEqual(row.generator, "love_premium_v1" if row.report_slug == LOVE else "standard_v1")
                    self.assertIn(row.generator, KNOWN_GENERATORS)
                    self.assertEqual(row.prompt_template_id, row.report_slug)
                    self.assertEqual(row.price, 199 if row.report_slug == LOVE else 51)
                    for language in ("en", "hi"):
                        path = Path(f"prompts/{row.prompt_template_id}_{language}.txt")
                        self.assertTrue(path.is_file(), str(path))
                        self.assertTrue(path.read_text(encoding="utf-8").strip())
                        if row.report_slug != LOVE:
                            ns = {"product_slug": row.report_slug, "template_path": str(path)}
                            captured = io.StringIO()
                            with contextlib.redirect_stdout(captured):
                                exec(compile(ast.Module(body=[loader], type_ignores=[]), "tasks-loader", "exec"), ns)
                            self.assertEqual(captured.getvalue(), "", "No fallback allowed")
                            self.assertEqual(ns["template"], path.read_text(encoding="utf-8"))
        # Relationship uses the existing bilingual Python prompt builder, not
        # the legacy relationship .txt files (which also exist in both languages).
        from modules.love.love_prompt_builder import build_love_premium_prompt
        prompts = [build_love_premium_prompt(dict(language=lang, compiled_report={},
                                                compatibility={}, astro_facts={}))
                   for lang in ("en", "hi")]
        self.assertTrue(all(prompts))
        self.assertNotEqual(prompts[0], prompts[1])
        self.assertFalse(Path("prompts/saturn_transit_report_hi").exists())
        self.assertEqual(hashlib.sha256(Path("prompts/saturn_transit_report_hi.txt").read_bytes()).hexdigest(),
                         "0c207848eb4c36195385f7f3b230b70840ee564e5dec3ccc96bc044cf7a7914f")

    def test_all_original_pending_orders_prices_and_paid_dispatch(self):
        for slug in sorted(EXPECTED):
            with self.subTest(product=slug):
                fixture = incident.SureshWebhookFirstRegression()
                try:
                    fixture.setUp()
                    payload = dict(fixture.payload, product=slug, price=1, amount=1, amount_paise=1)
                    amount = 19900 if slug == LOVE else 5100
                    if slug == LOVE:
                        del payload["phone"]
                        payload["partner"] = dict(name="Synthetic Partner", dob="1993-02-17",
                            tob="11:30", pob="Mumbai", latitude="19.0760", longitude="72.8777")
                    fixture.fetch_remote.return_value["amount"] = amount
                    response = fixture.client.post("/api/razorpay-order", json=payload)
                    self.assertEqual(response.status_code, 200, response.get_json())
                    fixture.order_id = response.get_json()["internal_order_id"]
                    self.assertEqual(response.get_json()["amount"], amount)
                    self.assertEqual(fixture.create_remote.call_args.args[0]["amount"], amount)
                    incident.db.session.remove()
                    order = incident.db.session.get(incident.Order, fixture.order_id)
                    self.assertEqual(order.product, slug)
                    self.assertEqual(order.amount_paise, amount)
                    self.assertEqual(order.payment_status, "PAYMENT_PENDING")
                    self.assertEqual(order.status, "PENDING")
                    self.assertEqual(order.report_stage, "Pending")
                    for key in ("name", "email", "dob", "tob", "pob", "latitude", "longitude", "language"):
                        self.assertEqual(getattr(order, key), payload[key])
                    self.assertEqual(order.phone, payload.get("phone"))
                    self.assertEqual(order.partner_payload, payload.get("partner"))
                    fixture.assert_claim(0)
                    fixture.thread.assert_not_called()
                    fixture.assert_success(fixture.server_callback(), "success")
                    incident.db.session.refresh(order)
                    self.assertEqual((order.payment_status, order.status, order.report_stage), ("PAID", "PAID", "Queued"))
                    fixture.assert_claim(1)
                    self.assertEqual(fixture.dispatches, [incident.Dispatch.DISPATCHED])
                    self.assertEqual(fixture.ownership_transitions, [1])
                    fixture.thread.assert_called_once_with(target=fixture.generator, args=(order.id,), daemon=True)
                    fixture.generator.assert_not_called()
                    if slug == LOVE:
                        # Execute the real task's early relationship branch and
                        # router, stopping at the actual premium generator boundary.
                        import tasks
                        import modules.love.love_report_router as router
                        with patch.object(router, "generate_love_premium_report") as premium:
                            tasks._generate_and_send_report_core(order.id)
                            premium.assert_called_once_with(order.id)
                    print(f"MATRIX PASS: {slug} | {amount} paise | Pending -> PAID/Queued")
                finally:
                    self.assertTrue(fixture.doCleanups(), "Matrix fixture cleanup failed")

    def test_negative_controls(self):
        fixture = incident.SureshWebhookFirstRegression()
        try:
            fixture.setUp()
            inactive = "step3_inactive_" + fixture.token
            row = ReportProduct(report_slug=inactive, name="Synthetic inactive", price=51,
                active=False, generator="standard_v1", prompt_template_id="career_report")
            incident.db.session.add(row)
            incident.db.session.commit()
            try:
                missing = dict(fixture.payload)
                del missing["dob"]
                for payload in (dict(fixture.payload, product="step3_unknown_" + fixture.token),
                                dict(fixture.payload, product=inactive), missing,
                                dict(fixture.payload, product=LOVE)):
                    response = fixture.client.post("/api/razorpay-order", json=payload)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(incident.Order.query.count(), fixture.before_orders)
                fixture.create_remote.assert_not_called()
                fixture.thread.assert_not_called()
                fixture.assert_claim(0)
            finally:
                incident.db.session.rollback()
                ReportProduct.query.filter_by(report_slug=inactive).delete()
                incident.db.session.commit()
        finally:
            self.assertTrue(fixture.doCleanups(), "Negative-control fixture cleanup failed")


if __name__ == "__main__":
    unittest.main()
