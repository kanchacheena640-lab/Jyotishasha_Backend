"""All actual Career keys: evidence, exact prompts, mocked AI and HTML rendering."""
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
from modules.focused_reports import career_evidence as collector, dispatcher, pdf_adapter
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_contract import Capability, EvidenceRequirement
from modules.focused_reports.prompt_assembler import MissingEvidenceError
from modules.focused_reports.career_reports import build_career_report_prompt
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence
from summary_blocks import build_summary_blocks_with_transit
from transit_engine import get_current_positions
import pdf_generator_weasy as renderer

CAREER = tuple(q for q in QUESTIONS if q.category == "career")


class CareerFamilyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.snapshot = get_current_positions()
            cls.blocks = build_summary_blocks_with_transit(cls.kundali, cls.snapshot)
            cls.transits = {months: build_promotion_transit_evidence(cls.kundali["lagna_sign"], horizon_months=months)
                            for months in (12, 60)}

    def setUp(self):
        # Reuse real frozen engine facts for the 24 assembly paths; do not
        # recalculate ephemeris for every question or call any external model.
        for target, kwargs in (
            ("get_current_positions", {"return_value": self.snapshot}),
            ("build_summary_blocks_with_transit", {"return_value": self.blocks}),
            ("build_promotion_transit_evidence", {"side_effect": lambda lagna, horizon_months: copy.deepcopy(self.transits[horizon_months])}),
        ):
            p = patch.object(collector, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_exact_career_registration_and_noncareer_fail_closed(self):
        self.assertEqual(set(dispatcher.HANDLERS), {q.question_key for q in QUESTIONS if q.category in ("career", "money_business", "marriage", "relationship", "foreign", "education", "property", "life")})
        for q in QUESTIONS:
            if q.category in ("career", "money_business", "marriage", "relationship", "foreign", "education", "property", "life"):
                selected, handler = dispatcher.resolve_focused_handler(q.question_key)
                self.assertEqual(selected.intent_slug, q.intent_slug)
                self.assertEqual(get_prompt_spec(q.question_key).capability, Capability.IMPLEMENTED)
            else:
                with self.assertRaises(dispatcher.FocusedReportNotImplementedError):
                    dispatcher.resolve_focused_handler(q.question_key)
        with self.assertRaises(UnknownQuestionError):
            dispatcher.resolve_focused_handler(CAREER[0].question_en)

    def test_each_question_uses_exact_spec_and_only_its_declared_evidence(self):
        for q in CAREER:
            spec = get_prompt_spec(q.question_key)
            for language in ("en", "hi"):
                built = build_career_report_prompt(q.question_key, self.kundali, language)
                self.assertIn(spec.question.get(language), built.prompt)
                self.assertIn(spec.analysis_objective, built.prompt)
                self.assertIn(spec.output_emphasis, built.prompt)
                self.assertEqual(set(built.evidence.sections), {r.key for r in spec.evidence_requirements})
                self.assertEqual({p["planet"] for p in built.evidence.transit_evidence["planets"]}, {"Jupiter", "Saturn", "Rahu"})
                for planet in built.evidence.transit_evidence["planets"]:
                    self.assertTrue(planet["sign_residence"])
                    self.assertTrue(planet["motion_periods"])
                    self.assertTrue(all("motion" not in r for r in planet["sign_residence"]))
                for banned in ("shadbala", "pratyantar", "ashtakavarga", "wealth_yoga_summary", "gemstone_summary"):
                    self.assertNotIn(banned, built.prompt.lower())
                self.assertNotRegex(built.prompt.lower(), r"\bd-?(9|10)\b")
                self.assertNotRegex(built.prompt, r"\d{4}-\d{2}-\d{2}")
                if q.question_key == "best_career_years":
                    self.assertNotIn("dasha_window_summary", built.evidence.sections)
                    self.assertIn("dasha_sequence", built.evidence.sections)
                    self.assertEqual(built.evidence.horizon_end, "2031-09-21")
                else:
                    self.assertEqual(built.evidence.horizon_end, "2027-09-21")

    def test_all_handlers_mocked_generation_and_shared_pdf_template_both_languages(self):
        prompts = {}
        with tempfile.TemporaryDirectory() as folder:
            for q in CAREER:
                for language in ("en", "hi"):
                    with patch("modules.payments.report_ai_client.generate_report_completion",
                               return_value=SimpleNamespace(content=response())) as ai:
                        result = dispatcher.generate_focused_report(q.question_key, self.kundali, language)
                    ai.assert_called_once()
                    prompt = ai.call_args.args[0]
                    self.assertIn(q.question.get(language), prompt)
                    self.assertIn(get_prompt_spec(q.question_key).analysis_objective, prompt)
                    prompts[q.question_key, language] = prompt
                    self.assertEqual(result["question_key"], q.question_key)
                    self.assertEqual(result["intent_slug"], q.intent_slug)
                    self.assertEqual(result["customer_question"], q.question.get(language))
                    self.assertNotIn("2026-10-15", result["report"])
                    args = pdf_adapter.focused_pdf_arguments(result, PERSONA)
                    self.assertEqual(args["product"], get_prompt_spec(q.question_key).title.get(language))
                    with patch.object(renderer, "HTML") as html:
                        renderer.generate_pdf_report_weasy(output_path=str(Path(folder) / "mock.pdf"), **args)
                    text = html.call_args.kwargs["string"]
                    self.assertIn(q.question.get(language), text)
                    self.assertIn(args["product"], text)
                    self.assertIn(PERSONA["name"], text)
                    self.assertIn(PERSONA["tob"], text)
                    self.assertIn(PERSONA["pob"], text)
                    self.assertIn("15 June 1990" if language == "en" else "15 जून 1990", text)
                    for internal in (q.question_key, q.intent_slug, "===META===", "gpt-5.6-luna", "raw_evidence"):
                        self.assertNotIn(internal, text)
        self.assertEqual(len(set(prompts.values())), 2 * len(CAREER))

    def test_missing_required_summary_fails_before_ai(self):
        with patch.object(collector, "build_summary_blocks_with_transit", return_value={}), patch(
                "modules.payments.report_ai_client.generate_report_completion") as ai:
            for q in CAREER:
                with self.assertRaises(MissingEvidenceError):
                    dispatcher.generate_focused_report(q.question_key, self.kundali)
            ai.assert_not_called()

    def test_missing_natal_facts_fail_before_ai(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for data in (None, {}, {"lagna_sign": "Libra", "planets": []}):
                with self.assertRaises(MissingEvidenceError):
                    dispatcher.generate_focused_report("new_job_timing", data)
            ai.assert_not_called()

    def test_unexpected_spec_requirement_is_rejected_not_silently_expanded(self):
        spec = get_prompt_spec("new_job_timing")
        extra = EvidenceRequirement("unexpected_evidence", "Unexpected", "New unsupported facts", ("test:placeholder",))
        with patch.object(collector, "get_prompt_spec", return_value=replace(spec, evidence_requirements=spec.evidence_requirements + (extra,))):
            with self.assertRaises(MissingEvidenceError):
                collector.collect_career_evidence(spec.question_key, self.kundali)

    def test_multiyear_uses_original_dates_and_rejects_missing_or_gapped_coverage(self):
        start, end = "2026-09-21", "2031-09-21"
        text = collector.multi_year_dasha_summary(self.kundali, start, end)
        expected = [r for r in collector._flatten_dasha_sequence(self.kundali["Mahadasha"])
                    if r["end"] >= start and r["start"] <= end]
        self.assertGreaterEqual(len(expected), 3)
        self.assertEqual(len(text.splitlines()), len(expected))
        for row in expected:
            self.assertIn(row["start"], text)
            self.assertIn(row["end"], text)
        for kundali in ({}, {"Mahadasha": []}, {"Mahadasha": [{"mahadasha": "Mercury", "antardashas": [
                {"planet": "Mercury", "start": "2026-01-01", "end": "2027-01-01"},
                {"planet": "Venus", "start": "2028-01-01", "end": "2032-01-01"}]}]}):
            with self.assertRaises(MissingEvidenceError):
                collector.multi_year_dasha_summary(kundali, start, end)

    def test_boundaries_and_example_names_do_not_invent_catalog_questions(self):
        for q in CAREER:
            boundaries = " ".join(get_prompt_spec(q.question_key).boundaries)
            self.assertIn("continued employment", boundaries)
            self.assertIn("job loss" if q.intent_slug == "job_change_timing" else "job-loss", boundaries)
            if q.intent_slug == "job_change_timing":
                self.assertIn("Do not tell the user to resign", boundaries)
                self.assertIn("selection or appointment", boundaries)
        self.assertIn("salary amount", " ".join(get_prompt_spec("salary_growth_timing").boundaries))
        keys = {q.question_key for q in QUESTIONS}
        for absent in ("job_stability", "job_vs_business", "government_job"):
            self.assertNotIn(absent, keys)
        foreign = get_prompt_spec("foreign_work_timing")
        self.assertIn("guaranteed job or visa", foreign.output_emphasis)
        selection, handler = dispatcher.resolve_focused_handler("foreign_work_timing")
        self.assertEqual(selection.intent_slug, "foreign_move_timing")
        self.assertEqual(handler.key, "foreign_work_timing")
        self.assertIn("not commands", " ".join(get_prompt_spec("business_start_timing").boundaries))

    def test_pdf_rejects_other_career_keys_leaked_in_narrative(self):
        with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=response())):
            result = dispatcher.generate_focused_report("new_job_timing", self.kundali)
        for internal in ("new_job_timing", "job_change_timing", "best_career_years", "dasha_sequence"):
            with self.assertRaises(ValueError):
                pdf_adapter.focused_pdf_arguments({**result, "report": internal}, PERSONA)


if __name__ == "__main__":
    unittest.main()
