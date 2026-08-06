"""
services/ai_prediction_lab/finance_context_builder.py
-------------------------------------------------------
Transforms an EXISTING backend kundali payload (as returned by
full_kundali_api.calculate_full_kundali()) into a compact, structured
"Finance Profile" AI context -- the Finance segment's equivalent of
context_builder.py's build_love_profile_context() /
career_context_builder.py's build_career_profile_context(), reusing
context_builder.py's data-extraction helpers rather than duplicating
them.

This module performs NO astrology calculation of its own. It only reads
fields the backend has already computed (planet positions, houses,
nakshatras, aspects, house lords, and the yoga evaluators already
included in calculate_full_kundali()'s own return dict) and reshapes
them into a smaller dict. Returns structured data only -- no prose, no
interpretation.
"""

from __future__ import annotations

from typing import Any, Dict, List

from services.full_kundali_service import derive_house_lords
from services.ai_prediction_lab.context_builder import (
    _aspects_on_house,
    _conjunctions_with,
    _find_ascendant,
    _find_planet,
    _planet_summary,
    _planets_in_house,
    _planets_list,
)

SECOND_HOUSE = 2  # Earned wealth, savings, values
ELEVENTH_HOUSE = 11  # Gains, income, long-term rewards
FIFTH_HOUSE = 5  # Investment, speculation
EIGHTH_HOUSE = 8  # Unexpected gains/losses, other people's money

# Already computed by full_kundali_api.calculate_full_kundali() -- each
# entry is one of its existing yoga-evaluator results (see
# services/dhan_yog.py, services/kuber_rajyog.py,
# services/lakshmi_yog.py, services/chandra_mangal.py). Not recomputed
# here; only the wealth-relevant subset of the full yoga list
# calculate_full_kundali() already returns is read. The display label is
# a fixed, short name per key rather than each evaluator's own `name`/
# `heading` field -- those are inconsistent in shape across evaluators
# (the same issue found and fixed for CAREER's gajakesari_yog), and this
# module must not modify those existing services to make them
# consistent.
FINANCE_RELEVANT_YOGA_LABELS = {
    "dhan_yog": "Dhan Yog",  # direct wealth yoga
    "kuber_rajyog": "Kuber Rajyog",  # wealth/treasury yoga
    "lakshmi_yog": "Lakshmi Yog",  # prosperity yoga
    "chandra_mangal_yog": "Chandra-Mangal Yog",  # Moon-Mars -- business acumen, wealth through effort
}


def _house_summary(planets: List[Dict[str, Any]], house_number: int) -> Dict[str, Any]:
    return {
        "house_number": house_number,
        "planets": [_planet_summary(p) for p in _planets_in_house(planets, house_number)],
        "aspects_on_house": _aspects_on_house(planets, house_number),
    }


def _active_yogas(kundali: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reads only the wealth-relevant subset of the yoga evaluator
    results calculate_full_kundali() already computed, keeping only the
    ones actually active in this chart (`is_active` is a field every one
    of these evaluators already returns)."""
    active = []
    for key, label in FINANCE_RELEVANT_YOGA_LABELS.items():
        yoga = kundali.get(key) or {}
        if yoga.get("is_active"):
            active.append({
                "name": label,
                "strength": yoga.get("strength"),
            })
    return active


def build_finance_profile_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the Finance Profile AI context from an existing backend
    kundali payload. `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- this function does not
    call it itself, so the backend remains the single source of truth
    for when/how that payload is produced.
    """
    planets = _planets_list(kundali)

    ascendant = _find_ascendant(planets)
    lagna_sign = kundali.get("lagna_sign") or (ascendant or {}).get("sign")

    # House lords: whole-sign lordship, already computed by
    # services/full_kundali_service.derive_house_lords() -- not
    # recomputed here, same reuse pattern as context_builder.py /
    # career_context_builder.py.
    lords = kundali.get("lords") or derive_house_lords(lagna_sign)
    second_lord_name = lords.get(f"{SECOND_HOUSE}_house_lord")
    second_lord = _find_planet(planets, second_lord_name) if second_lord_name else None

    eleventh_lord_name = lords.get(f"{ELEVENTH_HOUSE}_house_lord")
    eleventh_lord = _find_planet(planets, eleventh_lord_name) if eleventh_lord_name else None

    jupiter = _find_planet(planets, "Jupiter")
    venus = _find_planet(planets, "Venus")
    mercury = _find_planet(planets, "Mercury")
    saturn = _find_planet(planets, "Saturn")
    rahu = _find_planet(planets, "Rahu")

    context = {
        "ascendant": {
            "sign": lagna_sign,
            "nakshatra": (ascendant or {}).get("nakshatra"),
            "pada": (ascendant or {}).get("pada"),
        },
        "second_house": _house_summary(planets, SECOND_HOUSE),
        "second_lord": {
            "name": second_lord_name,
            **_planet_summary(second_lord),
            # Same backend limitation documented in context_builder.py's
            # fifth_lord/seventh_lord and career_context_builder.py's
            # tenth_lord -- retrograde is never captured for natal
            # planets anywhere in the backend.
            "retrograde": "not_available_in_backend",
        },
        "eleventh_house": _house_summary(planets, ELEVENTH_HOUSE),
        "eleventh_lord": {
            "name": eleventh_lord_name,
            **_planet_summary(eleventh_lord),
            "retrograde": "not_available_in_backend",
        },
        "fifth_house": _house_summary(planets, FIFTH_HOUSE),
        "eighth_house": _house_summary(planets, EIGHTH_HOUSE),
        "jupiter": _planet_summary(jupiter),
        "venus": _planet_summary(venus),
        "mercury": _planet_summary(mercury),
        "saturn": _planet_summary(saturn),
        "rahu": _planet_summary(rahu),
        "conjunctions": {
            "second_house": _conjunctions_with(planets, SECOND_HOUSE),
            "second_lord": _conjunctions_with(
                planets, (second_lord or {}).get("house"), exclude_name=second_lord_name
            ),
            "eleventh_house": _conjunctions_with(planets, ELEVENTH_HOUSE),
            "eleventh_lord": _conjunctions_with(
                planets, (eleventh_lord or {}).get("house"), exclude_name=eleventh_lord_name
            ),
            "jupiter": _conjunctions_with(planets, (jupiter or {}).get("house"), exclude_name="Jupiter"),
        },
        "yogas": _active_yogas(kundali),
    }

    return context
