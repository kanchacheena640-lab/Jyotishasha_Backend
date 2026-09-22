"""Career evidence selection over existing summaries and transit primitives."""
from dataclasses import dataclass
from datetime import date

from modules.focused_reports.career_keys import CAREER_QUESTION_KEYS
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.prompt_assembler import MissingEvidenceError, language_key
from modules.focused_reports.promotion_transit_evidence import build_promotion_transit_evidence, render_promotion_transit_summary
from modules.payments.report_date_format import format_customer_date_range, normalize_customer_dates
from summary_blocks import build_summary_blocks_with_transit, _flatten_dasha_sequence
from transit_engine import get_current_positions

SUMMARY_KEYS = ("birth_chart_summary", "house_lord_summary", "career_yoga_summary", "dasha_window_summary")
SUPPORTED_KEYS = frozenset((*SUMMARY_KEYS, "dasha_sequence", "Jupiter", "Saturn", "Rahu"))


@dataclass(frozen=True)
class CareerEvidence:
    language: str
    career_evidence: dict
    prompt_evidence: dict
    sections: dict
    transit_evidence: dict
    transit_summary: str
    report_date: str
    horizon_end: str
    report_period: str


def multi_year_dasha_summary(kundali, start, end):
    """All existing MD/AD windows overlapping the requested coming years.

    No date calculation or scoring. Preserve original boundary dates and fail
    closed on missing/gapped coverage rather than imply unsupported years.
    """
    try:
        rows = _flatten_dasha_sequence(kundali.get("Mahadasha"))
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        selected = []
        for row in rows:
            first, last = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
            if last < first or not row["mahadasha"] or not row["planet"]:
                raise ValueError("Invalid MD/AD window")
            if last >= start_day and first <= end_day:
                selected.append((first, last, row))
        selected.sort(key=lambda item: item[0])
        covered = start_day
        for first, last, _ in selected:
            if first > covered and (first - covered).days > 1:
                raise ValueError("Gap in MD/AD coverage")
            covered = max(covered, last)
        if not selected or selected[0][0] > start_day or covered < end_day:
            raise ValueError("Incomplete MD/AD coverage")
    except (KeyError, TypeError, ValueError, AttributeError):
        raise MissingEvidenceError(("dasha_sequence",)) from None
    return "\n".join(
        f"{r['mahadasha']} Mahadasha - {r['planet']} Antardasha, from {r['start']} to {r['end']}."
        for _, _, r in selected
    )


def collect_career_evidence(question_key, kundali, language="en"):
    spec = get_prompt_spec(question_key)
    if question_key not in CAREER_QUESTION_KEYS:
        raise ValueError("Question has no career evidence collector.")
    lang = language_key(language)
    required = {r.key for r in spec.evidence_requirements}
    if required - SUPPORTED_KEYS:
        raise MissingEvidenceError(sorted(required - SUPPORTED_KEYS))
    if not isinstance(kundali, dict) or not kundali.get("lagna_sign") or not kundali.get("planets"):
        raise MissingEvidenceError(("birth_chart_summary", "house_lord_summary"))
    blocks = build_summary_blocks_with_transit(kundali, get_current_positions())
    career = {key: blocks.get(key, "") for key in SUMMARY_KEYS if key in required}
    # Five years for the coming-years question; near-term questions retain 12 months.
    months = 60 if "dasha_sequence" in required else 12
    transits = build_promotion_transit_evidence(kundali.get("lagna_sign", ""), horizon_months=months)
    if "dasha_sequence" in required:
        career["dasha_sequence"] = multi_year_dasha_summary(kundali, transits["as_of"], transits["horizon_end"])
    prompt_evidence = {key: normalize_customer_dates(value, lang) for key, value in career.items()}
    transit_summary = render_promotion_transit_summary(transits, lang)
    saturn = transit_summary.index("Saturn\nSign residence:")
    rahu = transit_summary.index("Rahu\nSign residence:")
    available = {**prompt_evidence,
                 "Jupiter": transit_summary[:saturn].rstrip(),
                 "Saturn": transit_summary[saturn:rahu].rstrip(), "Rahu": transit_summary[rahu:]}
    sections = {r.key: available[r.key] for r in spec.evidence_requirements}
    return CareerEvidence(lang, career, prompt_evidence, sections, transits, transit_summary,
                          transits["as_of"], transits["horizon_end"],
                          format_customer_date_range(transits["as_of"], transits["horizon_end"], lang))
