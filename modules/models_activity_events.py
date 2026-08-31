# modules/models_activity_events.py

"""
ActivityEvent -- the first-party analytics ledger table (`activity_events`),
Phase 2 Step 2 of the Event Tracking -> Analytics Dashboard project.

This is the durable, first-party record of the 33 canonical business/
behavioral events frozen in Phase 1's Activity Ledger Contract. It is an
ADDITIVE OBSERVATIONAL layer only -- see modules/activity_events/service.py
for the write path and the non-regression guarantee that governs it. This
file defines only the table.

19 columns, exactly as frozen (event_id, event_name, event_version,
occurred_at, recorded_at, firebase_uid, profile_id, anonymous_id,
session_id, platform, source, environment, correlation_id, entity_type,
entity_id, properties, campaign_context, notification_context,
dedupe_key). Only event_id/event_name/event_version/occurred_at/
recorded_at/platform/environment/properties are NOT NULL -- everything
else is genuinely optional and must never be fabricated by a producer
that doesn't truthfully have the value (see the write helper).

profile_id is a deliberate exception to this codebase's usual FK
convention (compare AIReport.profile_id / CurrentEntitlement.profile_id
in modules/models_ai_reports.py / modules/models_premium_subscription.py,
both `db.ForeignKey("app_users.id")`). activity_events is an 18-month
historical ledger, not a business record tightly coupled to AppUser's
current existence -- a hard FK here would let a future AppUser deletion/
merge/anonymization be blocked by Postgres's default RESTRICT behavior,
or invite a later `ondelete=CASCADE` that would silently wipe analytics
history. profile_id is therefore stored as a plain indexed identifier
only, exactly per the frozen Phase 1 contract's explicit instruction.
Same reasoning applies to firebase_uid, anonymous_id, session_id,
correlation_id, entity_id -- none of them are foreign keys.

properties / campaign_context / notification_context use PostgreSQL
JSONB (via sqlalchemy.dialects.postgresql), not this codebase's usual
`db.JSON` (see e.g. ProcessedPayment.response_payload,
CurrentEntitlement.receipt_payload). This is a deliberate, scoped
exception: every existing JSON column in this codebase is an opaque
payload dump, never queried by key. `properties` is the opposite by
design -- it exists to be filtered/aggregated by key for dashboard KPIs
(see modules/activity_events/event_schemas.py), and JSONB's decomposed
storage and containment operators (@>, ?, ?&) serve that even with no
GIN index -- none is added here (see the migration for the full index
list; deliberately no GIN index, per the frozen Step 1 design).

NOT in this file, per the frozen contract and explicit Step 2
instruction: no identity_links table, no partitioning, no FK to
users/app_users, no new Profile model, no speculative columns.
"""

import uuid

from sqlalchemy.dialects.postgresql import JSONB, UUID

from extensions import db


class ActivityEvent(db.Model):
    __tablename__ = "activity_events"

    # ---- identity of the row itself ------------------------------------
    event_id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ---- what happened, and under which schema version -----------------
    # Plain String, not a native Postgres ENUM -- matches this codebase's
    # existing convention for status/type columns (e.g.
    # CurrentEntitlement.status, SubscriptionEvent.event_type) validated
    # at the application layer rather than requiring an ALTER TYPE
    # migration to add a new canonical event name.
    event_name = db.Column(db.String(64), nullable=False)
    event_version = db.Column(db.SmallInteger, nullable=False, server_default="1")

    # ---- when it happened vs. when the ledger recorded it --------------
    # occurred_at has NO default: every producer must supply it
    # explicitly. A silent insert-time fallback would make a forgotten
    # value indistinguishable from recorded_at and mask a producer bug.
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False)
    # recorded_at is SERVER-GENERATED ONLY. The write helper never
    # accepts it as a caller argument -- see modules/activity_events/
    # service.py.
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    # ---- identity (all optional -- never fabricated if not truthfully
    # known, see the write helper) ----------------------------------------
    # No index=True here -- (firebase_uid, occurred_at) below already
    # covers a firebase_uid-only lookup via leftmost-prefix; a separate
    # single-column index would just be a redundant, write-amplifying
    # duplicate (Step 1 design, S4/S13: "avoid speculative indexing").
    firebase_uid = db.Column(db.String(255), nullable=True)
    # Indexed identifier only -- NOT a ForeignKey. See module docstring.
    profile_id = db.Column(db.Integer, nullable=True, index=True)
    anonymous_id = db.Column(db.String(64), nullable=True, index=True)
    session_id = db.Column(db.String(64), nullable=True, index=True)

    # ---- producer context -----------------------------------------------
    platform = db.Column(db.String(20), nullable=False)  # app_android | app_ios | website | backend_internal
    source = db.Column(db.String(64), nullable=True)
    # No DB-level default -- set explicitly by the write helper from
    # deployment config. A default of "production" here would silently
    # mislabel staging/dev traffic if a call site ever forgot to pass it.
    environment = db.Column(db.String(20), nullable=False)

    # ---- cross-event / cross-system correlation --------------------------
    correlation_id = db.Column(db.String(64), nullable=True, index=True)
    entity_type = db.Column(db.String(32), nullable=True)  # order | ai_report | subscription_event | chat_pack | processed_payment | notification
    entity_id = db.Column(db.String(64), nullable=True)

    # ---- structured payload (key-allowlisted by event_schemas.py --
    # never a free dump; see Phase 1 Privacy Contract) ---------------------
    properties = db.Column(JSONB, nullable=False, server_default="{}")
    campaign_context = db.Column(JSONB, nullable=True)
    notification_context = db.Column(JSONB, nullable=True)

    # ---- dedupe / idempotency --------------------------------------------
    # Nullable -- uniqueness is enforced only for non-null values via a
    # partial unique index (see the migration), not this column
    # definition itself.
    dedupe_key = db.Column(db.String(255), nullable=True)

    __table_args__ = (
        db.Index("ix_activity_events_entity", "entity_type", "entity_id"),
        db.Index("ix_activity_events_event_name_occurred_at", "event_name", "occurred_at"),
        db.Index("ix_activity_events_firebase_uid_occurred_at", "firebase_uid", "occurred_at"),
        db.Index("ix_activity_events_occurred_at", "occurred_at"),
        # Partial unique index -- correctness AND write-amplification
        # reasoning are both in the frozen Step 1 design: NULLs are
        # already distinct from each other under a plain UNIQUE
        # constraint, but a partial index additionally avoids indexing
        # the majority of rows that never set a dedupe_key at all.
        db.Index(
            "ux_activity_events_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=db.text("dedupe_key IS NOT NULL"),
        ),
    )

    def to_dict(self) -> dict:
        return {
            "event_id": str(self.event_id) if self.event_id else None,
            "event_name": self.event_name,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "firebase_uid": self.firebase_uid,
            "profile_id": self.profile_id,
            "anonymous_id": self.anonymous_id,
            "session_id": self.session_id,
            "platform": self.platform,
            "source": self.source,
            "environment": self.environment,
            "correlation_id": self.correlation_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "properties": self.properties,
            "campaign_context": self.campaign_context,
            "notification_context": self.notification_context,
            "dedupe_key": self.dedupe_key,
        }

    def __repr__(self) -> str:
        return f"<ActivityEvent event_name={self.event_name} event_id={self.event_id}>"
