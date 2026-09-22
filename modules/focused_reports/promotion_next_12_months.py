# modules/focused_reports/promotion_next_12_months.py

"""
promotion_next_12_months.py -- Focused Reports prototype: assembles the Luna
prompt for "Promotion Report -- Next 12 Months".

    birth fixture -> existing calculate_full_kundali()
                  -> existing Career Report evidence (the SAME four summary
                     blocks prompts/career_report_*.txt consumes, produced by
                     the SAME summary_blocks.build_summary_blocks_with_transit())
                  -> concise transit evidence (promotion_transit_evidence.py)
                  -> this report's own prompt template

This module never calls Luna, never touches tasks.py, orders, payment, the PDF
renderer or e-mail, and adds no prediction or scoring logic. The prompt asks
Luna to do the Jyotish reasoning over facts the backend supplies; it forbids
Luna from calculating or inventing positions, houses, transit dates or Dasha
dates. The response wire format (===META=== hero JSON, ===REPORT=== narrative)
is the existing one, so report_structured_output.parse_structured_response /
validate_required_hero_fields work on it unchanged.

DATES: backend structures stay ISO. Everything Luna sees -- the career blocks'
Dasha dates, the transit block, the report period -- is passed through the
EXISTING Q5.6 utilities (report_date_format) so it already reads
"21 September 2026" / "21 सितंबर 2026"; no ISO date is in the prompt, and
finalize_customer_output() applies the same utility to Luna's answer as a
deterministic safety net.

Privacy: the prompt carries no name, date of birth, birth time or birth place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from modules.intents.question_catalog import get_question
from modules.focused_reports.prompt_assembler import build_focused_prompt, language_key
from modules.focused_reports.career_evidence import collect_career_evidence
from modules.payments.report_date_format import (
    normalize_customer_dates,
    normalize_customer_payload,
)
from modules.payments.report_structured_output import ReportMetadataError, parse_structured_response, validate_required_hero_fields

REPORT_KEY = "promotion_next_12_months"
HERO_LABEL = "Promotion Outlook"
PRICE_RUPEES = 51

# The customer's question stays simple and natural; the astrology lives inside the report.
QUESTION_KEY = "promotion_timing"

CUSTOMER_QUESTION = {
    language: get_question(QUESTION_KEY).question.get(language)
    for language in ("en", "hi")
}

# Exactly the four evidence blocks the existing career_report prompt consumes.
CAREER_EVIDENCE_BLOCKS = (
    "birth_chart_summary",
    "house_lord_summary",
    "career_yoga_summary",
    "dasha_window_summary",
)



@dataclass(frozen=True)
class PromotionReportPrompt:
    report_key: str
    language: str
    customer_question: str
    prompt: str
    career_evidence: Dict[str, str]         # internal: byte-identical to the Career Report blocks (ISO dates)
    prompt_evidence: Dict[str, str]         # what Luna sees: the same blocks with dates in the customer format
    transit_evidence: Dict[str, Any]        # internal structured facts (ISO dates)
    transit_summary: str                    # what Luna sees (customer-format dates)
    report_date: str                        # internal ISO
    horizon_end: str                        # internal ISO
    report_period: str                      # customer format, e.g. "21 September 2026 to 21 September 2027"

    @property
    def evidence_payload(self) -> str:
        """The data section exactly as Luna receives it (the five evidence blocks, in prompt order)."""
        return "\n\n".join([
            self.prompt_evidence["birth_chart_summary"],
            self.prompt_evidence["house_lord_summary"],
            self.prompt_evidence["career_yoga_summary"],
            self.prompt_evidence["dasha_window_summary"],
            self.transit_summary,
        ])


def _language_key(language: str) -> str:
    return language_key(language)


def build_promotion_report_prompt(kundali: Dict[str, Any], language: str = "en") -> PromotionReportPrompt:
    """`kundali` is the dict returned by full_kundali_api.calculate_full_kundali()."""
    facts = collect_career_evidence(QUESTION_KEY, kundali, language)
    language_key = facts.language
    career_evidence, prompt_evidence = facts.career_evidence, facts.prompt_evidence
    evidence, transit_summary = facts.transit_evidence, facts.transit_summary
    report_period = facts.report_period
    question = CUSTOMER_QUESTION[language_key]

    prompt = build_focused_prompt(QUESTION_KEY, language_key, facts.sections, {"report_period": report_period})
    return PromotionReportPrompt(
        report_key=REPORT_KEY,
        language=language_key,
        customer_question=question,
        prompt=prompt,
        career_evidence=career_evidence,
        prompt_evidence=prompt_evidence,
        transit_evidence=evidence,
        transit_summary=transit_summary,
        report_date=evidence["as_of"],
        horizon_end=evidence["horizon_end"],
        report_period=report_period,
    )


def finalize_customer_output(raw_response: str, language: str = "en") -> Dict[str, Any]:
    """Deterministic presentation step for a Luna answer (no Luna call): parse it with the EXISTING structured
    parser/validator, then run every customer-visible string through the EXISTING Q5.6 normalizer, so any ISO
    date Luna might still write is shown in the customer format. Returns {"hero", "action_items", "report"}."""
    language_key = _language_key(language)
    metadata, narrative = parse_structured_response(raw_response)
    hero = validate_required_hero_fields(metadata, ("label", "value", "interpretation", "evidence"))
    if not narrative.strip():
        raise ReportMetadataError("Focused report narrative is empty.")
    actions = metadata.get("action_items") or []
    if not isinstance(actions, list) or not all(isinstance(item, str) and item.strip() for item in actions):
        raise ReportMetadataError("Focused report action_items must be a list of non-empty strings.")
    return {
        "hero": normalize_customer_payload(hero, language_key),
        "action_items": normalize_customer_payload(metadata.get("action_items") or [], language_key),
        "report": normalize_customer_dates(narrative, language_key),
    }
