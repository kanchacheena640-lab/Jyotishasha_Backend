"""
services/ai_prediction_lab/family_prompt_builder.py
--------------------------------------------------------
Loads the Family Profile prompt template from
services/ai_prediction_lab/prompts/family_profile_v1.txt and fills it
with a Family Profile context (as produced by
family_context_builder.build_family_profile_context()). Mirrors
health_prompt_builder.py's exact pattern.

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_FAMILY_PROFILE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "family_profile_v1.txt")


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


def _flatten_family_profile_context(context: Dict[str, Any]) -> Dict[str, str]:
    ascendant = context.get("ascendant", {})
    second_house = context.get("second_house", {})
    second_lord = context.get("second_lord", {})
    fourth_house = context.get("fourth_house", {})
    fourth_lord = context.get("fourth_lord", {})
    moon = context.get("moon", {})
    jupiter = context.get("jupiter", {})
    venus = context.get("venus", {})
    saturn = context.get("saturn", {})
    conjunctions = context.get("conjunctions", {})

    def planet_names(house: Dict[str, Any]) -> List[str]:
        return [p.get("name") for p in house.get("planets", []) if p.get("name")]

    return {
        "ascendant_sign": ascendant.get("sign") or "Unknown",
        "ascendant_nakshatra": ascendant.get("nakshatra") or "Unknown",
        "ascendant_pada": str(ascendant.get("pada") or "Unknown"),

        "second_house_planets": _list_to_text(planet_names(second_house)),
        "second_house_aspects": _list_to_text(second_house.get("aspects_on_house", [])),
        "second_lord_name": second_lord.get("name") or "Unknown",
        "second_lord_sign": second_lord.get("sign") or "Unknown",
        "second_lord_house": str(second_lord.get("house") or "Unknown"),
        "second_lord_nakshatra": second_lord.get("nakshatra") or "Unknown",

        "fourth_house_planets": _list_to_text(planet_names(fourth_house)),
        "fourth_house_aspects": _list_to_text(fourth_house.get("aspects_on_house", [])),
        "fourth_lord_name": fourth_lord.get("name") or "Unknown",
        "fourth_lord_sign": fourth_lord.get("sign") or "Unknown",
        "fourth_lord_house": str(fourth_lord.get("house") or "Unknown"),
        "fourth_lord_nakshatra": fourth_lord.get("nakshatra") or "Unknown",
        "fourth_lord_aspects": _list_to_text(fourth_lord.get("aspected_by", [])),

        "moon_sign": moon.get("sign") or "Unknown",
        "moon_house": str(moon.get("house") or "Unknown"),
        "moon_nakshatra": moon.get("nakshatra") or "Unknown",
        "moon_aspects": _list_to_text(moon.get("aspected_by", [])),

        "jupiter_sign": jupiter.get("sign") or "Unknown",
        "jupiter_house": str(jupiter.get("house") or "Unknown"),
        "jupiter_nakshatra": jupiter.get("nakshatra") or "Unknown",
        "jupiter_aspects": _list_to_text(jupiter.get("aspected_by", [])),

        "venus_sign": venus.get("sign") or "Unknown",
        "venus_house": str(venus.get("house") or "Unknown"),
        "venus_nakshatra": venus.get("nakshatra") or "Unknown",
        "venus_aspects": _list_to_text(venus.get("aspected_by", [])),

        "saturn_sign": saturn.get("sign") or "Unknown",
        "saturn_house": str(saturn.get("house") or "Unknown"),
        "saturn_nakshatra": saturn.get("nakshatra") or "Unknown",
        "saturn_aspects": _list_to_text(saturn.get("aspected_by", [])),

        "conjunctions_second_house": _list_to_text(conjunctions.get("second_house", [])),
        "conjunctions_fourth_house": _list_to_text(conjunctions.get("fourth_house", [])),
        "conjunctions_fourth_lord": _list_to_text(conjunctions.get("fourth_lord", [])),
        "conjunctions_moon": _list_to_text(conjunctions.get("moon", [])),

        "relevant_yogas": _yogas_to_text(context.get("yogas", [])),
    }


def build_family_profile_prompt(context: Dict[str, Any]) -> str:
    """Load the family_profile_v1.txt template and fill it with `context`."""
    template = _load_template(_FAMILY_PROFILE_TEMPLATE)
    values = _flatten_family_profile_context(context)
    return template.format(**values)
