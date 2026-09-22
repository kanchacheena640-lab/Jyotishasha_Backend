"""Marriage focused contracts with real local evidence and mocked Luna only."""
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
from modules.focused_reports import marriage_evidence as collector, dispatcher, pdf_adapter
from modules.focused_reports.marriage_keys import MARRIAGE_HORIZONS, MARRIAGE_QUESTION_KEYS
from modules.focused_reports.marriage_reports import build_marriage_report_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_contract import Capability, EvidenceRequirement
from modules.focused_reports.prompt_assembler import MissingEvidenceError, PromptAssemblyError
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence
from modules.payments.report_structured_output import ReportMetadataError
from summary_blocks import build_summary_blocks_with_transit
from transit_engine import get_current_positions
import pdf_generator_weasy as renderer


class MarriageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.snapshot = get_current_positions()
            cls.blocks = build_summary_blocks_with_transit(cls.kundali, cls.snapshot)
            cls.transits = {m: build_promotion_transit_evidence(
                cls.kundali["lagna_sign"], horizon_months=m,
                selected_planets=("Jupiter", "Saturn")) for m in (12, 60)}

    def setUp(self):
        for target, kwargs in (
            ("get_current_positions", {"return_value": self.snapshot}),
            ("build_summary_blocks_with_transit", {"return_value": {
                **self.blocks, "compatibility_facts": "PARTNER_SECRET", "irrelevant": "UNRELATED_FACT"}}),
            ("build_promotion_transit_evidence", {"side_effect": lambda lagna, horizon_months, selected_planets:
                copy.deepcopy(self.transits[horizon_months])}),
        ):
            p = patch.object(collector, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_exact_registration_and_remaining_fail_closed_before_ai(self):
        self.assertEqual(set(MARRIAGE_QUESTION_KEYS), {q.question_key for q in QUESTIONS if q.category == "marriage"})
        self.assertEqual(len(MARRIAGE_QUESTION_KEYS), 6)
        self.assertEqual(len(dispatcher.HANDLERS), 61)
        unsupported = [q for q in QUESTIONS if q.question_key not in dispatcher.HANDLERS]
        self.assertEqual(len(unsupported), 0)
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for q in unsupported:
                with self.assertRaises(dispatcher.FocusedReportNotImplementedError):
                    dispatcher.generate_focused_report(q.question_key, None)
            for key in MARRIAGE_QUESTION_KEYS:
                selection, handler = dispatcher.resolve_focused_handler(key)
                self.assertEqual(handler.key, key)
                self.assertEqual(selection.person_mode, "single")
                self.assertEqual(get_prompt_spec(key).capability, Capability.IMPLEMENTED)
                with self.assertRaises(UnknownQuestionError):
                    dispatcher.resolve_focused_handler(get_prompt_spec(key).question.en)
            ai.assert_not_called()

    def test_distinct_prompts_exact_evidence_and_horizons_both_languages(self):
        prompts, objectives = set(), set()
        for key, months in MARRIAGE_HORIZONS.items():
            spec = get_prompt_spec(key)
            objectives.add(spec.analysis_objective)
            expected = {"birth_chart_summary", "house_lord_summary", "Jupiter", "Saturn",
                        "dasha_sequence" if months == 60 else "dasha_window_summary"}
            for lang in ("en", "hi"):
                built = build_marriage_report_prompt(key, self.kundali, lang)
                prompts.add(built.prompt)
                self.assertEqual(built.customer_question, spec.question.get(lang))
                self.assertEqual(set(built.evidence.sections), expected)
                self.assertEqual({r.key for r in spec.evidence_requirements}, expected)
                self.assertEqual(built.evidence.report_date, "2026-09-21")
                self.assertEqual(built.evidence.horizon_end, "2031-09-21" if months == 60 else "2027-09-21")
                collector.build_promotion_transit_evidence.assert_called_with(
                    self.kundali["lagna_sign"], horizon_months=months, selected_planets=("Jupiter", "Saturn"))
                for value in (spec.question.get(lang), spec.analysis_objective, spec.astrological_focus, spec.output_emphasis):
                    self.assertIn(value, built.prompt)
                for banned in ("PARTNER_SECRET", "UNRELATED_FACT", "compatibility_facts", "wealth_yoga_summary", "shadbala", "pratyantar"):
                    self.assertNotIn(banned, built.prompt)
                self.assertNotRegex(built.prompt, r"\d{4}-\d{2}-\d{2}")
        self.assertEqual(len(prompts), 12)
        self.assertEqual(len(objectives), 6)

    def test_missing_required_evidence_fails_before_ai(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for key, months in MARRIAGE_HORIZONS.items():
                for req in get_prompt_spec(key).evidence_requirements:
                    if req.key in collector.SUMMARY_KEYS:
                        with patch.object(collector, "build_summary_blocks_with_transit", return_value={**self.blocks, req.key: ""}):
                            with self.assertRaises(MissingEvidenceError):
                                dispatcher.generate_focused_report(key, self.kundali)
                for name in ("Jupiter", "Saturn"):
                    bad = copy.deepcopy(self.transits[months])
                    bad["planets"] = [p for p in bad["planets"] if p["planet"] != name]
                    with patch.object(collector, "build_promotion_transit_evidence", return_value=bad):
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(key, self.kundali)
                for timeline in ([], [{"mahadasha": "Venus", "antardashas": [
                    {"planet": "Venus", "start": "2026-01-01", "end": "2027-01-01"}]}]):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, {**self.kundali, "Mahadasha": timeline})
            for data in (None, {}, {"lagna_sign": "Libra", "planets": []}):
                with self.assertRaises(MissingEvidenceError):
                    dispatcher.generate_focused_report(MARRIAGE_QUESTION_KEYS[0], data)
            ai.assert_not_called()

    def test_self_boundary_and_unsupported_requirements(self):
        key = "relationship_to_marriage_window"
        spec = get_prompt_spec(key)
        for lang in ("en", "hi"):
            prompt = build_marriage_report_prompt(key, self.kundali, lang).prompt
            for phrase in ("own commitment timing", "intentions", "feelings", "willingness", "future decisions", "consent", "partner's chart"):
                self.assertIn(phrase, prompt)
        for change, error in (({"person_mode": "dual"}, PromptAssemblyError),
                              ({"evidence_requirements": spec.evidence_requirements + (
                                  EvidenceRequirement("missing", "Missing", "Unavailable", ("test",)),)}, MissingEvidenceError)):
            with patch.object(collector, "get_prompt_spec", return_value=replace(spec, **change)):
                with self.assertRaises(error):
                    collector.collect_marriage_evidence(key, self.kundali)
        self.assertIn("permanent denial", " ".join(get_prompt_spec("marriage_delay_reason").boundaries))

    def test_unavailable_current_summary_is_not_hidden_by_timeline(self):
        for value in ("Dasha window data not available.", "unavailable", "   ", None):
            with patch.object(collector, "build_summary_blocks_with_transit", return_value={
                **self.blocks, "dasha_window_summary": value}):
                with self.assertRaises(MissingEvidenceError):
                    build_marriage_report_prompt("marriage_delay_reason", self.kundali)

    def test_shared_results_pdf_all_keys_both_languages(self):
        with tempfile.TemporaryDirectory() as folder:
            for key in MARRIAGE_QUESTION_KEYS:
                for lang in ("en", "hi"):
                    spec = get_prompt_spec(key)
                    with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=response())) as ai:
                        result = dispatcher.generate_focused_report(key, self.kundali, lang)
                    ai.assert_called_once()
                    self.assertEqual(result["handler_key"], key)
                    self.assertEqual(result["intent_slug"], "marriage_timing")
                    self.assertEqual(result["customer_question"], spec.question.get(lang))
                    self.assertNotIn("2026-10-15", result["report"])
                    args = pdf_adapter.focused_pdf_arguments(result, PERSONA)
                    self.assertEqual(args["product"], spec.title.get(lang))
                    with patch.object(renderer, "HTML") as html:
                        renderer.generate_pdf_report_weasy(output_path=str(Path(folder) / "mock.pdf"), **args)
                    text = html.call_args.kwargs["string"]
                    self.assertEqual(args["disclaimer"], pdf_adapter.get_mandatory_disclaimer(
                        pdf_adapter.REGISTRY["marriage_report"].disclaimer_type, lang))
                    for value in (spec.question.get(lang), PERSONA["name"], PERSONA["tob"], PERSONA["pob"]):
                        self.assertIn(value, text)
                    for internal in (key, "marriage_timing", "===META===", "horizon_months", "gpt-5.6-luna"):
                        self.assertNotIn(internal, text)
                    path = pdf_adapter.render_focused_report_pdf(result, PERSONA, Path(folder) / f"{key}_{lang}.pdf")
                    self.assertGreater(pdf_adapter.validate_focused_pdf(path), 0)

    def test_luna_and_output_errors_propagate_without_fallback(self):
        for key in MARRIAGE_QUESTION_KEYS:
            with patch("modules.payments.report_ai_client.generate_report_completion", side_effect=RuntimeError("Luna unavailable")) as ai:
                with self.assertRaisesRegex(RuntimeError, "Luna unavailable"):
                    dispatcher.generate_focused_report(key, self.kundali)
                ai.assert_called_once()
            with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content="generic text")):
                with self.assertRaises(ReportMetadataError):
                    dispatcher.generate_focused_report(key, self.kundali)


if __name__ == "__main__":
    unittest.main()
