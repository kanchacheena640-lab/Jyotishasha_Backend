# modules/payments/report_structured_output.py

"""
report_structured_output.py -- Paid Report Platform, Q3 Batch 0.

Parses the shared META/REPORT wire format (Q3B, approved) that
Q3-enabled products' prompts will emit, validates the structured
metadata against a product's own declared required-field contract, and
assembles the final answer_hero/gemstone dicts generate_pdf_report_weasy()
(Q2/Q2.1, frozen) expects -- WITHOUT ever trusting AI output for a
value this codebase already knows deterministically.

Wire format (exact, case-sensitive; Q3B Part 2/5):

    ===META===
    { valid JSON, containing at minimum an "answer_hero" object }
    ===REPORT===
    narrative text (unchanged from today -- still runs through
    pdf_generator_weasy.py::convert_headings() exactly as before)

At Batch 0, NO product in report_product_intelligence.py is
q3_enabled=True -- every one of the 25 products' real AI response is
still treated as pure narrative (parse_structured_response() is not
even called for them). This module exists, and is fully tested here,
so that flipping a single product's q3_enabled flag in a later batch
is the only change needed to activate it -- no parser/validator/
assembly code is written per-product.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

_META_MARKER = "===META==="
_REPORT_MARKER = "===REPORT==="


class ReportMetadataError(Exception):
    """
    Raised ONLY for a Q3-enabled product whose structured metadata is
    missing, malformed, or fails its own declared required-field
    contract (report_product_intelligence.py's `required_hero_fields`).

    Q3 Batch 0 correction #1 (LOCKED): this is deliberately a hard
    failure, never a soft degrade-to-narrative-only fallback -- a
    Q3-enabled product's Page 2 must answer the purchased question, or
    the report must not be delivered at all. Raising this from inside
    tasks.py::_generate_and_send_report_core()'s or modules/love/
    love_premium_task.py::generate_love_premium_report()'s existing
    try block requires NO change to their own exception handling --
    both already catch a bare `except Exception` and set
    report_stage="Failed", which is exactly the F2-recoverable path
    this error is meant to land in. This class deliberately does not
    subclass anything more specific than Exception, so no change to
    either function's existing `except Exception` clause is required.
    """


def parse_structured_response(raw_text: str) -> tuple[Optional[dict], str]:
    """Best-effort, NEVER-RAISING split of one Luna response into
    (metadata_dict_or_None, narrative_text).

    Returns (None, raw_text) whenever the markers are absent, out of
    order, or the text between them is not valid JSON (or not a JSON
    object) -- this function makes no policy judgment about whether a
    None result is acceptable; that is validate_required_hero_fields()'s
    job, called only for a product that actually requires structured
    metadata. Parsing and validation are deliberately separate
    concerns so a non-Q3-enabled product's response -- which will
    never contain these markers at all -- is handled by exactly the
    same code path as a Q3-enabled product's malformed response,
    rather than two different parsers."""
    if not raw_text:
        return None, ""

    meta_idx = raw_text.find(_META_MARKER)
    report_idx = raw_text.find(_REPORT_MARKER)
    if meta_idx == -1 or report_idx == -1 or report_idx <= meta_idx:
        return None, raw_text

    meta_block = raw_text[meta_idx + len(_META_MARKER): report_idx].strip()
    narrative = raw_text[report_idx + len(_REPORT_MARKER):].strip()

    try:
        metadata = json.loads(meta_block)
    except (json.JSONDecodeError, ValueError):
        return None, narrative

    if not isinstance(metadata, dict):
        return None, narrative

    return metadata, narrative


def validate_required_hero_fields(metadata: Optional[dict], required_fields: Iterable[str]) -> dict:
    """Q3 Batch 0 correction #1 (LOCKED): for a Q3-enabled product,
    missing/malformed/incomplete structured metadata is a HARD
    FAILURE -- raises ReportMetadataError, never silently degrades to
    narrative-only. Returns the validated `answer_hero` dict (still
    AI-authored at this point, not yet merged with any deterministic
    override -- see assemble_answer_hero() below) only when every
    field named in `required_fields` is present and non-empty.

    `evidence` is treated specially: it must be a non-empty list of
    non-empty strings (matching generate_pdf_report_weasy()'s own
    `answer_hero.get('evidence')` list-rendering contract, Q2.1).
    Every other required field must be a non-empty string.

    `required_fields` is a product's own declared list
    (report_product_intelligence.py) -- callers for a non-Q3-enabled
    product never call this function at all, so its behavior has no
    effect on any of the 25 products until their own batch flips
    q3_enabled=True."""
    if metadata is None:
        raise ReportMetadataError(
            "Structured metadata missing or unparseable for a Q3-enabled product."
        )

    hero = metadata.get("answer_hero")
    if not isinstance(hero, dict):
        raise ReportMetadataError(
            "Structured metadata is missing a valid 'answer_hero' object."
        )

    missing = []
    for field in required_fields:
        value = hero.get(field)
        if field == "evidence":
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item.strip() for item in value)
            ):
                missing.append(field)
        elif not isinstance(value, str) or not value.strip():
            missing.append(field)

    if missing:
        raise ReportMetadataError(
            f"Structured answer_hero is missing required field(s): {', '.join(missing)}"
        )

    return hero


def assemble_answer_hero(
    hero: dict,
    *,
    deterministic_value: Optional[str] = None,
    deterministic_timing: Optional[str] = None,
) -> dict:
    """Merges an AI-authored (and already-validated, via
    validate_required_hero_fields()) hero dict with any deterministic
    override a product declares (report_product_intelligence.py's own
    `hero_value_source`).

    AI's own `value`/`timing` -- whatever it supplied -- is DISCARDED,
    never merged, whenever a deterministic source is given: this
    codebase's own already-known facts (Sade Sati phase, gemstone
    name, Ashtakoot score, a transiting house, exact Dasha-window
    dates, etc.) are never something the AI is trusted to reproduce
    (Q3B Part 4/Part 5 -- "AI interprets deterministic facts, backend
    remains authority for deterministic facts"). Every other
    AI-authored field (label/interpretation/evidence/caution/
    action_items) passes through unchanged."""
    result = dict(hero)
    if deterministic_value is not None:
        result["value"] = deterministic_value
    if deterministic_timing is not None:
        result["timing"] = deterministic_timing
    return result


def assemble_gemstone_component(
    gemstone_suggestion: Optional[dict],
    *,
    ai_reason: Optional[str] = None,
) -> Optional[dict]:
    """Builds the Q2.1 `gemstone` component dict entirely from trusted
    Kundali data -- kundali["gemstone_suggestion"], the SAME structured
    dict services/gemstone_recommender.py::recommend_gemstone_from_
    lagna_9th() already computes for every order (Q1, unchanged).
    `planet`/`gemstone`/`substone` are NEVER taken from AI output --
    only `reason` may be AI-authored, and even then only when a real
    planet or gemstone name is actually present. Returns None (the
    component is simply omitted, matching Q2.1's own template guard)
    whenever the deterministic data itself is absent/incomplete --
    never a partial or invented gemstone box."""
    if not gemstone_suggestion:
        return None
    planet = gemstone_suggestion.get("planet")
    gemstone = gemstone_suggestion.get("gemstone")
    if not planet and not gemstone:
        return None
    return {
        "planet": planet,
        "gemstone": gemstone,
        "substone": gemstone_suggestion.get("substone"),
        "reason": ai_reason,
    }
