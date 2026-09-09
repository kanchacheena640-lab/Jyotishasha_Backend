"""N5 due-scheduled-campaign discovery + claim + dispatch decision.

process_due_scheduled_campaigns() is the ONLY entry point that moves a
SCHEDULED execution forward in time. It is a plain, directly-callable
function -- deliberately NOT wired to Celery (celery_app.py requires
REDIS_URL at import time; N5 must not force that dependency onto local
tests, exactly mirroring campaign_worker.py's own established
precedent). Never called from any Flask route/request handler, never
started as a background thread on web-process startup, never triggered
by ordinary Flask request traffic (N5.20/21). A future controlled
activation step would call this on a periodic trigger (this repo's own
existing convention for that is a scheduled GitHub Actions workflow --
see .github/workflows/notifications.yml, unmodified and untouched by
N5) -- building that trigger is explicitly out of scope here.

This module NEVER calls Transport.send() -- see campaign_worker.py for
the only code that does. Dispatching a due execution here only ever
decides EXPIRED / BLOCKED / PAUSED / FROZEN; actual delivery attempts
against a FROZEN execution remain campaign_worker.process_execution()'s
job, called separately (by a test, or a future worker), exactly as N4
already established for Send Now.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from extensions import db
from modules.models_saved_audience import SavedAudience
from notifications.campaign_service import get_campaign
from notifications.campaign_execution_models import NotificationCampaignExecution
from notifications.campaign_execution_service import _drifted, _freeze_targets, _resolve_live
from notifications.saved_audience_recipient_resolver import RecipientResolutionError, resolve_saved_audience_recipients
from notifications.campaign_execution_service import LARGE_AUDIENCE_THRESHOLD


def _now():
    return datetime.now(timezone.utc)


def _claim_due_batch(now, batch_limit, worker_id, lease_seconds):
    """Same atomic-claim convention as campaign_worker.py's own
    _claim_batch(): row lock + SKIP LOCKED plus a compare-and-set lease,
    so two concurrent scheduler invocations can never claim the same
    due execution. Reuses the execution-level lease_owner/lease_
    generation/lease_until columns N4's migration already added but
    never used (N4 only ever leases individual deliveries)."""
    claimable = (db.session.query(NotificationCampaignExecution)
                 .filter(NotificationCampaignExecution.state == 'SCHEDULED',
                         NotificationCampaignExecution.scheduled_for.isnot(None),
                         NotificationCampaignExecution.scheduled_for <= now,
                         or_(NotificationCampaignExecution.lease_until.is_(None),
                             NotificationCampaignExecution.lease_until <= now))
                 .order_by(NotificationCampaignExecution.scheduled_for)
                 .limit(batch_limit)
                 .with_for_update(skip_locked=True)
                 .all())
    lease_until = now + timedelta(seconds=lease_seconds)
    for execution in claimable:
        execution.lease_owner = worker_id
        execution.lease_generation = (execution.lease_generation or 0) + 1
        execution.lease_until = lease_until
        execution.dispatch_started_at = execution.dispatch_started_at or now
    if claimable:
        db.session.commit()
    return claimable


def _block(execution, reason, now, *, matched_hint=None):
    """N5.16/17 -- an absolute, non-reconfirmable stop: no target
    freeze, no delivery rows, no transport. Distinct from PAUSED (which
    IS reconfirmable) -- BLOCKED requires a new campaign, exactly like
    any other N1 terminal-without-recovery outcome."""
    execution.state = 'BLOCKED'
    execution.hold_reason = reason
    execution.completed_at = now
    execution.updated_at = now
    execution.lease_owner = None
    execution.lease_until = None
    campaign = get_campaign(execution.campaign_id)
    campaign.state = 'FAILED'
    campaign.hold_reason = reason
    campaign.updated_at = now
    db.session.commit()


def _dispatch_due_execution(execution, now):
    """Runs the full N5.12-18 safety sequence for one claimed, due
    SCHEDULED execution. Every branch commits before returning -- never
    leaves an execution mid-decision."""
    # N5.12 -- expiry is checked BEFORE anything else touches live data.
    if execution.expires_at is not None and now >= execution.expires_at:
        execution.state = 'EXPIRED'
        execution.hold_reason = None
        execution.completed_at = now
        execution.updated_at = now
        execution.lease_owner = None
        execution.lease_until = None
        campaign = get_campaign(execution.campaign_id)
        campaign.state = 'FAILED'
        campaign.hold_reason = 'EXPIRED'
        campaign.updated_at = now
        db.session.commit()
        return

    # N5.17 -- approved audience must still exist/be active; a resolver
    # dependency failure is never treated as "zero recipients."
    audience = db.session.get(SavedAudience, execution.approved_saved_audience_id)
    if audience is None or not audience.is_active:
        _block(execution, 'AUDIENCE_UNAVAILABLE', now)
        return

    try:
        # N5.13/5.36 -- resolved against the APPROVED criteria snapshot,
        # via the same N2 authority (resolve_user_ids), never a second
        # filter engine and never the audience's possibly-since-edited
        # current criteria.
        resolution = resolve_saved_audience_recipients(
            execution.approved_saved_audience_id, approved_criteria=execution.approved_criteria)
    except RecipientResolutionError as exc:
        if exc.code == 'SAFETY_CEILING_EXCEEDED':
            # N5.16 -- absolute block, never a reconfirmable drift pause,
            # regardless of the count approved at schedule time.
            _block(execution, 'SAFETY_CEILING_EXCEEDED', now, matched_hint=exc.matched_user_count)
        else:
            _block(execution, 'RESOLUTION_UNAVAILABLE', now)
        return

    matched, eligible = resolution.matched_user_count, resolution.eligible_recipient_count

    # All Users was already confirmed at schedule time and cannot change
    # (the approved criteria snapshot is immutable) -- this is a
    # structural defense, not expected to ever actually trigger.
    if resolution.is_all_users and not execution.all_users_confirmed:
        _block(execution, 'ALL_USERS_NOT_CONFIRMED', now)
        return
    if max(matched, eligible) >= LARGE_AUDIENCE_THRESHOLD:
        execution.large_audience_acknowledged = True

    paused = _drifted(execution.baseline_matched_user_count, matched) or \
        _drifted(execution.baseline_eligible_recipient_count, eligible)

    execution.resolved_matched_user_count = matched
    execution.resolved_eligible_recipient_count = eligible
    execution.resolved_excluded_recipient_count = resolution.excluded_recipient_count
    execution.resolved_exclusion_counts = dict(resolution.exclusion_counts)
    execution.updated_at = now
    execution.lease_owner = None
    execution.lease_until = None

    campaign = get_campaign(execution.campaign_id)
    if paused:
        execution.state = 'PAUSED'
        execution.hold_reason = 'DRIFT'
        campaign.state = 'PROCESSING'
        campaign.hold_reason = 'DRIFT'
    else:
        execution.state = 'FROZEN'
        execution.hold_reason = None
        execution.frozen_at = now
        campaign.state = 'PROCESSING'
        campaign.hold_reason = None
        _freeze_targets(execution, resolution, now)
    campaign.updated_at = now
    db.session.commit()


def process_due_scheduled_campaigns(*, now=None, batch_limit=20, worker_id=None, lease_seconds=120):
    """Claims and dispatches at most `batch_limit` due SCHEDULED
    executions. Returns a structured summary; call again to drain
    further due work. Survives application/worker restart and Redis
    unavailability by construction -- the DB row is the only state that
    matters (N5.9)."""
    now = now or _now()
    worker_id = worker_id or f'scheduler-{uuid.uuid4().hex[:8]}'
    claimed = _claim_due_batch(now, batch_limit, worker_id, lease_seconds)
    results = []
    for execution in claimed:
        try:
            _dispatch_due_execution(execution, now)
            results.append({'execution_id': execution.id, 'state': execution.state, 'hold_reason': execution.hold_reason})
        except Exception as exc:
            db.session.rollback()
            results.append({'execution_id': execution.id, 'error': str(exc)})
    return {'claimed': len(claimed), 'results': results}
