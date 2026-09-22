"""Catalog -> typed prompt spec -> validated evidence -> prompt. No AI call."""
from collections.abc import Mapping
import re

from modules.intents.question_catalog import resolve_selection
from modules.focused_reports.prompt_specs import get_prompt_spec
from modules.focused_reports.master_contract import PROMPT_DIR, REMEDY_INSTRUCTION, master_contract, output_contract
from modules.payments.report_date_format import normalize_customer_dates


class PromptAssemblyError(ValueError):
    code = "focused_prompt_invalid"


class MissingEvidenceError(PromptAssemblyError):
    code = "focused_evidence_missing"

    def __init__(self, sections):
        self.sections = tuple(sections)
        super().__init__("Missing mandatory evidence: " + ", ".join(self.sections))


def language_key(language):
    if not isinstance(language, str):
        raise PromptAssemblyError("Language must be en or hi (supported locale aliases allowed).")
    value = language.strip().lower()
    if value not in {"en", "en-us", "en-in", "hi", "hi-in"}:
        raise PromptAssemblyError(f"Unsupported focused-report language: {language!r}")
    return value.split("-")[0]


def _present(value):
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().lower() not in {"none", "null", "n/a", "unknown", "unavailable", "not available"}
            and not re.fullmatch(r".*data not available\.?", value.strip(), flags=re.I))


def build_focused_prompt(question_key, language, evidence, customer_context=None):
    selection = resolve_selection(question_key)
    spec = get_prompt_spec(question_key)
    if (spec.question_key, spec.intent_slug, spec.person_mode, spec.question) != (
            selection.question_key, selection.intent_slug, selection.person_mode, selection.display_question):
        raise PromptAssemblyError("Prompt specification does not match the selected catalog question.")
    lang = language_key(language)
    if not isinstance(evidence, Mapping):
        raise MissingEvidenceError(r.key for r in spec.evidence_requirements)
    missing = [r.key for r in spec.evidence_requirements if not _present(evidence.get(r.key))]
    if missing:
        raise MissingEvidenceError(missing)
    if customer_context is not None and not isinstance(customer_context, Mapping):
        raise PromptAssemblyError("Customer context must be a mapping.")
    context = customer_context or {}
    context_parts = []
    for key, label in (("report_period", "The supplied evidence period is"),
                       ("situation", "Customer context (not astrology evidence):")):
        if context.get(key) is not None:
            if not isinstance(context[key], str):
                raise PromptAssemblyError(f"Customer context {key} must be text.")
            context_parts.append(label + " " + normalize_customer_dates(context[key], lang))
    # Whitelist required sections. Same-group transit strings stay adjacent,
    # preserving the existing residence/motion rendering verbatim.
    blocks = []
    previous_group = None
    for requirement in spec.evidence_requirements:
        value = normalize_customer_dates(evidence[requirement.key], lang)
        if requirement.group and requirement.group == previous_group:
            blocks[-1] += "\n" + value
        else:
            blocks.append("--- " + requirement.label + ":\n" + value)
        previous_group = requirement.group or None
    instructions = "\n".join((
        "Analysis objective: " + spec.analysis_objective,
        "Astrological focus: " + spec.astrological_focus,
        "Timing: " + spec.timing_requirement,
        "Output emphasis: " + spec.output_emphasis,
        "Boundaries: " + " ".join(spec.boundaries),
    ))
    if question_key == "promotion_timing":
        instructions += "\n" + (PROMPT_DIR / f"promotion_next_12_months_{lang}.txt").read_text(encoding="utf-8")
    if spec.remedies:
        instructions += "\n" + REMEDY_INSTRUCTION[lang]
    return "\n\n".join((master_contract(lang), 'Customer question: "' + selection.display(lang) + '"',
                          "\n".join(context_parts), instructions,
                          "Authoritative backend evidence:\n" + "\n\n".join(blocks), output_contract(spec, lang)))
