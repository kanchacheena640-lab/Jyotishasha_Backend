"""Education focused reports through the shared PromptSpec/assembler contract."""
from dataclasses import dataclass
from modules.focused_reports.education_evidence import EducationEvidence, collect_education_evidence
from modules.focused_reports.prompt_assembler import build_focused_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec


@dataclass(frozen=True)
class EducationReportPrompt:
    question_key: str
    language: str
    customer_question: str
    prompt: str
    evidence: EducationEvidence


def build_education_report_prompt(question_key, kundali, language="en"):
    facts = collect_education_evidence(question_key, kundali, language)
    prompt = build_focused_prompt(question_key, facts.language, facts.sections,
                                 {"report_period": facts.report_period})
    return EducationReportPrompt(question_key, facts.language,
        get_prompt_spec(question_key).question.get(facts.language), prompt, facts)
