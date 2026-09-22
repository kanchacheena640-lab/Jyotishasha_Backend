"""Generation-only focused reports. No orders, routes, payment or delivery.

Dispatch is by exact question key: sharing an intent never enables another
question implicitly. Kundali input comes from calculate_full_kundali().
"""
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType
from typing import Any, Callable

from modules.intents.intent_contract import IntentSelection
from modules.intents.question_catalog import resolve_selection
from modules.focused_reports.promotion_next_12_months import (
    QUESTION_KEY, build_promotion_report_prompt, finalize_customer_output,
)
from modules.focused_reports.career_keys import CAREER_QUESTION_KEYS
from modules.focused_reports.career_reports import build_career_report_prompt
from modules.focused_reports.money_business_keys import MONEY_BUSINESS_QUESTION_KEYS
from modules.focused_reports.money_business_reports import build_money_business_report_prompt
from modules.focused_reports.marriage_keys import MARRIAGE_QUESTION_KEYS
from modules.focused_reports.marriage_reports import build_marriage_report_prompt
from modules.focused_reports.relationship_keys import RELATIONSHIP_QUESTION_KEYS
from modules.focused_reports.relationship_reports import build_relationship_report_prompt
from modules.focused_reports.foreign_keys import FOREIGN_QUESTION_KEYS
from modules.focused_reports.foreign_reports import build_foreign_report_prompt
from modules.focused_reports.education_keys import EDUCATION_QUESTION_KEYS
from modules.focused_reports.education_reports import build_education_report_prompt
from modules.focused_reports.property_keys import PROPERTY_QUESTION_KEYS
from modules.focused_reports.property_reports import build_property_report_prompt
from modules.focused_reports.life_keys import LIFE_QUESTION_KEYS
from modules.focused_reports.life_reports import build_life_report_prompt


class FocusedReportNotImplementedError(LookupError):
    code = "focused_report_not_implemented"

    def __init__(self, question_key: str):
        self.question_key = question_key
        super().__init__(f"No focused-report handler implemented for question_key '{question_key}'.")


@dataclass(frozen=True)
class FocusedReportHandler:
    key: str
    build_prompt: Callable
    finalize: Callable


HANDLERS = MappingProxyType({
    **{key: FocusedReportHandler(key, partial(build_life_report_prompt, key), finalize_customer_output)
       for key in LIFE_QUESTION_KEYS},
    **{key: FocusedReportHandler(key, partial(build_property_report_prompt, key), finalize_customer_output)
       for key in PROPERTY_QUESTION_KEYS},
    **{key: FocusedReportHandler(key, partial(build_education_report_prompt, key), finalize_customer_output)
       for key in EDUCATION_QUESTION_KEYS},
    **{key: FocusedReportHandler(key, partial(build_foreign_report_prompt, key), finalize_customer_output)
       for key in FOREIGN_QUESTION_KEYS},
    **{key: FocusedReportHandler(key, partial(build_relationship_report_prompt, key), finalize_customer_output)
       for key in RELATIONSHIP_QUESTION_KEYS},
    **{key: FocusedReportHandler(key, partial(build_marriage_report_prompt, key), finalize_customer_output)
       for key in MARRIAGE_QUESTION_KEYS},
    **{key: FocusedReportHandler(key, partial(build_money_business_report_prompt, key), finalize_customer_output)
       for key in MONEY_BUSINESS_QUESTION_KEYS},
    **{key: FocusedReportHandler(key, partial(build_career_report_prompt, key), finalize_customer_output)
       for key in CAREER_QUESTION_KEYS if key != QUESTION_KEY},
    QUESTION_KEY: FocusedReportHandler("promotion", build_promotion_report_prompt, finalize_customer_output),
})


def resolve_focused_handler(question_key: str) -> tuple[IntentSelection, FocusedReportHandler]:
    selection = resolve_selection(question_key)  # UnknownQuestionError for unknown keys
    handler = HANDLERS.get(selection.question_key)
    if handler is None:
        raise FocusedReportNotImplementedError(selection.question_key)
    return selection, handler


def generate_focused_report(question_key: str, kundali: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """Resolve before any evidence/AI work; propagate AI and validation errors.

Uses the paid Luna client and its configured model, with no fallback. The
result contains customer output and selection identity, never raw evidence.
"""
    selection, handler = resolve_focused_handler(question_key)
    built = handler.build_prompt(kundali, language)
    from modules.payments.report_ai_client import generate_report_completion

    completion = generate_report_completion(built.prompt)
    output = handler.finalize(completion.content, built.language)
    return {
        "question_key": selection.question_key,
        "intent_slug": selection.intent_slug,
        "handler_key": handler.key,
        "language": built.language,
        "customer_question": selection.display(built.language),
        **output,
    }
