# modules/models_saved_audience.py

"""
Saved Audience -- U6A backend foundation.

Frozen U6.0 architecture (do not deviate without a fresh audit):
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

criteria is the ONE durable fact this table stores:
    {"version": 1, "filters": {...}}
-- filters uses EXACTLY the same key names as
modules/services/admin_users_service.py::list_users()'s own keyword
arguments (never a frontend camelCase name, never an invented alias).
See modules/services/saved_audience_criteria.py for the full schema/
validation contract enforced before a row is ever written here.
"""

from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB
from extensions import db


class SavedAudience(db.Model):
    __tablename__ = "saved_audiences"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # The ONE durable fact -- {"version": 1, "filters": {...}}. See
    # modules/services/saved_audience_criteria.py for the schema this
    # is validated against before ever reaching this column.
    criteria = db.Column(JSONB, nullable=False)

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
    # to False; the row and its criteria are never physically removed.
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "criteria": self.criteria,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
        }

    def __repr__(self):
        return f"<SavedAudience id={self.id} name={self.name!r} is_active={self.is_active}>"
