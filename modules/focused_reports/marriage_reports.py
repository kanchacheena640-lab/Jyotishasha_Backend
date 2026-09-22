"""Single-chart Marriage reports through the shared focused prompt contract."""
from dataclasses import dataclass

from modules.focused_reports.marriage_evidence import MarriageEvidence, collect_marriage_evidence
from modules.focused_reports.prompt_assembler import build_focused_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec


@dataclass(frozen=True)
class MarriageReportPrompt:
    question_key: str
    language: str
    customer_question: str
    prompt: str
    evidence: MarriageEvidence


def build_marriage_report_prompt(question_key, kundali, language="en"):
    spec = get_prompt_spec(question_key)
    facts = collect_marriage_evidence(question_key, kundali, language)
    prompt = build_focused_prompt(question_key, facts.language, facts.sections,
                                  {"report_period": facts.report_period})
    return MarriageReportPrompt(question_key, facts.language, spec.question.get(facts.language), prompt, facts)
