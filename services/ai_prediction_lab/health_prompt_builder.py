"""
services/ai_prediction_lab/health_prompt_builder.py
--------------------------------------------------------
Loads the Health Profile prompt template from
services/ai_prediction_lab/prompts/health_profile_v1.txt and fills it
with a Health Profile context (as produced by
health_context_builder.build_health_profile_context()). Mirrors
finance_prompt_builder.py's exact pattern.

The prompt text itself lives entirely in the .txt template -- nothing is
hardcoded in this file.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")
_HEALTH_PROFILE_TEMPLATE = os.path.join(_TEMPLATE_DIR, "health_profile_v1.txt")


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


def _flatten_health_profile_context(context: Dict[str, Any]) -> Dict[str, str]:
    ascendant = context.get("ascendant", {})
    lagna_lord = context.get("lagna_lord", {})
    sixth_house = context.get("sixth_house", {})
    sixth_lord = context.get("sixth_lord", {})
    eighth_house = context.get("eighth_house", {})
    eighth_lord = context.get("eighth_lord", {})
    twelfth_house = context.get("twelfth_house", {})
    twelfth_lord = context.get("twelfth_lord", {})
    moon = context.get("moon", {})
    sun = context.get("sun", {})
    mars = context.get("mars", {})
    saturn = context.get("saturn", {})
    jupiter = context.get("jupiter", {})
    conjunctions = context.get("conjunctions", {})

    def planet_names(house: Dict[str, Any]) -> List[str]:
        return [p.get("name") for p in house.get("planets", []) if p.get("name")]

    return {
        "ascendant_sign": ascendant.get("sign") or "Unknown",
        "ascendant_nakshatra": ascendant.get("nakshatra") or "Unknown",
        "ascendant_pada": str(ascendant.get("pada") or "Unknown"),

        "lagna_lord_name": lagna_lord.get("name") or "Unknown",
        "lagna_lord_sign": lagna_lord.get("sign") or "Unknown",
        "lagna_lord_house": str(lagna_lord.get("house") or "Unknown"),
        "lagna_lord_nakshatra": lagna_lord.get("nakshatra") or "Unknown",
        "lagna_lord_aspects": _list_to_text(lagna_lord.get("aspected_by", [])),

        "sixth_house_planets": _list_to_text(planet_names(sixth_house)),
        "sixth_house_aspects": _list_to_text(sixth_house.get("aspects_on_house", [])),
        "sixth_lord_name": sixth_lord.get("name") or "Unknown",
        "sixth_lord_sign": sixth_lord.get("sign") or "Unknown",
        "sixth_lord_house": str(sixth_lord.get("house") or "Unknown"),
        "sixth_lord_nakshatra": sixth_lord.get("nakshatra") or "Unknown",

        "eighth_house_planets": _list_to_text(planet_names(eighth_house)),
        "eighth_house_aspects": _list_to_text(eighth_house.get("aspects_on_house", [])),
        "eighth_lord_name": eighth_lord.get("name") or "Unknown",
        "eighth_lord_sign": eighth_lord.get("sign") or "Unknown",
        "eighth_lord_house": str(eighth_lord.get("house") or "Unknown"),
        "eighth_lord_nakshatra": eighth_lord.get("nakshatra") or "Unknown",

        "twelfth_house_planets": _list_to_text(planet_names(twelfth_house)),
        "twelfth_house_aspects": _list_to_text(twelfth_house.get("aspects_on_house", [])),
        "twelfth_lord_name": twelfth_lord.get("name") or "Unknown",
        "twelfth_lord_sign": twelfth_lord.get("sign") or "Unknown",
        "twelfth_lord_house": str(twelfth_lord.get("house") or "Unknown"),
        "twelfth_lord_nakshatra": twelfth_lord.get("nakshatra") or "Unknown",

        "moon_sign": moon.get("sign") or "Unknown",
        "moon_house": str(moon.get("house") or "Unknown"),
        "moon_nakshatra": moon.get("nakshatra") or "Unknown",
        "moon_aspects": _list_to_text(moon.get("aspected_by", [])),

        "sun_sign": sun.get("sign") or "Unknown",
        "sun_house": str(sun.get("house") or "Unknown"),
        "sun_nakshatra": sun.get("nakshatra") or "Unknown",
        "sun_aspects": _list_to_text(sun.get("aspected_by", [])),

        "mars_sign": mars.get("sign") or "Unknown",
        "mars_house": str(mars.get("house") or "Unknown"),
        "mars_nakshatra": mars.get("nakshatra") or "Unknown",
        "mars_aspects": _list_to_text(mars.get("aspected_by", [])),

        "saturn_sign": saturn.get("sign") or "Unknown",
        "saturn_house": str(saturn.get("house") or "Unknown"),
        "saturn_nakshatra": saturn.get("nakshatra") or "Unknown",
        "saturn_aspects": _list_to_text(saturn.get("aspected_by", [])),

        "jupiter_sign": jupiter.get("sign") or "Unknown",
        "jupiter_house": str(jupiter.get("house") or "Unknown"),
        "jupiter_nakshatra": jupiter.get("nakshatra") or "Unknown",
        "jupiter_aspects": _list_to_text(jupiter.get("aspected_by", [])),

        "conjunctions_lagna_lord": _list_to_text(conjunctions.get("lagna_lord", [])),
        "conjunctions_sixth_house": _list_to_text(conjunctions.get("sixth_house", [])),
        "conjunctions_eighth_house": _list_to_text(conjunctions.get("eighth_house", [])),
        "conjunctions_twelfth_house": _list_to_text(conjunctions.get("twelfth_house", [])),
        "conjunctions_moon": _list_to_text(conjunctions.get("moon", [])),
        "conjunctions_saturn": _list_to_text(conjunctions.get("saturn", [])),

        "relevant_yogas": _yogas_to_text(context.get("yogas", [])),
    }


def build_health_profile_prompt(context: Dict[str, Any]) -> str:
    """Load the health_profile_v1.txt template and fill it with `context`."""
    template = _load_template(_HEALTH_PROFILE_TEMPLATE)
    values = _flatten_health_profile_context(context)
    return template.format(**values)
