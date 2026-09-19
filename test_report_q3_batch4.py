"""Q3 Batch 4: deterministic fixtures, real routing/collector/parser, no DB or network.

Run with the repository venv: python -m unittest test_report_q3_batch4 -v
"""
import ast
import copy
import io
import json
import os
from pathlib import Path
import re
import unittest
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.payments.report_product_intelligence import REGISTRY
from modules.payments.report_q3_batch4 import STANDARD_BATCH4_PRODUCT_SLUGS
from modules.payments.report_q3_batch1 import get_mandatory_disclaimer
from modules.payments.report_q3_batch2 import compute_dasha_window_timeline
from modules.payments.report_structured_output import parse_structured_response, validate_required_hero_fields, ReportMetadataError
from modules.love.ashtakoot_love import compute_ashtakoot
from modules.love.love_prompt_builder import build_love_premium_prompt
from summary_blocks import build_house_lord_facts, build_summary_blocks_with_transit

ROOT = Path(__file__).resolve().parent
LOVE = "relationship_future_report"
LABELS = {"love_relationship_report": "Relationship Pattern", "love_marriage_report": "Love-Marriage Tendency",
          "love_disappointment_report": "Emotional Relationship Pattern", LOVE: "Relationship Outlook"}
USER_MOON = {"rashi": "Cancer", "degree": 10, "nakshatra": "Pushya"}
PARTNER_MOON = {"rashi": "Taurus", "degree": 15, "nakshatra": "Rohini"}
KUNDALI = {
    "lagna_sign": "Aries", "lagna_rashi": "Aries",
    "planets": [
        {"name": "Sun", "sign": "Gemini", "house": 3, "degree": 10, "nakshatra": "Ardra"},
        {"name": "Venus", "sign": "Taurus", "house": 2, "degree": 15, "nakshatra": "Rohini"},
        {"name": "Moon", "sign": "Cancer", "house": 4, "degree": 10, "nakshatra": "Pushya"},
        {"name": "Mars", "sign": "Aries", "house": 1, "degree": 10, "nakshatra": "Ashwini"},
        {"name": "Jupiter", "sign": "Sagittarius", "house": 9, "degree": 10, "nakshatra": "Mula"},
    ],
    "current_mahadasha": {"mahadasha": "Venus", "start": "2020-01-01", "end": "2040-01-01"},
    "current_antardasha": {"planet": "Moon", "start": "2026-01-01", "end": "2027-01-01"},
    "gemstone_suggestion": {"planet": "Jupiter", "gemstone": "Yellow Sapphire", "substone": "Citrine"},
}


def ashtakoot_fixture():
    return compute_ashtakoot(PARTNER_MOON, USER_MOON)


def partner_fixture(case):
    partner = {"name": "Synthetic Partner", "dob": "1992-08-15"}
    if case == "A":
        partner.update(tob="06:30", lat=19.076, lng=72.8777)
    return partner


def payload_fixture(language="en", case="A"):
    return {"language": language, "compiled_report": {"signals": {"stability_score": 99},
            "sections": [{"summary": "HEURISTIC_SECRET_MARKER 99%"}]},
            "astro_facts": {"love_vs_arranged": {"percentage": 98}},
            "compatibility": {"case": "A_FULL_DUAL" if case == "A" else "B_DOB_ONLY_HYBRID",
                              "ashtakoot": ashtakoot_fixture(), "fallback": {"stability_score": 99}},
            "user_house_lord_facts": [f for f in build_house_lord_facts(KUNDALI) if f["house"] in (5, 7)],
            "user_dasha_context": "Venus / Moon: 01/01/2026 to 01/01/2027"}


def completion_fixture(slug, value=None, malformed=False):
    hero = {"label": LABELS[slug], "value": value or ("Moderate" if slug == "love_marriage_report" else "Steady With Communication"),
            "interpretation": "Interpretive guidance from supplied evidence.",
            "evidence": ["Ashtakoot compatibility: 35/36"] if slug == LOVE else ["5th house Leo; lord Sun in house 3."],
            "action_items": ["Discuss expectations calmly."]}
    metadata = {"hero" if slug == LOVE else "answer_hero": hero, "action_items": hero["action_items"],
                "gemstone_reason": "Optional symbolic support."}
    content = "unstructured response" if malformed else "===META===\n" + json.dumps(metadata) + "\n===REPORT===\n**Summary**\nGrounded guidance."
    return SimpleNamespace(content=content, model="gpt-5.6-luna", input_tokens=10,
                           output_tokens=20, total_tokens=30, duration_seconds=0.1)


def boot_local_app():
    # Synthetic certificate already used by the repository's boot tests.
    from test_worker_boot_lazy_clients import _FAKE_FCM_JSON
    os.environ["FCM_SERVICE_ACCOUNT_JSON"] = _FAKE_FCM_JSON
    os.environ["DATABASE_URL"] = "postgresql://batch4:unused@localhost:5432/jyotishasha_local"
    os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
    os.environ["OPENAI_API_KEY"] = "sk-local-test-unused"
    import tasks
    import modules.love.love_premium_task as premium
    return tasks, premium


class ContractTests(unittest.TestCase):
    def test_registry_exact_migration(self):
        # Exact registry-wide total/tally is test_report_product_
        # intelligence.py's own job, not this file's -- it grows with
        # each later batch (Q3 Batch 5 enabled the final 7, reaching
        # 25/25). This file only asserts that ITS OWN 4 Batch-4
        # products (plus everything already enabled before Batch 4)
        # are, and remain, enabled -- never that the registry-wide
        # total stays frozen at 18.
        prior = set("gemstone_consultation saturn_transit_report mood_mental_health_report divorce_possibility_report marriage_report delay_in_marriage_report problem_in_marriage_report second_marriage_report financial_report financial_stability_report career_report government_job_report business_report startup_suggestion_report".split())
        enabled = {s for s, p in REGISTRY.items() if p.q3_enabled}
        self.assertEqual(len(REGISTRY), 25)
        self.assertTrue((prior | set(LABELS)) <= enabled)
        self.assertGreaterEqual(len(enabled), 18)
        self.assertEqual(STANDARD_BATCH4_PRODUCT_SLUGS, set(LABELS) - {LOVE})

    def test_registry_components_and_sources(self):
        for slug, label in LABELS.items():
            with self.subTest(slug=slug):
                p = REGISTRY[slug]
                self.assertEqual(p.hero_label, label)
                self.assertEqual(p.hero_value_source, "ai")
                self.assertEqual(set(p.required_hero_fields), {"label", "value", "interpretation", "evidence"})
                self.assertEqual(p.generator, "love_premium_v1" if slug == LOVE else "standard_v1")
                self.assertEqual(p.gemstone_policy, "optional" if slug in {"love_relationship_report", "love_marriage_report"} else "disabled")
                for component in ("answer_hero", "action_list", "disclaimer"):
                    self.assertTrue(p.components_enabled[component])
                self.assertEqual(p.components_enabled["timeline"], slug != LOVE)
                self.assertNotEqual(p.disclaimer_type, "relationship_privacy")
        self.assertEqual(REGISTRY[LOVE].required_context_keys, ())
        self.assertEqual(REGISTRY[LOVE].relevant_houses, ())
        self.assertEqual(REGISTRY[LOVE].relevant_planets, ())
        self.assertEqual(REGISTRY["love_disappointment_report"].relevant_houses, (5, 7, 8, 12))

    def test_price_and_architecture(self):
        from config.pricing import PRODUCT_PRICES
        self.assertEqual(PRODUCT_PRICES[LOVE], 199)
        source = (ROOT / "tasks.py").read_text(encoding="utf-8")
        self.assertIn('if product == "relationship_future_report":', source)
        self.assertIn('route_report_generation(order_id, product)', source)
        premium = (ROOT / "modules/love/love_premium_task.py").read_text(encoding="utf-8")
        tree = ast.parse(premium)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertEqual(sum(n.func.id == "generate_report_completion" for n in calls), 1)
        self.assertFalse(any(isinstance(n, ast.Constant) and n.value == "gpt-4o-mini" for n in ast.walk(tree)))
        self.assertIn('getattr(order, "partner_payload", None)', premium)
        self.assertNotIn('payment_status =', premium)
        self.assertIn('deliver_generated_report(order_id, output_path', premium)
        self.assertIn('STANDARD_BATCH4_PRODUCT_SLUGS', source)
        self.assertIn('compute_dasha_window_timeline(kundali, language=language)', source)

    def test_real_ashtakoot_fixture(self):
        result = ashtakoot_fixture()
        self.assertEqual(result["total_score"], 27)
        self.assertEqual(result["max_score"], 36)
        self.assertEqual(len(result["kootas"]), 8)
        self.assertEqual(sum(k["score"] for k in result["kootas"].values()), 27)
        self.assertFalse(result["invalid_kootas"])

    def test_empty_houses_and_real_dates(self):
        facts = {f["house"]: f for f in build_house_lord_facts(KUNDALI)}
        self.assertEqual((facts[5]["sign"], facts[5]["lord"], facts[5]["lord_house"]), ("Leo", "Sun", 3))
        self.assertEqual((facts[7]["sign"], facts[7]["lord"], facts[7]["lord_house"]), ("Libra", "Venus", 2))
        self.assertEqual(facts[5]["occupying_planets"], [])
        self.assertEqual(facts[7]["occupying_planets"], [])
        for lang in ("en", "hi"):
            timeline = compute_dasha_window_timeline(KUNDALI, lang)
            self.assertIn("01/01/2026", timeline["entries"][0]["date_range"])
            self.assertIn("01/01/2027", timeline["entries"][0]["date_range"])
            self.assertIsNone(compute_dasha_window_timeline({}, lang))

    def test_disclaimers_exact_supplied_text(self):
        for slug in LABELS:
            key = REGISTRY[slug].disclaimer_type
            en = get_mandatory_disclaimer(key, "en")
            hi = get_mandatory_disclaimer(key, "hi")
            self.assertTrue(en and hi and en != hi)
            self.assertIn("relationship", en.lower())
            self.assertRegex(hi, "[अ-ह]")
            self.assertIn("not", en)

    def test_standard_bilingual_contracts(self):
        blocks = build_summary_blocks_with_transit(copy.deepcopy(KUNDALI), {})
        for slug in STANDARD_BATCH4_PRODUCT_SLUGS:
            for lang in ("en", "hi"):
                with self.subTest(slug=slug, language=lang):
                    source = (ROOT / f"prompts/{slug}_{lang}.txt").read_text(encoding="utf-8")
                    prompt = source.format(**blocks)
                    meta, body = parse_structured_response(prompt[prompt.index("===META==="):])
                    hero = validate_required_hero_fields(meta, REGISTRY[slug].required_hero_fields)
                    self.assertEqual(hero["label"], LABELS[slug])
                    self.assertEqual(len(re.findall(r"^\*\*\d+\.", body, re.M)), 8 if slug == "love_marriage_report" else 9)
                    for key in REGISTRY[slug].required_context_keys:
                        self.assertIn("{" + key + "}", source)
                    self.assertIn("DD/MM/YYYY", source)
                    for token in (["private thoughts", "feelings", "intentions", "cheating", "betrayal", "breakup", "depression", "anxiety", "trauma", "ending a relationship"] if lang == "en" else ["निजी विचार", "भावनाएँ", "इरादे", "बेवफाई", "विश्वासघात", "संबंध-विच्छेद", "अवसाद", "चिंता", "आघात", "संबंध खत्म"]):
                        self.assertIn(token, source)
                    if slug == "love_disappointment_report":
                        self.assertNotIn("gemstone", source.lower())
                        self.assertNotIn("रत्न", source)
                    if slug == "love_marriage_report":
                        for token in ("Low", "Moderate", "Elevated", "marriage_report", "love_relationship_report", "love_vs_arranged", "stability_score"):
                            self.assertIn(token, source)
                    if slug == "love_relationship_report":
                        self.assertIn("love_marriage_report", source)
                        self.assertIn("marriage_report", source)

    def test_live_builder_bilingual_cases_and_exclusions(self):
        for language in ("en", "hi"):
            for case in ("A", "B"):
                with self.subTest(language=language, case=case):
                    prompt = build_love_premium_prompt(payload_fixture(language, case))
                    self.assertIn("===META===", prompt)
                    self.assertIn("===REPORT===", prompt)
                    self.assertIn('"label":"Relationship Outlook"', prompt)
                    self.assertEqual(len(re.findall(r"^\d+\.", prompt, re.M)), 10)
                    for forbidden in ("love_vs_arranged", "stability_score", "HEURISTIC_SECRET_MARKER", "99%", "98%"):
                        self.assertNotIn(forbidden, prompt)
                    data = json.loads(prompt.split("Deterministic evidence:\n")[1])
                    self.assertEqual(data["ashtakoot"]["total_score"], 27)
                    # Q4.4B: internal mode names are never sent to the model; completeness is described in plain words.
                    self.assertEqual(data["partner_birth_data"]["completeness"], "full" if case == "A" else "partial")
                    self.assertEqual(len(data["user_house_lord_facts"]), 2)
                    self.assertIn(get_mandatory_disclaimer(REGISTRY[LOVE].disclaimer_type, language), prompt)
                    for token in (["thoughts", "feelings", "intentions", "fidelity", "breakup", "exact relationship event timing"] if language == "en" else ["विचार", "भावनाएँ", "इरादे", "निष्ठा", "संबंध-विच्छेद", "निश्चित तारीख"]):
                        self.assertIn(token, prompt)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks, cls.premium = boot_local_app()

    def run_pipeline(self, slug, language="en", case="A", malformed=False, value=None, missing_partner=False, ai_failure=False, retry=False):
        tasks, premium = self.tasks, self.premium
        import modules.love.service_love as service
        partner_chart = copy.deepcopy(KUNDALI)
        moon = next(p for p in partner_chart["planets"] if p["name"] == "Moon")
        moon.update(sign="Taurus", degree=15, nakshatra="Rohini")
        order = SimpleNamespace(id=987654, name="Synthetic Batch4", email="fixture@example.invalid", phone=None,
            product=slug, dob="1990-06-15", tob="10:30", pob="Delhi", latitude="28.6139", longitude="77.2090",
            language=language, payment_status="PAID", status="PAID", report_stage="Pending", pdf_url=None,
            created_at=None, partner_payload=None if missing_partner else partner_fixture(case))
        original_partner = copy.deepcopy(order.partner_payload)
        query = MagicMock(); query.get.return_value = order
        captured = {}
        reader = open
        def safe_open(path, mode="r", *args, **kwargs):
            return io.StringIO() if "w" in mode else reader(path, mode, *args, **kwargs)
        def capture_pdf(**kwargs):
            captured.update(kwargs)
        module = premium if slug == LOVE else tasks
        with ExitStack() as stack, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            stack.enter_context(patch("sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Database access forbidden")))
            stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network access forbidden")))
            for target in (tasks, premium):
                stack.enter_context(patch.object(target, "Order", SimpleNamespace(query=query)))
                stack.enter_context(patch.object(target, "db", SimpleNamespace(session=MagicMock())))
                stack.enter_context(patch.object(target, "calculate_full_kundali", side_effect=lambda **kw: copy.deepcopy(KUNDALI)))
                stack.enter_context(patch.object(target, "get_current_positions", return_value={}))
                stack.enter_context(patch.object(target, "generate_kundali_drawing", return_value=None))
                stack.enter_context(patch.object(target, "generate_pdf_report", side_effect=capture_pdf))
                stack.enter_context(patch.object(target, "record_event"))
                stack.enter_context(patch.object(target, "deliver_generated_report"))
                stack.enter_context(patch.object(target, "open", safe_open, create=True))
            stack.enter_context(patch("os.makedirs"))
            stack.enter_context(patch.object(service, "calculate_full_kundali", side_effect=lambda **kw: copy.deepcopy(partner_chart if kw["name"] == "Synthetic Partner" else KUNDALI)))
            stack.enter_context(patch.object(service, "derive_moon_from_dob", return_value=PARTNER_MOON))
            ai = stack.enter_context(patch.object(module, "generate_report_completion", return_value=completion_fixture(slug, value, malformed),
                                side_effect=RuntimeError("fixture AI failure") if ai_failure else None))
            other_ai = stack.enter_context(patch.object(tasks if slug == LOVE else premium, "generate_report_completion"))
            tasks._generate_and_send_report_core(order.id)
            if retry:
                self.assertEqual(order.report_stage, "Failed")
                self.assertFalse(captured)
                ai.return_value = completion_fixture(slug)
                tasks._generate_and_send_report_core(order.id)
            self.assertEqual(other_ai.call_count, 0)
            self.assertEqual(ai.call_count, 0 if missing_partner else (2 if retry else 1))
            if ai.called and slug == LOVE:
                live_prompt = ai.call_args.args[0]
                self.assertIn("27.0", live_prompt)
                self.assertNotIn("stability_score", live_prompt)
                self.assertNotIn("love_vs_arranged", live_prompt)
                self.assertIn('"house": 5', live_prompt)
                self.assertIn('"house": 7', live_prompt)
            self.assertEqual(order.partner_payload, original_partner)
            self.assertEqual(order.payment_status, "PAID")
            self.assertEqual(order.status, "PAID")
        return order, captured

    def test_malformed_premium_fails_without_delivery(self):
        order, captured = self.run_pipeline(LOVE, malformed=True)
        self.assertEqual(order.report_stage, "Failed")
        self.assertIsNone(order.pdf_url)
        self.assertFalse(captured)

    def test_retry_same_case_b_order_uses_dedicated_pipeline(self):
        order, pdf = self.run_pipeline(LOVE, case="B", malformed=True, retry=True)
        self.assertEqual(order.report_stage, "Ready")
        self.assertEqual(pdf["answer_hero"]["label"], "Relationship Outlook")

    def test_missing_partner_fails_before_ai(self):
        order, captured = self.run_pipeline(LOVE, missing_partner=True)
        self.assertEqual(order.report_stage, "Failed")
        self.assertFalse(captured)

    def test_collector_preserves_empty_houses_for_dict_planets(self):
        from modules.love.love_data_collector import collect_love_report_data
        chart = copy.deepcopy(KUNDALI)
        chart["planets"] = {p["name"]: p for p in chart["planets"]}
        with patch("modules.love.love_data_collector.run_love_compatibility", return_value=payload_fixture()["compatibility"]):
            payload = collect_love_report_data(
                {"name": "Fixture", "dob": "1990-06-15", "tob": "10:30", "lat": 28.6, "lng": 77.2,
                 "partner": partner_fixture("A")}, chart, "en")
        self.assertEqual([f["house"] for f in payload["user_house_lord_facts"]], [5, 7])
        self.assertTrue(all(f["occupying_planets"] == [] for f in payload["user_house_lord_facts"]))
        self.assertIn("Venus", payload["user_dasha_context"]["window_summary"])

    def test_standard_malformed_metadata_never_renders(self):
        for slug in STANDARD_BATCH4_PRODUCT_SLUGS:
            with self.subTest(slug=slug):
                order, captured = self.run_pipeline(slug, malformed=True)
                self.assertEqual(order.report_stage, "Failed")
                self.assertFalse(captured)

    def test_premium_ai_failure_stays_recoverable(self):
        order, captured = self.run_pipeline(LOVE, ai_failure=True)
        self.assertEqual(order.report_stage, "Failed")
        self.assertFalse(captured)

    def test_invalid_love_marriage_tier_fails(self):
        order, captured = self.run_pipeline("love_marriage_report", value="87%")
        self.assertEqual(order.report_stage, "Failed")
        self.assertFalse(captured)

    def test_premium_numeric_hero_is_rejected(self):
        for value in ("90% compatible", "27/36", "९० प्रतिशत"):
            with self.subTest(value=value):
                order, captured = self.run_pipeline(LOVE, value=value)
                self.assertEqual(order.report_stage, "Failed")
                self.assertFalse(captured)

    def test_premium_malformed_object_or_evidence_fails(self):
        for metadata in (None, {}, {"answer_hero": {}}, {"answer_hero": {"label": "Relationship Outlook", "value": "Calm", "interpretation": "Some text", "evidence": []}}):
            with self.assertRaises(ReportMetadataError):
                validate_required_hero_fields(metadata, REGISTRY[LOVE].required_hero_fields)


def add_pipeline_tests():
    for slug in LABELS:
        for language in ("en", "hi"):
            for case in (("A", "B") if slug == LOVE else ("A",)):
                def test(self, slug=slug, language=language, case=case):
                    order, pdf = self.run_pipeline(slug, language, case)
                    self.assertEqual(order.report_stage, "Ready")
                    self.assertEqual(pdf["answer_hero"]["label"], LABELS[slug])
                    self.assertEqual(pdf["language"], language)
                    self.assertEqual(pdf["disclaimer"], get_mandatory_disclaimer(REGISTRY[slug].disclaimer_type, language))
                    self.assertEqual(pdf["app_download"]["play_store_url"], "https://play.google.com/store/apps/details?id=com.jyotishasha.app&pcampaignid=web_share")
                    if REGISTRY[slug].gemstone_policy == "disabled":
                        self.assertIsNone(pdf.get("gemstone"))
                    else:
                        self.assertEqual(pdf["gemstone"]["gemstone"], "Yellow Sapphire")
                    if slug == LOVE:
                        self.assertIsNone(pdf.get("timeline"))
                        self.assertEqual(pdf["answer_hero"]["evidence"], ["अष्टकूट अनुकूलता: 27/36" if language == "hi" else "Ashtakoot compatibility: 27/36"])
                        self.assertNotIn("35/36", str(pdf))
                        self.assertTrue(pdf["action_list"]["items"])
                    else:
                        self.assertEqual(pdf["timeline"], compute_dasha_window_timeline(KUNDALI, language))
                setattr(PipelineTests, f"test_{slug}_{language}_case_{case}", test)
add_pipeline_tests()

if __name__ == "__main__":
    unittest.main(verbosity=2)
