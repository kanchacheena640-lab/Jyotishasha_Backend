"""
services/ai_prediction_lab/health_context_builder.py
-------------------------------------------------------
Transforms an EXISTING backend kundali payload (as returned by
full_kundali_api.calculate_full_kundali()) into a compact, structured
"Health Profile" AI context -- the Health segment's equivalent of
context_builder.py's build_love_profile_context() /
career_context_builder.py's build_career_profile_context() /
finance_context_builder.py's build_finance_profile_context(), reusing
context_builder.py's data-extraction helpers rather than duplicating
them.

This module performs NO astrology calculation of its own. It only reads
fields the backend has already computed (planet positions, houses,
nakshatras, aspects, house lords, and the yoga evaluators already
included in calculate_full_kundali()'s own return dict) and reshapes
them into a smaller dict. Returns structured data only -- no prose, no
interpretation, and NO medical claim of any kind -- this module only
ever surfaces astrological facts, never health advice.
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

LAGNA_HOUSE = 1  # Body, vitality, overall constitution
SIXTH_HOUSE = 6  # Daily routines, resistance, minor ailments
EIGHTH_HOUSE = 8  # Chronic/hidden conditions, resilience, longevity
TWELFTH_HOUSE = 12  # Rest, recovery, hospitalization, isolation

# Already computed by full_kundali_api.calculate_full_kundali() -- each
# entry is one of its existing yoga-evaluator results (see
# services/neechbhang_rajyog.py, services/vipreet_rajyog.py,
# services/shubh_kartari_yog.py, services/panch_mahapurush.py,
# services/adhi_rajyog.py). Not recomputed here; only the
# resilience/protection/vitality-relevant subset of the full yoga list
# calculate_full_kundali() already returns is read -- deliberately NOT
# the dosha report functions (manglik_dosh/kaalsarp_dosh/sadhesati),
# whose return shape has no consistent `is_active`-style flag to read
# generically (their "present"/"absent" state is only distinguishable by
# comparing free-text `heading` strings), and this module must not
# modify those existing services to make them consistent. The display
# label is a fixed, short name per key rather than each evaluator's own
# `name`/`heading` field, for the same reason already established in
# career_context_builder.py/finance_context_builder.py (inconsistent
# shape across evaluators, e.g. gajakesari_yog's `heading` being a full
# sentence rather than a short label).
HEALTH_RELEVANT_YOGA_LABELS = {
    "neechbhang_rajyog": "Neechbhang Rajyog",  # a weakness turned into strength -- resilience
    "vipreet_rajyog": "Vipreet Rajyog",  # adversity turned into advantage -- recovery
    "shubh_kartari_yog": "Shubh Kartari Yog",  # protective/shielding yoga
    "panch_mahapurush_yog": "Panch Mahapurush Yog",  # vitality, personal strength
    "adhi_rajyog": "Adhi Rajyog",  # support/comfort from benefics around the Moon (mind) and 6th/8th (health houses)
}


def _house_summary(planets: List[Dict[str, Any]], house_number: int) -> Dict[str, Any]:
    return {
        "house_number": house_number,
        "planets": [_planet_summary(p) for p in _planets_in_house(planets, house_number)],
        "aspects_on_house": _aspects_on_house(planets, house_number),
    }


def _active_yogas(kundali: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Reads only the resilience/protection-relevant subset of the yoga
    evaluator results calculate_full_kundali() already computed, keeping
    only the ones actually active in this chart (`is_active` is a field
    every one of these evaluators already returns)."""
    active = []
    for key, label in HEALTH_RELEVANT_YOGA_LABELS.items():
        yoga = kundali.get(key) or {}
        if yoga.get("is_active"):
            active.append({
                "name": label,
                "strength": yoga.get("strength"),
            })
    return active


def build_health_profile_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the Health Profile AI context from an existing backend kundali
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
    # recomputed here, same reuse pattern as the other segment context
    # builders.
    lords = kundali.get("lords") or derive_house_lords(lagna_sign)
    lagna_lord_name = lords.get(f"{LAGNA_HOUSE}_house_lord")
    lagna_lord = _find_planet(planets, lagna_lord_name) if lagna_lord_name else None

    sixth_lord_name = lords.get(f"{SIXTH_HOUSE}_house_lord")
    sixth_lord = _find_planet(planets, sixth_lord_name) if sixth_lord_name else None

    eighth_lord_name = lords.get(f"{EIGHTH_HOUSE}_house_lord")
    eighth_lord = _find_planet(planets, eighth_lord_name) if eighth_lord_name else None

    twelfth_lord_name = lords.get(f"{TWELFTH_HOUSE}_house_lord")
    twelfth_lord = _find_planet(planets, twelfth_lord_name) if twelfth_lord_name else None

    moon = _find_planet(planets, "Moon")
    sun = _find_planet(planets, "Sun")
    mars = _find_planet(planets, "Mars")
    saturn = _find_planet(planets, "Saturn")
    jupiter = _find_planet(planets, "Jupiter")

    context = {
        "ascendant": {
            "sign": lagna_sign,
            "nakshatra": (ascendant or {}).get("nakshatra"),
            "pada": (ascendant or {}).get("pada"),
        },
        "lagna_lord": {
            "name": lagna_lord_name,
            **_planet_summary(lagna_lord),
            # Same backend limitation documented in every other segment
            # context builder -- retrograde is never captured for natal
            # planets anywhere in the backend.
            "retrograde": "not_available_in_backend",
        },
        "sixth_house": _house_summary(planets, SIXTH_HOUSE),
        "sixth_lord": {
            "name": sixth_lord_name,
            **_planet_summary(sixth_lord),
            "retrograde": "not_available_in_backend",
        },
        "eighth_house": _house_summary(planets, EIGHTH_HOUSE),
        "eighth_lord": {
            "name": eighth_lord_name,
            **_planet_summary(eighth_lord),
            "retrograde": "not_available_in_backend",
        },
        "twelfth_house": _house_summary(planets, TWELFTH_HOUSE),
        "twelfth_lord": {
            "name": twelfth_lord_name,
            **_planet_summary(twelfth_lord),
            "retrograde": "not_available_in_backend",
        },
        "moon": _planet_summary(moon),
        "sun": _planet_summary(sun),
        "mars": _planet_summary(mars),
        "saturn": _planet_summary(saturn),
        "jupiter": _planet_summary(jupiter),
        "conjunctions": {
            "lagna_lord": _conjunctions_with(
                planets, (lagna_lord or {}).get("house"), exclude_name=lagna_lord_name
            ),
            "sixth_house": _conjunctions_with(planets, SIXTH_HOUSE),
            "eighth_house": _conjunctions_with(planets, EIGHTH_HOUSE),
            "twelfth_house": _conjunctions_with(planets, TWELFTH_HOUSE),
            "moon": _conjunctions_with(planets, (moon or {}).get("house"), exclude_name="Moon"),
            "saturn": _conjunctions_with(planets, (saturn or {}).get("house"), exclude_name="Saturn"),
        },
        "yogas": _active_yogas(kundali),
    }

    return context
