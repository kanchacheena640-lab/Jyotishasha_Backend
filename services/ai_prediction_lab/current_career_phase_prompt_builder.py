"""
services/ai_prediction_lab/current_career_phase_prompt_builder.py
--------------------------------------------------------------------
Loads prompts/current_career_phase_v1.txt and fills it with the Current
Career Phase context (current_career_phase_context.py) plus the birth
details and the already-generated Career DNA text (first section).
Mirrors current_love_phase_prompt_builder.py's exact pattern.

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from services.ai_prediction_lab.prompt_input_sanitizer import sanitize_prompt_text

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_CURRENT_CAREER_PHASE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "current_career_phase_v1.txt")

_TRANSIT_PLANETS = ["sun", "saturn", "jupiter", "mercury", "moon"]


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _reasons_to_text(reasons: List[str]) -> str:
    return "; ".join(reasons) if reasons else "None"


def _language_instruction(language: str) -> str:
    # Additive fix -- language was never previously threaded into this
    # builder (the .txt template had no language placeholder at all), so
    # every CURRENT_PHASE call silently ignored the caller's requested
    # language. Only two languages are handled, matching this project's
    # existing `language` convention elsewhere ("en"/"hi"); anything else
    # falls back to English rather than guessing.
    if language == "hi":
        return (
            "Write your ENTIRE response in Hindi, using Devanagari script "
            "only. Do not use any English sentence or phrase anywhere in "
            "the response (except a proper noun that has no Hindi form)."
        )
    return "Write your ENTIRE response in English."


def build_current_career_phase_prompt(
    birth_date: str,
    birth_time: str,
    birth_place: str,
    career_dna: str,
    context: Dict[str, Any],
    language: str = "en",
) -> str:
    template = _load_template(_CURRENT_CAREER_PHASE_TEMPLATE)

    mahadasha = context.get("mahadasha", {})
    antardasha = context.get("antardasha", {})
    phase = context.get("career_phase", {})
    transits = context.get("transits", {})

    values: Dict[str, str] = {
        # Free-text profile fields -- sanitized immediately before
        # entering this prompt's `values` dict (defensive hardening
        # only; ordinary birth date/time/place text passes through
        # unchanged). See prompt_input_sanitizer.py.
        "birth_date": sanitize_prompt_text(birth_date),
        "birth_time": sanitize_prompt_text(birth_time),
        "birth_place": sanitize_prompt_text(birth_place),
        "career_dna": career_dna,
        "language_instruction": _language_instruction(language),

        "mahadasha_planet": mahadasha.get("planet") or "Unknown",
        "mahadasha_start": mahadasha.get("start") or "Unknown",
        "mahadasha_end": mahadasha.get("end") or "Unknown",

        "antardasha_planet": antardasha.get("planet") or "Unknown",
        "antardasha_start": antardasha.get("start") or "Unknown",
        # Raw Antardasha end date -- unchanged, still feeds the factual
        # "CURRENT PLANETARY PERIOD" block in the template.
        "antardasha_end": antardasha.get("end") or "Unknown",

        # Next Phase Change value -- the nearest of the Antardasha end
        # date or the next major transit date (see next_phase_change_date,
        # computed in current_career_phase_context.py). Falls back to the
        # raw Antardasha end date, then "Unknown", if that computation
        # returned nothing. Feeds a DIFFERENT template placeholder
        # ({next_phase_change_date}, only in the NEXT PHASE CHANGE RULES
        # section) so it never overwrites the factual Antardasha display
        # above.
        "next_phase_change_date": context.get("next_phase_change_date") or antardasha.get("end") or "Unknown",

        "career_phase_level": phase.get("level") or "Unknown",
        "career_phase_confidence": phase.get("confidence") or "Unknown",
        "career_phase_reasons": _reasons_to_text(phase.get("reasons", [])),
    }

    planet_name_map = {"sun": "Sun", "saturn": "Saturn", "jupiter": "Jupiter", "mercury": "Mercury", "moon": "Moon"}
    for key in _TRANSIT_PLANETS:
        t = transits.get(planet_name_map[key], {}) or {}
        values[f"{key}_sign"] = t.get("sign") or "Unknown"
        values[f"{key}_house"] = str(t.get("house") if t.get("house") is not None else "Unknown")
        values[f"{key}_nakshatra"] = t.get("nakshatra") or "Unknown"
        values[f"{key}_motion"] = t.get("motion") or "Unknown"
        values[f"{key}_career_role"] = t.get("career_role") or "Unknown"

    return template.format(**values)
