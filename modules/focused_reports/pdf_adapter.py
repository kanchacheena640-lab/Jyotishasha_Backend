"""Focused output -> existing paid PDF renderer, without orders or delivery."""
from pathlib import Path
import os
import re
import tempfile

from pypdf import PdfReader

from modules.focused_reports.dispatcher import resolve_focused_handler
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_assembler import language_key
from modules.intents.question_catalog import QUESTIONS
from modules.payments.report_product_intelligence import REGISTRY
from modules.payments.report_q3_batch1 import get_mandatory_disclaimer
from modules.payments.report_structured_output import validate_required_hero_fields
from pdf_generator_weasy import generate_pdf_report_weasy


# Backward-compatible Promotion alias; every adapter call uses its own spec.
TITLES = {lang: get_prompt_spec("promotion_timing").title.get(lang) for lang in ("en", "hi")}
_INTERNAL = re.compile(
    r"===META===|===REPORT===|question_key|intent_slug|promotion_timing|career_growth_timing|"
    r"gpt-[\w.-]+|birth_chart_summary|house_lord_summary|career_yoga_summary|wealth_yoga_summary|"
    r"dasha_window_summary|dasha_sequence|transit_evidence|raw_evidence|"
    r"user_natal|partner_natal|compatibility_facts|both_dasha_windows|both_relevant_transits|" +
    "|".join(re.escape(value) for q in QUESTIONS for value in (q.question_key, q.intent_slug)), re.I,
)


def focused_pdf_arguments(result: dict, customer: dict, *, is_sample: bool = False) -> dict:
    """Whitelist presentation fields; keep raw prompt/evidence and selection IDs out.

    The narrative already contains the answer and actions, so META components
    are validated but not repeated as additional cards. No extra chart is added.
    """
    selection, handler = resolve_focused_handler(result.get("question_key"))
    spec = get_prompt_spec(selection.question_key)
    if result.get("handler_key") != handler.key or result.get("intent_slug") != selection.intent_slug:
        raise ValueError("Focused PDF result does not match its selected handler.")
    language = language_key(result.get("language", "en"))
    validate_required_hero_fields({"answer_hero": result.get("hero")},
                                  ("label", "value", "interpretation", "evidence"))
    narrative = result.get("report")
    if not isinstance(narrative, str) or not narrative.strip() or _INTERNAL.search(narrative):
        raise ValueError("Focused PDF requires a customer-facing narrative without internal fields.")
    identity = {}
    for key in ("name", "dob", "tob", "pob"):
        value = customer.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Focused PDF requires customer {key}.")
        identity[key] = value
    dual_context = {}
    if selection.person_mode == "dual":
        partner = customer.get("partner")
        if not isinstance(partner, dict):
            raise ValueError("Dual focused PDF requires partner identity.")
        partner_identity = {}
        for key in ("name", "dob", "tob", "pob"):
            value = partner.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Dual focused PDF requires partner {key}.")
            partner_identity[key] = value
        dual_context["partner_info"] = partner_identity
    policy = {"money_improvement_timing": "financial_report", "business_timing": "business_report",
              "marriage_timing": "marriage_report",
              "foreign_move_timing": "foreign_travel_report",
              "study_exam_timing": None,
              "property_timing": "property_report",
              "life_turning_points": None,
              "life_direction_and_strengths": None,
              "relationship_marriage_potential": "marriage_report",
              "relationship_strengths_and_challenges": "marriage_report"}.get(
        selection.intent_slug, "career_report")
    disclaimer = get_mandatory_disclaimer(REGISTRY[policy].disclaimer_type if policy else "general", language)
    return dict(
        user_info=identity, summary_blocks={}, gpt_response=narrative,
        kundali_drawing=None, used_placeholders=[], product=spec.title.get(language),
        report_subtitle=selection.display(language), language=language,
        narrative_style="plain", is_sample=is_sample, disclaimer=disclaimer,
        **dual_context,
    )


def validate_focused_pdf(path) -> int:
    """Q4's PdfReader verification, with strict parsing and nonempty pages.

    Paid delivery's header check alone cannot detect truncated PDFs. Do not
    invoke delivery to validate a local artifact.
    """
    with open(path, "rb") as artifact:
        if artifact.read(5) != b"%PDF-":
            raise ValueError("Focused report artifact is not a PDF.")
        artifact.seek(0)
        reader = PdfReader(artifact, strict=True)
        if not reader.pages or any(not page.extract_text().strip() for page in reader.pages):
            raise ValueError("Focused report PDF contains no readable content or a blank page.")
        return len(reader.pages)


def render_focused_report_pdf(result: dict, customer: dict, output_path, *, is_sample: bool = False) -> str:
    """Render and validate a temporary file before publishing the local PDF.

    On failure only this call's temporary file is removed; any existing output
    is preserved. No AI, database, payment, email or route is invoked.
    """
    arguments = focused_pdf_arguments(result, customer, is_sample=is_sample)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".focused_", suffix=".pdf", dir=destination.parent)
    os.close(descriptor)
    try:
        generate_pdf_report_weasy(output_path=temporary, **arguments)
        validate_focused_pdf(temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return str(destination)
