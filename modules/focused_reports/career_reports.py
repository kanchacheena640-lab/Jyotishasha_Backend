"""Question-specific Career generation using shared factual components."""
from dataclasses import dataclass

from modules.focused_reports.career_evidence import CareerEvidence, collect_career_evidence
from modules.focused_reports.prompt_assembler import build_focused_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec


@dataclass(frozen=True)
class CareerReportPrompt:
    question_key: str
    language: str
    customer_question: str
    prompt: str
    evidence: CareerEvidence


def build_career_report_prompt(question_key, kundali, language="en"):
    spec = get_prompt_spec(question_key)
    facts = collect_career_evidence(question_key, kundali, language)
    prompt = build_focused_prompt(question_key, facts.language, facts.sections,
                                  {"report_period": facts.report_period})
    return CareerReportPrompt(question_key, facts.language, spec.question.get(facts.language), prompt, facts)
