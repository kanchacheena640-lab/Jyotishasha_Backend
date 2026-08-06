"""
services/ai_prediction_lab/career_context_builder.py
-----------------------------------------------------
Transforms an EXISTING backend kundali payload (as returned by
full_kundali_api.calculate_full_kundali()) into a compact, structured
"Career Profile" AI context -- the Career segment's equivalent of
context_builder.py's build_love_profile_context(), reusing that same
module's data-extraction helpers rather than duplicating them.

This module performs NO astrology calculation of its own. It only reads
fields the backend has already computed (planet positions, houses,
nakshatras, aspects, house lords, and the yoga evaluators already
included in calculate_full_kundali()'s own return dict) and reshapes
them into a smaller dict. Returns structured data only -- no prose, no
interpretation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

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

TENTH_HOUSE = 10  # Career, status, profession
SIXTH_HOUSE = 6  # Service, obstacles, competition, daily work
SECOND_HOUSE = 2  # Earned wealth, values, income
ELEVENTH_HOUSE = 11  # Gains, networks, long-term rewards

# Already computed by full_kundali_api.calculate_full_kundali() -- each
# entry is one of its existing yoga-evaluator results (see
# services/dharma_karmadhipati.py, services/rajya_sambandh_rajyog.py,
# services/parashari_rajyog.py, services/panch_mahapurush.py,
# services/gajakesari.py, services/budh_aditya.py). Not recomputed here;
# only the career/status/intellect-relevant subset of the full yoga list
# calculate_full_kundali() already returns is read. Every one of these
# evaluators returns an "is_active" flag -- read generically below,
# never re-derived from raw planet positions. The display label is a
# fixed, short name per key rather than each evaluator's own `name`/
# `heading` field -- those are inconsistent in shape across evaluators
# (e.g. gajakesari_yog's `heading` is a full sentence, not a short
# label), and this module must not modify those existing services to
# make them consistent.
CAREER_RELEVANT_YOGA_LABELS = {
    "dharma_karmadhipati_rajyog": "Dharma-Karmadhipati Rajyog",  # 9th-10th lord connection -- career/purpose alignment
    "rajya_sambandh_rajyog": "Rajya Sambandh Rajyog",  # authority/status connection
    "parashari_rajyog": "Parashari Rajyog",  # classical Raj Yoga -- status and power
    "panch_mahapurush_yog": "Panch Mahapurush Yog",  # personal excellence/achievement
    "gajakesari_yog": "Gajakesari Yog",  # intellect and public standing
    "budh_aditya_yog": "Budh-Aditya Yog",  # Sun-Mercury -- intellect, communication, decision-making
}


def _house_summary(planets: List[Dict[str, Any]], house_number: int) -> Dict[str, Any]:
    return {
        "house_number": house_number,
        "planets": [_planet_summary(p) for p in _planets_in_house(planets, house_number)],
        "aspects_on_house": _aspects_on_house(planets, house_number),
    }


def _active_yogas(kundali: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reads only the career-relevant subset of the yoga evaluator
    results calculate_full_kundali() already computed, keeping only the
    ones actually active in this chart (`is_active` is a field every one
    of these evaluators already returns -- see e.g.
    services/dharma_karmadhipati.py::evaluate_dharma_karmadhipati)."""
    active = []
    for key, label in CAREER_RELEVANT_YOGA_LABELS.items():
        yoga = kundali.get(key) or {}
        if yoga.get("is_active"):
            active.append({
                "name": label,
                "strength": yoga.get("strength"),
            })
    return active


def build_career_profile_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the Career Profile AI context from an existing backend kundali
    payload. `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- this function does not
    call it itself, so the backend remains the single source of truth
    for when/how that payload is produced.
    """
    planets = _planets_list(kundali)

    ascendant = _find_ascendant(planets)
    lagna_sign = kundali.get("lagna_sign") or (ascendant or {}).get("sign")

    # House lords: whole-sign lordship, already computed by
    # services/full_kundali_service.derive_house_lords() -- not
    # recomputed here, same reuse pattern as context_builder.py.
    lords = kundali.get("lords") or derive_house_lords(lagna_sign)
    tenth_lord_name = lords.get(f"{TENTH_HOUSE}_house_lord")
    tenth_lord = _find_planet(planets, tenth_lord_name) if tenth_lord_name else None

    sun = _find_planet(planets, "Sun")
    saturn = _find_planet(planets, "Saturn")
    mercury = _find_planet(planets, "Mercury")
    jupiter = _find_planet(planets, "Jupiter")

    context = {
        "ascendant": {
            "sign": lagna_sign,
            "nakshatra": (ascendant or {}).get("nakshatra"),
            "pada": (ascendant or {}).get("pada"),
        },
        "tenth_house": _house_summary(planets, TENTH_HOUSE),
        "tenth_lord": {
            "name": tenth_lord_name,
            **_planet_summary(tenth_lord),
            # Same backend limitation documented in context_builder.py's
            # fifth_lord/seventh_lord -- retrograde is never captured
            # for natal planets anywhere in the backend.
            "retrograde": "not_available_in_backend",
        },
        "sixth_house": _house_summary(planets, SIXTH_HOUSE),
        "second_house": _house_summary(planets, SECOND_HOUSE),
        "eleventh_house": _house_summary(planets, ELEVENTH_HOUSE),
        "sun": _planet_summary(sun),
        "saturn": _planet_summary(saturn),
        "mercury": _planet_summary(mercury),
        "jupiter": _planet_summary(jupiter),
        "conjunctions": {
            "tenth_house": _conjunctions_with(planets, TENTH_HOUSE),
            "tenth_lord": _conjunctions_with(
                planets, (tenth_lord or {}).get("house"), exclude_name=tenth_lord_name
            ),
            "sun": _conjunctions_with(planets, (sun or {}).get("house"), exclude_name="Sun"),
            "saturn": _conjunctions_with(planets, (saturn or {}).get("house"), exclude_name="Saturn"),
        },
        "yogas": _active_yogas(kundali),
    }

    return context
