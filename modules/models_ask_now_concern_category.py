# modules/models_ask_now_concern_category.py

"""
Ask Now Concern Category Master -- Ask Now Category Architecture v1.

FINAL PRODUCT DECISION (Category Architecture v1 correction task): NOT
the 36-item granular hardcoded taxonomy, and NOT dynamically model-
invented categories either. A small, controlled, DB-backed master list,
seeded with 13 initial categories (see the chained migration this table
is created in), designed so an Admin Dashboard can later list/add/
enable/disable categories WITHOUT a code deployment -- see
modules/services/asknow_category_service.py for the read/write
functions chat_engine.py and a future Admin Dashboard both use.

This deliberately replaces the previous approach of hardcoding
ASKNOW_CONCERN_CATEGORIES as a Python list literal directly inside
modules/services/chat_engine.py -- that constant no longer exists.
chat_engine.py now asks this table (via the service layer) for the
currently active category names at generation time, every time -- so
adding/disabling a category here takes effect on the very next Ask Now
question with no code change and no redeploy.

Fields:
- name: must remain unique (enforced by both the DB unique constraint
  here and modules/services/asknow_category_service.py::add_category()'s
  own pre-check before insert).
- is_active: only active categories are ever offered to Luna or
  accepted as a valid classification. Disabling a category here (rather
  than deleting it) preserves any AskNowIntentHistory rows that already
  reference its name.
- created_at: insertion order also doubles as the category's stable
  display/prompt order (categories are always read ordered by id).
"""

from datetime import datetime
from extensions import db


class AskNowConcernCategory(db.Model):
    __tablename__ = "ask_now_concern_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<AskNowConcernCategory id={self.id} name={self.name!r} is_active={self.is_active}>"
