"""
services/ai_prediction_lab/family_context_builder.py
-------------------------------------------------------
Transforms an EXISTING backend kundali payload (as returned by
full_kundali_api.calculate_full_kundali()) into a compact, structured
"Family Profile" AI context -- the Family segment's equivalent of
context_builder.py's build_love_profile_context() /
career_context_builder.py's build_career_profile_context() /
finance_context_builder.py's build_finance_profile_context() /
health_context_builder.py's build_health_profile_context(), reusing
context_builder.py's data-extraction helpers rather than duplicating
them.

This module performs NO astrology calculation of its own. It only reads
fields the backend has already computed (planet positions, houses,
nakshatras, aspects, house lords, and the yoga evaluators already
included in calculate_full_kundali()'s own return dict) and reshapes
them into a smaller dict. Returns structured data only -- no prose, no
interpretation, and no judgment of any specific family member -- this
module only ever surfaces astrological facts, never a claim about a
real person other than the profile owner.
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

SECOND_HOUSE = 2  # Family, speech, immediate household
FOURTH_HOUSE = 4  # Home, mother, emotional foundation, domestic comfort

# Already computed by full_kundali_api.calculate_full_kundali() -- each
# entry is one of its existing yoga-evaluator results (see
# services/gajakesari.py, services/shubh_kartari_yog.py,
# services/adhi_rajyog.py -- shapes already confirmed consistent
# (`is_active`) in the CAREER and HEALTH phases of this project). Not
# recomputed here; only the harmony/protection-relevant subset of the
# full yoga list calculate_full_kundali() already returns is read.
# Reused across segments (gajakesari_yog also informs CAREER;
# shubh_kartari_yog and adhi_rajyog also inform HEALTH) -- each
# generator's own file independently decides its subset and label, so
# there is no shared state or conflict between them. The display label
# is a fixed, short name per key rather than each evaluator's own
# `name`/`heading` field, for the same reason already established in
# every prior segment's context builder.
FAMILY_RELEVANT_YOGA_LABELS = {
    "gajakesari_yog": "Gajakesari Yog",  # Moon-Jupiter -- family wisdom, protection, emotional harmony
    "shubh_kartari_yog": "Shubh Kartari Yog",  # protective/shielding yoga
    "adhi_rajyog": "Adhi Rajyog",  # benefic support around the Moon -- domestic comfort and peace
}


def _house_summary(planets: List[Dict[str, Any]], house_number: int) -> Dict[str, Any]:
    return {
        "house_number": house_number,
        "planets": [_planet_summary(p) for p in _planets_in_house(planets, house_number)],
        "aspects_on_house": _aspects_on_house(planets, house_number),
    }


def _active_yogas(kundali: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reads only the harmony/protection-relevant subset of the yoga
    evaluator results calculate_full_kundali() already computed, keeping
    only the ones actually active in this chart (`is_active` is a field
    every one of these evaluators already returns)."""
    active = []
    for key, label in FAMILY_RELEVANT_YOGA_LABELS.items():
        yoga = kundali.get(key) or {}
        if yoga.get("is_active"):
            active.append({
                "name": label,
                "strength": yoga.get("strength"),
            })
    return active


def build_family_profile_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the Family Profile AI context from an existing backend kundali
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
    # recomputed here, same reuse pattern as every other segment context
    # builder.
    lords = kundali.get("lords") or derive_house_lords(lagna_sign)
    second_lord_name = lords.get(f"{SECOND_HOUSE}_house_lord")
    second_lord = _find_planet(planets, second_lord_name) if second_lord_name else None

    fourth_lord_name = lords.get(f"{FOURTH_HOUSE}_house_lord")
    fourth_lord = _find_planet(planets, fourth_lord_name) if fourth_lord_name else None

    moon = _find_planet(planets, "Moon")
    jupiter = _find_planet(planets, "Jupiter")
    venus = _find_planet(planets, "Venus")
    saturn = _find_planet(planets, "Saturn")

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
            # Same backend limitation documented in every other segment
            # context builder -- retrograde is never captured for natal
            # planets anywhere in the backend.
            "retrograde": "not_available_in_backend",
        },
        "fourth_house": _house_summary(planets, FOURTH_HOUSE),
        "fourth_lord": {
            "name": fourth_lord_name,
            **_planet_summary(fourth_lord),
            "retrograde": "not_available_in_backend",
        },
        "moon": _planet_summary(moon),
        "jupiter": _planet_summary(jupiter),
        "venus": _planet_summary(venus),
        "saturn": _planet_summary(saturn),
        "conjunctions": {
            "second_house": _conjunctions_with(planets, SECOND_HOUSE),
            "fourth_house": _conjunctions_with(planets, FOURTH_HOUSE),
            "fourth_lord": _conjunctions_with(
                planets, (fourth_lord or {}).get("house"), exclude_name=fourth_lord_name
            ),
            "moon": _conjunctions_with(planets, (moon or {}).get("house"), exclude_name="Moon"),
        },
        "yogas": _active_yogas(kundali),
    }

    return context
