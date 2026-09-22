"""Real EN/HI PDF renders with deterministic fixtures; no AI or delivery."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from weasyprint import HTML

from modules.focused_reports import pdf_adapter as adapter
from scripts.generate_focused_promotion_samples import PERSONA, sample_result


class FocusedPdfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.outputs = {}
        for language in ("en", "hi"):
            captured = []
            def capture(string, base_url):
                captured.append(string)
                return HTML(string=string, base_url=base_url)
            result = sample_result(language)
            # Exercise the renderer's Q5.6 safety net even if a caller supplies
            # a valid ISO range instead of the already-normalized result text.
            displayed = "15 October 2026 to 20 April 2027" if language == "en" else "15 अक्टूबर 2026 से 20 अप्रैल 2027"
            iso_range = "2026-10-15 to 2027-04-20" if language == "en" else "2026-10-15 से 2027-04-20"
            result["report"] = result["report"].replace(displayed, iso_range)
            # These extra internal fields must never enter the renderer contract.
            result.update(prompt="PRIVATE_PROMPT", raw_evidence={"secret": "PRIVATE_EVIDENCE"}, model="gpt-5.6-luna")
            original = copy.deepcopy(result)
            with patch("pdf_generator_weasy.HTML", side_effect=capture):
                path = adapter.render_focused_report_pdf(result, PERSONA,
                    Path(cls.folder.name) / f"promotion_{language}.pdf", is_sample=True)
            reader = PdfReader(path, strict=True)
            cls.outputs[language] = (path, captured[0], "\n".join(p.extract_text() for p in reader.pages), result, original)

    def test_adapter_uses_shared_renderer_contract_without_extra_astrology(self):
        for language in ("en", "hi"):
            args = adapter.focused_pdf_arguments(sample_result(language), PERSONA)
            self.assertEqual(args["summary_blocks"], {})
            self.assertEqual(args["used_placeholders"], [])
            self.assertIsNone(args["kundali_drawing"])
            self.assertEqual(set(args["user_info"]), {"name", "dob", "tob", "pob"})
            self.assertEqual(args["narrative_style"], "plain")

    def test_bilingual_title_question_identity_and_dates(self):
        for lang, dob, timing in (("en", "15 June 1990", "15 October 2026 to 20 April 2027"),
                                  ("hi", "15 जून 1990", "15 अक्टूबर 2026 से 20 अप्रैल 2027")):
            path, html, text, _, _ = self.outputs[lang]
            for expected in (adapter.TITLES[lang], sample_result(lang)["customer_question"],
                             PERSONA["name"], PERSONA["pob"], PERSONA["tob"], dob, timing):
                self.assertIn(expected, html)
                # pypdf inserts spaces between shaped Hindi glyphs and cannot
                # faithfully reconstruct all month-name ligatures. Exact dates
                # are asserted in the rendered HTML; actual PDF pages are also
                # visually checked by the local sample workflow.
                if lang == "hi" and expected == timing:
                    self.assertIn("2026", text)
                    self.assertIn("2027", text)
                else:
                    self.assertIn("".join(expected.split()), "".join(text.split()))
            self.assertNotIn("1990-06-15", text)
            self.assertNotIn("2026-10-15", text)
            self.assertIn("Jyotishasha", text)
            self.assertIn("Page 1 of", text)
            self.assertIn("NotoSansDevanagari-Regular.ttf", html)
            self.assertIn('body class="hi"' if lang == "hi" else 'body class=""', html)
            self.assertGreaterEqual(adapter.validate_focused_pdf(path), 2)

    def test_internal_fields_never_render_and_inputs_are_unchanged(self):
        for _, html, text, result, original in self.outputs.values():
            self.assertEqual(result, original)
            for internal in ("===META===", "===REPORT===", "question_key", "intent_slug", "promotion_timing",
                             "career_growth_timing", "PRIVATE_PROMPT", "PRIVATE_EVIDENCE", "gpt-5.6-luna"):
                self.assertNotIn(internal, html)
                self.assertNotIn(internal, text)

    def test_sections_preserved_and_no_invented_watch_period(self):
        for lang, headings in (("en", ("Direct Answer", "Why Your Chart Says This", "Strongest Periods", "What You Should Do", "Bottom Line")),
                               ("hi", ("सीधा जवाब", "आपकी Chart ऐसा क्यों कहती है", "सबसे मजबूत समय", "आपको क्या करना चाहिए", "सीधी बात"))):
            html = self.outputs[lang][1]
            positions = [html.index(heading) for heading in headings]
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn("Slower or Watch Period", html)
            self.assertGreaterEqual(len(sample_result(lang)["report"].split()), 400)
            self.assertLessEqual(len(sample_result(lang)["report"].split()), 520)

    def test_rejects_mismatched_result_and_internal_narrative(self):
        for updates in ({"intent_slug": "wrong"}, {"report": "===META=== {}"}, {"report": "gpt-5.6-luna"}, {"report": ""}):
            with self.assertRaises(ValueError):
                adapter.focused_pdf_arguments({**sample_result("en"), **updates}, PERSONA)
        with self.assertRaises(ValueError):
            adapter.focused_pdf_arguments(sample_result("en"), {"name": "Incomplete"})

    def test_failed_render_preserves_existing_output_and_removes_own_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "existing.pdf"
            path.write_bytes(b"original")
            with patch.object(adapter, "generate_pdf_report_weasy", side_effect=RuntimeError("render failure")):
                with self.assertRaises(RuntimeError):
                    adapter.render_focused_report_pdf(sample_result("en"), PERSONA, path)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_strict_validation_rejects_empty_fake_and_truncated_files(self):
        path = Path(self.folder.name) / "invalid.pdf"
        for content in (b"", b"not PDF", b"%PDF-1.7\nfake", Path(self.outputs["en"][0]).read_bytes()[:100]):
            path.write_bytes(content)
            with self.assertRaises(Exception):
                adapter.validate_focused_pdf(path)


if __name__ == "__main__":
    unittest.main()
