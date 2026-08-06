"""
services/ai_prediction_lab/finance_action_context.py
-------------------------------------------------------------
Foundation for the Finance segment's third layer (Practical Action
Guidance) -- a dedicated, isolated context object carrying ONLY the
fast-moving current transits relevant to short-term financial action
(Moon, Mercury, Venus). Mirrors career_action_context.py's exact
pattern for the CAREER segment.

Deliberately kept separate from current_finance_phase_context.py
(slower Mahadasha/Antardasha/Jupiter/Saturn/Rahu influences): that
module tracks slow, long-period influences; this one tracks day-to-day
movement. This module has no import dependency on
current_finance_phase_context.py at all -- it composes the same
underlying backend functions independently.

Only three planets, not four: of FINANCE CONTEXT's five named planets
(Jupiter, Venus, Mercury, Saturn, Rahu), Jupiter/Saturn/Rahu are slow
movers already tracked at phase cadence in
current_finance_phase_context.py -- Venus and Mercury are the only ones
that move fast enough to matter at a 24-48 hour cadence, so Moon (the
universal fast mover every other segment's action layer already
tracks) is added alongside them rather than inventing a fourth
finance-specific fast planet the task never named.

No new astrology calculation is performed here. It only reuses:
- transit_engine.get_current_positions() for current transit
  sign/degree/motion (unchanged, read directly)
- modules/smartchat/chart_summarizer._rashi_to_house() to derive a
  transit's house from the natal lagna
- full_kundali_api.get_nakshatra_pada() to derive a transit's nakshatra
  from the sign+degree transit_engine already returns

Returns structured facts only -- no interpretation, no scoring, no
static role labels.
"""

from __future__ import annotations

from typing import Any, Dict

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house

FINANCE_ACTION_PLANETS = ["Moon", "Mercury", "Venus"]


def _action_transit_summary(planet_name: str, lagna_sign: str) -> Dict[str, Any]:
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


def build_finance_action_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- only `lagna_sign` is
    read from it (for house derivation); nothing about this person's
    natal chart is otherwise touched.

    Returns ONLY the three fast-moving current transits -- no
    Mahadasha, no Antardasha, no Jupiter/Saturn/Rahu, no finance_phase.
    """
    lagna_sign = kundali.get("lagna_sign")

    return {
        planet.lower(): _action_transit_summary(planet, lagna_sign)
        for planet in FINANCE_ACTION_PLANETS
    }
