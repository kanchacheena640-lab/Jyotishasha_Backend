"""
services/ai_prediction_lab/career_action_guidance_prompt_builder.py
-----------------------------------------------------------------------
Loads prompts/career_action_guidance_v1.txt (the Career segment's third
layer -- Action Guidance) and fills it with:
- the already-generated Career DNA text (first section's output)
- the already-generated Current Career Phase text (second section's
  output)
- the fast-transit action context (career_action_context.py)

Mirrors daily_love_prediction_prompt_builder.py's exact pattern. The
prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_CAREER_ACTION_GUIDANCE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "career_action_guidance_v1.txt")

_ACTION_PLANETS = ["moon", "mercury", "sun", "mars"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_career_action_guidance_prompt(
    career_dna: str,
    current_career_phase: str,
    career_action_context: Dict[str, Any],
) -> str:
    template = _load_template(_CAREER_ACTION_GUIDANCE_TEMPLATE)

    values: Dict[str, str] = {
        "career_dna": career_dna,
        "current_career_phase": current_career_phase,
    }

    for planet in _ACTION_PLANETS:
        t = career_action_context.get(planet, {}) or {}
        values[f"{planet}_sign"] = t.get("sign") or "Unknown"
        values[f"{planet}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{planet}_nakshatra"] = t.get("nakshatra") or "Unknown"
        values[f"{planet}_motion"] = t.get("motion") or "Unknown"

    return template.format(**values)
