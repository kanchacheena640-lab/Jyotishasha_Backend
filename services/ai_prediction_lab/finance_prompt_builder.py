"""
services/ai_prediction_lab/finance_prompt_builder.py
--------------------------------------------------------
Loads the Finance Profile prompt template from
services/ai_prediction_lab/prompts/finance_profile_v1.txt and fills it
with a Finance Profile context (as produced by
finance_context_builder.build_finance_profile_context()). Mirrors
career_prompt_builder.py's exact pattern.

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_FINANCE_PROFILE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "finance_profile_v1.txt")


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


def _flatten_finance_profile_context(context: Dict[str, Any]) -> Dict[str, str]:
    ascendant = context.get("ascendant", {})
    second_house = context.get("second_house", {})
    second_lord = context.get("second_lord", {})
    eleventh_house = context.get("eleventh_house", {})
    eleventh_lord = context.get("eleventh_lord", {})
    fifth_house = context.get("fifth_house", {})
    eighth_house = context.get("eighth_house", {})
    jupiter = context.get("jupiter", {})
    venus = context.get("venus", {})
    mercury = context.get("mercury", {})
    saturn = context.get("saturn", {})
    rahu = context.get("rahu", {})
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
        "second_lord_pada": str(second_lord.get("pada") or "Unknown"),
        "second_lord_retrograde": second_lord.get("retrograde") or "Not available",
        "second_lord_aspects": _list_to_text(second_lord.get("aspected_by", [])),

        "eleventh_house_planets": _list_to_text(planet_names(eleventh_house)),
        "eleventh_house_aspects": _list_to_text(eleventh_house.get("aspects_on_house", [])),

        "eleventh_lord_name": eleventh_lord.get("name") or "Unknown",
        "eleventh_lord_sign": eleventh_lord.get("sign") or "Unknown",
        "eleventh_lord_house": str(eleventh_lord.get("house") or "Unknown"),
        "eleventh_lord_nakshatra": eleventh_lord.get("nakshatra") or "Unknown",
        "eleventh_lord_pada": str(eleventh_lord.get("pada") or "Unknown"),
        "eleventh_lord_retrograde": eleventh_lord.get("retrograde") or "Not available",
        "eleventh_lord_aspects": _list_to_text(eleventh_lord.get("aspected_by", [])),

        "fifth_house_planets": _list_to_text(planet_names(fifth_house)),
        "fifth_house_aspects": _list_to_text(fifth_house.get("aspects_on_house", [])),

        "eighth_house_planets": _list_to_text(planet_names(eighth_house)),
        "eighth_house_aspects": _list_to_text(eighth_house.get("aspects_on_house", [])),

        "jupiter_sign": jupiter.get("sign") or "Unknown",
        "jupiter_house": str(jupiter.get("house") or "Unknown"),
        "jupiter_nakshatra": jupiter.get("nakshatra") or "Unknown",
        "jupiter_aspects": _list_to_text(jupiter.get("aspected_by", [])),

        "venus_sign": venus.get("sign") or "Unknown",
        "venus_house": str(venus.get("house") or "Unknown"),
        "venus_nakshatra": venus.get("nakshatra") or "Unknown",
        "venus_aspects": _list_to_text(venus.get("aspected_by", [])),

        "mercury_sign": mercury.get("sign") or "Unknown",
        "mercury_house": str(mercury.get("house") or "Unknown"),
        "mercury_nakshatra": mercury.get("nakshatra") or "Unknown",
        "mercury_aspects": _list_to_text(mercury.get("aspected_by", [])),

        "saturn_sign": saturn.get("sign") or "Unknown",
        "saturn_house": str(saturn.get("house") or "Unknown"),
        "saturn_nakshatra": saturn.get("nakshatra") or "Unknown",
        "saturn_aspects": _list_to_text(saturn.get("aspected_by", [])),

        "rahu_sign": rahu.get("sign") or "Unknown",
        "rahu_house": str(rahu.get("house") or "Unknown"),
        "rahu_nakshatra": rahu.get("nakshatra") or "Unknown",
        "rahu_aspects": _list_to_text(rahu.get("aspected_by", [])),

        "conjunctions_second_house": _list_to_text(conjunctions.get("second_house", [])),
        "conjunctions_second_lord": _list_to_text(conjunctions.get("second_lord", [])),
        "conjunctions_eleventh_house": _list_to_text(conjunctions.get("eleventh_house", [])),
        "conjunctions_eleventh_lord": _list_to_text(conjunctions.get("eleventh_lord", [])),
        "conjunctions_jupiter": _list_to_text(conjunctions.get("jupiter", [])),

        "relevant_yogas": _yogas_to_text(context.get("yogas", [])),
    }


def build_finance_profile_prompt(context: Dict[str, Any]) -> str:
    """Load the finance_profile_v1.txt template and fill it with `context`."""
    template = _load_template(_FINANCE_PROFILE_TEMPLATE)
    values = _flatten_finance_profile_context(context)
    return template.format(**values)
