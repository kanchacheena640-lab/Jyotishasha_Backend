"""Deterministic Money/Business contracts; no external model calls."""
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
from modules.focused_reports import money_business_evidence as collector, dispatcher, pdf_adapter
from modules.focused_reports.money_business_keys import MONEY_QUESTION_KEYS, BUSINESS_QUESTION_KEYS, MULTI_YEAR_KEYS
from modules.focused_reports.money_business_reports import build_money_business_report_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_contract import Capability, EvidenceRequirement
from modules.focused_reports.prompt_assembler import MissingEvidenceError
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence
from summary_blocks import build_summary_blocks_with_transit
from transit_engine import get_current_positions
import pdf_generator_weasy as renderer

QUESTIONS_MB = tuple(q for q in QUESTIONS if q.category == "money_business")


class MoneyBusinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kundali = fixture_kundali()
        with frozen_clock():
            cls.snapshot = get_current_positions()
            cls.blocks = build_summary_blocks_with_transit(cls.kundali, cls.snapshot)
            cls.transits = {m: build_promotion_transit_evidence(cls.kundali["lagna_sign"], horizon_months=m,
                              selected_planets=("Jupiter", "Saturn")) for m in (12, 60)}

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

    def test_registration_and_fail_closed(self):
        self.assertEqual(len(QUESTIONS_MB), 11)
        self.assertEqual(len(dispatcher.HANDLERS), 61)
        unsupported = []
        for q in QUESTIONS:
            if q.category in ("career", "money_business", "marriage", "relationship", "foreign", "education", "property", "life"):
                selected, handler = dispatcher.resolve_focused_handler(q.question_key)
                self.assertEqual(selected.intent_slug, q.intent_slug)
                self.assertEqual(get_prompt_spec(q.question_key).capability, Capability.IMPLEMENTED)
            else:
                unsupported.append(q)
                with self.assertRaises(dispatcher.FocusedReportNotImplementedError):
                    dispatcher.resolve_focused_handler(q.question_key)
        self.assertEqual(len(unsupported), 0)
        for q in QUESTIONS_MB:
            for text in (q.question_en, q.question_hi):
                with self.assertRaises(UnknownQuestionError):
                    dispatcher.resolve_focused_handler(text)

    def test_exact_distinct_specs_languages_evidence_and_horizons(self):
        objectives, prompts = set(), set()
        for q in QUESTIONS_MB:
            spec = get_prompt_spec(q.question_key)
            objectives.add(spec.analysis_objective)
            for lang in ("en", "hi"):
                built = build_money_business_report_prompt(q.question_key, self.kundali, lang)
                prompts.add(built.prompt)
                self.assertEqual(built.customer_question, q.question.get(lang))
                for value in (q.question.get(lang), spec.analysis_objective, spec.astrological_focus, spec.output_emphasis):
                    self.assertIn(value, built.prompt)
                expected = {"birth_chart_summary", "house_lord_summary", "wealth_yoga_summary", "Jupiter", "Saturn"}
                expected.add("dasha_sequence" if q.question_key in MULTI_YEAR_KEYS else "dasha_window_summary")
                if q.question_key in BUSINESS_QUESTION_KEYS:
                    expected.add("career_yoga_summary")
                self.assertEqual(set(built.evidence.sections), expected)
                self.assertEqual(expected, {r.key for r in spec.evidence_requirements})
                self.assertEqual({p["planet"] for p in built.evidence.transit_evidence["planets"]}, {"Jupiter", "Saturn"})
                self.assertEqual(built.evidence.horizon_end, "2031-09-21" if q.question_key in MULTI_YEAR_KEYS else "2027-09-21")
                for banned in ("DO_NOT_INCLUDE", "shadbala", "pratyantar", "ashtakavarga", "gemstone_summary", "success score", "wealth score", "debt score"):
                    self.assertNotIn(banned.lower(), built.prompt.lower())
                self.assertNotRegex(built.prompt.lower(), r"\bd-?(9|10)\b")
                self.assertNotRegex(built.prompt, r"\d{4}-\d{2}-\d{2}")
                self.assertNotIn("Ketu is always", built.prompt)
        self.assertEqual(len(objectives), 11)
        self.assertEqual(len(prompts), 22)

    def test_each_mandatory_summary_missing_fails_before_ai(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for q in QUESTIONS_MB:
                for req in get_prompt_spec(q.question_key).evidence_requirements:
                    if req.key not in collector.SUMMARY_KEYS:
                        continue
                    with patch.object(collector, "build_summary_blocks_with_transit", return_value={**self.blocks, req.key: ""}):
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(q.question_key, self.kundali)
            ai.assert_not_called()

    def test_missing_natal_timeline_transit_and_unsupported_requirement(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for data in (None, {}, {"lagna_sign": "Libra", "planets": []}):
                with self.assertRaises(MissingEvidenceError):
                    dispatcher.generate_focused_report(MONEY_QUESTION_KEYS[0], data)
            for key in MULTI_YEAR_KEYS:
                with self.assertRaises(MissingEvidenceError):
                    dispatcher.generate_focused_report(key, {**self.kundali, "Mahadasha": []})
            bad = copy.deepcopy(self.transits[12]); bad["planets"] = []
            with patch.object(collector, "build_promotion_transit_evidence", return_value=bad):
                with self.assertRaises(MissingEvidenceError):
                    dispatcher.generate_focused_report(MONEY_QUESTION_KEYS[0], self.kundali)
            spec = get_prompt_spec(MONEY_QUESTION_KEYS[0])
            extra = EvidenceRequirement("absent", "Absent", "Unavailable", ("test:absent",))
            with patch.object(collector, "get_prompt_spec", return_value=replace(spec, evidence_requirements=spec.evidence_requirements + (extra,))):
                with self.assertRaises(MissingEvidenceError):
                    collector.collect_money_evidence(spec.question_key, self.kundali)
            ai.assert_not_called()

    def test_financial_and_question_specific_boundaries(self):
        for q in QUESTIONS_MB:
            boundaries = " ".join(get_prompt_spec(q.question_key).boundaries)
            for word in ("trading", "lending", "borrowing", "tax", "salary", "investment returns", "debt repayment", "wealth creation"):
                self.assertIn(word, boundaries)
            if q.question_key in BUSINESS_QUESTION_KEYS:
                for phrase in ("take a loan", "quit employment", "close a business", "sign a partnership", "buy/sell securities"):
                    self.assertIn(phrase, boundaries)
        self.assertIn("definitely disappear", " ".join(get_prompt_spec("debt_pressure_easing").boundaries))
        for key in ("business_start_timing", "business_expansion_timing"):
            self.assertIn("not a command to proceed", " ".join(get_prompt_spec(key).boundaries))
        self.assertIn("partner reliability", " ".join(get_prompt_spec("new_venture_partnership_timing").boundaries))

    def test_all_results_shared_pdf_template_and_real_pdf_both_languages(self):
        with tempfile.TemporaryDirectory() as folder:
            for q in QUESTIONS_MB:
                for lang in ("en", "hi"):
                    with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=response())) as ai:
                        result = dispatcher.generate_focused_report(q.question_key, self.kundali, lang)
                    ai.assert_called_once()
                    self.assertEqual(result["customer_question"], q.question.get(lang))
                    self.assertEqual(result["intent_slug"], q.intent_slug)
                    self.assertNotIn("2026-10-15", result["report"])
                    args = pdf_adapter.focused_pdf_arguments(result, PERSONA)
                    self.assertTrue(args["disclaimer"])
                    with patch.object(renderer, "HTML") as html:
                        renderer.generate_pdf_report_weasy(output_path=str(Path(folder) / "mock.pdf"), **args)
                    text = html.call_args.kwargs["string"]
                    self.assertEqual(args["product"], get_prompt_spec(q.question_key).title.get(lang))
                    # The existing renderer title-cases product display labels.
                    self.assertIn(get_prompt_spec(q.question_key).title.get(lang).lower(), text.lower())
                    for value in (q.question.get(lang), PERSONA["name"], PERSONA["tob"], PERSONA["pob"], args["disclaimer"]):
                        self.assertIn(value, text)
                    for internal in (q.question_key, q.intent_slug, "===META===", "gpt-5.6-luna", "wealth_yoga_summary", "horizon_months"):
                        self.assertNotIn(internal, text)
                    if q.question_key in ("financial_improvement_timing", "business_start_timing"):
                        path = pdf_adapter.render_focused_report_pdf(result, PERSONA, Path(folder) / f"{q.question_key}_{lang}.pdf")
                        self.assertGreater(pdf_adapter.validate_focused_pdf(path), 0)


if __name__ == "__main__":
    unittest.main()
