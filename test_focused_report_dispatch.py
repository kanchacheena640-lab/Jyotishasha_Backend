"""Deterministic generation dispatch tests; the paid AI boundary is mocked."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_focused_promotion_prototype import fixture_kundali, frozen_clock
from modules.focused_reports import dispatcher
from modules.intents.question_catalog import QUESTIONS, UnknownQuestionError, resolve_selection
from modules.payments.report_structured_output import ReportMetadataError


def response(report="Timing: 2026-10-15 to 2027-04-20", actions=None):
    return '===META===\n' + json.dumps({
        "answer_hero": {"label": "Promotion Outlook", "value": "Supportive",
                        "interpretation": "Review from 2026-10-15", "evidence": ["Current Dasha"]},
        "action_items": ["Prepare"] if actions is None else actions,
    }) + '\n===REPORT===\n' + report


class FocusedDispatchTests(unittest.TestCase):
    def test_study_abroad_once_and_foreign_study_absent(self):
        studies = [q for q in QUESTIONS if q.question_en == "Would studying abroad be good for me?"]
        self.assertEqual(len(studies), 1)
        self.assertEqual(studies[0].question_key, "study_abroad")
        self.assertEqual(studies[0].question_hi, "क्या विदेश में पढ़ाई करना मेरे लिए अच्छा रहेगा?")
        self.assertFalse(any("foreign_study" in q.question_key for q in QUESTIONS))
        for q in QUESTIONS:
            for lang in ("en", "hi"):
                self.assertEqual(resolve_selection(q.question_key).display(lang), q.question.get(lang))

    def test_exact_question_dispatch_and_all_other_questions_fail_before_ai(self):
        selection, handler = dispatcher.resolve_focused_handler("promotion_timing")
        self.assertEqual(handler.key, "promotion")
        self.assertEqual(selection.intent_slug, "career_growth_timing")
        with patch("modules.payments.report_ai_client.generate_report_completion") as ai:
            for q in QUESTIONS:
                if q.category in ("career", "money_business", "marriage", "relationship", "foreign", "education", "property", "life"):
                    continue
                with self.assertRaises(dispatcher.FocusedReportNotImplementedError) as caught:
                    dispatcher.generate_focused_report(q.question_key, None)
                self.assertEqual(caught.exception.code, "focused_report_not_implemented")
                self.assertEqual(caught.exception.question_key, q.question_key)
            with self.assertRaises(UnknownQuestionError):
                dispatcher.generate_focused_report("unknown", None)
            ai.assert_not_called()

    def test_generation_reuses_evidence_and_normalizes_both_languages(self):
        kundali = fixture_kundali()
        for lang, date in (("en", "15 October 2026"), ("hi-IN", "15 अक्टूबर 2026")):
            with frozen_clock(), patch("modules.payments.report_ai_client.generate_report_completion",
                                       return_value=SimpleNamespace(content=response())) as ai:
                result = dispatcher.generate_focused_report("promotion_timing", kundali, lang)
            ai.assert_called_once()
            prompt = ai.call_args.args[0]
            self.assertIn(result["customer_question"], prompt)
            self.assertIn("Sign residence:", prompt)
            self.assertIn("Motion:", prompt)
            self.assertNotIn("shadbala", prompt.lower())
            self.assertIn(date, result["report"])
            self.assertIn(date, result["hero"]["interpretation"])
            self.assertNotIn("2026-10-15", json.dumps(result))

    def test_ai_failure_propagates_without_fallback(self):
        with patch.object(dispatcher, "HANDLERS", {"promotion_timing": dispatcher.FocusedReportHandler(
            "promotion", lambda *args: SimpleNamespace(prompt="facts", language="en"), lambda *args: {})}), patch(
                "modules.payments.report_ai_client.generate_report_completion", side_effect=RuntimeError("Luna unavailable")) as ai:
            with self.assertRaisesRegex(RuntimeError, "Luna unavailable"):
                dispatcher.generate_focused_report("promotion_timing", {})
            ai.assert_called_once()

    def test_invalid_output_fails_closed(self):
        _, handler = dispatcher.resolve_focused_handler("promotion_timing")
        for raw in ("generic text", response(report=""), response(actions="not a list"), response(actions=[1])):
            with self.assertRaises(ReportMetadataError):
                handler.finalize(raw, "en")


if __name__ == "__main__":
    unittest.main()
