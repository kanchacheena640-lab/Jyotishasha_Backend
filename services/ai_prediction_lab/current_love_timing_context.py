# services/ai_prediction_lab/current_love_timing_context.py

"""
services/ai_prediction_lab/current_love_timing_context.py
-------------------------------------------------------------
Builds the "Current Love Timing" AI context -- LOVE's THIRD layer
(DNA -> CURRENT_PHASE -> CURRENT_TIMING). A short, immediate
continuation covering only the next 2-3 days.

Deliberately self-contained, mirroring daily_transit_context.py's own
isolation pattern: it has no import dependency on
current_love_phase_context.py, so a fast-changing daily data source
never gets coupled to the phase-level module. It composes the same
underlying backend functions independently, exactly as
daily_transit_context.py already does for DAILY_INSIGHT.

This module performs NO new astrology calculation. It only reuses:
- transit_engine.get_current_positions() for current transit
  sign/degree/motion (unchanged, read directly)
- modules/smartchat/chart_summarizer._rashi_to_house() to derive a
  transit's house from the natal lagna -- the same reuse path every
  other phase/timing context module already uses
- full_kundali_api.get_nakshatra_pada() to derive a transit's nakshatra
  from the sign+degree transit_engine already returns -- same reuse path
- services.ai_prediction_lab.context_builder.build_love_profile_context()
  -- the EXISTING, UNMODIFIED DNA-layer Lab function -- called a second
  time here (same as the generator already does for DNA) purely to
  read the natal 5th Lord's NAME (which planet it is). No natal fact is
  otherwise read or exposed; only that one planet's CURRENT transit
  position is computed and returned, via the exact same
  _timing_transit_summary() helper used for Moon/Venus/Mercury/Mars
  below. This keeps build_current_love_timing_context()'s own signature
  at just `(kundali)`, so LoveGenerator's existing call site is
  unchanged.

Tracks Moon, Venus, Mercury, and Mars -- LOVE's classical
relationship-relevant fast-moving planets (Venus = karaka of love,
Mars = karaka of passion, already used natally in
prompts/love_profile_v1.txt, now also tracked live here) -- plus which
other planets currently share Moon's sign (for internal reasoning only)
and the natal 5th Lord's current transit position ("foundation").

No permanent birth chart data is otherwise read or exposed by this
module -- only the identity (name) of the 5th Lord planet is read from
the natal chart, purely to know WHICH planet's current transit to look
up.
"""

from __future__ import annotations

from typing import Any, Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house
from services.ai_prediction_lab.context_builder import build_love_profile_context

LOVE_TIMING_PLANETS = ["Moon", "Venus", "Mercury", "Mars"]


def _timing_transit_summary(planet_name: str, lagna_sign: str, positions: Dict[str, Any]) -> Dict[str, Any]:
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
    }


def _conjunct_planets(planet_name: str, positions: Dict[str, Any]) -> List[str]:
    """Other planets currently sharing `planet_name`'s rashi -- a live
    conjunction, computed from the SAME get_current_positions() call
    already made for every other planet here (no extra engine call)."""
    target_rashi = (positions.get(planet_name) or {}).get("rashi")
    if not target_rashi:
        return []
    return [
        name for name, pos in positions.items()
        if name != planet_name and pos.get("rashi") == target_rashi
    ]


def build_current_love_timing_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- only `lagna_sign` is
    read from it (for house derivation); nothing else about this
    person's natal chart is read here directly (the 5th Lord's identity
    is read via build_love_profile_context(), not from `kundali`
    itself).

    Returns LOVE's fast-moving current transits (Moon, Venus, Mercury,
    Mars), Moon's current conjunction planets (if any), and the natal
    5th Lord's CURRENT transit position (sign/house only) -- no
    Mahadasha, no Antardasha, no relationship_phase, no other permanent
    chart facts.
    """
    lagna_sign = kundali.get("lagna_sign")
    positions = get_current_positions().get("positions", {})

    result: Dict[str, Any] = {
        planet.lower(): _timing_transit_summary(planet, lagna_sign, positions)
        for planet in LOVE_TIMING_PLANETS
    }
    result["moon_conjunctions"] = _conjunct_planets("Moon", positions)

    # Foundation lord -- the natal 5th Lord's CURRENT transit position.
    # build_love_profile_context() is the existing, unmodified DNA-layer
    # Lab function (the same one LoveGenerator already calls for DNA);
    # only the planet's NAME is read from its output, never any natal
    # sign/house/nakshatra fact.
    birth_summary = build_love_profile_context(kundali)
    fifth_lord_name = (birth_summary.get("fifth_lord") or {}).get("name")
    result["foundation_lord"] = (
        _timing_transit_summary(fifth_lord_name, lagna_sign, positions)
        if fifth_lord_name else {"sign": None, "house": None, "nakshatra": None, "motion": None}
    )

    return result
