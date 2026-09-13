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
  attempted_count             = target_count - delivery_counts.PENDING -
                                delivery_counts.SUPPRESSED. By
                                campaign_worker.py's own construction
                                (_claim_batch/_classify_and_apply),
                                every OTHER status (ACCEPTED,
                                FAILED_RETRYABLE, FAILED_PERMANENT,
                                UNKNOWN) is reached ONLY after at least
                                one NotificationCampaignAttempt row was
                                actually created for that delivery --
                                PENDING (never claimed yet) and
                                SUPPRESSED (missing/ambiguous token at
                                claim time, no transport call made) are
                                the only two statuses where zero attempts
                                exist. Exact, not approximated -- no new
                                column, no schema change.
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
  retry_exhausted_count       = of the deliveries counted in
                                delivery_counts.FAILED_PERMANENT, how
                                many reached that status ONLY because
                                MAX_ATTEMPTS was reached on an otherwise-
                                retryable outcome -- never a genuinely
                                permanent rejection (bad token, a hard
                                FCM error). Reliably derivable WITHOUT a
                                schema change: campaign_worker.py's own
                                _classify_and_apply() explicitly
                                overwrites that delivery's LATEST
                                attempt's error_code to the literal
                                sentinel 'RETRY_EXHAUSTED' at the exact
                                moment exhaustion (not a permanent
                                classification) is what caused the
                                FAILED_PERMANENT transition -- this
                                queries that existing, already-persisted
                                value; it invents nothing.
  permanent_failure_count     = delivery_counts.FAILED_PERMANENT -
                                retry_exhausted_count -- a genuinely
                                permanent rejection (invalid token, or
                                an FCM outcome classified
                                FAILED_PERMANENT on the very first
                                attempt that mattered), never merged
                                with retry exhaustion.
  notification_opened_count  = COUNT(activity_events WHERE event_name=
                                'notification_opened' AND
                                notification_context.campaign_id ==
                                str(this campaign's id)), scoped to the
                                current ACTIVITY_EVENTS_ENVIRONMENT.
                                Correlated by campaign identity only
                                (execution:campaign is 1:1 in this
                                system -- NotificationCampaignExecution.
                                campaign_id is UNIQUE) -- two different
                                campaigns' opens can never merge. As of
                                the Campaign C Analytics Hardening pass,
                                the Flutter client attaches a stable,
                                per-notification idempotency_key
                                (notification_opened_producer.dart) to
                                this event, so this COUNT already
                                reflects deduplicated, unique physical
                                opens -- a repeated getInitialMessage/
                                onMessageOpenedApp dispatch or a
                                duplicate tap for the SAME notification
                                can never inflate it (the backend's own
                                pre-existing partial unique index on
                                activity_events.dedupe_key, ux_activity_
                                events_dedupe_key, silently collapses
                                the retry to the same row -- no new
                                infrastructure was added here).
  destination_opened_count   = same query, event_name='destination_opened'
                                -- a GENUINELY DISTINCT client-observed
                                moment (the app actually reached the
                                notification's destination screen, not
                                merely that the OS notification was
                                tapped). See event_schemas.py's own
                                registration comment for why this is a
                                new event, not a rename/reuse of
                                notification_opened. Same idempotency-key
                                protection as notification_opened above
                                (destination_opened_producer.dart), using
                                a DIFFERENT key namespace so the two
                                events can never collide with each other.
  open_rate                  = notification_opened_count / ACCEPTED, or
                                "UNKNOWN" when ACCEPTED == 0.
  destination_rate           = destination_opened_count /
                                notification_opened_count, or "UNKNOWN"
                                when notification_opened_count == 0.
  conversion_count           = report_conversion_count +
                                ask_now_conversion_count +
                                subscription_conversion_count -- see
                                CONVERSION ATTRIBUTION below. Identical
                                value to this module's pre-hardening
                                combined-only conversion_count (same
                                qualifying clicks/purchases/window; only
                                the per-user winning purchase's own
                                purpose is now also recorded).
  conversion_rate            = conversion_count / ACCEPTED, or "UNKNOWN"
                                when ACCEPTED == 0.
  report_conversion_count     = of the attributed converted users, how
                                many were attributed to a REPORT_PURCHASE
                                (see CONVERSION ATTRIBUTION).
  ask_now_conversion_count    = same, for ASK_NOW_CHAT_PACK.
  subscription_conversion_count = same, for SUBSCRIPTION.

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

  Per-purpose breakdown (Campaign C Analytics Hardening addition, same
  algorithm, no change to who counts as converted): when a converted
  user has more than one qualifying purchase inside their own window
  (e.g. a Report purchase, then later a Subscription, both within 24h of
  the same click), the EARLIEST qualifying purchase (chronologically) is
  the one whose purpose that user is attributed to -- deterministic, and
  the user still contributes to `conversion_count` exactly once, exactly
  as before this addition. This tie-break is new bookkeeping only; it
  was never observable before this pass because only a single combined
  total existed.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import timedelta

from sqlalchemy import and_, func

from extensions import db
from modules.models_activity_events import ActivityEvent
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
)

ATTRIBUTION_WINDOW = timedelta(hours=24)

# The ONLY events this module treats as a genuine purchase conversion.
CONVERSION_EVENT_NAME = "payment_verified"
CONVERSION_PURPOSES = frozenset({"REPORT_PURCHASE", "ASK_NOW_CHAT_PACK", "SUBSCRIPTION"})

# campaign_worker.py::_classify_and_apply()'s own literal sentinel,
# written to a delivery's LATEST attempt's error_code ONLY when
# MAX_ATTEMPTS was reached on an otherwise-retryable outcome -- read
# here verbatim, never redefined independently, so the two files can
# never silently drift apart.
RETRY_EXHAUSTED_ERROR_CODE = 'RETRY_EXHAUSTED'

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


def campaign_conversion_breakdown(campaign_id, environment=None):
    """See module docstring's CONVERSION ATTRIBUTION section (including
    its per-purpose breakdown tie-break) for the exact rule this
    implements. Returns a dict with 'report_conversion_count',
    'ask_now_conversion_count', 'subscription_conversion_count', and
    'conversion_count' (their sum -- identical to the pre-hardening
    combined-only total for the same inputs)."""
    environment = environment or _env()
    zero = {
        'report_conversion_count': 0, 'ask_now_conversion_count': 0,
        'subscription_conversion_count': 0, 'conversion_count': 0,
    }
    clicks = (
        db.session.query(ActivityEvent.firebase_uid, ActivityEvent.occurred_at)
        .filter(ActivityEvent.environment == environment)
        .filter(ActivityEvent.event_name == "destination_opened")
        .filter(ActivityEvent.notification_context["campaign_id"].astext == str(campaign_id))
        .filter(ActivityEvent.firebase_uid.isnot(None))
        .all()
    )
    if not clicks:
        return zero

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
        .order_by(ActivityEvent.occurred_at.asc())
        .all()
    )
    # Single-touch: each user is attributed at most once, to the
    # EARLIEST qualifying purchase in their own window (deterministic
    # tie-break -- see module docstring). A user already attributed is
    # never re-attributed to a later purchase, matching the exact same
    # "counts once, period" contract the pre-hardening combined-only
    # function already enforced via its own `set`.
    attributed_purpose_by_user = {}
    for uid, purchased_at, purpose in purchases:
        if purpose not in CONVERSION_PURPOSES:
            continue
        if uid in attributed_purpose_by_user:
            continue
        click_at = latest_click_by_user.get(uid)
        if click_at is None or purchased_at is None:
            continue
        if click_at <= purchased_at <= click_at + ATTRIBUTION_WINDOW:
            attributed_purpose_by_user[uid] = purpose

    by_purpose = Counter(attributed_purpose_by_user.values())
    return {
        'report_conversion_count': by_purpose.get('REPORT_PURCHASE', 0),
        'ask_now_conversion_count': by_purpose.get('ASK_NOW_CHAT_PACK', 0),
        'subscription_conversion_count': by_purpose.get('SUBSCRIPTION', 0),
        'conversion_count': len(attributed_purpose_by_user),
    }


def campaign_conversion_count(campaign_id, environment=None):
    """Backward-compatible combined total -- unchanged public contract
    (still a plain int). Delegates to campaign_conversion_breakdown()
    rather than re-deriving the rule a second time; the returned int is
    identical to what this function always returned."""
    return campaign_conversion_breakdown(campaign_id, environment=environment)['conversion_count']


def failed_permanent_breakdown(execution_id, failed_permanent_total):
    """Splits delivery_counts.FAILED_PERMANENT into 'retry_exhausted_
    count' and 'permanent_failure_count' -- see module docstring. Reads
    only the already-persisted NotificationCampaignAttempt.error_code
    sentinel campaign_worker.py itself writes; never a new column,
    never a heuristic/guess. Short-circuits to all-zero when there are
    no FAILED_PERMANENT deliveries at all -- no query needed."""
    if not failed_permanent_total:
        return {'retry_exhausted_count': 0, 'permanent_failure_count': 0}

    latest_attempt_numbers = (
        db.session.query(
            NotificationCampaignAttempt.delivery_id,
            func.max(NotificationCampaignAttempt.attempt_number).label('max_attempt_number'),
        )
        .join(NotificationCampaignDelivery, NotificationCampaignDelivery.id == NotificationCampaignAttempt.delivery_id)
        .filter(NotificationCampaignDelivery.execution_id == execution_id)
        .filter(NotificationCampaignDelivery.status == 'FAILED_PERMANENT')
        .group_by(NotificationCampaignAttempt.delivery_id)
        .subquery()
    )
    retry_exhausted_count = (
        db.session.query(func.count(NotificationCampaignAttempt.id))
        .join(
            latest_attempt_numbers,
            and_(
                NotificationCampaignAttempt.delivery_id == latest_attempt_numbers.c.delivery_id,
                NotificationCampaignAttempt.attempt_number == latest_attempt_numbers.c.max_attempt_number,
            ),
        )
        .filter(NotificationCampaignAttempt.error_code == RETRY_EXHAUSTED_ERROR_CODE)
        .scalar() or 0
    )
    return {
        'retry_exhausted_count': retry_exhausted_count,
        'permanent_failure_count': failed_permanent_total - retry_exhausted_count,
    }


def execution_metrics(execution, environment=None):
    """Full metrics contract for one execution -- the shape returned by
    the Admin execution-detail endpoint. See module docstring for exact
    numerator/denominator of every field."""
    counts = delivery_counts(execution.id)
    accepted = counts['ACCEPTED']
    attempted_count = sum(counts.values()) - counts['PENDING'] - counts['SUPPRESSED']
    failed_breakdown = failed_permanent_breakdown(execution.id, counts['FAILED_PERMANENT'])
    opens = campaign_open_counts(execution.campaign_id, environment=environment)
    conversions = campaign_conversion_breakdown(execution.campaign_id, environment=environment)
    return {
        'target_count': sum(counts.values()),
        'attempted_count': attempted_count,
        'delivery_counts': counts,
        'retry_exhausted_count': failed_breakdown['retry_exhausted_count'],
        'permanent_failure_count': failed_breakdown['permanent_failure_count'],
        'notification_opened_count': opens['notification_opened_count'],
        'destination_opened_count': opens['destination_opened_count'],
        'open_rate': _rate(opens['notification_opened_count'], accepted),
        'destination_rate': _rate(opens['destination_opened_count'], opens['notification_opened_count']),
        'conversion_count': conversions['conversion_count'],
        'report_conversion_count': conversions['report_conversion_count'],
        'ask_now_conversion_count': conversions['ask_now_conversion_count'],
        'subscription_conversion_count': conversions['subscription_conversion_count'],
        'conversion_rate': _rate(conversions['conversion_count'], accepted),
    }
