"""Life focused reports through the shared PromptSpec/assembler contract."""
from dataclasses import dataclass
from modules.focused_reports.life_evidence import LifeEvidence, collect_life_evidence
from modules.focused_reports.prompt_assembler import build_focused_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec


@dataclass(frozen=True)
class LifeReportPrompt:
    question_key: str
    language: str
    customer_question: str
    prompt: str
    evidence: LifeEvidence


def build_life_report_prompt(question_key, kundali, language="en"):
    facts = collect_life_evidence(question_key, kundali, language)
    prompt = build_focused_prompt(question_key, facts.language, facts.sections,
                                 {"report_period": facts.report_period})
    return LifeReportPrompt(question_key, facts.language,
        get_prompt_spec(question_key).question.get(facts.language), prompt, facts)
