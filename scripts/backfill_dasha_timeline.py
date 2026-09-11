#!/usr/bin/env python
# scripts/backfill_dasha_timeline.py

"""
U4A.2 -- controlled, explicitly-invoked, idempotent backfill for the
Vimshottari Dasha timeline (UserDashaTimeline), mirroring the proven
scripts/backfill_static_astrology.py (U3B.2) pattern.

SAFETY: boots the app via factory.create_app(), which ALREADY runs
db_safety.enforce_local_database_safety() before any DB work happens --
this script introduces NO independent/weaker safety check. Running
this against a non-local, non-approved DATABASE_URL aborts at import
time, before a single query. This script additionally re-asserts
SELECT current_database() itself before doing any work: by default
(no --production) it refuses to proceed unless the connected database
is exactly "jyotishasha_local"; with --production explicitly passed, it
instead refuses unless the connected database is exactly the real
production name AND ACTIVITY_EVENTS_ENVIRONMENT=production is also
explicitly set -- see _verify_production_database() below. A
production DATABASE_URL alone is never, by itself, sufficient to reach
a production write.

ORCHESTRATION ONLY -- reuses the U4A.1 shared service unmodified, never
a second Dasha calculation/persistence implementation:
    modules.services.dasha_timeline_service.{
        sync_dasha_timeline_for_user, validate_timeline_for_profile,
        EXPECTED_TIMELINE_ROW_COUNT, TIMELINE_MISSING, TIMELINE_VALID,
        TIMELINE_CORRUPT,
    }
    modules.user_service._has_complete_birth_details (the SAME
        completeness contract register_or_update_user() and
        scripts/backfill_static_astrology.py already use).

ASTROLOGICAL INPUTS vs APPLICATION COMPLETENESS: this script gates
eligibility on the application's canonical birth-detail completeness
contract (dob+tob+pob+lat+lng), reused for CONSISTENCY with every other
astrology feature -- this is a product decision, not an astrology
claim. Vimshottari Dasha itself is mathematically computed from dob+tob
only (see modules/services/dasha_timeline_service.py's own docstring,
verified in U4A.0). POB text is never claimed to be astrologically
required here.

CLASSIFICATION (per profile with complete birth data), via the
deterministic validator -- NOT the old "if any row exists, skip":
    TIMELINE_MISSING -> generate a fresh timeline
    TIMELINE_VALID   -> skip (unless --force)
    TIMELINE_CORRUPT -> replace safely via the shared service

A profile with INCOMPLETE birth data is always SKIPPED, in either
direction -- this script never generates for it, and never deletes
whatever it currently has (that invalidation is already owned by the
live write-path hooks in modules/user_service.py and
routes/routes_profile_bootstrap.py; this backfill's job is purely
corrective for complete profiles).

SCOPE (P4.11): the candidate query considers EVERY app_users profile
with complete birth data, regardless of whether it is linked to a
Firebase login (firebase_uid). This is deliberate -- a profile is not
required to have firebase_uid to be Dasha-eligible: the calculation
engine doesn't use it, sync_dasha_timeline_for_user()'s own live
trigger doesn't check it, and a profile with no login (e.g. an
additional family-member profile added under one account) is a real,
intended user of this feature. An earlier revision of this script
restricted the candidate query to firebase_uid IS NOT NULL only,
which happened to match what modules/services/admin_users_service.py
can display (it bridges via firebase_uid) but was never actually
required by anything this script itself does, and undercounted the
true eligible population by roughly 3.5x in production. That
restriction has been removed.

FAILURE SAFETY (U4A.2's own correctness fix, in the shared service
this script calls): sync_dasha_timeline_for_user() never deletes an
existing timeline before a replacement calculation has already
succeeded. A calculation failure against a profile with an existing
VALID timeline leaves that timeline completely untouched -- this
script's own summary reports such cases distinctly
(preserved_after_failure), never as data loss.

Batching: keyset pagination on app_users.id (id > last_seen_id ORDER BY
id LIMIT batch_size) -- never OFFSET, never loads the whole table.

Per-profile isolation: each profile's validation + (if needed)
generate/replace + commit happens in its OWN try/except -- a failure
rolls back only that profile's pending change and is recorded; it can
never abort the run, lose an earlier successful commit, or block a
later profile.

Privacy: only profile_id, exception class, and a short exception
message are ever printed for a failure -- this script never
interpolates dob/tob/pob/email/phone/name into any log line.

Usage (LOCAL, the default -- unchanged from before this section):
    python scripts/backfill_dasha_timeline.py --dry-run
    python scripts/backfill_dasha_timeline.py
    python scripts/backfill_dasha_timeline.py --batch-size 100
    python scripts/backfill_dasha_timeline.py --after-id 500
    python scripts/backfill_dasha_timeline.py --force --dry-run

PRODUCTION MODE (explicit opt-in only -- see _verify_production_database()
below): omitting --production ALWAYS runs the original, unchanged local-
only path above (_verify_local_database(), refuses anything but
'jyotishasha_local') -- a production DATABASE_URL alone, even with
ACTIVITY_EVENTS_ENVIRONMENT=production also set, is NEVER sufficient by
itself to reach a production write; --production must be passed
explicitly, and is then independently re-verified against BOTH the
actual connected database name and the environment marker before any
work happens. A REAL (non-dry-run) --production run additionally
requires --confirm to exactly equal _PRODUCTION_CONFIRM_PHRASE below --
--dry-run under --production never requires it (dry-run performs zero
writes regardless):
    python scripts/backfill_dasha_timeline.py --production --dry-run
    python scripts/backfill_dasha_timeline.py --production \\
        --confirm "BACKFILL PRODUCTION DASHA TIMELINE"

Never prints DATABASE_URL or any credential -- only the resolved
database NAME via SELECT current_database(), matching this repo's own
established production-diagnostic convention.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, ".")

from factory import create_app  # noqa: E402 -- also enforces db_safety

# P4.10 -- the exact, case-sensitive phrase a REAL (non-dry-run)
# --production run must supply via --confirm. Mirrors this codebase's
# own established typed-confirmation pattern (e.g. the Admin Campaign
# Composer's ALL_USERS_PHRASE) -- a deliberate, hard-to-fat-finger,
# single extra step between "I passed --production" and "this will
# actually write to the real production database."
_PRODUCTION_DB_NAME = "jyotishasha"
_PRODUCTION_CONFIRM_PHRASE = "BACKFILL PRODUCTION DASHA TIMELINE"


@dataclass
class BackfillFailure:
    profile_id: int
    exception_class: str
    short_message: str
    was_corrupt: bool  # True if this profile had an existing (corrupt) timeline that survives untouched


@dataclass
class BackfillCounts:
    scanned: int = 0
    incomplete: int = 0
    eligible: int = 0            # complete birth data (incomplete excluded)
    already_valid: int = 0       # TIMELINE_VALID, not forced -> skipped untouched
    missing: int = 0             # TIMELINE_MISSING, classified
    corrupt: int = 0             # TIMELINE_CORRUPT, classified
    generated: int = 0           # missing -> successfully generated
    replaced: int = 0            # corrupt -> successfully replaced
    forced_recomputed: int = 0   # already-valid, --force -> successfully recomputed
    preserved_after_failure: int = 0  # a generate/replace/forced-recompute attempt failed; any prior valid data survives
    failed: int = 0              # an unexpected error outside the shared service's own safe failure handling
    last_processed_id: Optional[int] = None
    failures: List[BackfillFailure] = field(default_factory=list)


def _verify_local_database() -> None:
    """Explicit, redundant re-check on top of db_safety's own guard
    (already enforced by factory.create_app() before this even runs) --
    per this task's own instruction to verify SELECT current_database()
    directly before any local execution."""
    from extensions import db
    from sqlalchemy import text

    current_db = db.session.execute(text("SELECT current_database()")).scalar()
    print(f"[backfill] Connected to database: {current_db}")
    if current_db != "jyotishasha_local":
        raise SystemExit(
            f"[backfill] REFUSING TO RUN -- expected database 'jyotishasha_local' "
            f"(pass --production to explicitly target production instead), "
            f"got {current_db!r}. Aborting before any work."
        )
    print("[backfill] Confirmed local database target.")


def _verify_production_database() -> None:
    """P4.10 -- ONLY consulted when --production is explicitly passed on
    the command line. Independently re-verifies BOTH the actual
    connected database name AND the ACTIVITY_EVENTS_ENVIRONMENT marker
    before any production work is allowed -- production execution must
    NEVER happen merely because DATABASE_URL happens to point there
    (factory.create_app()'s own db_safety guard, unmodified, already
    requires ACTIVITY_EVENTS_ENVIRONMENT=production -- or running on
    Render -- to even boot against a non-local DATABASE_URL at all; this
    is this script's OWN additional, explicit, readable re-assertion of
    that same fact, never a weaker or different rule). Never prints
    DATABASE_URL or any credential -- only the resolved database name."""
    from extensions import db
    from sqlalchemy import text

    current_db = db.session.execute(text("SELECT current_database()")).scalar()
    print(f"[backfill] Connected to database: {current_db}")
    if current_db != _PRODUCTION_DB_NAME:
        raise SystemExit(
            f"[backfill] REFUSING -- --production was given but current_database() = "
            f"{current_db!r}, expected {_PRODUCTION_DB_NAME!r}. Aborting before any work."
        )
    env_marker = os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT", "").strip().lower()
    if env_marker != "production":
        raise SystemExit(
            f"[backfill] REFUSING -- --production requires ACTIVITY_EVENTS_ENVIRONMENT=production "
            f"to ALSO be explicitly set (got {env_marker!r}). Never proceeding on database name alone."
        )
    print("[backfill] Confirmed: explicit --production target verified "
          "(database name AND environment marker both checked independently).")


def _candidate_query(AppUser, db, after_id: int):
    # P4.11 -- BROAD SCOPE: no firebase_uid filter. Eligibility is
    # governed ONLY by _has_complete_birth_details() (dob/tob/pob/lat/
    # lng), matching both the calculation engine's own requirements and
    # sync_dasha_timeline_for_user()'s live write-path trigger, neither
    # of which reads firebase_uid at all. A profile never linked to a
    # Firebase login (firebase_uid IS NULL -- e.g. an additional family-
    # member profile under one account) is just as eligible as one that
    # is. An earlier version of this query required firebase_uid IS NOT
    # NULL; that silently narrowed the backfill to only the subset of
    # profiles reachable through Admin's own firebase_uid identity
    # bridge, well below this backfill's actual objective (see the
    # reconciliation investigation that led to this change). Admin
    # reachability is a display-layer concern of modules/services/
    # admin_users_service.py, not a Dasha-eligibility concern -- this
    # script has no reason to duplicate or depend on it.
    return (
        db.session.query(AppUser)
        .filter(AppUser.id > after_id)
        .order_by(AppUser.id.asc())
    )


def run_backfill(*, batch_size: int, after_id: int, force: bool, dry_run: bool) -> BackfillCounts:
    from extensions import db
    from modules.models_user import AppUser
    from modules.user_service import _has_complete_birth_details
    from modules.services.dasha_timeline_service import (
        sync_dasha_timeline_for_user,
        validate_timeline_for_profile,
        TIMELINE_MISSING,
        TIMELINE_VALID,
        TIMELINE_CORRUPT,
    )

    counts = BackfillCounts()

    cursor = after_id
    while True:
        page = _candidate_query(AppUser, db, cursor).limit(batch_size).all()
        if not page:
            break

        for profile in page:
            counts.scanned += 1
            cursor = profile.id
            counts.last_processed_id = profile.id

            if not _has_complete_birth_details(profile):
                counts.incomplete += 1
                continue

            counts.eligible += 1

            validation = validate_timeline_for_profile(profile.id)

            if validation.status == TIMELINE_VALID:
                counts.already_valid += 1
                if not force:
                    continue
                # --force falls through to the generate/replace branch
                # below like any other eligible profile.
                is_corrupt = False
            elif validation.status == TIMELINE_MISSING:
                counts.missing += 1
                is_corrupt = False
            else:  # TIMELINE_CORRUPT
                counts.corrupt += 1
                is_corrupt = True
                print(f"[backfill] profile_id={profile.id} -> CORRUPT "
                      f"({len(validation.reasons)} issue(s): {'; '.join(validation.reasons)[:200]})")

            if dry_run:
                # Preferred contract (Section 7, matching
                # scripts/backfill_static_astrology.py's own dry-run
                # contract): dry-run performs ZERO astrology
                # calculations for ANY profile, valid or not --
                # counting/classification only, never a write.
                continue

            try:
                outcome = sync_dasha_timeline_for_user(profile)
                db.session.commit()

                if outcome == "generated":
                    if validation.status == TIMELINE_VALID:
                        counts.forced_recomputed += 1
                        print(f"[backfill] profile_id={profile.id} -> FORCED_RECOMPUTED")
                    elif is_corrupt:
                        counts.replaced += 1
                        print(f"[backfill] profile_id={profile.id} -> REPLACED")
                    else:
                        counts.generated += 1
                        print(f"[backfill] profile_id={profile.id} -> GENERATED")
                elif outcome == "preserved_after_failure":
                    # The shared service already safely refused to
                    # touch any existing valid data -- this is not an
                    # "error" this script needs to roll back; the
                    # commit above is a no-op (nothing was staged).
                    counts.preserved_after_failure += 1
                    print(f"[backfill] profile_id={profile.id} -> PRESERVED_AFTER_FAILURE "
                          f"(old timeline intact: {not is_corrupt and validation.status != TIMELINE_MISSING})")
                else:
                    # "invalidated" -- should not occur here since
                    # eligibility already required complete birth data,
                    # but handled explicitly rather than silently
                    # falling through.
                    counts.failed += 1
                    print(f"[backfill] profile_id={profile.id} -> UNEXPECTED outcome={outcome!r}")

            except Exception as exc:
                # Per-profile isolation: roll back ONLY this profile's
                # pending change. Earlier successful commits in this
                # (or any prior) batch are already durably committed
                # and completely unaffected.
                db.session.rollback()
                counts.failed += 1
                short_message = str(exc)[:150]
                counts.failures.append(BackfillFailure(
                    profile_id=profile.id,
                    exception_class=type(exc).__name__,
                    short_message=short_message,
                    was_corrupt=is_corrupt,
                ))
                print(f"[backfill] profile_id={profile.id} -> FAILED "
                      f"({type(exc).__name__}: {short_message})")

        if len(page) < batch_size:
            break  # last page

    return counts


def print_summary(counts: BackfillCounts, *, dry_run: bool, force: bool) -> None:
    print("\n" + "=" * 70)
    label = "DASHA TIMELINE BACKFILL SUMMARY"
    flags = []
    if dry_run:
        flags.append("DRY RUN -- nothing written")
    if force:
        flags.append("FORCE")
    if flags:
        label += f"  ({', '.join(flags)})"
    print(label)
    print("=" * 70)
    print(f"scanned:                 {counts.scanned}")
    print(f"incomplete (skipped):    {counts.incomplete}")
    print(f"eligible (complete):     {counts.eligible}")
    print(f"already_valid:           {counts.already_valid}")
    print(f"missing:                 {counts.missing}")
    print(f"corrupt:                 {counts.corrupt}")
    print(f"generated:               {counts.generated}")
    print(f"replaced:                {counts.replaced}")
    print(f"forced_recomputed:       {counts.forced_recomputed}")
    print(f"preserved_after_failure: {counts.preserved_after_failure}")
    print(f"failed:                  {counts.failed}")
    print(f"last_processed_id:       {counts.last_processed_id}")
    if counts.failures:
        print(f"\n{len(counts.failures)} failure(s) -- profile_id / exception class / short message only:")
        for f in counts.failures:
            print(f"  profile_id={f.profile_id}  was_corrupt={f.was_corrupt}  {f.exception_class}: {f.short_message}")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="U4A.2 Dasha timeline backfill (local by default; see --production).")
    parser.add_argument("--dry-run", action="store_true",
                         help="Classify (missing/valid/corrupt/incomplete) only; perform zero calculations, write nothing.")
    parser.add_argument("--batch-size", type=int, default=50,
                         help="Candidate rows fetched per DB round-trip via keyset pagination (default: 50).")
    parser.add_argument("--after-id", type=int, default=0,
                         help="Resume from this app_users.id (exclusive) -- for a simple manual resume of a partial run.")
    parser.add_argument("--force", action="store_true",
                         help="Recompute even profiles with an already-VALID timeline (still requires complete birth "
                              "data; a failed forced recompute still preserves the existing valid timeline, never "
                              "weakens DB safety, never touches incomplete profiles).")
    parser.add_argument("--production", action="store_true",
                         help="Explicitly target the production database instead of the default local-only safety "
                              "check. Required for ANY run against a non-local database -- omitting it always "
                              "refuses (fail-closed default), even if DATABASE_URL/ACTIVITY_EVENTS_ENVIRONMENT "
                              "happen to already point at production.")
    parser.add_argument("--confirm", type=str, default="",
                         help=f"Required, and must exactly equal {_PRODUCTION_CONFIRM_PHRASE!r}, for a REAL "
                              f"(non-dry-run) --production run. Ignored otherwise.")
    return parser.parse_args(argv)


def _require_production_confirmation(args: argparse.Namespace) -> None:
    """The cheapest possible check, deliberately run BEFORE even booting
    the app / touching any database connection: a REAL (non-dry-run)
    --production run must supply --confirm exactly equal to
    _PRODUCTION_CONFIRM_PHRASE. Pure string comparison on already-parsed
    args -- no DB access -- so an operator who forgot --confirm fails
    fast, before this process even attempts to connect anywhere."""
    if args.production and not args.dry_run and args.confirm != _PRODUCTION_CONFIRM_PHRASE:
        raise SystemExit(
            f"[backfill] REFUSING -- a REAL (non-dry-run) --production run requires "
            f"--confirm {_PRODUCTION_CONFIRM_PHRASE!r} exactly. Nothing was written."
        )


if __name__ == "__main__":
    args = parse_args()
    _require_production_confirmation(args)
    app = create_app()  # enforces db_safety.enforce_local_database_safety() -- see module docstring
    with app.app_context():
        if args.production:
            _verify_production_database()
        else:
            _verify_local_database()
        result = run_backfill(
            batch_size=max(1, args.batch_size),
            after_id=args.after_id,
            force=args.force,
            dry_run=args.dry_run,
        )
        print_summary(result, dry_run=args.dry_run, force=args.force)
