# modules/models_saved_audience.py

"""
Saved Audience -- U6A backend foundation, extended by Saved Audience V2.

Frozen U6.0 architecture for DYNAMIC audiences (do not deviate without a
fresh audit):
  - DYNAMIC / criteria-based, never a snapshot. Membership is NEVER
    persisted here -- see modules/services/admin_users_service.py::
    resolve_user_ids() for how membership is resolved, fresh, every
    time an audience is used.
  - Canonical member identity is users.id, exclusively -- this table
    never stores firebase_uid/app_users.id/fcm_token, and criteria
    itself is validated to only ever reference users.id-scoped facts
    (the same filter surface GET /admin/api/users already exposes).
  - No member_ids, no last_member_count, no last_resolved_at, no
    notification_job_id -- U6A explicitly excludes these (see the U6A
    task's own "Do NOT add" list): membership/count are dynamic facts
    that would become stale persisted truth the moment they were
    written down. A future task MAY add an explicitly-labeled, always-
    stale-tolerant cache field if a real UX need justifies it -- not
    invented speculatively here.

criteria is the ONE durable fact this table stores for a DYNAMIC
audience:
    {"version": 1, "filters": {...}}
-- filters uses EXACTLY the same key names as
modules/services/admin_users_service.py::list_users()'s own keyword
arguments (never a frontend camelCase name, never an invented alias).
See modules/services/saved_audience_criteria.py for the full schema/
validation contract enforced before a row is ever written here.

Saved Audience V2 -- explicit FIXED audience type. Production QA
repeatedly produced an unintended filters={} / All Users audience from
search-based Saved Audience creation (a frontend timing bug, fixed
separately) -- rather than trying to make "isolate one exact user"
perfectly reliable through the DYNAMIC/criteria path, this adds a
SECOND, explicit audience_type for exact, canonical users.id membership:
  - audience_type == "dynamic" (default, existing behavior): criteria
    is required, membership resolved live via resolve_user_ids() --
    completely unchanged.
  - audience_type == "fixed": criteria is NULL (never overloaded with
    fake filter values -- e.g. never search=user_id), and membership is
    an explicit set of users.id rows in SavedAudienceMember below.
    Membership is immutable once created (no edit-members endpoint) --
    intentional, for internal tests/canaries/intentionally fixed
    groups -- and must NEVER expand because a user's attributes change,
    and must NEVER be inferred from/fall back to an empty-filters "All
    Users" interpretation under any failure. The only thing that can
    shrink a FIXED audience after creation is a member's own account
    being deleted (SavedAudienceMember.user_id -> users.id ON DELETE
    CASCADE) -- the same legitimate, privacy-driven exclusion every
    other users.id-scoped table in this codebase already allows.
A CHECK constraint enforces the two shapes never mix: dynamic rows
always have non-NULL criteria, fixed rows always have NULL criteria.
"""

from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB
from extensions import db

AUDIENCE_TYPE_DYNAMIC = "dynamic"
AUDIENCE_TYPE_FIXED = "fixed"
AUDIENCE_TYPES = (AUDIENCE_TYPE_DYNAMIC, AUDIENCE_TYPE_FIXED)


class SavedAudience(db.Model):
    __tablename__ = "saved_audiences"
    __table_args__ = (
        db.CheckConstraint(
            "audience_type IN ('dynamic', 'fixed')",
            name="ck_saved_audiences_audience_type",
        ),
        db.CheckConstraint(
            "(audience_type = 'dynamic' AND criteria IS NOT NULL) OR "
            "(audience_type = 'fixed' AND criteria IS NULL)",
            name="ck_saved_audiences_criteria_matches_type",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Saved Audience V2 -- explicit type discriminator. Every consumer
    # (resolver, campaign_service.audience_definition(), the Admin API)
    # must branch on THIS column, never infer "fixed" from criteria
    # being null/empty and never treat an empty/null criteria as All
    # Users for a fixed row -- see module docstring.
    # Both a Python-side default() -- so SavedAudience(...) constructed
    # without audience_type= (every existing test fixture/caller, since
    # this column didn't exist before) is "dynamic" immediately on the
    # in-memory object, no refresh needed -- AND a server_default() --
    # so a raw-SQL insert or this migration's own backfill of existing
    # rows gets the identical value at the database level.
    audience_type = db.Column(
        db.String(10), nullable=False,
        default=AUDIENCE_TYPE_DYNAMIC, server_default=AUDIENCE_TYPE_DYNAMIC,
    )

    # The ONE durable fact for a DYNAMIC audience -- {"version": 1,
    # "filters": {...}}. NULL for a FIXED audience (membership lives in
    # SavedAudienceMember instead) -- see modules/services/
    # saved_audience_criteria.py for the schema this is validated
    # against before ever reaching this column.
    # none_as_null=True: without it, SQLAlchemy's JSON/JSONB type stores
    # Python None as the JSON literal `null` (a real, non-NULL JSONB
    # value) rather than a genuine SQL NULL -- which would silently
    # violate (or worse, silently satisfy in a way that defeats)
    # ck_saved_audiences_criteria_matches_type's own `criteria IS NULL`
    # check for a FIXED row. This makes criteria=None actually mean SQL
    # NULL, matching the CHECK constraint's own literal semantics.
    criteria = db.Column(JSONB(none_as_null=True), nullable=True)

    # U6A Section 5 -- the resolved admin identity (users.id) from a
    # real admin JWT, when one was actually presented on the request
    # that created this row. NULL is a VALID, EXPECTED value for the
    # Next.js Admin BFF's bridge-key path (X-Admin-Bridge-Key), which
    # carries no admin JWT/identity at all -- see
    # routes/routes_admin_audiences.py's own docstring for the exact
    # authentication-path audit this is based on. Never fabricated,
    # never defaulted to a sentinel "system" id. No FK constraint --
    # matches this codebase's own established convention for every
    # other users.id-holding column with no dedicated identity table
    # (ChatPack.user_id, AskNowIntentHistory.user_id, ...).
    created_by = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Soft-deactivate, never hard delete -- matches this codebase's own
    # established convention (AskNowConcernCategory.is_active,
    # ChatPack.status, ...). DELETE /admin/api/audiences/<id> sets this
    # to False; the row (and, for a fixed audience, its member rows) are
    # never physically removed. This alone already satisfies "don't
    # silently destroy campaign auditability" -- NotificationCampaign.
    # saved_audience_id is an informational reference (no FK), and every
    # approved/scheduled campaign's real historical record lives in its
    # OWN immutable NotificationCampaignExecution.approved_criteria
    # snapshot (notifications/campaign_execution_models.py), completely
    # independent of this row's is_active state.
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "audience_type": self.audience_type,
            "criteria": self.criteria,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
        }

    def __repr__(self):
        return f"<SavedAudience id={self.id} name={self.name!r} type={self.audience_type} is_active={self.is_active}>"


class SavedAudienceMember(db.Model):
    """Saved Audience V2 -- explicit membership for a FIXED audience.

    Canonical identity ONLY: user_id is users.id, never app_users.id --
    matches SavedAudience's own frozen "canonical member identity is
    users.id, exclusively" rule. A dedicated relational table (not a
    JSON array on SavedAudience.criteria) so the database itself
    enforces referential integrity and duplicate-member prevention,
    rather than relying on application-level bookkeeping alone.

    ON DELETE CASCADE both ways:
      - saved_audience_id -> saved_audiences.id: member rows can never
        outlive their parent audience (the parent itself is normally
        only soft-deactivated, never hard-deleted, but this is a
        correctness guarantee, not a routine deletion path).
      - user_id -> users.id: when a user's account is hard-deleted
        (modules/auth/account_deletion_service.py), their membership
        row(s) are removed automatically by Postgres -- no Python-side
        cleanup required, and no dangling reference ever needs special-
        casing at resolve time. This is the ONLY way a fixed audience's
        membership can shrink after creation (membership itself has no
        edit endpoint -- immutable by design, see module docstring).
    """
    __tablename__ = "saved_audience_members"
    __table_args__ = (
        db.UniqueConstraint("saved_audience_id", "user_id", name="uq_saved_audience_member"),
    )

    id = db.Column(db.Integer, primary_key=True)
    saved_audience_id = db.Column(
        db.Integer, db.ForeignKey("saved_audiences.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<SavedAudienceMember saved_audience_id={self.saved_audience_id} user_id={self.user_id}>"
