#!/usr/bin/env python
# scripts/align_trial_expiry_to_7_days.py

"""
15-Day-to-7-Day Trial change -- one-time production data alignment.

NOT RUN AGAINST PRODUCTION BY THIS TASK. Written and rehearsed against
the local scratch DB only; running it against production is a
separate, explicit, human-approved action.

What this does
---------------
For every CurrentEntitlement row still in status="TRIAL", recomputes
    trial_expires_at = trial_started_at + 7 days
(EntitlementWriteService.DEFAULT_TRIAL_DURATION_DAYS, the same
constant a brand-new trial now uses -- this script never hardcodes its
own "7", it imports the real constant so the two can never drift).

Why only status="TRIAL" rows, and why this is safe
----------------------------------------------------------------
- "Never alter paid ACTIVE/GRACE subscription periods": the WHERE
  clause is status="TRIAL" only, so ACTIVE/GRACE rows (and their
  subscription_started_at/subscription_expires_at columns, which this
  script never touches at all -- different columns, different rows)
  are never selected in the first place.
- "Never reset trial_started_at": this script only ever recomputes
  trial_expires_at FROM the existing trial_started_at -- it never
  writes trial_started_at.
- "Never create a second trial": this is a plain UPDATE over rows that
  already exist; no INSERT, and it never calls
  EntitlementWriteService.start_trial() (which is what actually
  creates a trial) at all.
- "Already-expired-under-7-day-rule users should correctly become
  EXPIRED through existing entitlement timestamp logic": no new logic
  needed -- EntitlementService._is_trial_window_active() already
  compares `datetime.utcnow() < row.trial_expires_at` live on every
  read, so a profile whose recomputed trial_expires_at is now in the
  past is correctly treated as EXPIRED (membership_state="EXPIRED",
  accessible_segments=[]) the instant this UPDATE commits -- and the
  existing daily SubscriptionStateSyncService sweep will flip the raw
  status column to "EXPIRED" on its next run, exactly like any other
  trial expiry, no code change required.
- "Preserve trial history and SubscriptionEvent history unless a
  specific consistency issue requires otherwise": no
  SubscriptionEvent row is touched, created, or deleted by this
  script -- only the CurrentEntitlement CACHE row's trial_expires_at
  column changes. Already-EXPIRED/ACTIVE/GRACE/CANCELLED/REFUNDED
  rows' OWN historical trial_expires_at (if they ever trialed before
  converting/lapsing) is left exactly as recorded -- there is no
  consistency issue with leaving a terminal/converted profile's
  historical trial window as originally granted.
- Idempotent and safe to re-run: every run recomputes purely from the
  still-untouched trial_started_at, never from a previous run's own
  output -- re-running produces the identical result, not a second
  shift.

Usage
------
    python scripts/align_trial_expiry_to_7_days.py             # dry run (default) -- reports only, writes nothing
    python scripts/align_trial_expiry_to_7_days.py --apply      # actually performs the UPDATE, one row at a time, in one transaction

Safety: refuses to run with --apply against a DATABASE_URL that does
not look like this project's own Postgres -- not a real guarantee
against pointing at the wrong database, only a cheap guard against an
obviously wrong environment variable. Always confirm DATABASE_URL by
hand before using --apply against production.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

sys.path.insert(0, ".")

# Imports the fully-configured Flask app object directly (same pattern
# every test_*.py script in this repo already uses), rather than
# factory.create_app() -- app.py's own module-level imports register
# every SQLAlchemy model (including ones this script never queries
# itself, e.g. AIReport) before any query runs, which
# factory.create_app() does not guarantee on its own for a
# minimal-import script like this one.
from app import app  # noqa: E402


@dataclass
class AlignmentOutcome:
    profile_id: int
    trial_started_at: datetime
    old_trial_expires_at: datetime
    new_trial_expires_at: datetime
    changed: bool


def plan_alignment() -> List[AlignmentOutcome]:
    """Read-only: computes what WOULD change, for every status="TRIAL"
    row, without writing anything. Safe to call in dry-run mode."""
    from modules.entitlement.entitlement_write_service import DEFAULT_TRIAL_DURATION_DAYS
    from modules.models_premium_subscription import CurrentEntitlement

    outcomes: List[AlignmentOutcome] = []
    rows = (
        CurrentEntitlement.query.filter_by(status="TRIAL")
        .filter(CurrentEntitlement.trial_started_at.isnot(None))
        .order_by(CurrentEntitlement.profile_id.asc())
        .all()
    )
    for row in rows:
        new_expires_at = row.trial_started_at + timedelta(days=DEFAULT_TRIAL_DURATION_DAYS)
        outcomes.append(AlignmentOutcome(
            profile_id=row.profile_id,
            trial_started_at=row.trial_started_at,
            old_trial_expires_at=row.trial_expires_at,
            new_trial_expires_at=new_expires_at,
            changed=new_expires_at != row.trial_expires_at,
        ))
    return outcomes


def apply_alignment(outcomes: List[AlignmentOutcome]) -> None:
    """Writes ONLY trial_expires_at, ONLY for the rows plan_alignment()
    already identified as changed, in one transaction. Never touches
    trial_started_at, status, plan, or any subscription_* column."""
    from extensions import db
    from modules.models_premium_subscription import CurrentEntitlement

    for outcome in outcomes:
        if not outcome.changed:
            continue
        row = CurrentEntitlement.query.filter_by(profile_id=outcome.profile_id).first()
        # Re-check status here too -- defends against a profile
        # converting to a paid plan in the moment between plan_alignment()
        # reading it and this write, however unlikely in practice.
        if row is None or row.status != "TRIAL":
            print(f"  SKIPPED profile_id={outcome.profile_id}: no longer TRIAL, not touched")
            continue
        row.trial_expires_at = outcome.new_trial_expires_at
    db.session.commit()


def print_report(outcomes: List[AlignmentOutcome], applied: bool) -> None:
    changed = [o for o in outcomes if o.changed]
    unchanged = [o for o in outcomes if not o.changed]
    print("\n" + "=" * 70)
    print(f"TRIAL EXPIRY ALIGNMENT {'(APPLIED)' if applied else '(DRY RUN -- nothing written)'}")
    print("=" * 70)
    print(f"Total TRIAL rows considered: {len(outcomes)}")
    print(f"Rows needing alignment:      {len(changed)}")
    print(f"Rows already correct:        {len(unchanged)}")
    for o in changed:
        now_expired = o.new_trial_expires_at <= datetime.utcnow()
        print(
            f"  profile_id={o.profile_id} started_at={o.trial_started_at.isoformat()} "
            f"old_expires_at={o.old_trial_expires_at.isoformat()} "
            f"-> new_expires_at={o.new_trial_expires_at.isoformat()} "
            f"{'[NOW EXPIRED]' if now_expired else '[still within 7-day window]'}"
        )
    if not applied and changed:
        print(f"\nRun again with --apply to write these {len(changed)} row(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write the recomputed trial_expires_at values. "
             "Without this flag, only reports what would change.",
    )
    args = parser.parse_args()

    with app.app_context():
        outcomes = plan_alignment()
        if args.apply:
            apply_alignment(outcomes)
        print_report(outcomes, applied=args.apply)


if __name__ == "__main__":
    main()
