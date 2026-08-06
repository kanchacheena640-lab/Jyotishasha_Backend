# modules/alerts/future_planet_data.py

"""
Future Planet Data -- Phase 3's day-parameterized generalization of
planet_data.py's "today only" snapshot builder. Computes the same
PlanetSnapshot shape for ANY given day (today, tomorrow, or several days
ahead), which the Planning Window layer needs to simulate the next N
days rather than just this instant.

Does not modify planet_data.py or anything else in Phase 1/2 -- it
REUSES planet_data.py's own `_snapshot_for()` (unchanged) by feeding it
a `positions` dict computed for an arbitrary day instead of "now". That
positions dict is built with the exact same Swiss Ephemeris calling
convention transit_engine.py's own `get_current_positions()` and
`_planet_rashi_on_day()`/`_planet_motion_on_day()` already use (Lahiri
sidereal, `swe.calc_ut`) -- reusing transit_engine's own constants/
helpers (`RASHIS`, `NAME_TO_ID`, `_to_julday_utc`,
`_rashi_from_sidereal_lon`) rather than reimplementing them, so this is
the same existing astrology engine, just called for a different moment
than "right now". No new astrology calculation is introduced.
"""

from __future__ import annotations

import datetime
from typing import Dict

import swisseph as swe

from transit_engine import NAME_TO_ID, RASHIS, _rashi_from_sidereal_lon, _to_julday_utc

from modules.alerts.event_models import PlanetSnapshot
from modules.alerts.planet_data import TRACKED_PLANETS, _snapshot_for


def _positions_on_day(day_ist: datetime.datetime) -> Dict[str, Dict]:
    """Same computation as transit_engine.get_current_positions(), for
    an arbitrary `day_ist` instead of "now" -- Sun/Moon/Mercury/Venus/
    Mars/Jupiter/Saturn/Rahu/Ketu's sidereal sign, degree, and motion on
    that day."""
    jd = _to_julday_utc(day_ist)
    ay = swe.get_ayanamsa_ut(jd)

    out: Dict[str, Dict] = {}
    for name, pid in NAME_TO_ID.items():
        res, _ = swe.calc_ut(jd, pid)
        lon = res[0]
        speed = res[3] if len(res) > 3 else 0.0
        sid_lon = (lon - ay) % 360
        out[name] = {
            "rashi": _rashi_from_sidereal_lon(sid_lon),
            "degree": round(sid_lon % 30, 2),
            "motion": "Retrograde" if speed < 0 else "Direct",
        }

    rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
    ketu_sid = (rahu_sid + 180.0) % 360
    out["Ketu"] = {
        "rashi": _rashi_from_sidereal_lon(ketu_sid),
        "degree": round(ketu_sid % 30, 2),
        "motion": "Retrograde",
    }

    return out


def build_planet_snapshots_for_day(lagna_sign: str, day_ist: datetime.datetime) -> Dict[str, PlanetSnapshot]:
    """Same return shape as planet_data.build_planet_snapshots(), for
    `day_ist` instead of the current moment. `day_ist` should be
    midnight IST for the target day (see planning_window_engine.py) --
    the Planning Window works at daily granularity, not intraday."""
    positions = _positions_on_day(day_ist)
    return {
        planet: _snapshot_for(planet, lagna_sign, positions)
        for planet in TRACKED_PLANETS
    }
