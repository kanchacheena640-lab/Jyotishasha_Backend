"""
services/ai_prediction_lab/current_finance_phase_prompt_builder.py
--------------------------------------------------------------------
Loads prompts/current_finance_phase_v1.txt and fills it with the
Current Financial Phase context (current_finance_phase_context.py) plus
the birth details and the already-generated Financial DNA text (first
section). Mirrors current_career_phase_prompt_builder.py's exact
pattern.

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from services.ai_prediction_lab.prompt_input_sanitizer import sanitize_prompt_text

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_CURRENT_FINANCE_PHASE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "current_finance_phase_v1.txt")

_TRANSIT_PLANETS = ["jupiter", "venus", "mercury", "saturn", "rahu", "moon"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _reasons_to_text(reasons: List[str]) -> str:
    return "; ".join(reasons) if reasons else "None"


def build_current_finance_phase_prompt(
    birth_date: str,
    birth_time: str,
    birth_place: str,
    financial_dna: str,
    context: Dict[str, Any],
) -> str:
    template = _load_template(_CURRENT_FINANCE_PHASE_TEMPLATE)

    mahadasha = context.get("mahadasha", {})
    antardasha = context.get("antardasha", {})
    phase = context.get("finance_phase", {})
    transits = context.get("transits", {})

    values: Dict[str, str] = {
        # Free-text profile fields -- sanitized immediately before
        # entering this prompt's `values` dict (defensive hardening
        # only; ordinary birth date/time/place text passes through
        # unchanged). See prompt_input_sanitizer.py.
        "birth_date": sanitize_prompt_text(birth_date),
        "birth_time": sanitize_prompt_text(birth_time),
        "birth_place": sanitize_prompt_text(birth_place),
        "financial_dna": financial_dna,

        "mahadasha_planet": mahadasha.get("planet") or "Unknown",
        "mahadasha_start": mahadasha.get("start") or "Unknown",
        "mahadasha_end": mahadasha.get("end") or "Unknown",

        "antardasha_planet": antardasha.get("planet") or "Unknown",
        "antardasha_start": antardasha.get("start") or "Unknown",
        "antardasha_end": antardasha.get("end") or "Unknown",

        "finance_phase_level": phase.get("level") or "Unknown",
        "finance_phase_confidence": phase.get("confidence") or "Unknown",
        "finance_phase_reasons": _reasons_to_text(phase.get("reasons", [])),
    }

    planet_name_map = {
        "jupiter": "Jupiter", "venus": "Venus", "mercury": "Mercury",
        "saturn": "Saturn", "rahu": "Rahu", "moon": "Moon",
    }
    for key in _TRANSIT_PLANETS:
        t = transits.get(planet_name_map[key], {}) or {}
        values[f"{key}_sign"] = t.get("sign") or "Unknown"
        values[f"{key}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{key}_nakshatra"] = t.get("nakshatra") or "Unknown"
        values[f"{key}_motion"] = t.get("motion") or "Unknown"
        values[f"{key}_finance_role"] = t.get("finance_role") or "Unknown"

    return template.format(**values)
