"""Property contracts: actual local facts, mocked Luna, real PDFs."""
import copy
from collections import Counter
from dataclasses import replace
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_focused_promotion_prototype import fixture_kundali, frozen_clock
from test_focused_report_dispatch import response
from scripts.generate_focused_promotion_samples import PERSONA
from modules.intents.question_catalog import QUESTIONS, UnknownQuestionError
from modules.focused_reports import property_evidence as collector, dispatcher, pdf_adapter
from modules.focused_reports.property_keys import PROPERTY_HORIZONS, PROPERTY_HOUSES
from modules.focused_reports.property_reports import build_property_report_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_contract import Capability, EvidenceRequirement
from modules.focused_reports.prompt_assembler import MissingEvidenceError, PromptAssemblyError
from modules.payments.report_structured_output import ReportMetadataError
import pdf_generator_weasy as renderer


class PropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.snapshot = collector.get_current_positions()
            cls.blocks = collector.build_summary_blocks_with_transit(cls.kundali, cls.snapshot)
            cls.transits = {m: collector.build_promotion_transit_evidence(
                cls.kundali["lagna_sign"], horizon_months=m,
                selected_planets=collector.TRANSIT_PLANETS) for m in (12, 60)}

    def setUp(self):
        for target, kwargs in (
            ("get_current_positions", {"return_value": self.snapshot}),
            ("build_summary_blocks_with_transit", {"return_value": {**self.blocks, "irrelevant": "DO_NOT_INCLUDE"}}),
            ("build_promotion_transit_evidence", {"side_effect": lambda lagna, horizon_months, selected_planets:
                copy.deepcopy(self.transits[horizon_months])}),
        ):
            p = patch.object(collector, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_exact_keys_count_and_fail_closed(self):
        self.assertEqual(set(PROPERTY_HORIZONS), {q.question_key for q in QUESTIONS if q.category == "property"})
        self.assertEqual(len(PROPERTY_HORIZONS), 5)
        self.assertEqual(len(dispatcher.HANDLERS), 61)
        remaining = [q for q in QUESTIONS if q.question_key not in dispatcher.HANDLERS]
        self.assertEqual(len(remaining), 0)
        self.assertEqual(Counter(q.category for q in remaining), {})
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for q in remaining:
                with self.assertRaises(dispatcher.FocusedReportNotImplementedError):
                    dispatcher.generate_focused_report(q.question_key, None)
            for key in PROPERTY_HORIZONS:
                selection, handler = dispatcher.resolve_focused_handler(key)
                self.assertEqual(handler.key, key)
                self.assertEqual(selection.person_mode, "single")
                self.assertEqual(get_prompt_spec(key).capability, Capability.IMPLEMENTED)
                for lang in ("en", "hi"):
                    with self.assertRaises(UnknownQuestionError):
                        dispatcher.resolve_focused_handler(selection.display(lang))
            ai.assert_not_called()

    def test_bilingual_specs_evidence_horizons_and_question_specific_houses(self):
        prompts, objectives = set(), set()
        for key, months in PROPERTY_HORIZONS.items():
            spec = get_prompt_spec(key)
            objectives.add(spec.analysis_objective)
            for lang in ("en", "hi"):
                built = build_property_report_prompt(key, self.kundali, lang)
                prompts.add(built.prompt)
                expected = {"birth_chart_summary", "house_lord_summary", "Jupiter", "Saturn",
                            "dasha_sequence" if months == 60 else "dasha_window_summary"}
                self.assertEqual(set(built.evidence.sections), expected)
                self.assertEqual(expected, {r.key for r in spec.evidence_requirements})
                self.assertEqual(built.customer_question, spec.question.get(lang))
                for value in (spec.question.get(lang), spec.analysis_objective, spec.astrological_focus, spec.output_emphasis, spec.timing_requirement):
                    self.assertIn(value, built.prompt)
                self.assertEqual(built.evidence.horizon_end, "2031-09-21" if months == 60 else "2027-09-21")
                collector.build_promotion_transit_evidence.assert_called_with(self.kundali["lagna_sign"],
                    horizon_months=months, selected_planets=("Jupiter", "Saturn"))
                houses = tuple(map(int, re.findall(r"House (\d+) \(", built.evidence.sections["house_lord_summary"])))
                self.assertEqual(houses, PROPERTY_HOUSES[key])
                for banned in ("DO_NOT_INCLUDE", "shadbala", "pratyantar", "ashtakavarga", "career_yoga_summary", "wealth_yoga_summary", "compatibility_facts"):
                    self.assertNotIn(banned.lower(), built.prompt.lower())
                self.assertNotRegex(built.prompt.lower(), r"\bd-?(9|10)\b")
                self.assertNotRegex(built.prompt, r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(len(prompts), 10)
        self.assertEqual(len(objectives), 5)

    def test_semantic_distinctions_and_boundaries(self):
        self.assertIn("property purchase", get_prompt_spec("property_purchase_timing").analysis_objective)
        self.assertIn("current conditions", get_prompt_spec("property_current_period").analysis_objective)
        self.assertIn("Rank supported windows", get_prompt_spec("property_strongest_period").output_emphasis)
        self.assertIn("personal home", get_prompt_spec("own_home_timing").analysis_objective)
        self.assertIn("not permanent blockage", " ".join(get_prompt_spec("property_delay_reason").boundaries))
        for key in PROPERTY_HORIZONS:
            boundary = " ".join(get_prompt_spec(key).boundaries)
            for text in ("No guaranteed property purchase", "loan approval", "registration", "possession", "price appreciation", "investment return", "dispute outcome", "construction completion", "not financial, legal, mortgage, investment, tax, title", "buy a specific property", "take a loan", "borrow money", "invest a specific amount", "sign an agreement", "ignore legal/title verification", "No purchase probability", "loan probability", "property-success percentage", "investment-return score"):
                self.assertIn(text, boundary)

    def test_missing_evidence_fails_before_ai(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for key, months in PROPERTY_HORIZONS.items():
                for field in ("birth_chart_summary", "dasha_window_summary"):
                    if field not in {r.key for r in get_prompt_spec(key).evidence_requirements}:
                        continue
                    for value in ("", "unavailable", None):
                        with patch.object(collector, "build_summary_blocks_with_transit", return_value={**self.blocks, field: value}):
                            with self.assertRaises(MissingEvidenceError):
                                dispatcher.generate_focused_report(key, self.kundali)
                with patch.object(collector, "build_house_lord_facts", return_value=[]):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, self.kundali)
                for name in collector.TRANSIT_PLANETS:
                    bad = copy.deepcopy(self.transits[months])
                    bad["planets"] = [p for p in bad["planets"] if p["planet"] != name]
                    with patch.object(collector, "build_promotion_transit_evidence", return_value=bad):
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(key, self.kundali)
                for timeline in ([], [{"mahadasha": "Venus", "antardashas": [
                    {"planet": "Venus", "start": "2026-09-21", "end": "2026-12-01"},
                    {"planet": "Sun", "start": "2027-01-01", "end": "2032-01-01"}]}]):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, {**self.kundali, "Mahadasha": timeline})
            for data in (None, {}, {"lagna_sign": "Libra", "planets": []}):
                with self.assertRaises(MissingEvidenceError):
                    dispatcher.generate_focused_report("property_current_period", data)
            ai.assert_not_called()

    def test_unsupported_spec_and_person_mode_fail_closed(self):
        spec = get_prompt_spec("property_current_period")
        extra = EvidenceRequirement("absent", "Absent", "Unavailable", ("test:absent",))
        for change, error in (({"person_mode": "dual"}, PromptAssemblyError),
            ({"evidence_requirements": spec.evidence_requirements + (extra,)}, MissingEvidenceError)):
            with patch.object(collector, "get_prompt_spec", return_value=replace(spec, **change)):
                with self.assertRaises(error):
                    collector.collect_property_evidence("property_current_period", self.kundali)

    def test_all_shared_results_and_real_pdfs_both_languages(self):
        with tempfile.TemporaryDirectory() as folder:
            for key in PROPERTY_HORIZONS:
                for lang in ("en", "hi"):
                    with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=response())) as ai:
                        result = dispatcher.generate_focused_report(key, self.kundali, lang)
                    ai.assert_called_once()
                    self.assertEqual(result["handler_key"], key)
                    self.assertEqual(result["customer_question"], get_prompt_spec(key).question.get(lang))
                    args = pdf_adapter.focused_pdf_arguments(result, PERSONA)
                    self.assertEqual(args["product"], get_prompt_spec(key).title.get(lang))
                    self.assertEqual(args["disclaimer"], pdf_adapter.get_mandatory_disclaimer(
                        pdf_adapter.REGISTRY["property_report"].disclaimer_type, lang))
                    self.assertTrue(args["disclaimer"])
                    with patch.object(renderer, "HTML") as html:
                        renderer.generate_pdf_report_weasy(output_path=str(Path(folder) / "mock.pdf"), **args)
                    text = html.call_args.kwargs["string"]
                    for value in (result["customer_question"], PERSONA["name"], PERSONA["tob"], PERSONA["pob"]):
                        self.assertIn(value, text)
                    for internal in (key, "property_timing", "===META===", "horizon_months", "gpt-5.6-luna", "2026-10-15"):
                        self.assertNotIn(internal, text)
                    path = pdf_adapter.render_focused_report_pdf(result, PERSONA, Path(folder) / f"{key}_{lang}.pdf")
                    self.assertGreater(pdf_adapter.validate_focused_pdf(path), 0)

    def test_model_and_output_errors_propagate_without_fallback(self):
        for key in PROPERTY_HORIZONS:
            with patch("modules.payments.report_ai_client.generate_report_completion", side_effect=RuntimeError("Luna unavailable")) as ai:
                with self.assertRaisesRegex(RuntimeError, "Luna unavailable"):
                    dispatcher.generate_focused_report(key, self.kundali)
                ai.assert_called_once()
            with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content="generic text")):
                with self.assertRaises(ReportMetadataError):
                    dispatcher.generate_focused_report(key, self.kundali)


if __name__ == "__main__":
    unittest.main()
