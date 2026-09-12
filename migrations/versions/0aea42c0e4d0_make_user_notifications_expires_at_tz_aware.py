"""N-FIX-2A -- user_notifications.expires_at: naive -> timezone-aware UTC.

ROOT CAUSE (Notifications Final Audit, N-P1-1; confirmed by direct
Postgres testing, not assumed):

  Column:  user_notifications.expires_at was `TIMESTAMP WITHOUT TIME ZONE`
           (added by d3a9f1b2c7e4_add_expires_at_to_user_notifications.py).
  Writers: services/notification_lifecycle.py's _ist_midnight_utc() and
           services/event_scheduler.py's own inline Panchang expiry calc
           both computed an IST boundary, converted it to UTC, then
           explicitly stripped tzinfo (`.replace(tzinfo=None)`) before
           storing it -- so every stored value IS a real UTC wall-clock
           instant, just represented naively.
  Reader:  notifications/campaign_bell_service.py's unified Bell query
           (list_unified_bell/unread_count/mark_read/mark_all_read/
           dismiss_one/clear_all -- the ONLY place expires_at is ever
           compared against "now" in production) computes
           `now = datetime.now(timezone.utc)` -- AWARE.

  Comparing an aware Python datetime against a naive
  `TIMESTAMP WITHOUT TIME ZONE` column causes Postgres to interpret the
  aware value using the CONNECTION's session `TimeZone` GUC before
  comparing. Empirically verified against a real (local, non-production)
  Postgres connection whose session TimeZone is `Asia/Calcutta`: a
  naive-UTC value of 2026-09-12 03:00:00 compared `> ` an aware
  2026-09-12T02:59:00+00:00 (one minute EARLIER in real UTC terms)
  returned False -- it must return True. This shifts the effective
  expiry of every A/B Bell item (Panchang, event, transit, dasha,
  dasha_pre, alert) by the session's UTC offset whenever that session is
  not UTC.

THE FIX IS NOT MERELY "widen the column type". Also empirically verified:
inserting the SAME naive-UTC Python datetime into an already-`timestamptz`
column, under a session whose TimeZone is Asia/Calcutta, produces a
STORED value shifted by -5:30 from the intended instant (Postgres
interprets a naive value being written into a timestamptz column using
the session TimeZone too). So BOTH directions -- the historical stored
data AND the column's target type -- must be handled with an EXPLICIT,
session-timezone-independent UTC interpretation, never an implicit cast.
This migration does exactly that via `AT TIME ZONE 'UTC'`, which tells
Postgres unambiguously "this naive value already means UTC wall-clock"
regardless of whatever TimeZone GUC happens to be active when this
migration runs (in local dev, CI, or production).

This migration is a schema/data-representation fix ONLY:
  - Every existing row's real-world UTC instant is UNCHANGED (proven by
    this file's own test_notification_lifecycle.py-adjacent migration
    round-trip test -- see test_notification_expires_at_timezone.py).
  - No intended expiry TIME changes (Panchang still 17:00 IST, event/
    transit/dasha/dasha_pre/alert boundaries are untouched) -- those are
    all Python-side computations in services/notification_lifecycle.py
    and services/event_scheduler.py, fixed in the SAME commit as this
    migration (stop stripping tzinfo) but not touched by this file.
  - No other table/column is touched. No CHECK constraint changes.
  - run_panchang_dismiss_job() never reads or writes expires_at at all
    (verified by code inspection) -- zero interaction with this change.

Revision ID: 0aea42c0e4d0
Revises: b4e7f18a2c6d
"""
from alembic import op
import sqlalchemy as sa

revision = '0aea42c0e4d0'
down_revision = 'b4e7f18a2c6d'
branch_labels = None
depends_on = None

# Explicit, session-timezone-independent conversions -- never an
# implicit/plain ALTER COLUMN TYPE, which would silently reinterpret
# every existing naive value using whatever TimeZone GUC the migration
# happens to run under (proven wrong above).
_UPGRADE_USING = "expires_at AT TIME ZONE 'UTC'"
_DOWNGRADE_USING = "expires_at AT TIME ZONE 'UTC'"


def upgrade():
    # timestamp without time zone -> timestamp with time zone.
    # `col AT TIME ZONE 'UTC'` on a naive column means "interpret this
    # wall-clock value as UTC" and yields a timestamptz -- exactly the
    # existing writer convention, made explicit and CORRECT regardless
    # of the executing session's own TimeZone.
    op.alter_column(
        'user_notifications', 'expires_at',
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        postgresql_using=_UPGRADE_USING,
        existing_nullable=True,
    )


def downgrade():
    # timestamp with time zone -> timestamp without time zone.
    # `col AT TIME ZONE 'UTC'` on an AWARE column means "give me this
    # instant's wall-clock reading IN UTC" -- the exact inverse
    # operation, so a round-trip (upgrade then downgrade) reproduces the
    # original naive-UTC wall-clock values byte-for-byte, never
    # whatever the session's own TimeZone happens to be at downgrade time.
    op.alter_column(
        'user_notifications', 'expires_at',
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        postgresql_using=_DOWNGRADE_USING,
        existing_nullable=True,
    )
