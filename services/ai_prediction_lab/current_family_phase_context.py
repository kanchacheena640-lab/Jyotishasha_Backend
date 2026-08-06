"""
services/ai_prediction_lab/current_family_phase_context.py
----------------------------------------------------------------
Builds the "Current Family Phase" AI context -- the Family segment's
SECOND section, built on top of the Family DNA (first section) output.
Mirrors current_health_phase_context.py's exact pattern for the HEALTH
segment.

This module performs NO new astrology calculation. It only reuses:
- full_kundali_api.calculate_full_kundali()'s already-computed
  current_mahadasha / current_antardasha (unchanged, read directly)
- transit_engine.get_current_positions() for current transit
  sign/degree/motion (unchanged, read directly)
- modules/smartchat/chart_summarizer._rashi_to_house() to derive a
  transit's house from the natal lagna -- the same reuse path every
  other segment's phase context already uses
- full_kundali_api.get_nakshatra_pada() to derive a transit's nakshatra
  from the sign+degree transit_engine already returns -- same reuse path

The only "new" logic here is a small, deterministic cross-reference of
values the backend already produced (is the current dasha lord one of
the family-relevant planets? is a transit sitting in the 2nd or 4th
house?) -- not a new astrology engine, and never a claim about a real
family member. Planet family significations are fixed, classical labels
(the same category as "Moon (Karaka of Mother & Emotional Bonding)"
text in prompts/family_profile_v1.txt), not something computed from
this person's specific chart.
"""

from __future__ import annotations

from typing import Any, Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house

# Moon/Jupiter/Venus/Saturn -- the four family-significator planets this
# segment's context is scoped to (see FAMILY CONTEXT spec). All four are
# tracked here (the slower-moving cadence); Moon/Venus are re-tracked at
# daily cadence separately in family_action_context.py.
FAMILY_TRANSIT_PLANETS = ["Moon", "Jupiter", "Venus", "Saturn"]
FAMILY_HOUSE = 2  # Family, immediate household
HOME_HOUSE = 4  # Home, mother, emotional foundation

# Fixed, classical Vedic significations -- static labels, not computed
# from the birth data.
PLANET_FAMILY_ROLE = {
    "Moon": "mother, mood at home and emotional bonding",
    "Jupiter": "family wisdom, growth and shared values",
    "Venus": "harmony, affection and domestic comfort",
    "Saturn": "duty, structure and long-term commitment within the family",
}


def _transit_summary(planet_name: str, lagna_sign: str) -> Dict[str, Any]:
    positions = get_current_positions().get("positions", {})
    p = positions.get(planet_name) or {}

    rashi = p.get("rashi")
    degree = p.get("degree")
    motion = p.get("motion")

    house = _rashi_to_house(lagna_sign, rashi) if lagna_sign and rashi else None

    nakshatra = None
    if rashi in RASHIS and degree is not None:
        full_degree = RASHIS.index(rashi) * 30 + degree
        nakshatra, _pada = get_nakshatra_pada(full_degree)

    return {
        "sign": rashi,
        "house": house,
        "nakshatra": nakshatra,
        "motion": motion,
        "family_role": PLANET_FAMILY_ROLE.get(planet_name, ""),
    }


def _score_family_phase(
    mahadasha_planet: Any,
    antardasha_planet: Any,
    family_context: Dict[str, Any],
    transits: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    family_names = {
        family_context.get("second_lord", {}).get("name"),
        family_context.get("fourth_lord", {}).get("name"),
        "Moon",
        "Jupiter",
        "Venus",
        "Saturn",
    }
    family_names.discard(None)

    signals: List[str] = []

    if mahadasha_planet in family_names:
        signals.append(
            f"Your current Mahadasha lord ({mahadasha_planet}) is one of your family significators."
        )
    if antardasha_planet in family_names:
        signals.append(
            f"Your current Antardasha lord ({antardasha_planet}) is one of your family significators."
        )
    for planet in FAMILY_TRANSIT_PLANETS:
        house = transits.get(planet, {}).get("house")
        if house == FAMILY_HOUSE:
            signals.append(f"{planet} is currently transiting your 2nd house of family.")
        elif house == HOME_HOUSE:
            signals.append(f"{planet} is currently transiting your 4th house of home.")

    if len(signals) >= 2:
        level, confidence = "Active", "High"
    elif len(signals) == 1:
        level, confidence = "Building", "Medium"
    else:
        level, confidence = "Quiet", "Low"

    return {
        "level": level,
        "confidence": confidence,
        "reasons": signals
        or ["No current dasha lord or transit is directly activating your family or home houses right now."],
    }


def build_current_family_phase_context(kundali: Dict[str, Any], family_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali(). `family_context` must be
    the Family Profile already produced by
    family_context_builder.build_family_profile_context(kundali) for
    this same execution -- generated exactly once by the caller and
    passed in here, never recomputed by this function.
    """
    lagna_sign = kundali.get("lagna_sign")

    mahadasha = kundali.get("current_mahadasha") or {}
    antardasha = kundali.get("current_antardasha") or {}

    transits = {planet: _transit_summary(planet, lagna_sign) for planet in FAMILY_TRANSIT_PLANETS}

    family_phase = _score_family_phase(
        mahadasha.get("mahadasha"),
        antardasha.get("planet"),
        family_context,
        transits,
    )

    return {
        "mahadasha": {
            "planet": mahadasha.get("mahadasha"),
            "start": mahadasha.get("start"),
            "end": mahadasha.get("end"),
        },
        "antardasha": {
            "planet": antardasha.get("planet"),
            "start": antardasha.get("start"),
            "end": antardasha.get("end"),
        },
        "family_phase": family_phase,
        "transits": transits,
    }
