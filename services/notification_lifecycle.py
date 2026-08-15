# services/notification_lifecycle.py

"""
Notification Lifecycle Policy (N2, extended by N2.1) -- the single,
reusable place that decides `UserNotification.expires_at` for each
notification type, based on ACTUAL domain data (AstroEvent.date,
AlertMicroEvent.active_until, UserDashaTimeline.start_date, or the
calendar day a notification was generated on) rather than an arbitrary
generic retention number.

Deliberately pure and stateless: every function here takes plain values
(dates, an explicit "now"/reference where relevant) and returns a naive
UTC datetime -- no DB access, no import of the scheduling/detection/
entitlement layers, so this module can be reused (and unit-tested)
independently of services/event_scheduler.py and the Alerts pipeline.

Scope, explicitly:
- This module answers ONLY "when does this notification stop being
  useful/relevant" (VISIBILITY expiry). It does not decide who/whether/
  when to send anything, does not touch NotificationLog dedup, and does
  not change the existing "keep newest 10" physical-retention trim in
  services/event_scheduler.py -- that split (visibility vs. physical
  deletion) is unchanged by N2; see that file's own docstring.
- notifications/user_notification_routes.py's existing filter
  (`expires_at IS NULL OR expires_at > now`) is UNCHANGED by N2 and
  already correctly consumes whatever value this module produces --
  every function here only needs to compute a correct value, not wire
  up new filtering.

Timezone convention: every boundary is computed as IST midnight (or IST
17:00 for the one type that already had a rule -- Panchang, unchanged,
not duplicated here), expressed as a naive UTC datetime -- the exact
convention services/event_scheduler.py's own pre-existing Panchang
expiry already uses
(`datetime.combine(...).astimezone(timezone.utc).replace(tzinfo=None)`),
reused here rather than inventing a second convention.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_midnight_utc(d: date) -> datetime:
    """IST 00:00 of `d`, as a naive UTC datetime."""
    return (
        datetime.combine(d, time(hour=0), tzinfo=IST)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


def expiry_for_astro_event_notification(
    *, event_date: date, is_forward_looking: bool
) -> datetime:
    """
    Covers `event` (festival/vrat), `transit`, and `panchak` -- every
    notification type backed by a real `AstroEvent.date`.

    `is_forward_looking=True` is the "Tomorrow" framing used ONLY by the
    `event` type's evening-slot send (`relative_day == TOMORROW` at
    generation time -- see services/notification_builder.py::
    build_event_content()): the notification's own wording describes a
    day that hasn't started yet, so it must stop being valid the INSTANT
    that day begins -- expires at IST midnight of `event_date` itself.

    `is_forward_looking=False` covers every other case: the `event`
    type's morning-slot "Today" framing, and `transit`/`panchak` (neither
    of which carries today/tomorrow wording at all -- their relevance is
    simply "this AstroEvent's own day"). Valid through the END of
    `event_date` -- expires at IST midnight of the FOLLOWING day.
    """
    boundary = event_date if is_forward_looking else event_date + timedelta(days=1)
    return _ist_midnight_utc(boundary)


def expiry_for_same_day_notification(*, generated_on: date) -> datetime:
    """
    Covers `dasha` (same-day "phase started today" announcement --
    services/notification_builder.py's DASHA START section). There is no
    AstroEvent backing this type; the notification's own content is
    anchored entirely to the calendar day it was generated on ("...phase
    शुरू हो गया है"), so that is the only domain fact available to derive
    validity from. Valid through the end of `generated_on`.

    Does NOT cover `dasha_pre` -- see expiry_for_dasha_pre_notification()
    below (N2.1) for that type's own, differently-shaped policy.
    """
    return _ist_midnight_utc(generated_on + timedelta(days=1))


def expiry_for_dasha_pre_notification(*, transition_date: date) -> datetime:
    """
    Covers `dasha_pre` (the T-5 "⏳ Dasha Change Coming" warning --
    services/notification_builder.py's DASHA T-5 ALERT section).

    N2.1: `transition_date` is the ACTUAL date the new Mahadasha/
    Antardasha begins -- the same `UserDashaTimeline.start_date`
    services/personalization_engine.py::get_users_for_dasha_change()
    already queries by (unmodified), now surfaced through that
    function's own return dict and threaded into this notification's
    `data["start_date"]` (notification_builder.py) rather than
    recomputed or guessed here. Resolves the data-availability gap N2
    documented and deliberately left unexpired.

    The warning's own wording ("...5 din baad ... dasha shuru hogi") is
    a forward-looking claim about a day that hasn't arrived yet -- like
    the `event` type's "Tomorrow" framing (expiry_for_astro_event_notification
    above), it must stop being valid the INSTANT that day begins, not at
    the end of it: once the new Dasha has actually started, "coming in 5
    days" is not a softer version of the truth, it is simply wrong.
    Expires at IST midnight of `transition_date` itself.
    """
    return _ist_midnight_utc(transition_date)


def expiry_for_alert_notification(*, active_until: date) -> datetime:
    """
    Personalized Alert (`type: "alert"`) -- derived from the persisted
    `AlertMicroEvent.active_until` (a NOT NULL column -- see
    modules/alerts/persistence_models.py -- so this is never a guess).
    Valid through the end of `active_until`, matching the same "valid
    through the end of its relevant day" convention used above rather
    than expiring the instant that day begins (unlike the event type's
    forward-looking case, an Alert's wording is never phrased as
    "tomorrow" -- see modules/alerts/notification_content_adapter.py's
    fixed catalog title / category body templates -- so there is no
    stale "Tomorrow" wording risk to guard against here).
    """
    return _ist_midnight_utc(active_until + timedelta(days=1))
