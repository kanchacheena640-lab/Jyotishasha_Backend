# modules/alerts/planet_data.py

"""
Planet Data -- the first stage of the Micro Event Engine's pipeline.
Builds the current PlanetSnapshot for every tracked planet, resolved
against the natal Lagna.

This reuses only the existing, lower-level astrology engine primitives
already shared across the whole backend -- transit_engine.py (current
positions), modules/smartchat/chart_summarizer.py (sign -> house from
Lagna), full_kundali_api.py (nakshatra/pada from a sidereal degree) --
exactly the same primitives services/ai_prediction_lab/*_context.py
already reuses for the Premium Generators' own transit reading. It does
NOT import from services/ai_prediction_lab or any modules.ai_report_engine/
modules.love/modules.career/modules.finance/modules.health/modules.family
module -- the Alerts Engine owns its own copy of this thin adapter
logic to stay completely independent, exactly the same reasoning
already documented in modules/career/career_generator.py et al. for why
their own `_load_birth_details`/`_read_upstream_text` aren't shared
either. No new astrology calculation is introduced here.
"""

from __future__ import annotations

from typing import Dict, List

from full_kundali_api import get_nakshatra_pada
from transit_engine import RASHIS, get_current_positions
from modules.smartchat.chart_summarizer import _rashi_to_house

from modules.alerts.event_models import PlanetSnapshot

# The full set of planets the Micro Event Engine's Phase 1 catalog
# draws on (see config/micro_events.json). Rahu/Ketu are included
# because several caution-type events (Unexpected Expense, Foreign
# Travel Opportunity) key off them classically; both are tracked by
# transit_engine.get_current_positions() already.
TRACKED_PLANETS: List[str] = [
    "Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu",
]


def _snapshot_for(planet_name: str, lagna_sign: str, positions: Dict) -> PlanetSnapshot:
    p = positions.get(planet_name) or {}

    rashi = p.get("rashi")
    degree = p.get("degree")
    motion = p.get("motion")

    house = _rashi_to_house(lagna_sign, rashi) if lagna_sign and rashi else None

    nakshatra = None
    if rashi in RASHIS and degree is not None:
        full_degree = RASHIS.index(rashi) * 30 + degree
        nakshatra, _pada = get_nakshatra_pada(full_degree)

    return PlanetSnapshot(
        planet=planet_name,
        sign=rashi,
        house=house,
        nakshatra=nakshatra,
        motion=motion,
    )


def build_planet_snapshots(lagna_sign: str) -> Dict[str, PlanetSnapshot]:
    """Returns the current PlanetSnapshot for every planet in
    TRACKED_PLANETS, keyed by planet name. `lagna_sign` is the only
    natal fact this stage needs -- everything else is today's current
    transit, read fresh on every call (Micro Events are, by definition,
    about the current moment, not a cached birth-chart fact)."""
    positions = get_current_positions().get("positions", {})
    return {
        planet: _snapshot_for(planet, lagna_sign, positions)
        for planet in TRACKED_PLANETS
    }
