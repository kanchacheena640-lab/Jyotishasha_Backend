"""Property focused reports through the shared PromptSpec/assembler contract."""
from dataclasses import dataclass
from modules.focused_reports.property_evidence import PropertyEvidence, collect_property_evidence
from modules.focused_reports.prompt_assembler import build_focused_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec


@dataclass(frozen=True)
class PropertyReportPrompt:
    question_key: str
    language: str
    customer_question: str
    prompt: str
    evidence: PropertyEvidence


def build_property_report_prompt(question_key, kundali, language="en"):
    facts = collect_property_evidence(question_key, kundali, language)
    prompt = build_focused_prompt(question_key, facts.language, facts.sections,
                                 {"report_period": facts.report_period})
    return PropertyReportPrompt(question_key, facts.language,
        get_prompt_spec(question_key).question.get(facts.language), prompt, facts)
