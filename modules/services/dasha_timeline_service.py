# modules/services/dasha_timeline_service.py

"""
U4A.1 -- the ONE authoritative service for building and persisting a
profile's Vimshottari Dasha timeline (UserDashaTimeline rows).

This is an ORCHESTRATION layer only. It reuses, unmodified, the exact
astrology functions U4A.0 verified correct:
    full_kundali_api.get_moon_longitude_lahiri()
    full_kundali_api.calculate_vimshottari_dasha()
It does NOT reimplement Vimshottari math, does NOT touch the 27
Nakshatras / 9-lord sequence / Mahadasha years / proportional
Antardasha formula, and does NOT call full_kundali_api.calculate_full_
kundali() (the expensive, all-planet/yoga/shadbala pipeline) -- Dasha's
own inputs (dob, tob) are cheap enough on their own (see the
ASTROLOGICAL INPUTS note below) that this service is fully decoupled
from, and does not need to piggyback on, the separate static-astrology
recalculation that also happens on a birth-data change (see
modules/user_service.py::_recalculate_or_invalidate_static_astrology).
Keeping the two independent means a Dasha resync can never be blocked
by, or accidentally coupled to, a full-Kundali failure or vice versa.

ASTROLOGICAL INPUTS vs APPLICATION COMPLETENESS (U4A.0 audit, kept
explicit here so this distinction is never blurred by future edits):
    Vimshottari Dasha is mathematically computed from ONLY dob + tob
    (via the natal Moon's sidereal longitude). Latitude/longitude are
    accepted by get_moon_longitude_lahiri() for signature symmetry with
    the rest of the engine but are NOT used in its body (geocentric
    Moon longitude does not depend on the observer's location). POB
    (place name text) is never read by any Dasha function at all.
    This service nonetheless gates on
    modules.user_service._has_complete_birth_details() (dob+tob+pob+
    lat+lng) -- reused, not reinvented, purely for CONSISTENCY with the
    same "is this profile astrology-ready" bar every other feature
    (static astrology, /api/profile/completeness) already uses. This is
    an application-level product decision, not an astrology claim: it
    must never be read as "POB/lat/lng are mathematically required for
    Dasha" -- they are not.

TRANSACTION CONTRACT (U4A.1 Section 9):
    Every function in this module that mutates the database (`delete`,
    `db.session.add`) NEVER calls db.session.commit() or
    db.session.rollback() itself. The delete-old + insert-new pair for
    one profile is staged into the CALLER's own existing session/
    transaction, so it commits or rolls back atomically together with
    whatever else that caller is already doing (matching
    modules/user_service.py::register_or_update_user()'s single
    db.session.commit() at the end, and
    routes/routes_profile_bootstrap.py's own single commit). This is
    what guarantees a profile can never be left with zero rows after a
    failed replacement, a partial 81-row set, or old+new rows
    coexisting -- the whole delete+insert pair either lands in the same
    commit as the rest of the write, or none of it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, TypedDict

from extensions import db
from modules.models_user import AppUser, UserDashaTimeline

# Reused, not duplicated -- the SAME completeness contract static
# astrology and /api/profile/completeness already use. A local import
# inside the functions below (not at module top) would also work, but
# a top-level import here is safe: modules/user_service.py only reaches
# into THIS module via a local (in-function) import of
# sync_dasha_timeline_for_user, never at its own module top, so there
# is no import cycle.
from modules.user_service import _has_complete_birth_details

# Structural fact, not a "version" -- U4A's own architecture decision
# explicitly rejected a calculated_at/version column for this table
# (see U4A Section 9): the full lifetime timeline, once correctly
# generated, never goes stale from time passing, only from a birth-data
# change already handled by full delete+replace. This constant exists
# only so tests/callers can assert row-count invariants by name rather
# than a bare magic number.
EXPECTED_TIMELINE_ROW_COUNT = 81


class DashaTimelineRow(TypedDict):
    mahadasha: str
    antardasha: str
    start_date: "datetime.date"
    end_date: "datetime.date"


def build_dasha_timeline_rows(user: AppUser) -> List[DashaTimelineRow]:
    """Pure computation, no DB access -- given a profile with complete
    birth data, returns exactly EXPECTED_TIMELINE_ROW_COUNT (81) plain
    dicts (mahadasha, antardasha, start_date, end_date as real `date`
    objects, not strings), flattened from
    full_kundali_api.calculate_vimshottari_dasha()'s own 9-mahadasha/
    9-antardasha-each nested return shape -- exactly the same flatten
    services/dasha_db_filler.py's inner loop already did, extracted
    here as the ONE place that logic lives now.

    Raises whatever full_kundali_api's own functions raise (malformed
    dob/tob, swisseph errors, etc.) -- callers decide how to handle a
    failure (see sync_dasha_timeline_for_user below); this function
    itself never swallows an error into a fabricated empty result.
    """
    from full_kundali_api import calculate_vimshottari_dasha, get_moon_longitude_lahiri

    moon_deg = get_moon_longitude_lahiri(user.dob, user.tob, user.lat, user.lng)

    birth_date = datetime.strptime(f"{user.dob} {user.tob}", "%Y-%m-%d %H:%M")

    mahadashas = calculate_vimshottari_dasha(moon_deg, birth_date)

    rows: List[DashaTimelineRow] = []
    for md in mahadashas:
        for ad in md["antardashas"]:
            rows.append({
                "mahadasha": md["mahadasha"],
                "antardasha": ad["planet"],
                "start_date": datetime.strptime(ad["start"], "%Y-%m-%d").date(),
                "end_date": datetime.strptime(ad["end"], "%Y-%m-%d").date(),
            })
    return rows


def _delete_existing_timeline(profile_id: int) -> None:
    """Staged in the caller's session -- not committed here (see module
    docstring's TRANSACTION CONTRACT)."""
    UserDashaTimeline.query.filter_by(user_id=profile_id).delete(synchronize_session=False)


def sync_dasha_timeline_for_user(user: AppUser) -> str:
    """The ONE entry point every birth-data write path should call,
    ALWAYS gated by the caller on its own "did birth data actually
    change" check (this function itself is unconditional -- it does not
    re-derive whether anything changed, exactly mirroring
    _recalculate_or_invalidate_static_astrology()'s own contract).

    Behavior (U4A.1 Section 5/6, corrected by U4A.2 -- see below):
      - Incomplete birth data (_has_complete_birth_details() false):
        delete any existing rows, insert nothing. Returns "invalidated".
      - Complete birth data, calculation succeeds: delete any existing
        rows, then insert a freshly computed set of
        EXPECTED_TIMELINE_ROW_COUNT rows, all staged in the SAME
        session -- never a commit in between, so a profile is never
        observably left with zero rows just because this function is
        mid-execution. Returns "generated".
      - Complete birth data, calculation FAILS (e.g. a transient
        swisseph error, or structurally-present but unparseable dob/
        tob): U4A.2 CORRECTNESS FIX -- the existing timeline, if any,
        is NEVER touched. U4A.1's original version deleted the old
        timeline BEFORE attempting recalculation, which meant a
        transient/runtime failure on a profile that already had a
        perfectly valid timeline would permanently destroy it, having
        generated nothing to replace it. build_dasha_timeline_rows() is
        a pure function with no DB access (verified -- it only calls
        swisseph-backed astrology functions), so it is called FIRST,
        entirely before any DB mutation is even staged; only a
        SUCCESSFUL result ever reaches the delete-then-insert step
        below. Returns "preserved_after_failure" -- deliberately not
        reusing "invalidated_after_failure" (U4A.1's name for this
        outcome): nothing is invalidated any more, the old timeline (if
        any existed) survives completely untouched.

    Never calls db.session.commit()/rollback() -- see module docstring.
    """
    if not _has_complete_birth_details(user):
        _delete_existing_timeline(user.id)
        return "invalidated"

    try:
        rows = build_dasha_timeline_rows(user)
    except Exception as exc:
        print(f"⚠️ Dasha timeline generation failed for firebase_uid="
              f"{user.firebase_uid!r}: {exc}")
        return "preserved_after_failure"

    _delete_existing_timeline(user.id)
    for row in rows:
        db.session.add(UserDashaTimeline(
            user_id=user.id,
            mahadasha=row["mahadasha"],
            antardasha=row["antardasha"],
            start_date=row["start_date"],
            end_date=row["end_date"],
        ))

    return "generated"


# ======================================================================
# U4A.2 -- deterministic timeline validation. Added here (not inside
# scripts/backfill_dasha_timeline.py) because "is this profile's
# persisted timeline healthy" is a Dasha-timeline concern, not a
# backfill-specific one -- any future caller (a health-check route, a
# monitoring script) should reuse this exact function rather than a
# second hand-rolled copy of these invariants.
#
# Replaces the old, weak "if any row exists, skip" test (U4A.1's own
# services/dasha_db_filler.py, before its U4A.1 thin-wrapper refactor)
# with the actual invariants U4A.0 proved a correctly generated
# timeline must satisfy:
#   - exactly EXPECTED_TIMELINE_ROW_COUNT (81) rows
#   - all 81 (mahadasha, antardasha) pairs distinct
#   - chronological continuity: sorted by start_date, every adjacent
#     pair of periods satisfies previous.end_date == next.start_date
#     (U4A.0's proof: periods TOUCH, never overlap, never gap)
#   - the half-open [start, end) current-period lookup returns exactly
#     one row for an arbitrary date known to fall inside the timeline's
#     own coverage window
#
# Deliberately does NOT check start_date >= AppUser.dob -- U4A.0 proved
# the first Mahadasha's synthetic start (and therefore its early
# Antardashas) can legitimately predate birth. A row with
# start_date < dob is NOT evidence of corruption and must never be
# classified as such.
# ======================================================================

TIMELINE_MISSING = "missing"
TIMELINE_VALID = "valid"
TIMELINE_CORRUPT = "corrupt"


@dataclass(frozen=True)
class TimelineValidationResult:
    status: str  # TIMELINE_MISSING | TIMELINE_VALID | TIMELINE_CORRUPT
    row_count: int
    reasons: List[str] = field(default_factory=list)  # non-empty only when status == TIMELINE_CORRUPT


def validate_timeline_for_profile(profile_id: int) -> TimelineValidationResult:
    """Read-only -- issues no writes, no deletes, no commits. Fetches
    every UserDashaTimeline row for this profile ONCE and checks it
    against every invariant above."""
    rows = (
        UserDashaTimeline.query
        .filter_by(user_id=profile_id)
        .order_by(UserDashaTimeline.start_date)
        .all()
    )

    if not rows:
        return TimelineValidationResult(status=TIMELINE_MISSING, row_count=0)

    reasons: List[str] = []

    if len(rows) != EXPECTED_TIMELINE_ROW_COUNT:
        reasons.append(f"expected {EXPECTED_TIMELINE_ROW_COUNT} rows, found {len(rows)}")

    pairs = [(r.mahadasha, r.antardasha) for r in rows]
    if len(set(pairs)) != len(pairs):
        reasons.append(f"duplicate (mahadasha,antardasha) pairs present ({len(pairs)} rows, {len(set(pairs))} unique)")

    for i in range(len(rows) - 1):
        prev_end, next_start = rows[i].end_date, rows[i + 1].start_date
        if prev_end != next_start:
            kind = "overlap" if prev_end > next_start else "gap"
            reasons.append(
                f"{kind} between row {i} (ends {prev_end}) and row {i + 1} "
                f"(starts {next_start})"
            )

    # Half-open current-period spot check -- pick a date safely inside
    # the timeline's own coverage (a day into the LAST row's own
    # window, guaranteed to exist and be unambiguous for a structurally
    # sound timeline) and confirm exactly one row claims it.
    probe_date = rows[-1].start_date
    current_matches = [r for r in rows if r.start_date <= probe_date < r.end_date]
    if len(current_matches) != 1:
        reasons.append(
            f"half-open current-period lookup for {probe_date} matched "
            f"{len(current_matches)} rows, expected exactly 1"
        )

    if reasons:
        return TimelineValidationResult(status=TIMELINE_CORRUPT, row_count=len(rows), reasons=reasons)

    return TimelineValidationResult(status=TIMELINE_VALID, row_count=len(rows))
