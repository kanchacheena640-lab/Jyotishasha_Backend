# services/current_saturn_resolver.py

"""
U4B.1 -- a narrow, thin abstraction boundary for "what sign is Saturn
currently in", built so new U4B consumers (Admin, eventually) never
call an ephemeris function directly, and so U4C can later correct the
underlying timezone/date-semantics issue in exactly ONE place instead
of at every call site.

==================================================================
SOURCE-SELECTION DECISION (U4B.1 Section 5/6 -- documented, not fixed)
==================================================================
Two current-Saturn sources exist in this codebase today:

  smart_transit_engine.get_planet_position_on(date_str, "Saturn")
      Used EXCLUSIVELY by services/sadhesati_report_generator.py (the
      one verified-correct, live Sade Sati product) today. Its "now" is
      acquired by the CALLER as `datetime.now()` -- a NAIVE, server-
      local-clock read with no timezone attached -- then this function
      blindly `pytz.timezone("Asia/Kolkata").localize(...)`s it, i.e.
      ASSUMES that naive value already represents IST civil time. If
      the host OS clock is not itself IST (e.g. a UTC-clocked Linux/
      cloud server), this silently misinterprets "now" by the clock's
      offset from IST. U4B.0 confirmed this is a real, narrow-impact
      risk (only visible on the rare day a genuine sign-ingress falls
      within that window) -- flagged for U4C, not fixed here.

  transit_engine.get_current_positions()
      Used by ~10+ other consumers (chat_engine, the Premium Generators,
      alerts, /api/transit/current). Its own "now" is acquired via
      `datetime.now(pytz.timezone("Asia/Kolkata"))` -- a TIMEZONE-AWARE
      read, safe regardless of the host OS clock's own timezone.
      Architecturally the "better" of the two.

DECISION: this resolver calls smart_transit_engine, NOT transit_engine,
for U4B.1. This is a deliberate CONSISTENCY choice, not an endorsement
of smart_transit_engine's own date-semantics: the two engines CAN
disagree about "today"/"now" near a timezone boundary (see above), and
therefore CAN disagree about which sidereal sign Saturn is currently in
on the rare day it is genuinely crossing a boundary. If this resolver
called transit_engine instead, a NEW Admin consumer could report a
DIFFERENT current Saturn sign -- and therefore a different Sade Sati
active/phase result -- than the SAME MOMENT'S live Sadhesati Report
product (which will keep calling smart_transit_engine regardless, per
this task's explicit "do not silently switch existing production
consumers" instruction). Preserving agreement with the existing,
already-verified-correct product takes priority over an isolated
"cleaner architecture" swap. U4C owns reconciling the two engines
(and their date-semantics) ONCE, for every consumer at the same time --
not piecemeal here.

This module is intentionally minimal: one function, one small result
shape. No caching, no new API surface beyond what U4B.2 will actually
need.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

CURRENT_SATURN_SOURCE = "smart_transit_engine"


@dataclass(frozen=True)
class CurrentSaturnResolution:
    saturn_sign: str
    resolved_at: datetime   # the exact "now" this resolution used -- diagnostic only
    source: str             # CURRENT_SATURN_SOURCE, for diagnostics/logging


def resolve_current_saturn_sign() -> CurrentSaturnResolution:
    """The ONE place a new (U4B+) consumer should ask "what sign is
    Saturn in right now" -- never smart_transit_engine/transit_engine
    directly. Reproduces the EXACT same "now" acquisition
    services/sadhesati_report_generator.py already uses
    (datetime.now().strftime("%Y-%m-%d %H:%M")), so a caller of this
    resolver and the live Sadhesati Report product agree on Saturn's
    sign at any given instant -- see the module docstring above for
    why that agreement is this task's priority, not a new/cleaner
    source.

    Call this ONCE per Admin request (or any other bulk operation) --
    Saturn's sign is the same for every user at a given moment, so
    there is never a reason to call it per-row (see U4B.1 Section 8/10
    and test_sadhesati_classifier.py's own N+1-shaped proof).

    Raises whatever smart_transit_engine.get_planet_position_on() itself
    raises on failure (e.g. a swisseph error) -- this function never
    swallows a resolution failure into a fabricated sign, per Section 9
    ("do NOT classify users as inactive" when Saturn cannot be
    resolved -- callers must see the failure, not a guessed value).
    """
    from smart_transit_engine import get_planet_position_on

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d %H:%M")
    position = get_planet_position_on(today_str, "Saturn")

    return CurrentSaturnResolution(
        saturn_sign=position["rashi"],
        resolved_at=now,
        source=CURRENT_SATURN_SOURCE,
    )
