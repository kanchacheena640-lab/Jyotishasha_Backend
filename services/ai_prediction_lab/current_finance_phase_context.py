"""
services/ai_prediction_lab/current_finance_phase_context.py
----------------------------------------------------------------
Builds the "Current Financial Phase" AI context -- the Finance segment's
SECOND section, built on top of the Financial DNA (first section)
output. Mirrors current_career_phase_context.py's exact pattern for the
CAREER segment.

This module performs NO new astrology calculation. It only reuses:
- full_kundali_api.calculate_full_kundali()'s already-computed
  current_mahadasha / current_antardasha (unchanged, read directly)
- transit_engine.get_current_positions() for current transit
  sign/degree/motion (unchanged, read directly)
- modules/smartchat/chart_summarizer._rashi_to_house() to derive a
  transit's house from the natal lagna -- the same reuse path
  current_love_phase_context.py / current_career_phase_context.py
  already use
- full_kundali_api.get_nakshatra_pada() to derive a transit's nakshatra
  from the sign+degree transit_engine already returns -- same reuse path

The only "new" logic here is a small, deterministic cross-reference of
values the backend already produced (is the current dasha lord one of
the finance-relevant planets? is a transit sitting in the 2nd or 11th
house of wealth/gains?) -- not a new astrology engine. Planet financial
significations are fixed, classical labels (the same category as
"Jupiter (Karaka of Wealth & Growth)" text in
prompts/finance_profile_v1.txt), not something computed from this
person's specific chart.
"""

from __future__ import annotations

from typing import Any, Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house
from services.ai_prediction_lab.next_phase_change import compute_next_phase_change_date

# Jupiter/Venus/Mercury/Saturn/Rahu -- the five finance-significator
# planets this segment's context is scoped to (see FINANCE CONTEXT
# spec). All five are tracked here (the slower-moving cadence); Moon/
# Mercury/Venus are re-tracked at daily cadence separately in
# finance_action_context.py.
FINANCE_TRANSIT_PLANETS = ["Jupiter", "Venus", "Mercury", "Saturn", "Rahu"]
WEALTH_HOUSE = 2  # Earned wealth, savings
GAINS_HOUSE = 11  # Income, gains, long-term rewards

# Fixed, classical Vedic significations -- static labels, not computed
# from the birth data.
PLANET_FINANCE_ROLE = {
    "Jupiter": "growth, abundance and long-term financial wisdom",
    "Venus": "comfort, lifestyle spending and material enjoyment",
    "Mercury": "transactions, calculations and day-to-day money decisions",
    "Saturn": "discipline, delay and long-term financial structure",
    "Rahu": "sudden gain, ambition and unconventional financial risk",
    # Added for Remedy For This Phase (Current Phase refinement). Moon is
    # deliberately NOT added to FINANCE_TRANSIT_PLANETS below -- that list
    # also drives _score_finance_phase()'s house-transit signal count, and
    # Moon changes sign every ~2.25 days, so including it there would
    # silently change the existing phase-scoring calculation (forbidden).
    # Moon's transit is instead computed once, separately, in
    # build_current_finance_phase_context() below, using the exact same
    # _transit_summary() helper -- exposed for the prompt only, never fed
    # into scoring.
    "Moon": "day-to-day mindset around spending and money decisions",
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
        "finance_role": PLANET_FINANCE_ROLE.get(planet_name, ""),
    }


def _score_finance_phase(
    mahadasha_planet: Any,
    antardasha_planet: Any,
    finance_context: Dict[str, Any],
    transits: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    finance_names = {
        finance_context.get("second_lord", {}).get("name"),
        finance_context.get("eleventh_lord", {}).get("name"),
        "Jupiter",
        "Venus",
        "Mercury",
        "Saturn",
        "Rahu",
    }
    finance_names.discard(None)

    signals: List[str] = []

    if mahadasha_planet in finance_names:
        signals.append(
            f"Your current Mahadasha lord ({mahadasha_planet}) is one of your financial significators."
        )
    if antardasha_planet in finance_names:
        signals.append(
            f"Your current Antardasha lord ({antardasha_planet}) is one of your financial significators."
        )
    for planet in FINANCE_TRANSIT_PLANETS:
        house = transits.get(planet, {}).get("house")
        if house == WEALTH_HOUSE:
            signals.append(f"{planet} is currently transiting your 2nd house of wealth.")
        elif house == GAINS_HOUSE:
            signals.append(f"{planet} is currently transiting your 11th house of gains.")

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
        or ["No current dasha lord or transit is directly activating your wealth or gains houses right now."],
    }


def build_current_finance_phase_context(kundali: Dict[str, Any], finance_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali(). `finance_context` must be
    the Finance Profile already produced by
    finance_context_builder.build_finance_profile_context(kundali) for
    this same execution -- generated exactly once by the caller and
    passed in here, never recomputed by this function.
    """
    lagna_sign = kundali.get("lagna_sign")

    mahadasha = kundali.get("current_mahadasha") or {}
    antardasha = kundali.get("current_antardasha") or {}

    transits = {planet: _transit_summary(planet, lagna_sign) for planet in FINANCE_TRANSIT_PLANETS}

    finance_phase = _score_finance_phase(
        mahadasha.get("mahadasha"),
        antardasha.get("planet"),
        finance_context,
        transits,
    )

    # Moon, for Remedy For This Phase only -- computed AFTER scoring, via
    # the same _transit_summary() helper, so it can never influence
    # finance_phase's level/confidence/reasons above (unchanged
    # calculation) while still being available to the prompt.
    transits["Moon"] = _transit_summary("Moon", lagna_sign)

    # Next Phase Change -- nearest of the Antardasha end date or the next
    # rashi transit of a FINANCE_TRANSIT_PLANETS planet (Moon excluded;
    # see next_phase_change.py). Computed as a sibling field, never
    # mutating antardasha["end"] above, so compute_expires_at()'s
    # cache-expiry logic (FinanceGenerator.compute_expires_at) is
    # completely unaffected.
    next_phase_change_date = compute_next_phase_change_date(
        antardasha.get("end"), FINANCE_TRANSIT_PLANETS,
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
        "finance_phase": finance_phase,
        "transits": transits,
        "next_phase_change_date": next_phase_change_date,
    }
