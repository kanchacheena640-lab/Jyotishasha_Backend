"""Intent-Based Micro Reports -- foundation phase: Intent Contract registry + bilingual question catalog.

Database-free, network-free and payment-free. Proves the registry and catalog are internally consistent, that the
selected customer question survives mapping to its core intent, that everything is Rs 51 and INACTIVE, that the
astrology mapping is explicitly pending (never guessed), and that the 25 frozen paid reports are untouched.
"""
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from modules.intents import intent_contract as ic
from modules.intents.intent_registry import (
    INTENT_REGISTRY,
    INTENT_SLUGS,
    UnknownIntentError,
    get_intent_contract,
    is_purchasable,
    list_intents,
)
from modules.intents.question_catalog import (
    QUESTIONS,
    UnknownQuestionError,
    export_catalog,
    get_question,
    normalize_question_text,
    questions_for_category,
    questions_for_intent,
    resolve_selection,
    validate_catalog,
)

REPO = Path(__file__).resolve().parent
FRONTEND_CATALOG = REPO.parent / "jyotishasha-frontend" / "app" / "data" / "intentCatalog.json"
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

APPROVED_INTENTS = {
    "career_growth_timing", "job_change_timing", "money_improvement_timing", "business_timing", "marriage_timing",
    "relationship_marriage_potential", "relationship_strengths_and_challenges", "foreign_move_timing",
    "study_exam_timing", "property_timing", "life_turning_points", "life_direction_and_strengths",
    "kundali_obstacles", "kundali_strengths",
}
# kundali_obstacles/kundali_strengths are each a single, exact-titled Birth + Current diagnostic question
# (report #62/#63) rather than an umbrella over several customer wordings; they are the only 2 intents
# exempt from the >=3-questions "no orphan intents" rule below.
SINGLE_QUESTION_INTENTS = {"kundali_obstacles", "kundali_strengths"}
FROZEN_25 = {
    **{slug: 51 for slug in (
        "marriage_report", "career_report", "love_relationship_report", "foreign_travel_report",
        "government_job_report", "sadhesati_report", "financial_report", "startup_suggestion_report",
        "love_marriage_report", "business_report", "legal_disputes_report", "gemstone_consultation",
        "children_parenting_report", "delay_in_marriage_report", "financial_stability_report",
        "jupiter_transit_report", "lifestyle_analysis_report", "love_disappointment_report",
        "problem_in_marriage_report", "mood_mental_health_report", "property_report", "saturn_transit_report",
        "second_marriage_report", "divorce_possibility_report")},
    "relationship_future_report": 199,
}


def _existing_disclaimer_types():
    source = (REPO / "modules" / "payments" / "report_q3_batch1.py").read_text(encoding="utf-8")
    block = source[source.index("DISCLAIMER_TEXT = {"):source.index("def get_mandatory_disclaimer")]
    return set(re.findall(r'^    "([a-z_]+)": \{', block, re.M))


class RegistryTests(unittest.TestCase):
    def test_registry_loads_with_exactly_the_14_approved_core_intents(self):
        self.assertEqual(len(INTENT_SLUGS), 14)
        self.assertEqual(set(INTENT_SLUGS), APPROVED_INTENTS)
        self.assertEqual(len(set(INTENT_SLUGS)), 14, "intent slugs are unique")
        self.assertEqual(set(INTENT_REGISTRY), APPROVED_INTENTS)
        self.assertEqual(len(list_intents()), 14)

    def test_person_modes_and_categories(self):
        modes = {slug: c.person_mode for slug, c in INTENT_REGISTRY.items()}
        self.assertEqual({s for s, m in modes.items() if m == "dual"},
                         {"relationship_marriage_potential", "relationship_strengths_and_challenges"})
        self.assertEqual(sum(1 for m in modes.values() if m == "single"), 12)
        counts = {}
        for contract in INTENT_REGISTRY.values():
            counts[contract.category] = counts.get(contract.category, 0) + 1
            self.assertIn(contract.category, ic.CATEGORY_IDS)
        self.assertEqual(counts, {"career": 2, "money_business": 2, "marriage": 1, "relationship": 2, "foreign": 1,
                                  "education": 1, "property": 1, "life": 4})
        self.assertEqual(set(counts), set(ic.CATEGORY_IDS), "no empty category")

    def test_every_intent_is_rs_51_inactive_and_not_purchasable(self):
        for slug, contract in INTENT_REGISTRY.items():
            with self.subTest(slug=slug):
                self.assertEqual(contract.price_rupees, 51)
                self.assertEqual(contract.activation, ic.Activation.INACTIVE)
                self.assertFalse(is_purchasable(slug))
                self.assertEqual(contract.evidence_status, ic.EvidencePackStatus.NOT_IMPLEMENTED)
        self.assertEqual(ic.INTENT_REPORT_PRICE_RUPEES, 51)
        with self.assertRaises(ValueError):
            ic.IntentContract(**{**INTENT_REGISTRY["property_timing"].__dict__, "price_rupees": 99})
        with self.assertRaises(ValueError):
            ic.IntentContract(**{**INTENT_REGISTRY["property_timing"].__dict__, "activation": "active"})

    def test_no_intent_or_question_is_held_or_conditional(self):
        # life_direction_and_strengths was CONDITIONAL_NOT_READY/HELD_CONDITIONAL before its evidence
        # collector, handler, PromptSpec and dispatcher registration existed; all 63 catalog keys
        # are now implemented and audited, so no intent or question is held anymore.
        conditional = [s for s, c in INTENT_REGISTRY.items() if c.readiness == ic.Readiness.CONDITIONAL_NOT_READY]
        self.assertEqual(conditional, [])
        self.assertTrue(all(c.readiness == ic.Readiness.CONTRACT_DRAFT for c in INTENT_REGISTRY.values()))
        held = [q.question_key for q in QUESTIONS if q.status == ic.QuestionStatus.HELD_CONDITIONAL]
        self.assertEqual(held, [])
        self.assertTrue(all(q.status == ic.QuestionStatus.WORDING_READY for q in QUESTIONS))
        for key in ("natural_strengths", "life_direction", "focus_to_use_strengths"):
            self.assertEqual(get_question(key).status, ic.QuestionStatus.WORDING_READY)

    def test_bilingual_identity_and_output_contract(self):
        for slug, contract in INTENT_REGISTRY.items():
            with self.subTest(slug=slug):
                self.assertTrue(contract.canonical_question.en.strip())
                self.assertRegex(contract.canonical_question.hi, DEVANAGARI)
                keys = [s.key for s in contract.sections]
                self.assertEqual(keys[0], "your_question")
                self.assertEqual(len(keys), len(set(keys)))
                self.assertGreaterEqual(len(keys), 5)
                for section in contract.sections:
                    self.assertTrue(section.title.en.strip())
                    self.assertRegex(section.title.hi, DEVANAGARI)
                    self.assertGreater(len(section.instruction), 40, "private composer instruction present")

    def test_astrology_mapping_is_explicitly_pending_never_guessed(self):
        for slug, contract in INTENT_REGISTRY.items():
            with self.subTest(slug=slug):
                self.assertEqual(contract.houses.status, ic.RuleStatus.PENDING)
                self.assertEqual((contract.houses.primary, contract.houses.supporting, contract.houses.pressure), ((), (), ()))
                self.assertEqual(contract.planets.status, ic.RuleStatus.PENDING)
                self.assertEqual(contract.yogas_and_specials.status, ic.RuleStatus.PENDING)
                for rule in (contract.planets, contract.yogas_and_specials, contract.dasha_rule, contract.transit_rule):
                    self.assertEqual(rule.items, ())
                if ic.PACK_DASHA in contract.required_evidence_packs or contract.person_mode == "dual":
                    self.assertEqual(contract.dasha_rule.status, ic.RuleStatus.PENDING)
                else:
                    self.assertEqual(contract.dasha_rule.status, ic.RuleStatus.NOT_APPLICABLE)
        with self.assertRaises(ValueError):
            ic.HouseSpec(primary=(10,), status=ic.RuleStatus.PENDING)

    def test_seed_references_equal_the_frozen_reports_own_registry_entries(self):
        from modules.payments.report_product_intelligence import REGISTRY as FROZEN
        seeded = 0
        for slug, contract in INTENT_REGISTRY.items():
            seed = contract.houses.seed
            if seed is None:
                continue
            seeded += 1
            with self.subTest(slug=slug):
                self.assertIn(seed.report_slug, FROZEN)
                self.assertEqual(seed.houses, tuple(FROZEN[seed.report_slug].relevant_houses))
                self.assertEqual(seed.planets, tuple(FROZEN[seed.report_slug].relevant_planets))
        self.assertEqual(seeded, 9)
        for slug in ("study_exam_timing", "life_turning_points", "life_direction_and_strengths",
                     "kundali_obstacles", "kundali_strengths"):
            self.assertIsNone(INTENT_REGISTRY[slug].houses.seed, f"{slug} has no existing report to seed from")

    def test_dual_intents_require_both_people_and_the_dual_pack(self):
        for slug, contract in INTENT_REGISTRY.items():
            with self.subTest(slug=slug):
                if contract.person_mode == "dual":
                    self.assertTrue(contract.requires_partner)
                    self.assertTrue(contract.dual_rule.requires_full_birth_data)
                    self.assertEqual(contract.dual_rule.status, ic.RuleStatus.PENDING)
                    self.assertIn(ic.PACK_DUAL, contract.required_evidence_packs)
                    self.assertEqual(contract.upsell_slug, "relationship_future_report")
                    self.assertIn(ic.ForbiddenClaim.THIRD_PARTY_MIND, contract.forbidden_claims)
                    self.assertIn(ic.ForbiddenClaim.BREAKUP_PREDICTION, contract.forbidden_claims)
                    self.assertEqual(contract.generator_key, "intent_dual_v1")
                else:
                    self.assertFalse(contract.requires_partner)
                    self.assertIsNone(contract.dual_rule)
                    self.assertNotIn(ic.PACK_DUAL, contract.required_evidence_packs)
                    self.assertEqual(contract.generator_key, "intent_single_v1")
                self.assertTrue(set(contract.required_evidence_packs) <= set(ic.EVIDENCE_PACKS))

    def test_forbidden_claims_and_disclaimers(self):
        existing = _existing_disclaimer_types()
        for slug, contract in INTENT_REGISTRY.items():
            with self.subTest(slug=slug):
                self.assertTrue(set(ic.BASE_FORBIDDEN_CLAIMS) <= set(contract.forbidden_claims))
                if contract.disclaimer_status == ic.DisclaimerStatus.EXISTING:
                    self.assertIn(contract.disclaimer_type, existing)
                else:
                    self.assertEqual(contract.disclaimer_status, ic.DisclaimerStatus.PENDING_TEXT)
                    self.assertNotIn(contract.disclaimer_type, existing, "a pending type must genuinely not exist yet")
        self.assertIn(ic.ForbiddenClaim.VISA_IMMIGRATION, INTENT_REGISTRY["foreign_move_timing"].forbidden_claims)
        self.assertIn(ic.ForbiddenClaim.EXAM_RESULT, INTENT_REGISTRY["study_exam_timing"].forbidden_claims)
        self.assertIn(ic.ForbiddenClaim.INVESTMENT_RETURN, INTENT_REGISTRY["money_improvement_timing"].forbidden_claims)
        self.assertIn(ic.ForbiddenClaim.JOB_LOSS, INTENT_REGISTRY["job_change_timing"].forbidden_claims)

    def test_upsell_slugs_point_at_existing_reports(self):
        for slug, contract in INTENT_REGISTRY.items():
            if contract.upsell_slug is not None:
                with self.subTest(slug=slug):
                    self.assertIn(contract.upsell_slug, FROZEN_25)
        self.assertIsNone(INTENT_REGISTRY["study_exam_timing"].upsell_slug)

    def test_unknown_intent_raises_and_registry_is_read_only(self):
        with self.assertRaises(UnknownIntentError):
            get_intent_contract("not_an_intent")
        with self.assertRaises(UnknownIntentError):
            is_purchasable("not_an_intent")
        with self.assertRaises(TypeError):
            INTENT_REGISTRY["x"] = None
        with self.assertRaises(Exception):
            INTENT_REGISTRY["property_timing"].price_rupees = 1


class QuestionCatalogTests(unittest.TestCase):
    def test_catalog_size_and_distribution(self):
        self.assertEqual(len(QUESTIONS), len(export_catalog()["questions"]))
        by_category = {}
        for q in QUESTIONS:
            by_category[q.category] = by_category.get(q.category, 0) + 1
        self.assertEqual(by_category, {"career": 12, "money_business": 11, "marriage": 6, "relationship": 9,
                                       "foreign": 6, "education": 4, "property": 5, "life": 10})
        self.assertEqual(sum(1 for q in QUESTIONS if q.person_mode == "single"), 54)
        self.assertEqual(sum(1 for q in QUESTIONS if q.person_mode == "dual"), 9)
        self.assertGreater(len(QUESTIONS), 4 * len(INTENT_SLUGS), "many questions share each core intent")

    def test_question_keys_unique_and_never_equal_an_intent_slug(self):
        keys = [q.question_key for q in QUESTIONS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertFalse(set(keys) & set(INTENT_SLUGS))

    def test_every_question_is_bilingual(self):
        for q in QUESTIONS:
            with self.subTest(key=q.question_key):
                self.assertGreater(len(q.question_en.strip()), 8)
                self.assertGreater(len(q.question_hi.strip()), 8)
                self.assertRegex(q.question_hi, DEVANAGARI)
                self.assertNotEqual(q.question_en, q.question_hi)

    def test_references_person_mode_and_category_agree_with_the_intent(self):
        self.assertEqual(validate_catalog(), [])
        for q in QUESTIONS:
            with self.subTest(key=q.question_key):
                contract = INTENT_REGISTRY[q.intent_slug]
                self.assertEqual(q.category, contract.category)
                self.assertEqual(q.person_mode, contract.person_mode)
                if q.person_mode == "single":
                    self.assertFalse(contract.requires_partner, "a SINGLE question can never map to a DUAL contract")
                else:
                    self.assertTrue(q.requires_partner and contract.requires_partner)
                    self.assertEqual(q.category, "relationship")
        self.assertTrue(all(q.person_mode == "dual" for q in questions_for_category("relationship")))

    def test_no_orphan_intents(self):
        for slug in INTENT_SLUGS:
            if slug in SINGLE_QUESTION_INTENTS:
                self.assertEqual(len(questions_for_intent(slug)), 1, slug)
            else:
                self.assertGreaterEqual(len(questions_for_intent(slug)), 3, slug)

    def test_no_duplicate_normalized_wording(self):
        english = [normalize_question_text(q.question_en) for q in QUESTIONS]
        hindi = [normalize_question_text(q.question_hi) for q in QUESTIONS]
        self.assertEqual(len(english), len(set(english)))
        self.assertEqual(len(hindi), len(set(hindi)))
        self.assertEqual(normalize_question_text("When will I get a promotion?"), normalize_question_text("when will i get a  promotion"))
        self.assertEqual(normalize_question_text("मुझे प्रमोशन कब मिलेगा?"), normalize_question_text("मुझे प्रमोशन कब मिलेगा"))
        self.assertNotEqual(normalize_question_text("प्रमोशन"), normalize_question_text("प्रमोशा"), "matras are kept")

    def test_wording_avoids_mind_reading_medical_investment_legal_and_guarantees(self):
        banned = [
            re.compile(r"cheat|betray|unfaithful|affair|crush|thinks? of me|loves? me|pregnan|fertil|conceive|disease|illness|cancer", re.I),
            re.compile(r"invest|stock|lottery|profit guarantee|guarantee|surely|definitely|court case|win the case|selected in|pass the exam|exam result", re.I),
            re.compile("धोखा|बेवफ़ा|गर्भ|प्रेग्नेंसी|बीमारी|निवेश|लॉटरी|गारंटी|केस जीत|पास हो"),
        ]
        for q in QUESTIONS:
            for pattern in banned:
                with self.subTest(key=q.question_key):
                    self.assertIsNone(pattern.search(q.question_en))
                    self.assertIsNone(pattern.search(q.question_hi))

    def test_answer_modes_and_lenses_are_controlled(self):
        for q in QUESTIONS:
            self.assertIn(q.answer_mode, ic.ANSWER_MODES)
            if q.lens:
                self.assertRegex(q.lens, r"^[a-z][a-z0-9_]*$")

    def test_selected_question_survives_the_mapping_to_its_core_intent(self):
        selection = resolve_selection("promotion_timing")
        self.assertEqual(selection.intent_slug, "career_growth_timing")
        self.assertEqual(selection.question_key, "promotion_timing")
        self.assertEqual(selection.display("en"), "Is this a good time for my promotion?")
        self.assertEqual(selection.display("hi"), "क्या यह समय मेरे प्रमोशन के लिए अच्छा है?")
        self.assertEqual(selection.display("hi-IN"), "क्या यह समय मेरे प्रमोशन के लिए अच्छा है?")
        self.assertEqual(selection.display("fr"), "Is this a good time for my promotion?")
        self.assertEqual((selection.category, selection.person_mode, selection.price_rupees), ("career", "single", 51))
        self.assertFalse(selection.requires_partner)
        with self.assertRaises(Exception):
            selection.question_key = "other"
        for q in QUESTIONS:
            with self.subTest(key=q.question_key):
                s = resolve_selection(q.question_key)
                self.assertEqual((s.question_key, s.intent_slug, s.answer_mode, s.lens),
                                 (q.question_key, q.intent_slug, q.answer_mode, q.lens))
                self.assertEqual(s.display_question, q.question)
        # several questions -> one intent, all still distinguishable after mapping
        career = {resolve_selection(q.question_key).question_key for q in questions_for_intent("career_growth_timing")}
        self.assertEqual(len(career), len(questions_for_intent("career_growth_timing")))
        self.assertTrue(resolve_selection("relationship_lead_to_marriage").requires_partner)

    def test_unknown_question_raises(self):
        for bad in ("nope", "", None):
            with self.assertRaises(UnknownQuestionError):
                get_question(bad)
            with self.assertRaises(UnknownQuestionError):
                resolve_selection(bad)


class FrozenSystemAndIsolationTests(unittest.TestCase):
    def test_the_25_report_registries_are_unchanged(self):
        from config.pricing import PRODUCT_PRICES
        from modules.payments.report_product_intelligence import REGISTRY
        self.assertEqual(len(FROZEN_25), 25)
        self.assertEqual(dict(PRODUCT_PRICES), FROZEN_25)
        self.assertEqual(set(REGISTRY), set(FROZEN_25))
        self.assertEqual(PRODUCT_PRICES["relationship_future_report"], 199)
        self.assertEqual(sum(1 for p in PRODUCT_PRICES.values() if p == 51), 24)
        self.assertEqual(REGISTRY["relationship_future_report"].generator, "love_premium_v1")
        self.assertEqual(sum(1 for p in REGISTRY.values() if p.generator == "standard_v1"), 24)
        self.assertFalse(set(INTENT_SLUGS) & set(PRODUCT_PRICES))
        self.assertFalse({q.question_key for q in QUESTIONS} & set(PRODUCT_PRICES))

    def test_rs_51_reuses_the_existing_reports51_google_play_product(self):
        from config.google_play_report_products import expected_report_product_id
        for slug in INTENT_SLUGS:
            self.assertEqual(expected_report_product_id(slug, ic.INTENT_REPORT_PRICE_RUPEES), "reports51")

    def test_nothing_is_wired_into_payment_orders_or_the_dispatcher(self):
        dispatcher = (REPO / "modules" / "payments" / "report_generation_dispatcher.py").read_text(encoding="utf-8")
        known = re.search(r"KNOWN_GENERATORS = frozenset\(\{([^}]*)\}\)", dispatcher).group(1)
        self.assertEqual(set(re.findall(r'"([a-z_0-9]+)"', known)), {"standard_v1", "love_premium_v1"})
        importers = []
        for path in REPO.rglob("*.py"):
            parts = set(path.relative_to(REPO).parts)
            if parts & {"venv", ".claude", "tmp", "__pycache__", "worktrees", "intents", "focused_reports"} or path.name.startswith("test_"):
                continue
            if "modules.intents" in path.read_text(encoding="utf-8", errors="ignore"):
                importers.append(str(path.relative_to(REPO)))
        self.assertEqual(importers, [], "no production module imports modules.intents yet")

    def test_the_package_is_pure_no_db_table_no_flask_no_openai(self):
        allowed = {"__future__", "re", "unicodedata", "dataclasses", "typing", "types", "modules"}
        for path in (REPO / "modules" / "intents").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for top in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M):
                self.assertIn(top, allowed, f"{path.name} imports {top}")
            self.assertNotIn("db.Model", text)
            self.assertNotIn("__tablename__", text)
        probe = (
            "import sys; import modules.intents.intent_contract, modules.intents.intent_registry, "
            "modules.intents.question_catalog; "
            "bad=[m for m in ('flask','sqlalchemy','flask_sqlalchemy','openai','razorpay','extensions','models','tasks') if m in sys.modules]; "
            "print(','.join(bad)); sys.exit(1 if bad else 0)"
        )
        result = subprocess.run([sys.executable, "-c", probe], cwd=str(REPO), capture_output=True, text=True,
                                env={k: v for k, v in os.environ.items() if not k.upper().startswith(("OPENAI", "RAZORPAY", "DATABASE"))})
        self.assertEqual(result.returncode, 0, f"importing modules.intents pulled in: {result.stdout} {result.stderr[-300:]}")

    def test_catalog_export_round_trips_without_losing_bilingual_content(self):
        # Frontend synchronization is a separate phase; this task changes only the backend.
        exported = json.loads(json.dumps(export_catalog(), ensure_ascii=False))
        self.assertEqual(len(exported["questions"]), len(QUESTIONS))
        for question, row in zip(QUESTIONS, exported["questions"]):
            self.assertEqual(row["question_en"], question.question_en)
            self.assertEqual(row["question_hi"], question.question_hi)


if __name__ == "__main__":
    unittest.main()
