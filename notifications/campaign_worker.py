"""N4 Send Now worker boundary (N1 Section 12/13/21, N4.18-21).

process_execution() is the ONLY function in this codebase that ever
calls Transport.send(). It is a plain, directly-callable function --
deliberately NOT wired to Celery (celery_app.py requires REDIS_URL at
import time; N4 must not force that dependency onto local tests, see
this module's own docstring note below). A future N5 worker process
can call this function on a schedule/queue with zero changes here.

Never called from routes/routes_admin_notifications.py or any HTTP
request handler -- Send Now's own route only validates, approves and
freezes (notifications/campaign_execution_service.py::send_now()),
then returns. Actual delivery processing happens only when this
function is invoked directly (by a test, or by a future N5 worker).

Commit-before-send ordering (N4.19): a delivery's attempt_count is
bumped and its attempt row inserted (outcome=NULL, the durable
"ATTEMPTING" marker) and COMMITTED before transport.send() is ever
called; the outcome is written in a SEPARATE commit afterward. A crash
between those two commits leaves a delivery leased with an open
(outcome IS NULL) attempt row; _reap_expired_leases() is what
reconciles that back to UNKNOWN on a later call (N1 Section 11:
"Expired ATTEMPTING rows become UNKNOWN unless a durable provider
result can be reconciled") -- it is NEVER silently retried.
"""
import uuid
from collections import Counter
from uuid import UUID
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from extensions import db
from modules.auth.models import User  # noqa: F401 -- not queried here; AppUser is the token authority (N1 Section 7)
from modules.models_user import AppUser
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
)
from notifications.campaign_transport import (
    Target, RenderedMessage, backoff_seconds,
    OUTCOME_ACCEPTED, OUTCOME_UNKNOWN, OUTCOME_FAILED_PERMANENT, OUTCOME_FAILED_RETRYABLE,
)

TERMINAL_DELIVERY_STATUSES = ('ACCEPTED', 'FAILED_PERMANENT', 'UNKNOWN', 'SUPPRESSED')
# N4 locked retry contract: attempt 1 is the initial delivery attempt;
# retries 1/2/3 are attempts 2/3/4. Maximum 4 transport attempts total
# (1 initial + up to 3 retries) -- never a 5th. Only SAFE_TO_RETRY
# outcomes (FAILED_RETRYABLE) consume a retry; UNKNOWN and permanent
# failures are terminal on their first occurrence regardless of this
# limit (see _classify_and_apply()).
MAX_ATTEMPTS = 4


def _now():
    return datetime.now(timezone.utc)


def _reap_expired_leases(execution_id, now):
    """N1 Section 11 -- a delivery whose lease expired while its latest
    attempt is still open (outcome IS NULL) never resumes as a fresh
    retry; it is reconciled to UNKNOWN with the open attempt closed out
    as unresolved. Runs BEFORE claiming any new work."""
    stale = (NotificationCampaignDelivery.query
             .filter(NotificationCampaignDelivery.execution_id == execution_id,
                     NotificationCampaignDelivery.lease_until.isnot(None),
                     NotificationCampaignDelivery.lease_until <= now,
                     NotificationCampaignDelivery.status.notin_(TERMINAL_DELIVERY_STATUSES))
             .all())
    for delivery in stale:
        open_attempt = (NotificationCampaignAttempt.query
                        .filter_by(delivery_id=delivery.id, outcome=None)
                        .order_by(NotificationCampaignAttempt.attempt_number.desc())
                        .first())
        if open_attempt is not None:
            open_attempt.outcome = OUTCOME_UNKNOWN
            open_attempt.finished_at = now
            open_attempt.error_code = 'LEASE_EXPIRED_UNRECONCILED'
            open_attempt.error_class = 'unknown'
            delivery.status = 'UNKNOWN'
        delivery.lease_owner = None
        delivery.lease_until = None
    if stale:
        db.session.commit()
    return len(stale)


def _claim_batch(execution_id, worker_id, batch_limit, lease_seconds, now):
    """Atomic claim (N4.20): row lock + SKIP LOCKED so two concurrent
    callers can never claim the same delivery, and a compare-and-set
    style lease (lease_until in the future) so an already-claimed-but-
    not-yet-leased-expired row is invisible to a second caller. No
    Python-process-memory lock is involved."""
    claimable = (db.session.query(NotificationCampaignDelivery)
                 .filter(NotificationCampaignDelivery.execution_id == execution_id,
                         NotificationCampaignDelivery.status.in_(('PENDING', 'FAILED_RETRYABLE')),
                         or_(NotificationCampaignDelivery.next_attempt_at.is_(None),
                             NotificationCampaignDelivery.next_attempt_at <= now),
                         or_(NotificationCampaignDelivery.lease_until.is_(None),
                             NotificationCampaignDelivery.lease_until <= now))
                 .order_by(NotificationCampaignDelivery.created_at)
                 .limit(batch_limit)
                 .with_for_update(skip_locked=True)
                 .all())
    lease_until = now + timedelta(seconds=lease_seconds)
    for delivery in claimable:
        delivery.lease_owner = worker_id
        delivery.lease_until = lease_until
    if claimable:
        db.session.commit()
    return claimable


def _build_message(execution):
    return RenderedMessage(
        title=execution.approved_title, body=execution.approved_body,
        data={
            'contract_version': '1', 'source': 'ADMIN_CAMPAIGN',
            'campaign_id': str(execution.campaign_id), 'execution_id': str(execution.id),
            'action_registry_version': '1',
            'action_type': execution.approved_action.get('type'),
            'action_target': execution.approved_action.get('target') or '',
            'action_parameters': execution.approved_action.get('parameters') or {},
        },
    )


def _classify_and_apply(delivery, attempt, attempt_number, result, now):
    attempt.outcome = result.outcome
    attempt.finished_at = now
    attempt.error_code = result.error_code
    attempt.error_class = result.error_class
    delivery.lease_owner = None
    delivery.lease_until = None

    if result.outcome == OUTCOME_ACCEPTED:
        delivery.status = 'ACCEPTED'
        delivery.accepted_at = now
        delivery.next_attempt_at = None
    elif result.outcome == OUTCOME_UNKNOWN:
        # N1/N4.16 -- critical: UNKNOWN is terminal to the automatic
        # retry scheduler. next_attempt_at stays None; only explicit
        # later reconciliation (not built in N4) may change this.
        delivery.status = 'UNKNOWN'
        delivery.next_attempt_at = None
    elif result.outcome == OUTCOME_FAILED_PERMANENT or result.invalid_token:
        delivery.status = 'FAILED_PERMANENT'
        delivery.next_attempt_at = None
    elif result.outcome == OUTCOME_FAILED_RETRYABLE:
        if attempt_number >= MAX_ATTEMPTS:
            delivery.status = 'FAILED_PERMANENT'
            # Overwrite (not "or") -- exhaustion is itself the reason
            # this delivery is now permanent, regardless of what the
            # final individual attempt's own transport error_code was.
            attempt.error_code = 'RETRY_EXHAUSTED'
            delivery.next_attempt_at = None
        else:
            delivery.status = 'FAILED_RETRYABLE'
            delivery.next_attempt_at = now + timedelta(seconds=backoff_seconds(attempt_number))
    else:
        # Any unrecognized outcome value fails closed to UNKNOWN rather
        # than being silently retried or treated as success.
        delivery.status = 'UNKNOWN'
        delivery.next_attempt_at = None


def _finalize_if_complete(execution, now):
    from notifications.campaign_service import get_campaign
    counts = Counter(
        status for (status,) in
        db.session.query(NotificationCampaignDelivery.status)
        .filter(NotificationCampaignDelivery.execution_id == execution.id).all()
    )
    remaining = counts['PENDING'] + counts['FAILED_RETRYABLE']
    if remaining > 0:
        return False
    accepted = counts['ACCEPTED']
    total = sum(counts.values())
    if total == 0 or accepted == total:
        execution.state = 'COMPLETED'
    elif accepted > 0:
        execution.state = 'PARTIAL'
    else:
        execution.state = 'FAILED'
    execution.completed_at = now
    campaign = get_campaign(execution.campaign_id)
    campaign.state = execution.state
    campaign.hold_reason = None
    campaign.updated_at = now
    db.session.commit()
    return True


def process_execution(execution_id, transport, *, batch_limit=100, worker_id=None, lease_seconds=120):
    """Claims and attempts at most `batch_limit` due deliveries for one
    FROZEN/SENDING execution, using `transport` (NoSendTransport in
    production-shaped local/test code, FakeTransport in tests -- never
    a real Firebase-calling class in N4, see campaign_transport.py's
    own docstring). Returns a small summary dict; call again to drain
    further batches or process deliveries whose backoff has elapsed."""
    worker_id = worker_id or f'worker-{uuid.uuid4().hex[:8]}'
    now = _now()
    try:
        execution_id = str(UUID(str(execution_id)))
    except ValueError:
        raise ValueError('execution_id is not a valid UUID') from None
    execution = db.session.get(NotificationCampaignExecution, execution_id)
    if execution is None:
        raise ValueError('execution not found')
    if execution.state not in ('FROZEN', 'SENDING'):
        return {'claimed': 0, 'attempted': 0, 'suppressed': 0, 'reaped': 0, 'finalized': False}

    reaped = _reap_expired_leases(execution.id, now)
    claimable = _claim_batch(execution.id, worker_id, batch_limit, lease_seconds, now)

    if not claimable:
        finalized = _finalize_if_complete(execution, _now())
        return {'claimed': 0, 'attempted': 0, 'suppressed': 0, 'reaped': reaped, 'finalized': finalized}

    if execution.state == 'FROZEN':
        execution.state = 'SENDING'
        execution.started_at = execution.started_at or now
        db.session.commit()

    app_user_ids = [d.app_user_id for d in claimable]
    tokens = dict(
        db.session.query(AppUser.id, AppUser.fcm_token)
        .filter(AppUser.id.in_(app_user_ids)).all()
    )
    normalized = {aid: (tok or '').strip() for aid, tok in tokens.items()}
    token_counts = Counter(t for t in normalized.values() if t)
    message = _build_message(execution)

    attempted = 0
    suppressed = 0
    for delivery in claimable:
        token = normalized.get(delivery.app_user_id, '')
        if not token:
            delivery.status = 'SUPPRESSED'
            delivery.suppression_reason = 'MISSING_TOKEN'
            delivery.lease_owner = None
            delivery.lease_until = None
            db.session.commit()
            suppressed += 1
            continue
        if token_counts[token] > 1:
            # N1 Section 7 -- ownership/token changed since target
            # freeze into an ambiguous state; never guess which owner.
            delivery.status = 'SUPPRESSED'
            delivery.suppression_reason = 'TARGET_CHANGED'
            delivery.lease_owner = None
            delivery.lease_until = None
            db.session.commit()
            suppressed += 1
            continue

        attempt_number = delivery.attempt_count + 1
        started = _now()
        attempt = NotificationCampaignAttempt(
            delivery_id=delivery.id, attempt_number=attempt_number,
            started_at=started, outcome=None, provider=getattr(transport, 'provider', 'unknown'),
        )
        db.session.add(attempt)
        delivery.attempt_count = attempt_number
        delivery.first_attempted_at = delivery.first_attempted_at or started
        delivery.last_attempted_at = started
        # Durable pre-invocation commit (N1 Section 11 / N4.19) --
        # nothing below this line may run before this commit succeeds.
        db.session.commit()

        target = Target(user_id=delivery.user_id, app_user_id=delivery.app_user_id, fcm_token=token)
        try:
            result = transport.send(target, message)
        except Exception:
            from notifications.campaign_transport import TransportResult
            result = TransportResult(outcome=OUTCOME_UNKNOWN, provider=getattr(transport, 'provider', 'unknown'),
                                     error_code='transport_exception', error_class='unknown')

        finished = _now()
        _classify_and_apply(delivery, attempt, attempt_number, result, finished)
        db.session.commit()
        attempted += 1

    finalized = _finalize_if_complete(execution, _now())
    return {'claimed': len(claimable), 'attempted': attempted, 'suppressed': suppressed,
            'reaped': reaped, 'finalized': finalized}


# P3A -- the one addition this phase makes to this module: a read-only
# "which executions is a worker allowed to touch" query, so a production
# runner (scripts/campaign_worker_runner.py) never has to know the state
# contract itself (never a second, hand-copied state list anywhere else).
# Deliberately NOT a new capability -- process_execution() ALREADY only
# ever acts on 'FROZEN'/'SENDING' (see its own guard above); this
# function only makes "which execution ids currently qualify" a
# reusable, single-source-of-truth query instead of every caller
# re-deriving the same WHERE clause. Never touches SCHEDULED (that is
# campaign_scheduler.py's own, still-inactive, job -- not this one) or
# any terminal/paused state.
WORKER_PROCESSABLE_STATES = ('FROZEN', 'SENDING')


def discover_processable_executions(limit=20):
    """Read-only. Returns up to `limit` execution ids currently in a
    state process_execution() is willing to act on, oldest-frozen-first
    (so a backlog drains in the order it was approved, not arbitrarily).
    Never claims/locks anything itself -- process_execution()'s own
    FOR UPDATE SKIP LOCKED claim (per execution, per delivery) is what
    actually makes concurrent callers safe; this is purely discovery."""
    rows = (
        db.session.query(NotificationCampaignExecution.id)
        .filter(NotificationCampaignExecution.state.in_(WORKER_PROCESSABLE_STATES))
        .order_by(NotificationCampaignExecution.frozen_at.asc().nullsfirst(),
                  NotificationCampaignExecution.created_at.asc())
        .limit(limit)
        .all()
    )
    return [row.id for row in rows]
