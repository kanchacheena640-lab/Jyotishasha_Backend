"""N6 -- Campaign C metrics contract. Every returned count/rate states
its exact numerator/denominator here, in plain English, right next to
the code that computes it; nothing is fabricated or approximated, and a
rate whose denominator is 0 returns the literal string "UNKNOWN" rather
than a misleading 0%.

METRICS CONTRACT (exact numerator/denominator per metric):

  target_count               = COUNT(NotificationCampaignDelivery) rows
                                for this execution -- i.e. everyone
                                target-frozen for this send, regardless
                                of outcome.
  delivery_counts.ACCEPTED   = COUNT(status == 'ACCEPTED') -- confirms
                                the PUSH PROVIDER accepted the request.
                                NEVER labeled "Delivered" anywhere this
                                module's output reaches a UI (N1's own
                                explicit prohibition) -- it is not proof
                                the message reached the device.
  delivery_counts.FAILED_*   = COUNT of each failure status as recorded
                                by campaign_worker.py; FAILED_RETRYABLE
                                still in backoff is shown separately from
                                FAILED_PERMANENT, never merged.
  delivery_counts.UNKNOWN    = COUNT(status == 'UNKNOWN') -- "no
                                confirmed outcome". Kept strictly apart
                                from FAILED_* and from ACCEPTED; never
                                counted as either in any rate below.
  delivery_counts.SUPPRESSED = COUNT(status == 'SUPPRESSED') -- never
                                attempted at all (missing/ambiguous
                                token at claim time), distinct from a
                                transport failure.
  notification_opened_count  = COUNT(activity_events WHERE event_name=
                                'notification_opened' AND
                                notification_context.campaign_id ==
                                str(this campaign's id)), scoped to the
                                current ACTIVITY_EVENTS_ENVIRONMENT.
                                Correlated by campaign identity only
                                (execution:campaign is 1:1 in this
                                system -- NotificationCampaignExecution.
                                campaign_id is UNIQUE) -- two different
                                campaigns' opens can never merge.
  destination_opened_count   = same query, event_name='destination_opened'
                                -- a GENUINELY DISTINCT client-observed
                                moment (the app actually reached the
                                notification's destination screen, not
                                merely that the OS notification was
                                tapped). See event_schemas.py's own
                                registration comment for why this is a
                                new event, not a rename/reuse of
                                notification_opened.
  open_rate                  = notification_opened_count / ACCEPTED, or
                                "UNKNOWN" when ACCEPTED == 0.
  destination_rate           = destination_opened_count /
                                notification_opened_count, or "UNKNOWN"
                                when notification_opened_count == 0.
  conversion_count           = see attribute conversions below.
  conversion_rate            = conversion_count / ACCEPTED, or "UNKNOWN"
                                when ACCEPTED == 0.

CONVERSION ATTRIBUTION (N6.12 -- exact rule, no approximation):
  A qualifying "purchase" is exactly one payment_verified activity event
  whose properties.purpose is one of REPORT_PURCHASE, ASK_NOW_CHAT_PACK,
  or SUBSCRIPTION (modules/payments/payment_models.py::PaymentPurpose).
  payment_initiated ("checkout opened") is NEVER counted, per N6's own
  explicit instruction. A user is counted as converted for this campaign
  if their MOST RECENT destination_opened click for this campaign_id
  occurred at or before a qualifying purchase, and that purchase occurred
  within 24 hours AFTER that click (never before -- forward-looking only,
  no view-through). One user contributes at most once, even with
  multiple clicks or purchases in the window (single-touch, last-click,
  no cross-campaign credit sharing, no multi-touch, no cross-device
  merge beyond what firebase_uid itself already represents).
"""
from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import func

from extensions import db
from modules.models_activity_events import ActivityEvent
from notifications.campaign_execution_models import NotificationCampaignExecution, NotificationCampaignDelivery

ATTRIBUTION_WINDOW = timedelta(hours=24)

# The ONLY events this module treats as a genuine purchase conversion.
CONVERSION_EVENT_NAME = "payment_verified"
CONVERSION_PURPOSES = frozenset({"REPORT_PURCHASE", "ASK_NOW_CHAT_PACK", "SUBSCRIPTION"})

DELIVERY_STATUSES = ('PENDING', 'ACCEPTED', 'FAILED_RETRYABLE', 'FAILED_PERMANENT', 'UNKNOWN', 'SUPPRESSED')


def _env():
    return os.environ.get("ACTIVITY_EVENTS_ENVIRONMENT", "production")


def _rate(numerator, denominator):
    if not denominator:
        return "UNKNOWN"
    return round(numerator / denominator, 4)


def delivery_counts(execution_id):
    counts = dict(
        db.session.query(NotificationCampaignDelivery.status, func.count(NotificationCampaignDelivery.id))
        .filter(NotificationCampaignDelivery.execution_id == execution_id)
        .group_by(NotificationCampaignDelivery.status).all()
    )
    return {status: counts.get(status, 0) for status in DELIVERY_STATUSES}


def _count_notification_context_event(campaign_id, event_name, environment):
    return (
        db.session.query(func.count(ActivityEvent.event_id))
        .filter(ActivityEvent.environment == environment)
        .filter(ActivityEvent.event_name == event_name)
        .filter(ActivityEvent.notification_context["campaign_id"].astext == str(campaign_id))
        .scalar() or 0
    )


def campaign_open_counts(campaign_id, environment=None):
    environment = environment or _env()
    return {
        "notification_opened_count": _count_notification_context_event(campaign_id, "notification_opened", environment),
        "destination_opened_count": _count_notification_context_event(campaign_id, "destination_opened", environment),
    }


def campaign_conversion_count(campaign_id, environment=None):
    """See module docstring's CONVERSION ATTRIBUTION section for the
    exact rule this implements."""
    environment = environment or _env()
    clicks = (
        db.session.query(ActivityEvent.firebase_uid, ActivityEvent.occurred_at)
        .filter(ActivityEvent.environment == environment)
        .filter(ActivityEvent.event_name == "destination_opened")
        .filter(ActivityEvent.notification_context["campaign_id"].astext == str(campaign_id))
        .filter(ActivityEvent.firebase_uid.isnot(None))
        .all()
    )
    if not clicks:
        return 0

    latest_click_by_user = {}
    for uid, occurred_at in clicks:
        if uid not in latest_click_by_user or occurred_at > latest_click_by_user[uid]:
            latest_click_by_user[uid] = occurred_at

    purchases = (
        db.session.query(
            ActivityEvent.firebase_uid, ActivityEvent.occurred_at, ActivityEvent.properties["purpose"].astext,
        )
        .filter(ActivityEvent.environment == environment)
        .filter(ActivityEvent.event_name == CONVERSION_EVENT_NAME)
        .filter(ActivityEvent.firebase_uid.in_(list(latest_click_by_user.keys())))
        .all()
    )
    converted_users = set()
    for uid, purchased_at, purpose in purchases:
        if purpose not in CONVERSION_PURPOSES:
            continue
        click_at = latest_click_by_user.get(uid)
        if click_at is None or purchased_at is None:
            continue
        if click_at <= purchased_at <= click_at + ATTRIBUTION_WINDOW:
            converted_users.add(uid)
    return len(converted_users)


def execution_metrics(execution, environment=None):
    """Full metrics contract for one execution -- the shape returned by
    the Admin execution-detail endpoint. See module docstring for exact
    numerator/denominator of every field."""
    counts = delivery_counts(execution.id)
    accepted = counts['ACCEPTED']
    opens = campaign_open_counts(execution.campaign_id, environment=environment)
    conversions = campaign_conversion_count(execution.campaign_id, environment=environment)
    return {
        'target_count': sum(counts.values()),
        'delivery_counts': counts,
        'notification_opened_count': opens['notification_opened_count'],
        'destination_opened_count': opens['destination_opened_count'],
        'open_rate': _rate(opens['notification_opened_count'], accepted),
        'destination_rate': _rate(opens['destination_opened_count'], opens['notification_opened_count']),
        'conversion_count': conversions,
        'conversion_rate': _rate(conversions, accepted),
    }
