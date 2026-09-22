"""Dual-person focused reports using the shared assembler and result contract."""
from dataclasses import dataclass
from modules.focused_reports.relationship_evidence import RelationshipEvidence, collect_relationship_evidence
from modules.focused_reports.prompt_assembler import build_focused_prompt
from modules.focused_reports.prompt_specs import get_prompt_spec


@dataclass(frozen=True)
class RelationshipReportPrompt:
    question_key: str
    language: str
    customer_question: str
    prompt: str
    evidence: RelationshipEvidence


def build_relationship_report_prompt(question_key, payload, language="en"):
    facts = collect_relationship_evidence(question_key, payload, language)
    prompt = build_focused_prompt(question_key, facts.language, facts.sections,
                                 {"report_period": facts.report_period})
    return RelationshipReportPrompt(question_key, facts.language,
        get_prompt_spec(question_key).question.get(facts.language), prompt, facts)
