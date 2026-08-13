# services/ai_prediction_lab/current_health_timing_context.py

"""
services/ai_prediction_lab/current_health_timing_context.py
-------------------------------------------------------------
Builds the "Current Health Timing" AI context -- HEALTH's THIRD layer
(DNA -> CURRENT_PHASE -> CURRENT_TIMING). Mirrors
current_love_timing_context.py's exact pattern; see that module's
docstring for the isolation rationale and for why the natal foundation
lord's identity is read via a second call to the existing, unmodified
DNA-layer Lab function rather than by changing this function's
signature (HealthGenerator's call site stays unchanged). NOT a medical
assessment of any kind.

This module performs NO new astrology calculation -- see
current_love_timing_context.py's docstring for the reused backend
functions (identical here, using
services.ai_prediction_lab.health_context_builder.build_health_profile_context()
in place of the Love equivalent).

Tracks Moon, Sun, Mars -- HEALTH's already-established "fast-moving,
for Current Timing" planet set (unchanged from before;
current_health_phase_v1.txt already labels exactly these three planets
this way) -- plus which other planets currently share Moon's sign, and
the natal Lagna Lord's CURRENT transit position ("foundation" -- the
1st house = body/vitality/overall constitution, the closest health
analogue to Love's 5th-house identity house).
"""

from __future__ import annotations

from typing import Any, Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house
from services.ai_prediction_lab.health_context_builder import build_health_profile_context

HEALTH_TIMING_PLANETS = ["Moon", "Sun", "Mars"]


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
    target_rashi = (positions.get(planet_name) or {}).get("rashi")
    if not target_rashi:
        return []
    return [
        name for name, pos in positions.items()
        if name != planet_name and pos.get("rashi") == target_rashi
    ]


def build_current_health_timing_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- only `lagna_sign` is
    read from it directly (for house derivation).

    Returns HEALTH's fast-moving current transits (Moon, Sun, Mars),
    Moon's current conjunction planets (if any), and the natal Lagna
    Lord's CURRENT transit position (sign/house only) -- no Mahadasha,
    no Antardasha, no health_phase, no other permanent chart facts.
    """
    lagna_sign = kundali.get("lagna_sign")
    positions = get_current_positions().get("positions", {})

    result: Dict[str, Any] = {
        planet.lower(): _timing_transit_summary(planet, lagna_sign, positions)
        for planet in HEALTH_TIMING_PLANETS
    }
    result["moon_conjunctions"] = _conjunct_planets("Moon", positions)

    health_summary = build_health_profile_context(kundali)
    lagna_lord_name = (health_summary.get("lagna_lord") or {}).get("name")
    result["foundation_lord"] = (
        _timing_transit_summary(lagna_lord_name, lagna_sign, positions)
        if lagna_lord_name else {"sign": None, "house": None, "nakshatra": None, "motion": None}
    )

    return result
