# modules/services/asknow_intent_service.py

"""
Ask Now Intent History -- write path (Ask Now Improvement Batch,
Objective 1 / 5). ONE row per successfully classified Ask Now question,
keyed by users.id (Ask Now's own existing identity -- see
routes/routes_chat.py's own module docstring: "Ask Now is already
users.id-scoped in production"). Never overwrites a per-user column --
this is question-level history, not a rolling summary. See
modules/models_ask_now_intent_history.py for the full design rationale
(why this is a dedicated table, not activity_events).

Failure isolation (explicit Objective 5 requirement): a failure writing
this row must NEVER fail an otherwise valid, already-generated Ask Now
answer, and must NEVER affect free/pack credit consumption or
restoration -- both are already finalized by the time this is called
(chat_engine() has already returned successfully, and use_free_quota()/
deduct_question() already committed before that). Modeled on the exact
same isolation pattern already proven by
modules/activity_events/service.py::record_event() -- a SEPARATE
SQLAlchemy session bound to the same engine as db.session, not
db.session itself, so a failure/rollback here can never touch whatever
transaction state the caller's own request is in. Every exception is
caught, logged, and swallowed -- never re-raised.
"""

import logging

from sqlalchemy.orm import sessionmaker

from extensions import db
from modules.models_ask_now_intent_history import AskNowIntentHistory

logger = logging.getLogger("asknow_intent")


def record_intent_history(*, user_id: int, concern_category, source: str) -> bool:
    """Writes one AskNowIntentHistory row for a successfully classified
    Ask Now question. Returns True if written, False if skipped (no
    category to record) or if the write failed. The return value is
    informational/loggable only -- callers must never branch credit or
    response behavior on it (see module docstring's failure-isolation
    requirement)."""
    if not concern_category:
        # Classification degraded/failed upstream (chat_engine() already
        # handled that gracefully, per its own contract) -- nothing
        # truthful to record. Not an error; simply no history row for
        # this question.
        return False

    IntentSession = sessionmaker(bind=db.session.get_bind())
    session = IntentSession()
    try:
        row = AskNowIntentHistory(
            user_id=user_id,
            concern_category=concern_category,
            source=source,
        )
        session.add(row)
        session.commit()
        return True
    except Exception:
        session.rollback()
        logger.warning(
            "asknow_intent: failed to record intent history (user_id=%s, "
            "source=%s) -- swallowed, Ask Now answer/credits unaffected",
            user_id, source, exc_info=True,
        )
        return False
    finally:
        session.close()
