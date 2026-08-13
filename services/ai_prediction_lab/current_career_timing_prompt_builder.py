# services/ai_prediction_lab/current_career_timing_prompt_builder.py

"""
services/ai_prediction_lab/current_career_timing_prompt_builder.py
--------------------------------------------------------------------
Loads prompts/current_career_timing_v1.txt and fills it with the
Current Career Timing context (current_career_timing_context.py) plus
the already-generated Current Career Phase text (the report this layer
continues from). Mirrors current_love_timing_prompt_builder.py's exact
pattern.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_CURRENT_CAREER_TIMING_TEMPLATE = os.path.join(_TEMPLATE_DIR, "current_career_timing_v1.txt")

_TIMING_PLANETS = ["sun", "mercury", "moon"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _language_instruction(language: str) -> str:
    if language == "hi":
        return (
            "Write your ENTIRE response in Hindi, using Devanagari script "
            "only. Do not use any English sentence or phrase anywhere in "
            "the response (except a proper noun that has no Hindi form)."
        )
    return "Write your ENTIRE response in English."


def _conjunctions_text(conjunctions: List[str]) -> str:
    return ", ".join(conjunctions) if conjunctions else "None"


def build_current_career_timing_prompt(
    current_career_phase: str,
    context: Dict[str, Any],
    language: str = "en",
) -> str:
    template = _load_template(_CURRENT_CAREER_TIMING_TEMPLATE)

    values: Dict[str, str] = {
        "current_phase_text": current_career_phase,
        "language_instruction": _language_instruction(language),
    }

    for key in _TIMING_PLANETS:
        t = context.get(key, {}) or {}
        values[f"{key}_sign"] = t.get("sign") or "Unknown"
        values[f"{key}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{key}_nakshatra"] = t.get("nakshatra") or "Unknown"

    values["moon_conjunctions"] = _conjunctions_text(context.get("moon_conjunctions") or [])

    foundation = context.get("foundation_lord", {}) or {}
    values["foundation_lord_sign"] = foundation.get("sign") or "Unknown"
    values["foundation_lord_house"] = str(
        foundation.get("house") if foundation.get("house") is not None else "Unknown"
    )

    return template.format(**values)
