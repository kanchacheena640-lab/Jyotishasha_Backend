"""Regression tests for F12-P3.9: a focused-report section heading must never end a page with its paragraph on the next.

Focused reports render narrative_style="plain" (no card shell); their headings are `p.lead-in` outside any card, which
the card-scoped keep-with-next rule never reached. Needs the real WeasyPrint runtime (as test_focused_pdf.py does).
"""
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

from modules.focused_reports import pdf_adapter as adapter
from pdf_generator_weasy import convert_headings
from scripts.generate_focused_promotion_samples import PERSONA, sample_result

ROOT = Path(__file__).resolve().parent
HEADINGS = {"en": ["Direct Answer", "Why Your Chart Says This", "Strongest Periods", "What You Should Do", "Bottom Line"],
            "hi": ["सीधा जवाब", "आपकी Chart ऐसा क्यों कहती है", "सबसे मजबूत समय", "आपको क्या करना चाहिए", "सीधी बात"]}
SENTENCE = {"en": "Saturn's steady support in the 6th house rewards patient, consistent effort at work. ",
            "hi": "6th House में Saturn का स्थिर साथ धैर्य और लगातार मेहनत का फल देता है। "}


def key(text):
    """Latin letters, or Devanagari consonants/independent vowels only (PDF text extraction reorders vowel signs)."""
    return Counter(c for c in text if (c.isascii() and c.isalpha()) or "अ" <= c <= "ह")


def orphaned_headings(path, headings):
    pages = PdfReader(path).pages
    found = []
    for number, page in enumerate(pages[:-1], 1):
        lines = [l.strip() for l in (page.extract_text() or "").splitlines() if l.strip() and "Page " not in l]
        if lines and any(key(lines[-1]) == key(h) for h in headings):
            found.append((number, lines[-1]))
    return found


class FocusedHeadingPageFlowTests(unittest.TestCase):
    def test_template_keeps_every_lead_in_with_the_paragraph_after_it(self):
        css = (ROOT / "templates" / "report_template.html").read_text(encoding="utf-8")
        self.assertRegex(css, r"(?m)^\s*\.lead-in \{ page-break-after: avoid; \}")

    def test_card_mode_lead_ins_are_always_inside_a_card_so_standard_reports_are_unchanged(self):
        samples = ["**Overview**\nText.\n\n**Career:**\nMore text.\n\n1. Numbered\n\nPlain.",
                   "Intro line.\n\n**Label**\nBody\n- bullet\n\n**Another**\nBody", "**Only Lead-in**"]
        for text in samples:
            html = convert_headings(text)
            depth = 0
            for token in re.findall(r"<div class='card'>|</div>|<p class='lead-in'>", html):
                if token == "<p class='lead-in'>":
                    self.assertGreater(depth, 0, html)
                else:
                    depth += 1 if token.startswith("<div") else -1
        self.assertNotIn("class='card'", convert_headings(samples[0], narrative_style="plain"))

    def test_no_focused_pdf_page_ends_with_a_section_heading(self):
        checked = 0
        with tempfile.TemporaryDirectory() as tmp:
            for language in ("en", "hi"):
                for sentences in range(4, 16, 2):
                    result = sample_result(language)
                    paragraph = SENTENCE[language] * sentences
                    result["report"] = "\n\n".join(f"**{h}**\n{paragraph}" for h in HEADINGS[language])
                    path = adapter.render_focused_report_pdf(result, PERSONA, str(Path(tmp) / f"{language}_{sentences}.pdf"))
                    self.assertEqual(orphaned_headings(path, HEADINGS[language]), [], f"{language}/{sentences} sentences")
                    checked += 1
        self.assertEqual(checked, 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
