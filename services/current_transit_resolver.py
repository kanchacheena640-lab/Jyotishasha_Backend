# services/current_transit_resolver.py

"""
U4C.3 -- the ONE place Admin (or any future consumer) asks "what sign
is each of the 9 canonical planets currently in", via the canonical
transit engine frozen by U4C.0-U4C.2B:

    transit_engine.get_current_positions()

Mirrors services/current_saturn_resolver.py's own minimal-abstraction
pattern exactly (one function, one small frozen result shape, no
caching, no new API surface) -- but deliberately calls transit_engine,
not smart_transit_engine, per U4C.3's explicit instruction ("Canonical
current positions: get_current_positions()"). transit_engine.py already
establishes SIDM_LAHIRI on the calling thread immediately before every
Swiss Ephemeris call it makes (U4C.2B) -- this module adds no new
ephemeris call of its own and never touches swisseph directly.

==================================================================
CONSISTENCY NOTE (U4C.3 Section 16 -- documented, not fixed)
==================================================================
services/current_saturn_resolver.py's own resolve_current_saturn_sign()
deliberately calls smart_transit_engine, not transit_engine, for
reasons documented in ITS OWN docstring (agreement with the live
Sadhesati Report product, which will keep using smart_transit_engine
regardless). This resolver's own "current Saturn" value can therefore,
in principle, differ from current_saturn_resolver's on the rare instant
Saturn is genuinely crossing a sign boundary -- both engines were
proven mathematically identical for the SAME explicit instant in
U4C.1's own audit, so any divergence in practice can only come from
the two resolvers being invoked at very slightly different moments
in time, not from a calculation difference.

An Admin request combining `saturn_house` (this module) with
`sade_sati_active`/`sade_sati_phase` (current_saturn_resolver) will
therefore call TWO independent Saturn resolutions -- documented and
verified to agree in practice (see test_admin_transit.py's own
same-Saturn-rashi proof), not merged into one. Reconciling the two
engines into a single shared resolution is explicitly out of scope for
U4C.3 -- it would mean changing current_saturn_resolver.py's own
documented source-selection decision, i.e. redesigning U4B, which this
task must not do.
"""

from __future__ import annotations

from dataclasses import dataclass

CURRENT_TRANSIT_SOURCE = "transit_engine"

# The exact 9 canonical transit bodies this whole Users module (U4C.3)
# ever reports on -- identical set to transit_engine.get_current_positions()'s
# own "positions" keys, never a superset/subset invented here.
TRACKED_PLANETS = ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Rahu", "Ketu")


@dataclass(frozen=True)
class CurrentTransitSnapshot:
    positions: dict   # {"Sun": {"rashi": ..., "degree": ..., "motion": ...}, ...} -- transit_engine.get_current_positions()'s own "positions" value, untouched
    resolved_at: str  # transit_engine's own "timestamp_ist" string, diagnostic only
    source: str       # CURRENT_TRANSIT_SOURCE, for diagnostics/logging

    def rashi(self, planet: str) -> str:
        return self.positions[planet]["rashi"]


def resolve_current_transit_snapshot() -> CurrentTransitSnapshot:
    """The ONE place Admin (U4C.3) asks "what sign is each planet in
    right now" -- never transit_engine/smart_transit_engine directly.

    Call this AT MOST ONCE per Admin list/detail request -- transit
    signs are the same for every user at a given moment, so there is
    never a reason to call it per-row or per-filter-dimension (see
    test_admin_transit.py's own N+1-shaped, exactly-once proof).

    Raises whatever transit_engine.get_current_positions() itself
    raises on failure -- never swallows a resolution failure into a
    fabricated sign; callers must surface the failure (U4C.3 Section 13
    -- a controlled 503, exactly like U4B's SadeSatiUnavailableError
    pattern), never silently return null/incorrect planetary state.
    """
    from transit_engine import get_current_positions

    result = get_current_positions()
    return CurrentTransitSnapshot(
        positions=result["positions"],
        resolved_at=result["timestamp_ist"],
        source=CURRENT_TRANSIT_SOURCE,
    )
