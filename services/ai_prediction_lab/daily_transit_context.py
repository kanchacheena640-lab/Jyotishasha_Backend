"""
services/ai_prediction_lab/daily_transit_context.py
-------------------------------------------------------------
Foundation for Layer 3 (Daily Love Prediction) -- a dedicated, isolated
context object carrying ONLY the fast-moving current transits (Moon,
Mercury, Venus, Mars).

Deliberately kept separate from current_love_phase_context.py (Layer 2,
Mahadasha/Antardasha/Jupiter/Saturn/Rahu/Ketu): Layer 2 tracks slow,
long-period influences; Layer 3 tracks day-to-day movement. Merging them
would couple a daily-changing data source to a phase that is meant to
stay stable for weeks/months, so this module has no import dependency on
current_love_phase_context.py at all -- it composes the same underlying
backend functions independently.

No new astrology calculation is performed here. It only reuses:
- transit_engine.get_current_positions() for current transit
  sign/degree/motion (unchanged, read directly)
- modules/smartchat/chart_summarizer._rashi_to_house() to derive a
  transit's house from the natal lagna -- the same reuse path already
  used for Layer 2
- full_kundali_api.get_nakshatra_pada() to derive a transit's nakshatra
  from the sign+degree transit_engine already returns -- same reuse path

Returns structured facts only -- no interpretation, no scoring, no
static role labels. Prompt 3 does not exist yet; this is only the data
foundation for it.
"""

from __future__ import annotations

from typing import Any, Dict

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house

DAILY_TRANSIT_PLANETS = ["Moon", "Mercury", "Venus", "Mars"]


def _daily_transit_summary(planet_name: str, lagna_sign: str) -> Dict[str, Any]:
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
    }


def build_daily_transit_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- only `lagna_sign` is
    read from it (for house derivation); nothing about this person's
    natal chart is otherwise touched.

    Returns ONLY the four fast-moving current transits -- no Mahadasha,
    no Antardasha, no Jupiter/Saturn/Rahu/Ketu, no relationship_phase.
    """
    lagna_sign = kundali.get("lagna_sign")

    return {
        planet.lower(): _daily_transit_summary(planet, lagna_sign)
        for planet in DAILY_TRANSIT_PLANETS
    }
