# services/ai_prediction_lab/next_phase_change.py

"""
Computes the "Next Phase Change" date used by every segment's
CURRENT_PHASE prompt (the {antardasha_end} placeholder in
prompts/current_*_phase_v1.txt).

BUSINESS RULE (nearest-event, not Antardasha-only):
Next Phase Change is whichever occurs FIRST of --
  (a) the current Antardasha's end date, and
  (b) the next rashi (sign) transit of any of the segment's already
      -configured "major" transit planets -- the same *_TRANSIT_PLANETS
      list each current_*_phase_context.py already uses for phase
      scoring -- excluding Moon.

Moon is excluded here because it is not a "major" astrological event:
it changes rashi every ~2.25 days and every current_*_phase_v1.txt
prompt already treats it separately, as a fast-moving, Current-Timing
-only planet, never as one of the segment's phase-defining planets.

This module performs NO new astrology calculation. It only compares
dates already produced by the existing engines:
- the Antardasha end date already computed by
  full_kundali_api.calculate_full_kundali()
- transit_engine.get_next_12_rashi_segments() -- the same rashi-transit
  engine already imported by every current_*_phase_context.py file
  (get_current_positions() is that module's "now" half; this is its
  "next" half).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from transit_engine import get_next_12_rashi_segments

# Never a candidate for Next Phase Change -- see module docstring.
_EXCLUDED_FROM_MAJOR_TRANSIT = {"Moon"}


def _safe_parse(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def compute_next_phase_change_date(
    antardasha_end: Optional[str],
    relevant_planets: Iterable[str],
) -> Optional[str]:
    """
    Returns whichever comes first, as a "YYYY-MM-DD" string:
      - `antardasha_end` (the current Antardasha's end date), or
      - the nearest upcoming rashi-transit ("entering_date") of any
        planet in `relevant_planets` (Moon excluded regardless of
        whether the caller's list contains it).

    Returns None if no valid date could be determined at all -- callers
    fall back to their existing antardasha_end-only behaviour in that
    case, so an engine failure never breaks report generation.
    """
    candidates = []

    parsed_antardasha_end = _safe_parse(antardasha_end)
    if parsed_antardasha_end:
        candidates.append(parsed_antardasha_end)

    for planet in relevant_planets:
        if planet in _EXCLUDED_FROM_MAJOR_TRANSIT:
            continue
        try:
            events = get_next_12_rashi_segments(planet)
        except Exception:
            events = []
        if events:
            parsed = _safe_parse(events[0].get("entering_date"))
            if parsed:
                candidates.append(parsed)

    if not candidates:
        return None

    return min(candidates).strftime("%Y-%m-%d")
