"""
services/ai_prediction_lab/current_health_phase_context.py
----------------------------------------------------------------
Builds the "Current Health Phase" AI context -- the Health segment's
SECOND section, built on top of the Health DNA (first section) output.
Mirrors current_finance_phase_context.py's exact pattern for the
FINANCE segment.

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
the health-relevant planets? is a transit sitting in the 6th, 8th, or
12th house?) -- not a new astrology engine, and NOT a medical
assessment of any kind. Planet health significations are fixed,
classical labels (the same category as "Mars (Karaka of Energy &
Vitality)" text in prompts/health_profile_v1.txt), not something
computed from this person's specific chart, and never a diagnosis.
"""

from __future__ import annotations

from typing import Any, Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house

# Moon/Sun/Mars/Saturn/Jupiter -- the five health-significator planets
# this segment's context is scoped to (see HEALTH CONTEXT spec). All
# five are tracked here (the slower-moving cadence); Moon/Sun/Mars are
# re-tracked at daily cadence separately in health_action_context.py.
HEALTH_TRANSIT_PLANETS = ["Moon", "Sun", "Mars", "Saturn", "Jupiter"]
DAILY_HEALTH_HOUSE = 6  # Routines, minor resistance
CHRONIC_HOUSE = 8  # Chronic/hidden conditions, resilience
RECOVERY_HOUSE = 12  # Rest, recovery, isolation

# Fixed, classical Vedic significations -- static labels, not computed
# from the birth data, and never a medical claim.
PLANET_HEALTH_ROLE = {
    "Moon": "mind, mood and emotional steadiness",
    "Sun": "overall vitality and energy levels",
    "Mars": "physical energy, drive and resilience",
    "Saturn": "endurance, routine and long-term stamina",
    "Jupiter": "recovery, immunity and overall sense of wellbeing",
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
        "health_role": PLANET_HEALTH_ROLE.get(planet_name, ""),
    }


def _score_health_phase(
    mahadasha_planet: Any,
    antardasha_planet: Any,
    health_context: Dict[str, Any],
    transits: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    health_names = {
        health_context.get("lagna_lord", {}).get("name"),
        health_context.get("sixth_lord", {}).get("name"),
        "Moon",
        "Sun",
        "Mars",
        "Saturn",
        "Jupiter",
    }
    health_names.discard(None)

    signals: List[str] = []

    if mahadasha_planet in health_names:
        signals.append(
            f"Your current Mahadasha lord ({mahadasha_planet}) is one of your health significators."
        )
    if antardasha_planet in health_names:
        signals.append(
            f"Your current Antardasha lord ({antardasha_planet}) is one of your health significators."
        )
    for planet in HEALTH_TRANSIT_PLANETS:
        house = transits.get(planet, {}).get("house")
        if house == DAILY_HEALTH_HOUSE:
            signals.append(f"{planet} is currently transiting your 6th house of daily wellbeing.")
        elif house == CHRONIC_HOUSE:
            signals.append(f"{planet} is currently transiting your 8th house of resilience.")
        elif house == RECOVERY_HOUSE:
            signals.append(f"{planet} is currently transiting your 12th house of rest and recovery.")

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
        or ["No current dasha lord or transit is directly activating your wellbeing houses right now."],
    }


def build_current_health_phase_context(kundali: Dict[str, Any], health_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali(). `health_context` must be
    the Health Profile already produced by
    health_context_builder.build_health_profile_context(kundali) for
    this same execution -- generated exactly once by the caller and
    passed in here, never recomputed by this function.
    """
    lagna_sign = kundali.get("lagna_sign")

    mahadasha = kundali.get("current_mahadasha") or {}
    antardasha = kundali.get("current_antardasha") or {}

    transits = {planet: _transit_summary(planet, lagna_sign) for planet in HEALTH_TRANSIT_PLANETS}

    health_phase = _score_health_phase(
        mahadasha.get("mahadasha"),
        antardasha.get("planet"),
        health_context,
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
        "health_phase": health_phase,
        "transits": transits,
    }
