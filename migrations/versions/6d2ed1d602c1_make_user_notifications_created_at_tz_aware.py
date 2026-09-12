"""N-FIX-2C -- user_notifications.created_at: naive -> timezone-aware UTC.

ROOT CAUSE (Notifications Final Audit follow-up; confirmed by direct
production evidence, not assumed):

  Column:  user_notifications.created_at was `TIMESTAMP WITHOUT TIME ZONE`
           (added by c0258816b77b_add_user_notifications_table.py), with
           a model-level default of db.func.current_timestamp() -- a
           SQLAlchemy `func` construct compiled into literal SQL
           CURRENT_TIMESTAMP, evaluated INSIDE Postgres at INSERT time,
           never in Python. Unlike expires_at (N-FIX-2A, always
           Python-computed, deterministically UTC before this fix),
           created_at's actual meaning depended entirely on the
           connecting session's own TimeZone GUC at each row's insert
           time -- never explicitly set anywhere in this codebase.

  Readers: notifications/campaign_bell_service.py's unified Bell
           unread-lookback filter compared this naive column against an
           AWARE cutoff (`datetime.now(timezone.utc) - UNREAD_LOOKBACK`).
           services/attention_policy.py::count_pushes_sent_today() (the
           shared A/B+Alerts daily push-budget counter) compared it
           against a naive-but-deterministically-UTC `since` boundary --
           correct only if created_at's own naive values also meant UTC.
           services/event_scheduler.py and modules/alerts/
           alert_delivery_service.py each explicitly ASSUMED UTC via
           `.replace(tzinfo=timezone.utc)` when building
           notification_created activity-event timestamps -- a
           deliberate but previously unverified assumption.

PRODUCTION EVIDENCE (N-FIX-2C evidence-check task, read-only, no write):
  - `SHOW timezone` on the production connection = 'UTC'.
  - 10 of 10 recently-sampled user_notifications rows, correlated
    against the INDEPENDENTLY server-generated
    activity_events.recorded_at (db.func.now(), always an absolute,
    session-timezone-safe timestamptz, written moments after each
    UserNotification commit in the same request, for
    event_name='notification_created'), showed a gap of only 5-10
    seconds between `created_at AT TIME ZONE 'UTC'` and
    activity_events.recorded_at -- exactly consistent with "the
    activity event was recorded a few seconds after the notification
    row committed". Had created_at actually meant IST, this same
    arithmetic would have produced a ~+5:30:00 gap, not seconds.
  - No migration, code, or configuration anywhere in this repo has ever
    set a database/role-level timezone, and no evidence of a historical
    timezone reconfiguration was found.
  - Conclusion: created_at's naive values represent UTC wall-clock.
    `created_at AT TIME ZONE 'UTC'` is the correct, evidence-backed
    interpretation for this migration.

THIS FIX IS A SCHEMA/REPRESENTATION CHANGE ONLY, exactly mirroring
N-FIX-2A's own migration 0aea42c0e4d0:
  - Every existing row's real-world UTC instant is UNCHANGED.
  - default=db.func.current_timestamp() is UNCHANGED -- CURRENT_TIMESTAMP
    already returns a genuine, correct instant; only the column was
    silently discarding that instant's own timezone information.
  - No intended "today"/"unread lookback"/ordering semantics change --
    services/attention_policy.py::start_of_today_ist() and
    notifications/campaign_bell_service.py's UNREAD_LOOKBACK window
    compute the exact same real-world boundaries as before, now
    expressed consistently as aware UTC (fixed in the same commit as
    this migration, not by this file).
  - No other table/column touched. NotificationCampaignBellItem.created_at
    (already DateTime(timezone=True) since migration c4d8f21a9e05) is
    completely untouched -- Campaign C's own Bell isolation is
    unaffected by this migration.

Revision ID: 6d2ed1d602c1
Revises: 0aea42c0e4d0
"""
from alembic import op
import sqlalchemy as sa

revision = '6d2ed1d602c1'
down_revision = '0aea42c0e4d0'
branch_labels = None
depends_on = None

# Explicit, session-timezone-independent conversions -- never an
# implicit/plain ALTER COLUMN TYPE, which would silently reinterpret
# every existing naive value using whatever TimeZone GUC the migration
# happens to run under (the exact hazard N-FIX-2A's own migration
# empirically proved and closed for expires_at).
_UPGRADE_USING = "created_at AT TIME ZONE 'UTC'"
_DOWNGRADE_USING = "created_at AT TIME ZONE 'UTC'"


def upgrade():
    # timestamp without time zone -> timestamp with time zone.
    # `col AT TIME ZONE 'UTC'` on a naive column means "interpret this
    # wall-clock value as UTC" and yields a timestamptz -- exactly the
    # production-evidence-confirmed writer convention, made explicit
    # and correct regardless of the executing session's own TimeZone.
    op.alter_column(
        'user_notifications', 'created_at',
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(timezone=False),
        postgresql_using=_UPGRADE_USING,
        existing_nullable=False,
    )


def downgrade():
    # timestamp with time zone -> timestamp without time zone.
    # `col AT TIME ZONE 'UTC'` on an AWARE column means "give me this
    # instant's wall-clock reading IN UTC" -- the exact inverse
    # operation, so a round-trip (upgrade then downgrade) reproduces the
    # original naive-UTC wall-clock values byte-for-byte, never
    # whatever the session's own TimeZone happens to be at downgrade time.
    op.alter_column(
        'user_notifications', 'created_at',
        type_=sa.DateTime(timezone=False),
        existing_type=sa.DateTime(timezone=True),
        postgresql_using=_DOWNGRADE_USING,
        existing_nullable=False,
    )
