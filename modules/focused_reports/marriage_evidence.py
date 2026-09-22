"""Marriage evidence from existing natal, MD/AD and transit calculations only."""
from dataclasses import dataclass

from modules.focused_reports.career_evidence import multi_year_dasha_summary
from modules.focused_reports.marriage_keys import MARRIAGE_HORIZONS
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_assembler import MissingEvidenceError, PromptAssemblyError, language_key, _present
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence, render_promotion_transit_summary
from modules.payments.report_date_format import normalize_customer_dates, format_customer_date_range
from summary_blocks import build_summary_blocks_with_transit
from transit_engine import get_current_positions

SUMMARY_KEYS = ("birth_chart_summary", "house_lord_summary", "dasha_window_summary")
SUPPORTED_KEYS = frozenset((*SUMMARY_KEYS, "dasha_sequence", "Jupiter", "Saturn"))


@dataclass(frozen=True)
class MarriageEvidence:
    language: str
    sections: dict
    transit_evidence: dict
    report_date: str
    horizon_end: str
    report_period: str


def collect_marriage_evidence(question_key, kundali, language="en"):
    spec = get_prompt_spec(question_key)
    if question_key not in MARRIAGE_HORIZONS:
        raise ValueError("Question has no Marriage evidence collector.")
    if spec.person_mode != "single" or spec.intent_slug != "marriage_timing":
        raise PromptAssemblyError("Marriage evidence requires the customer's own single chart.")
    lang = language_key(language)
    required = {r.key for r in spec.evidence_requirements}
    if required - SUPPORTED_KEYS:
        raise MissingEvidenceError(sorted(required - SUPPORTED_KEYS))
    if not isinstance(kundali, dict) or not kundali.get("lagna_sign") or not kundali.get("planets"):
        raise MissingEvidenceError(("birth_chart_summary", "house_lord_summary"))
    blocks = build_summary_blocks_with_transit(kundali, get_current_positions())
    available = {key: blocks.get(key, "") for key in SUMMARY_KEYS if key in required}
    missing = [key for key, value in available.items() if not _present(value)]
    if missing:
        raise MissingEvidenceError(missing)
    transits = build_promotion_transit_evidence(kundali["lagna_sign"],
        horizon_months=MARRIAGE_HORIZONS[question_key], selected_planets=("Jupiter", "Saturn"))
    # Validate continuous MD/AD coverage for either horizon. The shared current
    # summary includes only two upcoming sub-periods, which can omit part of a
    # year when short sub-periods cross a Mahadasha boundary.
    sequence = multi_year_dasha_summary(kundali, transits["as_of"], transits["horizon_end"])
    if "dasha_sequence" in required:
        available["dasha_sequence"] = sequence
    elif available.get("dasha_window_summary"):
        available["dasha_window_summary"] += "\nMD/AD windows covering the report period:\n" + sequence
    for name in ("Jupiter", "Saturn"):
        selected = [p for p in transits["planets"] if p["planet"] == name]
        if len(selected) != 1 or not selected[0].get("sign_residence") or not selected[0].get("motion_periods"):
            raise MissingEvidenceError((name,))
        available[name] = render_promotion_transit_summary({**transits, "planets": selected}, lang)
    sections = {r.key: normalize_customer_dates(available[r.key], lang) for r in spec.evidence_requirements}
    return MarriageEvidence(lang, sections, transits, transits["as_of"], transits["horizon_end"],
                            format_customer_date_range(transits["as_of"], transits["horizon_end"], lang))
