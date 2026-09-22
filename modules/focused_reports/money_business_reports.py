"""Exact Money/Business specs through the shared focused prompt contract."""
from dataclasses import dataclass

from modules.focused_reports.money_business_keys import MONEY_QUESTION_KEYS
from modules.focused_reports.money_business_evidence import FinancialEvidence, collect_money_evidence, collect_business_evidence
from modules.focused_reports.prompt_assembler import build_focused_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec


@dataclass(frozen=True)
class MoneyBusinessReportPrompt:
    question_key: str
    language: str
    customer_question: str
    prompt: str
    evidence: FinancialEvidence


def build_money_business_report_prompt(question_key, kundali, language="en"):
    spec = get_prompt_spec(question_key)
    collect = collect_money_evidence if question_key in MONEY_QUESTION_KEYS else collect_business_evidence
    facts = collect(question_key, kundali, language)
    prompt = build_focused_prompt(question_key, facts.language, facts.sections,
                                  {"report_period": facts.report_period})
    return MoneyBusinessReportPrompt(question_key, facts.language, spec.question.get(facts.language), prompt, facts)
