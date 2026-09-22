"""Money and business projections of existing facts, with no prediction engine."""
from dataclasses import dataclass

from modules.focused_reports.career_evidence import multi_year_dasha_summary
from modules.focused_reports.money_business_keys import MONEY_QUESTION_KEYS, BUSINESS_QUESTION_KEYS, MULTI_YEAR_KEYS
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_assembler import MissingEvidenceError, language_key
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence, render_promotion_transit_summary
from modules.payments.report_date_format import normalize_customer_dates, format_customer_date_range
from summary_blocks import build_summary_blocks_with_transit
from transit_engine import get_current_positions

SUMMARY_KEYS = ("birth_chart_summary", "house_lord_summary", "wealth_yoga_summary",
                "career_yoga_summary", "dasha_window_summary")
SUPPORTED_KEYS = frozenset((*SUMMARY_KEYS, "dasha_sequence", "Jupiter", "Saturn"))


@dataclass(frozen=True)
class FinancialEvidence:
    language: str
    sections: dict
    transit_evidence: dict
    report_date: str
    horizon_end: str
    report_period: str


def _collect(question_key, kundali, language, allowed_keys):
    spec = get_prompt_spec(question_key)
    if question_key not in allowed_keys:
        raise ValueError("Question does not belong to this evidence family.")
    lang = language_key(language)
    required = {r.key for r in spec.evidence_requirements}
    if required - SUPPORTED_KEYS:
        raise MissingEvidenceError(sorted(required - SUPPORTED_KEYS))
    if not isinstance(kundali, dict) or not kundali.get("lagna_sign") or not kundali.get("planets"):
        raise MissingEvidenceError(("birth_chart_summary", "house_lord_summary"))
    blocks = build_summary_blocks_with_transit(kundali, get_current_positions())
    available = {key: blocks.get(key, "") for key in SUMMARY_KEYS if key in required}
    months = 60 if question_key in MULTI_YEAR_KEYS else 12
    transits = build_promotion_transit_evidence(kundali["lagna_sign"], horizon_months=months,
                                               selected_planets=("Jupiter", "Saturn"))
    if "dasha_sequence" in required:
        available["dasha_sequence"] = multi_year_dasha_summary(kundali, transits["as_of"], transits["horizon_end"])
    # Render each required planet independently, avoiding string slicing or nodal facts.
    for name in ("Jupiter", "Saturn"):
        selected = [p for p in transits["planets"] if p["planet"] == name]
        if len(selected) != 1 or not selected[0].get("sign_residence") or not selected[0].get("motion_periods"):
            raise MissingEvidenceError((name,))
        available[name] = render_promotion_transit_summary({**transits, "planets": selected}, lang)
    sections = {r.key: normalize_customer_dates(available[r.key], lang) for r in spec.evidence_requirements}
    return FinancialEvidence(lang, sections, transits, transits["as_of"], transits["horizon_end"],
                             format_customer_date_range(transits["as_of"], transits["horizon_end"], lang))


def collect_money_evidence(question_key, kundali, language="en"):
    return _collect(question_key, kundali, language, MONEY_QUESTION_KEYS)


def collect_business_evidence(question_key, kundali, language="en"):
    return _collect(question_key, kundali, language, BUSINESS_QUESTION_KEYS)
