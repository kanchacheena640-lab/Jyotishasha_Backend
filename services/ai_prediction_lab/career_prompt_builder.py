"""
services/ai_prediction_lab/career_prompt_builder.py
------------------------------------------------------
Loads the Career Profile prompt template from
services/ai_prediction_lab/prompts/career_profile_v1.txt and fills it
with a Career Profile context (as produced by
career_context_builder.build_career_profile_context()).

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file. Mirrors prompt_builder.py's exact pattern.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_CAREER_PROFILE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "career_profile_v1.txt")


def _list_to_text(items: List[str]) -> str:
    return ", ".join(items) if items else "None"


def _load_template(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _yogas_to_text(yogas: List[Dict[str, Any]]) -> str:
    if not yogas:
        return "None"
    return ", ".join(
        f"{y.get('name')} ({y.get('strength')})" if y.get("strength") else str(y.get("name"))
        for y in yogas
    )


def _flatten_career_profile_context(context: Dict[str, Any]) -> Dict[str, str]:
    ascendant = context.get("ascendant", {})
    tenth_house = context.get("tenth_house", {})
    tenth_lord = context.get("tenth_lord", {})
    sixth_house = context.get("sixth_house", {})
    second_house = context.get("second_house", {})
    eleventh_house = context.get("eleventh_house", {})
    sun = context.get("sun", {})
    saturn = context.get("saturn", {})
    mercury = context.get("mercury", {})
    jupiter = context.get("jupiter", {})
    conjunctions = context.get("conjunctions", {})

    def planet_names(house: Dict[str, Any]) -> List[str]:
        return [p.get("name") for p in house.get("planets", []) if p.get("name")]

    return {
        "ascendant_sign": ascendant.get("sign") or "Unknown",
        "ascendant_nakshatra": ascendant.get("nakshatra") or "Unknown",
        "ascendant_pada": str(ascendant.get("pada") or "Unknown"),

        "tenth_house_planets": _list_to_text(planet_names(tenth_house)),
        "tenth_house_aspects": _list_to_text(tenth_house.get("aspects_on_house", [])),

        "tenth_lord_name": tenth_lord.get("name") or "Unknown",
        "tenth_lord_sign": tenth_lord.get("sign") or "Unknown",
        "tenth_lord_house": str(tenth_lord.get("house") or "Unknown"),
        "tenth_lord_nakshatra": tenth_lord.get("nakshatra") or "Unknown",
        "tenth_lord_pada": str(tenth_lord.get("pada") or "Unknown"),
        "tenth_lord_retrograde": tenth_lord.get("retrograde") or "Not available",
        "tenth_lord_aspects": _list_to_text(tenth_lord.get("aspected_by", [])),

        "sixth_house_planets": _list_to_text(planet_names(sixth_house)),
        "sixth_house_aspects": _list_to_text(sixth_house.get("aspects_on_house", [])),

        "second_house_planets": _list_to_text(planet_names(second_house)),
        "second_house_aspects": _list_to_text(second_house.get("aspects_on_house", [])),

        "eleventh_house_planets": _list_to_text(planet_names(eleventh_house)),
        "eleventh_house_aspects": _list_to_text(eleventh_house.get("aspects_on_house", [])),

        "sun_sign": sun.get("sign") or "Unknown",
        "sun_house": str(sun.get("house") or "Unknown"),
        "sun_nakshatra": sun.get("nakshatra") or "Unknown",
        "sun_aspects": _list_to_text(sun.get("aspected_by", [])),

        "saturn_sign": saturn.get("sign") or "Unknown",
        "saturn_house": str(saturn.get("house") or "Unknown"),
        "saturn_nakshatra": saturn.get("nakshatra") or "Unknown",
        "saturn_aspects": _list_to_text(saturn.get("aspected_by", [])),

        "mercury_sign": mercury.get("sign") or "Unknown",
        "mercury_house": str(mercury.get("house") or "Unknown"),
        "mercury_nakshatra": mercury.get("nakshatra") or "Unknown",
        "mercury_aspects": _list_to_text(mercury.get("aspected_by", [])),

        "jupiter_sign": jupiter.get("sign") or "Unknown",
        "jupiter_house": str(jupiter.get("house") or "Unknown"),
        "jupiter_nakshatra": jupiter.get("nakshatra") or "Unknown",
        "jupiter_aspects": _list_to_text(jupiter.get("aspected_by", [])),

        "conjunctions_tenth_house": _list_to_text(conjunctions.get("tenth_house", [])),
        "conjunctions_tenth_lord": _list_to_text(conjunctions.get("tenth_lord", [])),
        "conjunctions_sun": _list_to_text(conjunctions.get("sun", [])),
        "conjunctions_saturn": _list_to_text(conjunctions.get("saturn", [])),

        "relevant_yogas": _yogas_to_text(context.get("yogas", [])),
    }


def build_career_profile_prompt(context: Dict[str, Any]) -> str:
    """Load the career_profile_v1.txt template and fill it with `context`."""
    template = _load_template(_CAREER_PROFILE_TEMPLATE)
    values = _flatten_career_profile_context(context)
    return template.format(**values)
