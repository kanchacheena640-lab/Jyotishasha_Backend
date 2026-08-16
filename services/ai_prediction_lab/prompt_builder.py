"""
services/ai_prediction_lab/prompt_builder.py
----------------------------------------------
Loads the Love Profile prompt template from
services/ai_prediction_lab/prompts/love_profile.txt and fills it with a
Love Profile context (as produced by context_builder.build_love_profile_context()).

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_LOVE_PROFILE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "love_profile_v1.txt")


def _list_to_text(items: List[str]) -> str:
    return ", ".join(items) if items else "None"


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _language_instruction(language: str) -> str:
    # Bilingual Contract fix -- language was never previously threaded
    # into this builder (the .txt template had no language placeholder
    # at all, and unconditionally instructed "conversational English"),
    # so every DNA call silently ignored the caller's requested
    # language. Same convention as current_love_phase_prompt_builder.py
    # ("en"/"hi" only; anything else falls back to English).
    if language == "hi":
        return (
            "Write your ENTIRE response in Hindi, using Devanagari script "
            "only. Do not use any English sentence or phrase anywhere in "
            "the response (except a proper noun that has no Hindi form)."
        )
    return "Write your ENTIRE response in English."


def _flatten_love_profile_context(context: Dict[str, Any]) -> Dict[str, str]:
    ascendant = context.get("ascendant", {})
    fifth_house = context.get("fifth_house", {})
    fifth_lord = context.get("fifth_lord", {})
    venus = context.get("venus", {})
    mars = context.get("mars", {})
    conjunctions = context.get("conjunctions", {})

    fifth_house_planet_names = [p.get("name") for p in fifth_house.get("planets", []) if p.get("name")]

    return {
        "ascendant_sign": ascendant.get("sign") or "Unknown",
        "ascendant_nakshatra": ascendant.get("nakshatra") or "Unknown",
        "ascendant_pada": str(ascendant.get("pada") or "Unknown"),

        "fifth_house_planets": _list_to_text(fifth_house_planet_names),
        "fifth_house_aspects": _list_to_text(fifth_house.get("aspects_on_house", [])),

        "fifth_lord_name": fifth_lord.get("name") or "Unknown",
        "fifth_lord_sign": fifth_lord.get("sign") or "Unknown",
        "fifth_lord_house": str(fifth_lord.get("house") or "Unknown"),
        "fifth_lord_nakshatra": fifth_lord.get("nakshatra") or "Unknown",
        "fifth_lord_pada": str(fifth_lord.get("pada") or "Unknown"),
        "fifth_lord_retrograde": fifth_lord.get("retrograde") or "Not available",
        "fifth_lord_aspects": _list_to_text(fifth_lord.get("aspected_by", [])),

        "venus_sign": venus.get("sign") or "Unknown",
        "venus_house": str(venus.get("house") or "Unknown"),
        "venus_nakshatra": venus.get("nakshatra") or "Unknown",
        "venus_aspects": _list_to_text(venus.get("aspected_by", [])),

        "mars_sign": mars.get("sign") or "Unknown",
        "mars_house": str(mars.get("house") or "Unknown"),
        "mars_nakshatra": mars.get("nakshatra") or "Unknown",
        "mars_aspects": _list_to_text(mars.get("aspected_by", [])),

        "conjunctions_fifth_house": _list_to_text(conjunctions.get("fifth_house", [])),
        "conjunctions_fifth_lord": _list_to_text(conjunctions.get("fifth_lord", [])),
        "conjunctions_venus": _list_to_text(conjunctions.get("venus", [])),
        "conjunctions_mars": _list_to_text(conjunctions.get("mars", [])),
    }


def build_love_profile_prompt(context: Dict[str, Any], language: str = "en") -> str:
    """Load the love_profile.txt template and fill it with `context`."""
    template = _load_template(_LOVE_PROFILE_TEMPLATE)
    values = _flatten_love_profile_context(context)
    values["language_instruction"] = _language_instruction(language)
    return template.format(**values)
