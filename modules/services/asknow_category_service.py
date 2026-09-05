# modules/services/asknow_category_service.py

"""
Ask Now Concern Category Master -- service layer (Ask Now Category
Architecture v1). Reads/writes modules/models_ask_now_concern_category.py
::AskNowConcernCategory, the small, controlled, DB-backed master list
that replaced chat_engine.py's previous hardcoded category constant.

Design intent: this is the ONE place category read/write logic lives,
so a future Admin Dashboard (list / add / enable / disable) and
chat_engine.py's own generation-time lookup both go through the same
functions -- no separate code path, no drift.

get_active_category_names() deliberately does NOT catch/swallow
exceptions itself -- a genuine DB failure (connection down, table
missing, etc.) propagates to the caller as a real exception.
chat_engine.py is the one responsible for the safe-fallback decision
(Ask Now Category Architecture v1, Objective 3: a category-master read
failure must never fail a valid Ask Now answer) -- keeping that
fallback policy OUT of this file keeps this service a plain, honest
data-access layer, and keeps the "never fail the answer" policy visible
in the one place it actually matters (chat_engine.py's own docstring/
comments), rather than silently baked in here where a future Admin
Dashboard caller might not expect it.

No Admin UI or Admin API route is added in this task -- list_categories()
/ add_category() / set_category_active() are plain service functions
only, ready for a future Admin route to call.
"""

from extensions import db
from modules.models_ask_now_concern_category import AskNowConcernCategory


def get_active_category_names() -> list:
    """
    Returns the names of all currently active categories, ordered by
    insertion order (id ascending) -- this ordering is also what
    chat_engine.py renders into the prompt, so category order in the
    prompt is stable and predictable.

    Raises whatever the underlying DB query raises on a genuine failure
    -- see this module's own docstring for why the fallback decision is
    deliberately NOT made here.
    """
    rows = (
        AskNowConcernCategory.query
        .filter_by(is_active=True)
        .order_by(AskNowConcernCategory.id.asc())
        .all()
    )
    return [row.name for row in rows]


def list_categories(include_inactive: bool = True) -> list:
    """Future Admin Dashboard: list every category (active + inactive by
    default), each as a plain dict. Ordered by insertion order."""
    query = AskNowConcernCategory.query
    if not include_inactive:
        query = query.filter_by(is_active=True)
    rows = query.order_by(AskNowConcernCategory.id.asc()).all()
    return [row.to_dict() for row in rows]


def add_category(name: str) -> AskNowConcernCategory:
    """
    Future Admin Dashboard: add a new category, active by default.

    Enforces uniqueness explicitly (in addition to the table's own
    unique DB constraint) so callers get a clean, catchable ValueError
    on a duplicate name rather than an uncaught IntegrityError.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Category name cannot be empty.")

    existing = AskNowConcernCategory.query.filter_by(name=name).first()
    if existing:
        raise ValueError(f"Category '{name}' already exists.")

    row = AskNowConcernCategory(name=name, is_active=True)
    db.session.add(row)
    db.session.commit()
    return row


def set_category_active(name: str, is_active: bool) -> AskNowConcernCategory:
    """Future Admin Dashboard: enable/disable an existing category by
    exact name. Raises ValueError if the name does not exist -- never
    silently creates one."""
    row = AskNowConcernCategory.query.filter_by(name=name).first()
    if not row:
        raise ValueError(f"Category '{name}' does not exist.")

    row.is_active = is_active
    db.session.commit()
    return row
