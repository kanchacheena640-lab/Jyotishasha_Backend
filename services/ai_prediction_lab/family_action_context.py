"""
services/ai_prediction_lab/family_action_context.py
-------------------------------------------------------------
Foundation for the Family segment's third layer (Practical Family
Guidance) -- a dedicated, isolated context object carrying ONLY the
fast-moving current transits relevant to short-term family interactions
(Moon, Venus). Mirrors health_action_context.py's exact pattern for the
HEALTH segment.

Deliberately kept separate from current_family_phase_context.py (slower
Mahadasha/Antardasha/Jupiter/Saturn influences): that module tracks
slow, long-period influences; this one tracks day-to-day movement. This
module has no import dependency on current_family_phase_context.py at
all -- it composes the same underlying backend functions independently.

Only two planets, not more: of FAMILY CONTEXT's four named planets
(Moon, Jupiter, Venus, Saturn), Jupiter/Saturn are slow movers already
tracked at phase cadence in current_family_phase_context.py -- Moon and
Venus are the only ones that move fast enough to matter at a 24-48 hour
cadence, so no planet outside the task's named list is introduced here.

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

FAMILY_ACTION_PLANETS = ["Moon", "Venus"]


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


def build_family_action_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- only `lagna_sign` is
    read from it (for house derivation); nothing about this person's
    natal chart is otherwise touched.

    Returns ONLY the two fast-moving current transits -- no Mahadasha,
    no Antardasha, no Jupiter/Saturn, no family_phase.
    """
    lagna_sign = kundali.get("lagna_sign")

    return {
        planet.lower(): _action_transit_summary(planet, lagna_sign)
        for planet in FAMILY_ACTION_PLANETS
    }
