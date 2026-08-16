"""
services/ai_prediction_lab/daily_love_prediction_prompt_builder.py
-----------------------------------------------------------------------
Loads prompts/daily_love_prediction_v1.txt (Layer 3 -- Prompt 3) and
fills it with:
- the already-generated Relationship DNA text (Prompt 1's output)
- the already-generated Current Love Phase text (Prompt 2's output)
- the Layer 3 daily transit context (daily_transit_context.py)

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_DAILY_LOVE_PREDICTION_TEMPLATE = os.path.join(_TEMPLATE_DIR, "daily_love_prediction_v1.txt")

_DAILY_TRANSIT_PLANETS = ["moon", "mercury", "venus", "mars"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _language_instruction(language: str) -> str:
    # Bilingual Contract fix -- same convention as every other prompt
    # builder in this package ("en"/"hi" only, anything else falls back
    # to English). Previously this builder unconditionally instructed
    # "plain, everyday English" with no language placeholder at all.
    if language == "hi":
        return (
            "Write your ENTIRE response in Hindi, using Devanagari script "
            "only. Do not use any English sentence or phrase anywhere in "
            "the response (except a proper noun that has no Hindi form)."
        )
    return "Write your ENTIRE response in English."


def build_daily_love_prediction_prompt(
    relationship_dna: str,
    current_love_phase: str,
    daily_transit_context: Dict[str, Any],
    language: str = "en",
) -> str:
    template = _load_template(_DAILY_LOVE_PREDICTION_TEMPLATE)

    values: Dict[str, str] = {
        "relationship_dna": relationship_dna,
        "current_love_phase": current_love_phase,
        "language_instruction": _language_instruction(language),
    }

    for planet in _DAILY_TRANSIT_PLANETS:
        t = daily_transit_context.get(planet, {}) or {}
        values[f"{planet}_sign"] = t.get("sign") or "Unknown"
        values[f"{planet}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{planet}_nakshatra"] = t.get("nakshatra") or "Unknown"
        values[f"{planet}_motion"] = t.get("motion") or "Unknown"

    return template.format(**values)
