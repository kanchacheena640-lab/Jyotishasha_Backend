"""
services/ai_prediction_lab/current_family_phase_prompt_builder.py
--------------------------------------------------------------------
Loads prompts/current_family_phase_v1.txt and fills it with the
Current Family Phase context (current_family_phase_context.py) plus the
birth details and the already-generated Family DNA text (first
section). Mirrors current_health_phase_prompt_builder.py's exact
pattern.

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from services.ai_prediction_lab.prompt_input_sanitizer import sanitize_prompt_text

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_CURRENT_FAMILY_PHASE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "current_family_phase_v1.txt")

_TRANSIT_PLANETS = ["moon", "jupiter", "venus", "saturn"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _reasons_to_text(reasons: List[str]) -> str:
    return "; ".join(reasons) if reasons else "None"


def build_current_family_phase_prompt(
    birth_date: str,
    birth_time: str,
    birth_place: str,
    family_dna: str,
    context: Dict[str, Any],
) -> str:
    template = _load_template(_CURRENT_FAMILY_PHASE_TEMPLATE)

    mahadasha = context.get("mahadasha", {})
    antardasha = context.get("antardasha", {})
    phase = context.get("family_phase", {})
    transits = context.get("transits", {})

    values: Dict[str, str] = {
        # Free-text profile fields -- sanitized immediately before
        # entering this prompt's `values` dict (defensive hardening
        # only; ordinary birth date/time/place text passes through
        # unchanged). See prompt_input_sanitizer.py.
        "birth_date": sanitize_prompt_text(birth_date),
        "birth_time": sanitize_prompt_text(birth_time),
        "birth_place": sanitize_prompt_text(birth_place),
        "family_dna": family_dna,

        "mahadasha_planet": mahadasha.get("planet") or "Unknown",
        "mahadasha_start": mahadasha.get("start") or "Unknown",
        "mahadasha_end": mahadasha.get("end") or "Unknown",

        "antardasha_planet": antardasha.get("planet") or "Unknown",
        "antardasha_start": antardasha.get("start") or "Unknown",
        "antardasha_end": antardasha.get("end") or "Unknown",

        "family_phase_level": phase.get("level") or "Unknown",
        "family_phase_confidence": phase.get("confidence") or "Unknown",
        "family_phase_reasons": _reasons_to_text(phase.get("reasons", [])),
    }

    planet_name_map = {"moon": "Moon", "jupiter": "Jupiter", "venus": "Venus", "saturn": "Saturn"}
    for key in _TRANSIT_PLANETS:
        t = transits.get(planet_name_map[key], {}) or {}
        values[f"{key}_sign"] = t.get("sign") or "Unknown"
        values[f"{key}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{key}_nakshatra"] = t.get("nakshatra") or "Unknown"
        values[f"{key}_motion"] = t.get("motion") or "Unknown"
        values[f"{key}_family_role"] = t.get("family_role") or "Unknown"

    return template.format(**values)
