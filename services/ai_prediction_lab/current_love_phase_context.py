"""
services/ai_prediction_lab/current_love_phase_context.py
-------------------------------------------------------------
Builds the "Current Love Phase" AI context -- the Lab's SECOND section,
built on top of the Relationship DNA (first section) output.

This module performs NO new astrology calculation. It only reuses:
- full_kundali_api.calculate_full_kundali()'s already-computed
  current_mahadasha / current_antardasha (unchanged, read directly)
- transit_engine.get_current_positions() for current transit
  sign/degree/motion (unchanged, read directly)
- modules/smartchat/chart_summarizer._rashi_to_house() to derive a
  transit's house from the natal lagna -- the exact reuse path
  identified during the backend audit, not a new house calculation
- full_kundali_api.get_nakshatra_pada() to derive a transit's nakshatra
  from the sign+degree transit_engine already returns -- again the
  exact reuse path identified during the audit
- the Relationship Birth Summary (context_builder.build_love_profile_context()'s
  output) for the already-derived 5th Lord / Venus / Mars facts --
  passed IN by the caller (see `love_context` parameter below) so it is
  generated exactly once per execution and never recomputed here

The only "new" logic here is a small, deterministic cross-reference of
values the backend already produced (is the current dasha lord one of
the love-relevant planets? is a transit sitting in the 5th house?) --
not a new astrology engine. Planet relationship-roles are fixed,
classical labels (the same category as the "Venus -- Karaka of Love &
Relationships" text already hardcoded in prompts/love_profile_v1.txt),
not something computed from this person's specific chart.
"""

from __future__ import annotations

from typing import Any, Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house
from services.ai_prediction_lab.next_phase_change import compute_next_phase_change_date

LOVE_TRANSIT_PLANETS = ["Jupiter", "Saturn", "Rahu", "Ketu"]
LOVE_HOUSE = 5

# Fixed, classical Vedic significations -- static labels, not computed
# from the birth data.
PLANET_RELATIONSHIP_ROLE = {
    "Jupiter": "growth, optimism and expansion of relationships",
    "Saturn": "commitment, responsibility and long-term stability",
    "Rahu": "intense desire and unconventional attraction",
    "Ketu": "detachment, release and completion of old patterns",
    # Added for Remedy For This Phase (Current Phase refinement). Moon is
    # deliberately NOT added to LOVE_TRANSIT_PLANETS above -- that list
    # also drives _score_relationship_phase()'s house-transit signal
    # count below, and Moon changes sign every ~2.25 days, so including
    # it there would silently change the existing phase-scoring
    # calculation (forbidden). Moon's transit is instead computed once,
    # separately, in build_current_love_phase_context() below, using the
    # exact same _transit_summary() helper -- exposed for the prompt only,
    # never fed into scoring.
    "Moon": "emotional mood and day-to-day openness in relationships",
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
        "relationship_role": PLANET_RELATIONSHIP_ROLE.get(planet_name, ""),
    }


def _score_relationship_phase(
    mahadasha_planet: Any,
    antardasha_planet: Any,
    love_context: Dict[str, Any],
    transits: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    love_names = {
        love_context.get("fifth_lord", {}).get("name"),
        (love_context.get("venus", {}) or {}).get("name"),
        (love_context.get("mars", {}) or {}).get("name"),
    }
    love_names.discard(None)

    signals: List[str] = []

    if mahadasha_planet in love_names:
        signals.append(
            f"Your current Mahadasha lord ({mahadasha_planet}) is one of your love/relationship significators."
        )
    if antardasha_planet in love_names:
        signals.append(
            f"Your current Antardasha lord ({antardasha_planet}) is one of your love/relationship significators."
        )
    for planet in LOVE_TRANSIT_PLANETS:
        if transits.get(planet, {}).get("house") == LOVE_HOUSE:
            signals.append(f"{planet} is currently transiting your 5th house of romance.")

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
        or ["No current dasha lord or transit is directly activating your love/relationship houses right now."],
    }


def build_current_love_phase_context(kundali: Dict[str, Any], love_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali(). `love_context` must be the
    Relationship Birth Summary already produced by
    context_builder.build_love_profile_context(kundali) for this same
    execution -- generated exactly once by the caller and passed in here,
    never recomputed by this function.
    """
    lagna_sign = kundali.get("lagna_sign")

    mahadasha = kundali.get("current_mahadasha") or {}
    antardasha = kundali.get("current_antardasha") or {}

    transits = {planet: _transit_summary(planet, lagna_sign) for planet in LOVE_TRANSIT_PLANETS}

    relationship_phase = _score_relationship_phase(
        mahadasha.get("mahadasha"),
        antardasha.get("planet"),
        love_context,
        transits,
    )

    # Moon, for Remedy For This Phase only -- computed AFTER scoring, via
    # the same _transit_summary() helper, so it can never influence
    # relationship_phase's level/confidence/reasons above (unchanged
    # calculation) while still being available to the prompt.
    transits["Moon"] = _transit_summary("Moon", lagna_sign)

    # Next Phase Change -- nearest of the Antardasha end date or the next
    # rashi transit of a LOVE_TRANSIT_PLANETS planet (Moon excluded; see
    # next_phase_change.py). Computed as a sibling field, never mutating
    # antardasha["end"] above, so compute_expires_at()'s cache-expiry
    # logic (LoveGenerator.compute_expires_at) is completely unaffected.
    next_phase_change_date = compute_next_phase_change_date(
        antardasha.get("end"), LOVE_TRANSIT_PLANETS,
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
        "relationship_phase": relationship_phase,
        "transits": transits,
        "next_phase_change_date": next_phase_change_date,
    }
