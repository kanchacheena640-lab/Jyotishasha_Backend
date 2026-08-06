"""
services/ai_prediction_lab/current_career_phase_context.py
-------------------------------------------------------------
Builds the "Current Career Phase" AI context -- the Career segment's
SECOND section, built on top of the Career DNA (first section) output.
Mirrors current_love_phase_context.py's exact pattern for the LOVE
segment.

This module performs NO new astrology calculation. It only reuses:
- full_kundali_api.calculate_full_kundali()'s already-computed
  current_mahadasha / current_antardasha (unchanged, read directly)
- transit_engine.get_current_positions() for current transit
  sign/degree/motion (unchanged, read directly)
- modules/smartchat/chart_summarizer._rashi_to_house() to derive a
  transit's house from the natal lagna -- the same reuse path
  current_love_phase_context.py already uses
- full_kundali_api.get_nakshatra_pada() to derive a transit's nakshatra
  from the sign+degree transit_engine already returns -- same reuse path

The only "new" logic here is a small, deterministic cross-reference of
values the backend already produced (is the current dasha lord one of
the career-relevant planets? is a transit sitting in the 10th house?) --
not a new astrology engine. Planet career significations are fixed,
classical labels (the same category as "Sun (Karaka of Authority)" text
in prompts/career_profile_v1.txt), not something computed from this
person's specific chart.
"""

from __future__ import annotations

from typing import Any, Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house

# Sun/Saturn/Jupiter/Mercury -- the four career-significator planets
# this segment's context is scoped to (see CAREER CONTEXT spec); Rahu/
# Ketu are deliberately out of scope here, unlike LOVE's transit set,
# since they were never named as career factors for this segment.
CAREER_TRANSIT_PLANETS = ["Sun", "Saturn", "Jupiter", "Mercury"]
CAREER_HOUSE = 10  # Career, status, profession

# Fixed, classical Vedic significations -- static labels, not computed
# from the birth data.
PLANET_CAREER_ROLE = {
    "Sun": "authority, leadership and personal recognition at work",
    "Saturn": "discipline, structure and long-term career stability",
    "Jupiter": "growth, opportunity and expansion of career prospects",
    "Mercury": "skill, communication and decision-making at work",
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
        "career_role": PLANET_CAREER_ROLE.get(planet_name, ""),
    }


def _score_career_phase(
    mahadasha_planet: Any,
    antardasha_planet: Any,
    career_context: Dict[str, Any],
    transits: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    career_names = {
        career_context.get("tenth_lord", {}).get("name"),
        "Sun",
        "Saturn",
        "Mercury",
        "Jupiter",
    }
    career_names.discard(None)

    signals: List[str] = []

    if mahadasha_planet in career_names:
        signals.append(
            f"Your current Mahadasha lord ({mahadasha_planet}) is one of your career significators."
        )
    if antardasha_planet in career_names:
        signals.append(
            f"Your current Antardasha lord ({antardasha_planet}) is one of your career significators."
        )
    for planet in CAREER_TRANSIT_PLANETS:
        if transits.get(planet, {}).get("house") == CAREER_HOUSE:
            signals.append(f"{planet} is currently transiting your 10th house of career.")

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
        or ["No current dasha lord or transit is directly activating your career house right now."],
    }


def build_current_career_phase_context(kundali: Dict[str, Any], career_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali(). `career_context` must be
    the Career Profile already produced by
    career_context_builder.build_career_profile_context(kundali) for
    this same execution -- generated exactly once by the caller and
    passed in here, never recomputed by this function.
    """
    lagna_sign = kundali.get("lagna_sign")

    mahadasha = kundali.get("current_mahadasha") or {}
    antardasha = kundali.get("current_antardasha") or {}

    transits = {planet: _transit_summary(planet, lagna_sign) for planet in CAREER_TRANSIT_PLANETS}

    career_phase = _score_career_phase(
        mahadasha.get("mahadasha"),
        antardasha.get("planet"),
        career_context,
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
        "career_phase": career_phase,
        "transits": transits,
    }
