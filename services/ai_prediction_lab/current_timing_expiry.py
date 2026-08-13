# services/ai_prediction_lab/current_timing_expiry.py

"""
Computes the cache expiry for the CURRENT_TIMING report type.

BUSINESS RULE: expires_at is the EARLIEST of --
  (a) the next rashi (sign) transit of any of the segment's own
      "fast-moving" planets -- the exact same planet set each segment's
      existing CURRENT_PHASE prompt (current_*_phase_v1.txt) already
      labels "(fast-moving, for Current Timing)" in its own "Current
      Timing (Next 2-3 Days)" section (reused verbatim below, not
      reinvented). Every one of these sets includes Moon, so a Moon
      sign change is inherently one of the candidates compared here --
      there is no separate "Moon change" branch.
  (b) a hard maximum of 24 hours from generation time.

Panchang is NOT used as an input by any current_*_timing_context.py
module in this implementation (see those modules' docstrings for the
reasoning), so the Panchang-change trigger this report type's spec
allows for is correctly omitted here -- the spec itself only requires
it "ONLY if Panchang is actually used."

This module performs NO new astrology calculation. It reuses
transit_engine.get_next_12_rashi_segments() -- the exact same
rashi-transit engine services/ai_prediction_lab/next_phase_change.py
already uses for CURRENT_PHASE's "Next Phase Change" date.

Precision note (shared with next_phase_change.py, not new here):
get_next_12_rashi_segments() returns a DATE ("YYYY-MM-DD"), not a
timestamp, so a transit landing "tomorrow" always compares as earlier
than "24 hours from now at HH:MM:SS" even if the real transit occurs
later in that day than the 24-hour mark. This can only make
CURRENT_TIMING regenerate a few hours EARLIER than the strict 24-hour
cap, never later/staler -- the same safe-direction rounding
next_phase_change.py already relies on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from transit_engine import get_next_12_rashi_segments

MAX_EXPIRY_HOURS = 24

# The exact "fast-moving, for Current Timing" planet set each segment's
# existing CURRENT_PHASE prompt already uses for its own Current Timing
# section -- see prompts/current_{segment}_phase_v1.txt's "CURRENT
# PLANETARY INFLUENCES" block for the source of truth this mirrors.
FAST_TIMING_PLANETS = {
    "LOVE": ["Moon"],
    "CAREER": ["Sun", "Mercury", "Moon"],
    "FINANCE": ["Venus", "Mercury", "Moon"],
    "HEALTH": ["Moon", "Sun", "Mars"],
    "FAMILY": ["Moon", "Venus"],
}


def _safe_parse(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def compute_current_timing_expiry(
    segment: str,
    generated_at: Optional[datetime] = None,
) -> datetime:
    """
    Returns the expiry datetime for a CURRENT_TIMING report for
    `segment` -- the earlier of a 24-hour cap from `generated_at`
    (defaults to now, UTC) and the nearest upcoming rashi-transit of any
    planet in that segment's FAST_TIMING_PLANETS set. Always returns a
    concrete datetime (never None) -- there is always at least the
    24-hour cap as a candidate, so this report type never depends on
    ReportLifecycleManager's generic report_type-only fallback.
    """
    generated_at = generated_at or datetime.utcnow()
    candidates = [generated_at + timedelta(hours=MAX_EXPIRY_HOURS)]

    for planet in FAST_TIMING_PLANETS.get(segment, ["Moon"]):
        try:
            events = get_next_12_rashi_segments(planet)
        except Exception:
            events = []
        if events:
            parsed = _safe_parse(events[0].get("entering_date"))
            if parsed:
                candidates.append(parsed)

    return min(candidates)
