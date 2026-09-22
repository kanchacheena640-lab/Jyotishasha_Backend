"""Final catalog integrity and Life evidence/PDF contracts; no live model."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_focused_promotion_prototype import fixture_kundali, frozen_clock
from test_focused_report_dispatch import response
from scripts.generate_focused_promotion_samples import PERSONA
from modules.intents.question_catalog import QUESTIONS, UnknownQuestionError
from modules.focused_reports import life_evidence as collector, dispatcher, pdf_adapter
from modules.focused_reports.life_keys import (
    LIFE_HORIZONS, LIFE_HOUSES, LIFE_NATAL_PLANETS, DIAGNOSTIC_BIRTH_CURRENT_KEYS,
    LIFE_TRANSIT_PLANETS_DEFAULT, LIFE_TRANSIT_PLANET_OVERRIDES,
)
from modules.focused_reports.life_reports import build_life_report_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec, PROMPT_SPECS
from modules.focused_reports.prompt_contract import Capability, EvidenceRequirement
from modules.focused_reports.prompt_assembler import MissingEvidenceError, PromptAssemblyError
from modules.payments.report_structured_output import ReportMetadataError
import pdf_generator_weasy as renderer


class LifeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.snapshot = collector.get_current_positions()
            # The 12-month fixture also carries Rahu (a superset), since major_kundali_obstacles/strengths
            # (both 12-month horizons) additionally require it; the mock below returns the same fixture
            # regardless of which selected_planets the production code actually requests, so the other,
            # narrower 12-month keys simply ignore the extra Rahu entry.
            cls.transits = {m: collector.build_promotion_transit_evidence(
                cls.kundali["lagna_sign"], horizon_months=m,
                selected_planets=("Jupiter", "Saturn", "Rahu") if m == 12 else ("Jupiter", "Saturn")) for m in (12, 36, 60)}

    def setUp(self):
        for target, kwargs in (
            ("get_current_positions", {"return_value": self.snapshot}),
            ("build_promotion_transit_evidence", {"side_effect": lambda lagna, horizon_months, selected_planets:
                copy.deepcopy(self.transits[horizon_months])}),
        ):
            p = patch.object(collector, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_final_63_catalog_integrity_and_unknown_keys(self):
        keys = [q.question_key for q in QUESTIONS]
        self.assertEqual(len(keys), 63)
        self.assertEqual(len(set(keys)), 63)
        self.assertEqual(set(keys), set(dispatcher.HANDLERS))
        self.assertEqual(set(keys), set(PROMPT_SPECS))
        registrations = [key for group in (
            dispatcher.CAREER_QUESTION_KEYS, dispatcher.MONEY_BUSINESS_QUESTION_KEYS,
            dispatcher.MARRIAGE_QUESTION_KEYS, dispatcher.RELATIONSHIP_QUESTION_KEYS,
            dispatcher.FOREIGN_QUESTION_KEYS, dispatcher.EDUCATION_QUESTION_KEYS,
            dispatcher.PROPERTY_QUESTION_KEYS, dispatcher.LIFE_QUESTION_KEYS) for key in group]
        self.assertEqual(len(registrations), 63)
        self.assertEqual(len(set(registrations)), 63)
        self.assertEqual(set(LIFE_HORIZONS), {q.question_key for q in QUESTIONS if q.category == "life"})
        self.assertEqual(len(LIFE_HORIZONS), 10)
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for q in QUESTIONS:
                selection, handler = dispatcher.resolve_focused_handler(q.question_key)
                spec = get_prompt_spec(q.question_key)
                self.assertEqual(spec.capability, Capability.IMPLEMENTED)
                self.assertEqual((spec.person_mode, spec.intent_slug), (q.person_mode, q.intent_slug))
                self.assertEqual(selection.person_mode, q.person_mode)
                for lang in ("en", "hi"):
                    self.assertEqual(spec.question.get(lang), q.question.get(lang))
                    with self.assertRaises(UnknownQuestionError):
                        dispatcher.generate_focused_report(q.question.get(lang), None)
            for invalid in ("unknown", "LIFE_DIRECTION", "life_direction ", "life_report", "", None):
                with self.assertRaises(UnknownQuestionError):
                    dispatcher.generate_focused_report(invalid, None)
            ai.assert_not_called()

    def test_bilingual_distinct_specs_minimum_evidence_horizons(self):
        prompts, objectives = set(), set()
        for key, months in LIFE_HORIZONS.items():
            spec = get_prompt_spec(key)
            objectives.add(spec.analysis_objective)
            diagnostic = key in DIAGNOSTIC_BIRTH_CURRENT_KEYS
            transit_planets = LIFE_TRANSIT_PLANET_OVERRIDES.get(key, LIFE_TRANSIT_PLANETS_DEFAULT)
            for lang in ("en", "hi"):
                collector.get_current_positions.reset_mock()
                collector.build_promotion_transit_evidence.reset_mock()
                built = build_life_report_prompt(key, self.kundali, lang)
                prompts.add(built.prompt)
                expected = {"birth_chart_summary", "house_lord_summary"}
                if diagnostic:
                    # major_kundali_obstacles/major_kundali_strengths: the same existing NATAL/HOUSES/CAREER/
                    # WEALTH/MD_AD/JUPITER/SATURN/RAHU EvidenceRequirement objects every other focused report
                    # already uses -- no new evidence calculation.
                    expected |= {"career_yoga_summary", "wealth_yoga_summary", "dasha_window_summary"} | set(transit_planets)
                    self.assertEqual(built.evidence.horizon_end, "2027-09-21")
                    collector.build_promotion_transit_evidence.assert_called_once_with(
                        self.kundali["lagna_sign"], horizon_months=months, selected_planets=transit_planets)
                elif months:
                    expected |= {"Jupiter", "Saturn", "dasha_sequence" if months > 12 else "dasha_window_summary"}
                    self.assertEqual(built.evidence.horizon_end, {12: "2027-09-21", 36: "2029-09-21", 60: "2031-09-21"}[months])
                    collector.build_promotion_transit_evidence.assert_called_once_with(
                        self.kundali["lagna_sign"], horizon_months=months, selected_planets=("Jupiter", "Saturn"))
                else:
                    collector.get_current_positions.assert_not_called()
                    collector.build_promotion_transit_evidence.assert_not_called()
                    self.assertIsNone(built.evidence.report_period)
                    self.assertEqual(built.evidence.transit_evidence, {})
                self.assertEqual(set(built.evidence.sections), expected)
                self.assertEqual(expected, {r.key for r in spec.evidence_requirements})
                for value in (spec.question.get(lang), spec.analysis_objective, spec.astrological_focus, spec.output_emphasis, spec.timing_requirement):
                    self.assertIn(value, built.prompt)
                for house in LIFE_HOUSES[key]:
                    self.assertIn(f"House {house} (", built.evidence.sections["house_lord_summary"])
                for banned in ("shadbala", "pratyantar", "ashtakavarga", "career_yoga_summary", "wealth_yoga_summary", "compatibility_facts"):
                    self.assertNotIn(banned, built.prompt.lower())
                self.assertNotRegex(built.prompt.lower(), r"\bd-?(9|10)\b")
                self.assertNotRegex(built.prompt, r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(len(prompts), 20)
        self.assertEqual(len(objectives), 10)

    def test_natal_reports_work_without_dasha_and_exclude_unrelated_facts(self):
        for key in ("natural_strengths", "life_direction"):
            data = {**self.kundali, "Mahadasha": [], "irrelevant": "DO_NOT_INCLUDE"}
            built = build_life_report_prompt(key, data)
            natal = built.evidence.sections["birth_chart_summary"]
            for planet in LIFE_NATAL_PLANETS:
                self.assertIn(planet, natal)
            for planet in ("Mars", "Venus", "Rahu", "Ketu"):
                self.assertNotIn(planet, natal)
            self.assertNotIn("DO_NOT_INCLUDE", built.prompt)
        collector.build_promotion_transit_evidence.assert_not_called()

    def test_meaning_and_agency_boundaries(self):
        self.assertIn("themes rather than inventing events", get_prompt_spec("major_turning_points").output_emphasis)
        self.assertIn("not a guaranteed event day", get_prompt_spec("next_life_change_period").output_emphasis)
        self.assertIn("Current context first", get_prompt_spec("current_phase_meaning").timing_requirement)
        self.assertIn("currently", get_prompt_spec("areas_needing_attention").analysis_objective)
        self.assertIn("not a command or a fixed destiny", get_prompt_spec("life_direction").output_emphasis)
        for key in LIFE_HORIZONS:
            boundary = " ".join(get_prompt_spec(key).boundaries)
            for phrase in ("Preserve customer agency", "No fixed destiny", "guaranteed success/failure", "death/longevity", "Do not diagnose mental illness", "physical disease", "fertility", "addiction", "personality disorders", "quit a job", "end a relationship", "avoid medical treatment", "make legal decisions", "abandon education", "destiny score", "event probability"):
                self.assertIn(phrase, boundary)

    def test_mandatory_missing_and_incomplete_evidence_before_ai(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for key, months in LIFE_HORIZONS.items():
                for data in (None, {}, {**self.kundali, "planets": []}):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, data)
                with patch.object(collector, "build_house_lord_facts", return_value=[]):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, self.kundali)
                with patch.object(collector, "build_summary_blocks_with_transit", return_value={}):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, self.kundali)
                blocks = collector.build_summary_blocks_with_transit(self.kundali, self.snapshot)
                for field in ("birth_chart_summary", "dasha_window_summary", "career_yoga_summary", "wealth_yoga_summary"):
                    if field not in {r.key for r in get_prompt_spec(key).evidence_requirements}:
                        continue
                    with patch.object(collector, "build_summary_blocks_with_transit", return_value={**blocks, field: "unavailable"}):
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(key, self.kundali)
                if not months:
                    continue
                for timeline in ([], [{"mahadasha": "Venus", "antardashas": [
                    {"planet": "Venus", "start": "2026-09-21", "end": "2026-12-01"},
                    {"planet": "Sun", "start": "2027-01-01", "end": "2032-01-01"}]}]):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, {**self.kundali, "Mahadasha": timeline})
                # Diagnostic reports (#62/#63) also require current Jupiter/Saturn/Rahu transit evidence.
                for name in LIFE_TRANSIT_PLANET_OVERRIDES.get(key, LIFE_TRANSIT_PLANETS_DEFAULT):
                    bad = copy.deepcopy(self.transits[months])
                    bad["planets"] = [p for p in bad["planets"] if p["planet"] != name]
                    with patch.object(collector, "build_promotion_transit_evidence", return_value=bad):
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(key, self.kundali)
            ai.assert_not_called()
        spec = get_prompt_spec("natural_strengths")
        for change, error in (({"person_mode": "dual"}, PromptAssemblyError),
            ({"evidence_requirements": spec.evidence_requirements + (EvidenceRequirement("missing", "Missing", "Missing", ("test",)),)}, MissingEvidenceError)):
            with patch.object(collector, "get_prompt_spec", return_value=replace(spec, **change)):
                with self.assertRaises(error):
                    collector.collect_life_evidence("natural_strengths", self.kundali)

    def test_all_shared_results_real_pdfs_both_languages(self):
        with tempfile.TemporaryDirectory() as folder:
            for key in LIFE_HORIZONS:
                for lang in ("en", "hi"):
                    with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=response())) as ai:
                        result = dispatcher.generate_focused_report(key, self.kundali, lang)
                    ai.assert_called_once()
                    self.assertEqual(result["handler_key"], key)
                    self.assertEqual(result["customer_question"], get_prompt_spec(key).question.get(lang))
                    args = pdf_adapter.focused_pdf_arguments(result, PERSONA)
                    self.assertEqual(args["product"], get_prompt_spec(key).title.get(lang))
                    with patch.object(renderer, "HTML") as html:
                        renderer.generate_pdf_report_weasy(output_path=str(Path(folder) / "mock.pdf"), **args)
                    text = html.call_args.kwargs["string"]
                    for value in (result["customer_question"], PERSONA["name"], PERSONA["tob"], PERSONA["pob"]):
                        self.assertIn(value, text)
                    for internal in (key, result["intent_slug"], "===META===", "horizon_months", "gpt-5.6-luna", "2026-10-15"):
                        self.assertNotIn(internal, text)
                    path = pdf_adapter.render_focused_report_pdf(result, PERSONA, Path(folder) / f"{key}_{lang}.pdf")
                    self.assertGreater(pdf_adapter.validate_focused_pdf(path), 0)

    def test_model_and_output_failure_has_no_fallback(self):
        for key in LIFE_HORIZONS:
            with patch("modules.payments.report_ai_client.generate_report_completion", side_effect=RuntimeError("Luna unavailable")) as ai:
                with self.assertRaisesRegex(RuntimeError, "Luna unavailable"):
                    dispatcher.generate_focused_report(key, self.kundali)
                ai.assert_called_once()
            with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content="generic text")):
                with self.assertRaises(ReportMetadataError):
                    dispatcher.generate_focused_report(key, self.kundali)


if __name__ == "__main__":
    unittest.main()
