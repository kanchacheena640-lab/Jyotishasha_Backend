"""
services/ai_prediction_lab/family_action_guidance_prompt_builder.py
-----------------------------------------------------------------------
Loads prompts/family_action_guidance_v1.txt (the Family segment's third
layer -- Practical Family Guidance) and fills it with:
- the already-generated Family DNA text (first section's output)
- the already-generated Current Family Phase text (second section's
  output)
- the fast-transit action context (family_action_context.py)

Mirrors health_action_guidance_prompt_builder.py's exact pattern. The
prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_FAMILY_ACTION_GUIDANCE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "family_action_guidance_v1.txt")

_ACTION_PLANETS = ["moon", "venus"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_family_action_guidance_prompt(
    family_dna: str,
    current_family_phase: str,
    family_action_context: Dict[str, Any],
) -> str:
    template = _load_template(_FAMILY_ACTION_GUIDANCE_TEMPLATE)

    values: Dict[str, str] = {
        "family_dna": family_dna,
        "current_family_phase": current_family_phase,
    }

    for planet in _ACTION_PLANETS:
        t = family_action_context.get(planet, {}) or {}
        values[f"{planet}_sign"] = t.get("sign") or "Unknown"
        values[f"{planet}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{planet}_nakshatra"] = t.get("nakshatra") or "Unknown"
        values[f"{planet}_motion"] = t.get("motion") or "Unknown"

    return template.format(**values)
