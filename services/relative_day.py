# services/relative_day.py
#
# Single source of truth for "how does this AstroEvent's date relate to
# today" (today / tomorrow / yesterday / future / past). Nothing else in
# the codebase should compare an event date to "now" and hand-roll its
# own Today/Tomorrow wording -- notification_builder.py and
# card_service.py both consume this instead of maintaining their own
# copies, which is what let a push say "Today" while the Event Detail
# for the same AstroEvent said "Tomorrow".

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

TODAY = "today"
TOMORROW = "tomorrow"
YESTERDAY = "yesterday"
FUTURE = "future"
PAST = "past"


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    return None


def get_relative_day(event_date, reference_date=None):
    """
    Returns one of TODAY / TOMORROW / YESTERDAY / FUTURE / PAST for how
    event_date relates to reference_date (defaults to "today" in IST,
    the timezone the rest of the scheduler already uses).

    Returns None if event_date can't be parsed -- callers decide their
    own fallback rather than this module guessing one.
    """
    event_date = _as_date(event_date)
    if event_date is None:
        return None

    if reference_date is None:
        reference_date = datetime.now(IST).date()
    else:
        reference_date = _as_date(reference_date)

    delta = (event_date - reference_date).days

    if delta == 0:
        return TODAY
    if delta == 1:
        return TOMORROW
    if delta == -1:
        return YESTERDAY
    if delta > 1:
        return FUTURE
    return PAST
