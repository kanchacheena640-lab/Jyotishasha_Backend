# modules/models_ask_now_intent_history.py

"""
Ask Now Intent History -- Ask Now Improvement Batch (Objective 1 / 5).

ONE row per successfully classified Ask Now question -- explicitly NOT a
single per-user category column that gets overwritten. A user asking 5
Marriage questions and 2 Love & Relationship questions produces 7 rows
here, not one row with the latest category.

Identity: user_id = users.id -- the SAME identity FreeDailyQuestion.user_id
/ ChatPack.user_id already use (see models_free_daily.py, models_chat_pack.py).
Ask Now is already users.id-scoped in production (see routes/routes_chat.py's
own module docstring) -- no app_users/profile_id bridge is introduced here.

Why a new table instead of activity_events: Ask Now's own activity_events
rows are deliberately written with firebase_uid=None/profile_id=None (see
routes/routes_chat.py::_emit_asknow_event's own docstring -- "No truthful
durable per-question entity/identity/session/correlation exists for Ask
Now"). That ledger cannot currently support per-user, per-question
category history without a separately-scoped identity change to the
ledger itself, which this batch does not make. activity_events remains
the general-purpose observational ledger; this table is Ask Now's own
small business table for this specific feature, following this
codebase's own established pattern of keeping ledger and business-state
tables separate (Orders, ChatPack, FreeDailyQuestion all do the same).

Convention: follows models_free_daily.py / models_chat_pack.py exactly --
a plain indexed Integer user_id, no FK constraint (neither of those two
tables uses one either).

Privacy: NEVER stores the raw question, the raw answer, birth data, or
the OpenAI prompt/response -- only the already-validated concern_category
label plus the minimal fields needed to segment by user/source/time.
"""

from datetime import datetime
from extensions import db


class AskNowIntentHistory(db.Model):
    __tablename__ = "ask_now_intent_history"

    id = db.Column(db.Integer, primary_key=True)

    # users.id -- Ask Now's own existing identity. No FK constraint,
    # matching FreeDailyQuestion.user_id / ChatPack.user_id.
    user_id = db.Column(db.Integer, nullable=False, index=True)

    # A category name that was active in the DB-backed master
    # (modules/models_ask_now_concern_category.py::AskNowConcernCategory,
    # Ask Now Category Architecture v1) at the moment this question was
    # classified -- validated server-side before this row is ever
    # created (see modules/services/chat_engine.py::
    # _parse_answer_and_category()). Stored as a plain string, not a FK,
    # so this row's meaning stays stable even if that category is later
    # disabled/renamed in the master.
    #
    # String(100) -- matches ask_now_concern_categories.name's own
    # VARCHAR(100) exactly (Category Length Alignment fix). Both
    # migrations (fc796ea78183, 0e2036a0b4b7) are still uncommitted and
    # the Admin Dashboard will later let categories be added freely, so
    # this history column must never be narrower than the master column
    # it stores values from -- a future admin-added long category name
    # must not silently fail/truncate here just because this table was
    # migrated a moment earlier.
    concern_category = db.Column(db.String(100), nullable=False)

    # "free" | "pack" -- mirrors the same source label already used by
    # routes/routes_chat.py::_emit_asknow_event()'s own "source" property.
    source = db.Column(db.String(10), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "concern_category": self.concern_category,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return (
            f"<AskNowIntentHistory user={self.user_id} "
            f"category={self.concern_category} source={self.source}>"
        )
