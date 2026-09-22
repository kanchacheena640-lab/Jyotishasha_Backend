"""Catalog-wide prompt contracts; deterministic, with no model calls."""
import ast
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest
from unittest.mock import patch

from modules.intents.question_catalog import QUESTIONS, UnknownQuestionError, get_question
from modules.focused_reports import prompt_specs
from modules.focused_reports.dispatcher import HANDLERS, FocusedReportNotImplementedError, resolve_focused_handler
from modules.focused_reports.prompt_contract import Archetype, Capability, EvidenceRequirement
from modules.focused_reports.prompt_assembler import build_focused_prompt, MissingEvidenceError, PromptAssemblyError
from modules.focused_reports.master_contract import REMEDY_INSTRUCTION

ROOT = Path(__file__).resolve().parent


def evidence_for(spec):
    # Test values prove assembly, not astrology. Negative facts remain valid.
    return {r.key: f"Test evidence for {r.key}: supplied period 2026-10-15." for r in spec.evidence_requirements}


class CatalogPromptTests(unittest.TestCase):
    def test_exact_coverage_bilingual_identity_and_typed_fields(self):
        specs = prompt_specs.PROMPT_SPECS
        self.assertEqual(set(specs), {q.question_key for q in QUESTIONS})
        self.assertEqual(len(specs), len(QUESTIONS))
        for q in QUESTIONS:
            with self.subTest(question=q.question_key):
                spec = specs[q.question_key]
                self.assertEqual((spec.question_key, spec.intent_slug, spec.person_mode),
                                 (q.question_key, q.intent_slug, q.person_mode))
                self.assertEqual(spec.question.en, q.question_en)
                self.assertEqual(spec.question.hi, q.question_hi)
                self.assertTrue(spec.title.en.strip())
                self.assertRegex(spec.title.hi, r"[\u0900-\u097f]")
                for field in (spec.analysis_objective, spec.astrological_focus, spec.timing_requirement, spec.output_emphasis):
                    self.assertGreater(len(field), 30)
                self.assertTrue(spec.evidence_requirements)
                self.assertIsInstance(spec.archetype, Archetype)
                self.assertIsInstance(spec.capability, Capability)
                self.assertTrue(spec.boundaries)
        # Actual distinct authored objectives, not one generic instruction.
        self.assertEqual(len({s.analysis_objective for s in specs.values()}), len(specs))
        self.assertNotIn("foreign_study_timing", specs)
        self.assertIn("study_abroad", specs)

    def test_capabilities_track_handlers_and_available_fact_sources(self):
        implemented = {s.question_key for s in prompt_specs.PROMPT_SPECS.values() if s.capability == Capability.IMPLEMENTED}
        self.assertEqual(implemented, set(HANDLERS))
        self.assertEqual(implemented, {q.question_key for q in QUESTIONS if q.category in ("career", "money_business", "marriage", "relationship", "foreign", "education", "property", "life")})
        self.assertEqual(sum(Counter(s.capability for s in prompt_specs.PROMPT_SPECS.values()).values()), len(QUESTIONS))
        parsed = {}
        for spec in prompt_specs.PROMPT_SPECS.values():
            self.assertEqual(bool(spec.missing_evidence), spec.capability == Capability.EVIDENCE_MISSING)
            for requirement in spec.evidence_requirements:
                for source in requirement.sources:
                    filename, function = source.split(":")
                    if filename not in parsed:
                        parsed[filename] = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
                    self.assertIn(function, {n.name for n in parsed[filename].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))})
        # Positive source-shape checks alongside the exact provenance paths.
        summary = (ROOT / "summary_blocks.py").read_text(encoding="utf-8")
        self.assertIn('md.get("antardashas"', summary)
        self.assertIn('"lord"', summary)
        compatibility = (ROOT / "modules/love/service_love.py").read_text(encoding="utf-8")
        self.assertIn("partner_kundali = calculate_full_kundali", compatibility)

    def test_available_definitions_do_not_enable_any_new_handler(self):
        for q in QUESTIONS:
            if q.category not in ("career", "money_business", "marriage", "relationship", "foreign", "education", "property", "life"):
                with self.assertRaises(FocusedReportNotImplementedError):
                    resolve_focused_handler(q.question_key)

    def test_promotion_minimum_and_no_excessive_evidence_anywhere(self):
        spec = prompt_specs.get_prompt_spec("promotion_timing")
        self.assertEqual([r.key for r in spec.evidence_requirements], [
            "birth_chart_summary", "house_lord_summary", "career_yoga_summary", "dasha_window_summary", "Jupiter", "Saturn", "Rahu"])
        for spec in prompt_specs.PROMPT_SPECS.values():
            text = " ".join(r.key + " " + r.focus for r in spec.evidence_requirements).lower()
            for forbidden in ("shadbala", "pratyantar", "ashtakavarga", "entire kundali", "all-planet"):
                self.assertNotIn(forbidden, text)
            self.assertNotRegex(text, r"\bd-?(9|10)\b")

    def test_person_and_decision_boundaries_and_archetypes(self):
        self.assertEqual({s.archetype for s in prompt_specs.PROMPT_SPECS.values()}, set(Archetype))
        for q in QUESTIONS:
            spec = prompt_specs.get_prompt_spec(q.question_key)
            keys = {r.key for r in spec.evidence_requirements}
            if q.person_mode == "dual":
                self.assertTrue({"user_natal", "partner_natal", "compatibility_facts"} <= keys)
                self.assertIn("separately attributed", " ".join(spec.boundaries))
            else:
                self.assertNotIn("partner_natal", keys)
                self.assertIn("do not infer another person's", " ".join(spec.boundaries))
            if q.intent_slug in ("job_change_timing", "business_timing", "property_timing"):
                self.assertIn("not commands to resign, buy, sell", " ".join(spec.boundaries))
        self.assertNotIn("compatibility_facts", {r.key for r in prompt_specs.get_prompt_spec("relationship_to_marriage_window").evidence_requirements})
        self.assertEqual(prompt_specs.get_prompt_spec("career_growth_delay_reason").archetype, Archetype.DIAGNOSTIC)
        self.assertEqual(prompt_specs.get_prompt_spec("natural_strengths").archetype, Archetype.DIRECTION)

    def test_specs_are_immutable_and_missing_capability_is_explicit(self):
        spec = prompt_specs.get_prompt_spec("promotion_timing")
        with self.assertRaises(FrozenInstanceError):
            spec.question_key = "changed"
        missing = EvidenceRequirement("future_fact", "Future fact", "A deliberately absent test fact", (), missing="test fact calculation unavailable")
        with self.assertRaises(ValueError):
            replace(spec, evidence_requirements=(missing,))
        test_spec = replace(spec, evidence_requirements=(missing,), capability=Capability.EVIDENCE_MISSING)
        self.assertEqual(test_spec.missing_evidence, ("test fact calculation unavailable",))


class PromptAssemblyTests(unittest.TestCase):
    def test_every_spec_assembles_both_languages_without_ai(self):
        with patch("modules.payments.report_ai_client.generate_report_completion", side_effect=AssertionError("No AI allowed")) as ai:
            for spec in prompt_specs.PROMPT_SPECS.values():
                for language in ("en", "hi"):
                    with self.subTest(question=spec.question_key, language=language):
                        prompt = build_focused_prompt(spec.question_key, language, evidence_for(spec))
                        self.assertIn(spec.question.get(language), prompt)
                        self.assertIn(spec.analysis_objective, prompt)
                        self.assertIn(spec.astrological_focus, prompt)
                        self.assertIn(spec.output_emphasis, prompt)
                        self.assertEqual(prompt.count("===META==="), 1)
                        self.assertEqual(prompt.count("===REPORT==="), 1)
                        self.assertNotIn("2026-10-15", prompt)
                        self.assertIn("15 October 2026" if language == "en" else "15 अक्टूबर 2026", prompt)
                        self.assertNotIn(spec.intent_slug, prompt)
                        self.assertNotIn(spec.capability.value, prompt)
            ai.assert_not_called()

    def test_missing_spec_and_unknown_question_fail_closed(self):
        with patch.object(prompt_specs, "PROMPT_SPECS", {}):
            with self.assertRaises(prompt_specs.MissingPromptSpecError):
                build_focused_prompt("promotion_timing", "en", {})
        with self.assertRaises(UnknownQuestionError):
            build_focused_prompt("no_such_question", "en", {})

    def test_missing_each_required_section_fails_before_assembly(self):
        for spec in prompt_specs.PROMPT_SPECS.values():
            for requirement in spec.evidence_requirements:
                evidence = evidence_for(spec)
                del evidence[requirement.key]
                with self.assertRaises(MissingEvidenceError) as error:
                    build_focused_prompt(spec.question_key, "en", evidence)
                self.assertEqual(error.exception.sections, (requirement.key,))

    def test_empty_or_invalid_evidence_is_not_a_fact(self):
        spec = prompt_specs.get_prompt_spec("promotion_timing")
        for bad in (None, "", " ", {}, [], "N/A", "Dasha window data not available."):
            evidence = evidence_for(spec)
            evidence["dasha_window_summary"] = bad
            with self.assertRaises(MissingEvidenceError):
                build_focused_prompt(spec.question_key, "en", evidence)
        evidence = evidence_for(spec)
        evidence["career_yoga_summary"] = "No career yogas detected."
        self.assertIn("No career yogas detected.", build_focused_prompt(spec.question_key, "en", evidence))

    def test_invalid_language_fails_and_supported_aliases_resolve(self):
        spec = prompt_specs.get_prompt_spec("promotion_timing")
        for language in (None, "", "fr", "hindi", "hi-garbage", 5):
            with self.assertRaises(PromptAssemblyError):
                build_focused_prompt(spec.question_key, language, evidence_for(spec))
        for alias, language in (("hi-IN", "hi"), ("EN-us", "en"), ("en-IN", "en")):
            self.assertEqual(build_focused_prompt(spec.question_key, alias, evidence_for(spec)),
                             build_focused_prompt(spec.question_key, language, evidence_for(spec)))

    def test_catalog_mismatch_fails_closed(self):
        spec = prompt_specs.get_prompt_spec("promotion_timing")
        for update in ({"question_key": "new_job_timing"}, {"intent_slug": "marriage_timing"},
                       {"person_mode": "dual"}, {"question": get_question("new_job_timing").question}):
            with patch("modules.focused_reports.prompt_assembler.get_prompt_spec", return_value=replace(spec, **update)):
                with self.assertRaises(PromptAssemblyError):
                    build_focused_prompt(spec.question_key, "en", evidence_for(spec))

    def test_extra_evidence_and_identity_are_not_sent(self):
        spec = prompt_specs.get_prompt_spec("promotion_timing")
        evidence = {**evidence_for(spec), "entire_kundali": "PRIVATE_RAW_DATA"}
        context = {"name": "PRIVATE_NAME", "dob": "PRIVATE_DOB", "situation": "Review after 2026-10-15"}
        prompt = build_focused_prompt(spec.question_key, "en", evidence, context)
        for secret in ("PRIVATE_RAW_DATA", "PRIVATE_NAME", "PRIVATE_DOB"):
            self.assertNotIn(secret, prompt)
        self.assertIn("Review after 15 October 2026", prompt)
        self.assertEqual(context["situation"], "Review after 2026-10-15")


class NewDiagnosticReportsTests(unittest.TestCase):
    """Reports #62/#63 (major_kundali_obstacles/major_kundali_strengths) and their shared, conditional
    obstacle/remedy/timing-overlap architecture -- catalog=63, no live Luna call."""

    def test_report_62_obstacles_is_wired_bilingually(self):
        q = get_question("major_kundali_obstacles")
        self.assertEqual(q.question_en, "What are the major obstacles in my birth chart, what is affecting me "
                                        "currently, and what remedies can help?")
        self.assertEqual(q.question_hi, "मेरी जन्म कुंडली में प्रमुख बाधाएँ क्या हैं, वर्तमान समय में कौन-सी बाधाएँ "
                                        "सक्रिय हैं और उनके लिए क्या उपाय किए जा सकते हैं?")
        self.assertEqual(q.category, "life")
        self.assertEqual(q.person_mode, "single")
        spec = prompt_specs.get_prompt_spec("major_kundali_obstacles")
        self.assertEqual(spec.title.en, "Major Obstacles in Your Kundali")
        self.assertEqual(spec.title.hi, "आपकी कुंडली की प्रमुख बाधाएँ")
        self.assertEqual(spec.archetype, Archetype.OBSTACLES)
        self.assertEqual(spec.capability, Capability.IMPLEMENTED)
        self.assertTrue(spec.remedies)
        keys = {r.key for r in spec.evidence_requirements}
        self.assertEqual(keys, {"birth_chart_summary", "house_lord_summary", "career_yoga_summary",
                                "wealth_yoga_summary", "dasha_window_summary", "Jupiter", "Saturn", "Rahu"})

    def test_report_63_strengths_is_wired_bilingually(self):
        q = get_question("major_kundali_strengths")
        self.assertEqual(q.question_en, "What are the strongest areas of my birth chart, which strengths are "
                                        "active now, and how can I use them effectively?")
        self.assertEqual(q.question_hi, "मेरी जन्म कुंडली की प्रमुख शक्तियाँ क्या हैं, वर्तमान समय में कौन-सी "
                                        "शक्तियाँ सक्रिय हैं और उनका सर्वोत्तम उपयोग कैसे करूँ?")
        self.assertEqual(q.category, "life")
        self.assertEqual(q.person_mode, "single")
        spec = prompt_specs.get_prompt_spec("major_kundali_strengths")
        self.assertEqual(spec.title.en, "Major Strengths in Your Kundali")
        self.assertEqual(spec.title.hi, "आपकी कुंडली की प्रमुख शक्तियाँ")
        self.assertEqual(spec.archetype, Archetype.STRENGTHS_NOW)
        self.assertEqual(spec.capability, Capability.IMPLEMENTED)
        self.assertFalse(spec.remedies)
        keys = {r.key for r in spec.evidence_requirements}
        self.assertEqual(keys, {"birth_chart_summary", "house_lord_summary", "career_yoga_summary",
                                "wealth_yoga_summary", "dasha_window_summary", "Jupiter", "Saturn", "Rahu"})

    def test_natural_strengths_remains_distinct_from_major_kundali_strengths(self):
        natural = prompt_specs.get_prompt_spec("natural_strengths")
        current = prompt_specs.get_prompt_spec("major_kundali_strengths")
        self.assertNotEqual(natural.question_key, current.question_key)
        self.assertNotEqual(natural.intent_slug, current.intent_slug)
        self.assertNotEqual(natural.archetype, current.archetype)
        self.assertEqual(natural.archetype, Archetype.DIRECTION)
        self.assertNotEqual({r.key for r in natural.evidence_requirements}, {r.key for r in current.evidence_requirements})
        self.assertNotIn("Jupiter", {r.key for r in natural.evidence_requirements}, "natural_strengths stays natal-only")
        self.assertEqual(natural.question.en, "What are my natural strengths?")
        self.assertEqual(natural.title.en, "Natural Strengths")

    def test_remedies_flag_is_conditional_not_global(self):
        with_remedies = {s.question_key for s in prompt_specs.PROMPT_SPECS.values() if s.remedies}
        self.assertEqual(with_remedies, {"major_kundali_obstacles"})
        with patch("modules.payments.report_ai_client.generate_report_completion", side_effect=AssertionError("No AI allowed")):
            for spec in prompt_specs.PROMPT_SPECS.values():
                for language in ("en", "hi"):
                    prompt = build_focused_prompt(spec.question_key, language, evidence_for(spec))
                    if spec.remedies:
                        self.assertIn(REMEDY_INSTRUCTION[language], prompt)
                    else:
                        self.assertNotIn(REMEDY_INSTRUCTION[language], prompt)

    def test_timing_overlap_clarity_instruction_present_in_master_contract(self):
        from modules.focused_reports.master_contract import master_contract
        en, hi = master_contract("en"), master_contract("hi")
        self.assertIn("retrograde sub-period", en)
        self.assertIn("direct portion as the stronger", en)
        self.assertIn("Retrograde का कोई हिस्सा", hi)
        # Same obstacle-guardrail sentence (requirement B) also lives in the shared master, not per-question.
        self.assertIn("2-3 most meaningful ones", en)
        self.assertIn('never call a placement a "dosha"', en.lower())
        self.assertIn("2-3 सबसे ज़्यादा मायने रखने वाले", hi)


if __name__ == "__main__":
    unittest.main()
