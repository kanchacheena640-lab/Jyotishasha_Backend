"""
services/ai_prediction_lab/health_action_guidance_prompt_builder.py
-----------------------------------------------------------------------
Loads prompts/health_action_guidance_v1.txt (the Health segment's third
layer -- Practical Health Guidance) and fills it with:
- the already-generated Health DNA text (first section's output)
- the already-generated Current Health Phase text (second section's
  output)
- the fast-transit action context (health_action_context.py)

Mirrors finance_action_guidance_prompt_builder.py's exact pattern. The
prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_HEALTH_ACTION_GUIDANCE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "health_action_guidance_v1.txt")

_ACTION_PLANETS = ["moon", "sun", "mars"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _language_instruction(language: str) -> str:
    # Bilingual Contract fix -- same convention as every other prompt
    # builder in this package ("en"/"hi" only, anything else falls back
    # to English).
    if language == "hi":
        return (
            "Write your ENTIRE response in Hindi, using Devanagari script "
            "only. Do not use any English sentence or phrase anywhere in "
            "the response (except a proper noun that has no Hindi form)."
        )
    return "Write your ENTIRE response in English."


def build_health_action_guidance_prompt(
    health_dna: str,
    current_health_phase: str,
    health_action_context: Dict[str, Any],
    language: str = "en",
) -> str:
    template = _load_template(_HEALTH_ACTION_GUIDANCE_TEMPLATE)

    values: Dict[str, str] = {
        "health_dna": health_dna,
        "current_health_phase": current_health_phase,
        "language_instruction": _language_instruction(language),
    }

    for planet in _ACTION_PLANETS:
        t = health_action_context.get(planet, {}) or {}
        values[f"{planet}_sign"] = t.get("sign") or "Unknown"
        values[f"{planet}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{planet}_nakshatra"] = t.get("nakshatra") or "Unknown"
        values[f"{planet}_motion"] = t.get("motion") or "Unknown"

    return template.format(**values)
