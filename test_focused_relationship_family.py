"""Dual focused reports: real astrology fixtures, mocked Luna, local PDFs."""
import contextlib
import copy
import io
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_focused_promotion_prototype import frozen_clock, FIXTURE
from test_focused_report_dispatch import response
from modules.focused_reports import relationship_evidence as collector, dispatcher, pdf_adapter
from modules.focused_reports.relationship_keys import RELATIONSHIP_QUESTION_KEYS as KEYS, RELATIONSHIP_HORIZONS, RELATIONSHIP_SELECTIONS
from modules.focused_reports.relationship_reports import build_relationship_report_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_contract import Capability
from modules.focused_reports.prompt_assembler import MissingEvidenceError, PromptAssemblyError
from modules.payments.report_structured_output import ReportMetadataError
from modules.intents.question_catalog import QUESTIONS, UnknownQuestionError
import pdf_generator_weasy as renderer


class RelationshipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = {**FIXTURE, "lng": FIXTURE["lon"]}
        cls.partner = {**cls.user, "name": "Partner Fixture", "dob": "1992-08-20", "tob": "09:15"}
        cls.payload = {"user": cls.user, "partner": cls.partner, "boy_is_user": True}
        cls.charts = {}
        with contextlib.redirect_stdout(io.StringIO()), frozen_clock():
            for p in (cls.user, cls.partner):
                cls.charts[p["name"]] = collector.calculate_full_kundali(
                    name=p["name"], dob=p["dob"], tob=p["tob"], lat=p["lat"], lon=p["lng"], language="en")
            cls.transits = {c["lagna_sign"]: collector.build_promotion_transit_evidence(
                c["lagna_sign"], horizon_months=12, selected_planets=("Jupiter", "Saturn")) for c in cls.charts.values()}

    def setUp(self):
        for target, kwargs in (
            ("calculate_full_kundali", {"side_effect": lambda **kw: copy.deepcopy(self.charts[kw["name"]])}),
            ("build_promotion_transit_evidence", {"side_effect": lambda lagna, **kw: copy.deepcopy(self.transits[lagna])}),
        ):
            p = patch.object(collector, target, **kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_exact_registry_and_fail_closed(self):
        self.assertEqual(set(KEYS), {q.question_key for q in QUESTIONS if q.category == "relationship"})
        self.assertEqual(len(KEYS), 9)
        self.assertEqual(len(dispatcher.HANDLERS), 61)
        remaining = [q for q in QUESTIONS if q.question_key not in dispatcher.HANDLERS]
        self.assertEqual(Counter(q.category for q in remaining), {})
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for q in remaining:
                with self.assertRaises(dispatcher.FocusedReportNotImplementedError):
                    dispatcher.generate_focused_report(q.question_key, None)
            for key in KEYS:
                selection, handler = dispatcher.resolve_focused_handler(key)
                self.assertEqual(handler.key, key)
                self.assertEqual(selection.person_mode, "dual")
                self.assertEqual(get_prompt_spec(key).capability, Capability.IMPLEMENTED)
                for lang in ("en", "hi"):
                    with self.assertRaises(UnknownQuestionError):
                        dispatcher.resolve_focused_handler(selection.display(lang))
            ai.assert_not_called()

    def test_all_prompts_exact_specs_and_minimal_evidence(self):
        prompts = set()
        for key in KEYS:
            for lang in ("en", "hi"):
                collector.build_promotion_transit_evidence.reset_mock()
                built = build_relationship_report_prompt(key, self.payload, lang)
                spec = get_prompt_spec(key)
                prompts.add(built.prompt)
                self.assertEqual(built.customer_question, spec.question.get(lang))
                self.assertEqual(set(built.evidence.sections), {r.key for r in spec.evidence_requirements})
                for value in (spec.question.get(lang), spec.analysis_objective, spec.astrological_focus, spec.output_emphasis, spec.timing_requirement):
                    self.assertIn(value, built.prompt)
                self.assertEqual(built.evidence.horizon_months, RELATIONSHIP_HORIZONS[key])
                if RELATIONSHIP_HORIZONS[key]:
                    self.assertEqual(collector.build_promotion_transit_evidence.call_count, 2)
                    for name in ("both_dasha_windows", "both_relevant_transits"):
                        self.assertIn("Primary person:", built.evidence.sections[name])
                        self.assertIn("Partner:", built.evidence.sections[name])
                    self.assertIn("2027", built.evidence.report_period)
                else:
                    collector.build_promotion_transit_evidence.assert_not_called()
                    self.assertIsNone(built.evidence.report_period)
                facts = built.evidence.sections["compatibility_facts"]
                components = json.loads(facts[facts.index("{"):])
                self.assertEqual(set(components) - {"total_score", "max_score"}, set(RELATIONSHIP_SELECTIONS[key][1]))
                self.assertEqual("total_score" in components, key == "kundali_match_for_marriage")
                for banned in ("shadbala", "pratyantar", "ashtakavarga", "dasha_sequence", "manglik_summary", "career_yoga_summary"):
                    self.assertNotIn(banned, built.prompt.lower())
                self.assertNotRegex(built.prompt.lower(), r"\bd-?(9|10)\b")
                self.assertNotRegex(built.prompt, r"\d{4}-\d{2}-\d{2}")
                for boundary in ("private feelings", "will consent/refuse", "hidden motive", "No guarantee of marriage, breakup, reconciliation", "No therapy diagnosis"):
                    self.assertIn(boundary, built.prompt)
        self.assertEqual(len(prompts), 18)

    def test_missing_profiles_coordinates_and_roles_fail_before_calculation_or_ai(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for key in KEYS:
                for who in ("user", "partner"):
                    for field in ("name", "dob", "tob", "pob", "lat", "lng"):
                        bad = copy.deepcopy(self.payload)
                        del bad[who][field]
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(key, bad)
                for lat, lng in ((None, 70), (True, 70), ("nan", 70), (91, 70), (20, 181), (0, 0), ("", 70)):
                    bad = copy.deepcopy(self.payload)
                    bad["partner"].update(lat=lat, lng=lng)
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, bad)
                for role in (None, "true", 1):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, {**self.payload, "boy_is_user": role})
            collector.calculate_full_kundali.assert_not_called()
            ai.assert_not_called()

    def test_aliases_and_explicit_role_order_reuse_authoritative_matching(self):
        payload = copy.deepcopy(self.payload)
        payload["partner"].update(latitude=0, longitude=70)
        payload["boy_is_user"] = False
        with patch.object(collector, "compute_ashtakoot", wraps=collector.compute_ashtakoot) as match:
            built = build_relationship_report_prompt("kundali_match_for_marriage", payload)
        self.assertEqual(match.call_args.kwargs["groom_moon"], collector._extract_moon(self.charts[self.partner["name"]]))
        self.assertEqual(collector.calculate_full_kundali.call_args.kwargs["lat"], 0)
        self.assertIn("Groom role: Partner", built.evidence.sections["compatibility_facts"])

    def test_missing_chart_matching_and_timing_evidence_fails(self):
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for key in KEYS:
                for missing in ("planets", "lagna_sign"):
                    bad = copy.deepcopy(self.charts[self.partner["name"]])
                    bad.pop(missing)
                    with patch.object(collector, "calculate_full_kundali", side_effect=[self.charts[self.user["name"]], bad]):
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(key, self.payload)
                with patch.object(collector, "compute_ashtakoot", return_value={"kootas": {}}):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, self.payload)
                if RELATIONSHIP_HORIZONS[key]:
                    bad = {**self.charts[self.partner["name"]], "Mahadasha": []}
                    with patch.object(collector, "calculate_full_kundali", side_effect=[self.charts[self.user["name"]], bad]):
                        with self.assertRaises(MissingEvidenceError):
                            dispatcher.generate_focused_report(key, self.payload)
            ai.assert_not_called()
        spec = get_prompt_spec(KEYS[0])
        with patch.object(collector, "get_prompt_spec", return_value=replace(spec, person_mode="single")):
            with self.assertRaises(PromptAssemblyError):
                collector.collect_relationship_evidence(KEYS[0], self.payload)

    def test_all_dual_results_and_real_pdfs_both_languages(self):
        customer = {**self.user, "partner": self.partner}
        with tempfile.TemporaryDirectory() as folder:
            for key in KEYS:
                for lang in ("en", "hi"):
                    with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content=response())) as ai:
                        result = dispatcher.generate_focused_report(key, self.payload, lang)
                    ai.assert_called_once()
                    self.assertEqual(result["customer_question"], get_prompt_spec(key).question.get(lang))
                    args = pdf_adapter.focused_pdf_arguments(result, customer)
                    self.assertEqual(set(args["partner_info"]), {"name", "dob", "tob", "pob"})
                    with patch.object(renderer, "HTML") as html:
                        renderer.generate_pdf_report_weasy(output_path=str(Path(folder) / "mock.pdf"), **args)
                    text = html.call_args.kwargs["string"]
                    for value in (self.user["name"], self.partner["name"], self.partner["tob"], result["customer_question"]):
                        self.assertIn(value, text)
                    for internal in (key, result["intent_slug"], "===META===", "user_natal", "gpt-5.6-luna"):
                        self.assertNotIn(internal, text)
                    path = pdf_adapter.render_focused_report_pdf(result, customer, Path(folder) / f"{key}_{lang}.pdf")
                    self.assertGreater(pdf_adapter.validate_focused_pdf(path), 0)
                    with self.assertRaises(ValueError):
                        pdf_adapter.focused_pdf_arguments(result, self.user)

    def test_timing_gaps_missing_transits_and_model_errors_have_no_fallback(self):
        for key in KEYS:
            with patch("modules.payments.report_ai_client.generate_report_completion", side_effect=RuntimeError("Luna unavailable")) as ai:
                with self.assertRaisesRegex(RuntimeError, "Luna unavailable"):
                    dispatcher.generate_focused_report(key, self.payload)
                ai.assert_called_once()
            with patch("modules.payments.report_ai_client.generate_report_completion", return_value=SimpleNamespace(content="generic text")):
                with self.assertRaises(ReportMetadataError):
                    dispatcher.generate_focused_report(key, self.payload)
            if not RELATIONSHIP_HORIZONS[key]:
                continue
            with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
                bad = copy.deepcopy(next(iter(self.transits.values())))
                bad["planets"] = []
                with patch.object(collector, "build_promotion_transit_evidence", return_value=bad):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, self.payload)
                chart = copy.deepcopy(self.charts[self.partner["name"]])
                chart["Mahadasha"] = [{"mahadasha": "Venus", "antardashas": [
                    {"planet": "Venus", "start": "2026-09-21", "end": "2026-12-01"},
                    {"planet": "Sun", "start": "2027-01-01", "end": "2028-01-01"}]}]
                with patch.object(collector, "calculate_full_kundali", side_effect=[self.charts[self.user["name"]], chart]):
                    with self.assertRaises(MissingEvidenceError):
                        dispatcher.generate_focused_report(key, self.payload)
                ai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
