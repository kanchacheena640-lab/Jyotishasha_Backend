"""Local renderer QA, following Q4's deterministic fixture pattern.

Run: venv\Scripts\python.exe scripts/generate_focused_promotion_samples.py
Fixtures are synthetic, not saved Luna readings. Both PDFs carry SAMPLE.
No astrology calculations, AI, orders, payment or delivery are called.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.focused_reports.dispatcher import resolve_focused_handler
from modules.focused_reports.pdf_adapter import render_focused_report_pdf, validate_focused_pdf


PERSONA = {
    "name": "Aarav Sharma", "dob": "1990-06-15", "tob": "14:30",
    "pob": "Lucknow, Uttar Pradesh, India", "lat": 26.8467, "lon": 80.9462,
}
OUTPUT_DIR = ROOT / "sample_reports" / "focused_promotion"


def sample_result(language):
    if language not in ("en", "hi"):
        raise ValueError("Sample language must be en or hi.")
    selection, handler = resolve_focused_handler("promotion_timing")
    raw = (ROOT / "scripts" / "fixtures" / f"promotion_report_{language}.txt").read_text(encoding="utf-8")
    return {
        "question_key": selection.question_key, "intent_slug": selection.intent_slug,
        "handler_key": handler.key, "language": language,
        "customer_question": selection.display(language), **handler.finalize(raw, language),
    }


def main():
    for language in ("en", "hi"):
        result = sample_result(language)
        path = render_focused_report_pdf(result, PERSONA, OUTPUT_DIR / f"promotion_report_{language}.pdf", is_sample=True)
        print(f"{path}: {validate_focused_pdf(path)} pages; deterministic SAMPLE")


if __name__ == "__main__":
    main()
