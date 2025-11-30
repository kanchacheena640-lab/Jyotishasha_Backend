# modules/services/free_quota_service.py

"""
Free Daily Question Service (ChatPack 51 System)

Handles:
- Checking if user already used today's free question
- Creating entry if user has no record
- Marking today's free question as used

Depends on:
- modules/models_free_daily.py → FreeDailyQuestion table
"""

from datetime import date
from extensions import db
from modules.models_free_daily import FreeDailyQuestion


def _today_str():
    """Returns YYYY-MM-DD string (IST not needed here because only date)."""
    return date.today().strftime("%Y-%m-%d")


def get_free_record(user_id):
    """
    Fetch user's free question record.
    If not found → create a new entry with empty last_used_date.
    """
    record = FreeDailyQuestion.query.filter_by(user_id=user_id).first()

    if not record:
        record = FreeDailyQuestion(
            user_id=user_id,
            last_used_date=None,
        )
        db.session.add(record)
        db.session.commit()

    return record


def has_free_quota(user_id):
    """
    Returns True if user has NOT used today's free question.
    Returns False if user already used it.
    """
    record = get_free_record(user_id)
    today = _today_str()
    return record.last_used_date != today


def use_free_quota(user_id):
    """
    Marks today's free question as used.
    Returns updated record.
    """
    record = get_free_record(user_id)
    record.last_used_date = _today_str()
    db.session.commit()
    return record


def get_free_quota_status(user_id):
    """
    Helper for Postman tests:
    Returns:
        {
            "user_id": ..,
            "used_today": True/False,
            "last_used_date": "YYYY-MM-DD" or None
        }
    """
    record = get_free_record(user_id)
    today = _today_str()

    return {
        "user_id": user_id,
        "used_today": (record.last_used_date == today),
        "last_used_date": record.last_used_date,
    }
