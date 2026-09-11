"""N5 Schedule: future-UTC campaign scheduling, reusing N4's approval/
drift/target-freeze architecture rather than duplicating it. This module
never calls transport/network -- scheduling only ever creates a
SCHEDULED execution row; dispatch of a DUE execution happens exclusively
in notifications/campaign_scheduler.py (which itself still never calls
transport -- see that module's own docstring), and actual delivery
attempts remain exclusively notifications/campaign_worker.py's job.

CRITICAL DISTINCTION (N5.4/N5.8): unlike send_now(), which trusts a
recently-fetched CLIENT-supplied preview as the drift baseline (safe
only because approval and resolution happen in the same request, with
no meaningful time gap for the audience to change), schedule_campaign()
NEVER trusts a client-supplied baseline. The baseline persisted here is
always the result of this function's OWN authoritative backend
resolution, performed at schedule-approval time -- the browser-supplied
`preview_generated_at` is used ONLY as a "did you look recently enough"
freshness gate (N5.6), never as a source of truth for any count.

Recipient MEMBERSHIP is never materialized here (N5.4): scheduling
freezes the campaign DEFINITION (criteria/title/body/action snapshot,
exactly like send_now()'s own approval-freeze), not membership. No
NotificationCampaignDelivery row is ever created by this module.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from extensions import db
from notifications.campaign_service import CampaignError, fail, get_campaign, audience_definition
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
    NotificationSendNowRequest,
)
from notifications.campaign_execution_service import (
    ALL_USERS_PHRASE, LARGE_AUDIENCE_THRESHOLD, PREVIEW_MAX_AGE,
    _now, _parse_utc, _resolve_live, serialize_execution,
)
from notifications.campaign_bell_service import dismiss_bell_items_for_execution

MAX_SCHEDULE_KEY_LENGTH = 128
# N5.28 -- a small safety floor, not an arbitrary large minimum delay:
# guards only against a request that is already in flight (network
# latency, a slow click) landing after "now" has ticked past a
# just-selected time, which would otherwise make an intended-future
# schedule look immediately due. Genuinely arbitrary future timestamps
# beyond this are always accepted.
MIN_SCHEDULE_LEAD = timedelta(seconds=60)
DEFAULT_EXPIRY_WINDOW = timedelta(hours=24)  # N1 Section 20/N5.12 locked default


def _schedule_request_hash(campaign_id, data):
    canonical = {
        'campaign_id': campaign_id,
        'revision': data.get('revision'),
        'scheduled_for': data.get('scheduled_for'),
        'expires_at': data.get('expires_at'),
        'preview_generated_at': data.get('preview_generated_at'),
        'all_users_phrase_correct': data.get('confirmation_phrase') == ALL_USERS_PHRASE,
        'large_audience_acknowledged': data.get('large_audience_acknowledged') is True,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _validate_schedule_request(data):
    if not isinstance(data, dict):
        fail('invalid_input', 'Expected a JSON object.')
    idempotency_key = data.get('idempotency_key')
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > MAX_SCHEDULE_KEY_LENGTH:
        fail('invalid_input', 'idempotency_key is required and must be a bounded non-empty string.')
    revision = data.get('revision')
    if type(revision) is not int or revision <= 0:
        fail('invalid_input', 'revision must be a positive integer.')

    preview_generated_at = _parse_utc(data.get('preview_generated_at'), 'preview_generated_at')
    scheduled_for = _parse_utc(data.get('scheduled_for'), 'scheduled_for')
    now = _now()
    if scheduled_for < now + MIN_SCHEDULE_LEAD:
        fail('invalid_schedule_time', 'scheduled_for must be at least 60 seconds in the future.')

    if 'expires_at' in data and data['expires_at'] is not None:
        expires_at = _parse_utc(data['expires_at'], 'expires_at')
        if expires_at <= scheduled_for:
            fail('invalid_expiry', 'expires_at must be after scheduled_for.')
        if expires_at > scheduled_for + DEFAULT_EXPIRY_WINDOW:
            fail('invalid_expiry', 'expires_at cannot exceed scheduled_for + 24 hours.')
    else:
        expires_at = scheduled_for + DEFAULT_EXPIRY_WINDOW

    allowed = {'idempotency_key', 'revision', 'scheduled_for', 'expires_at', 'preview_generated_at',
               'confirmation_phrase', 'large_audience_acknowledged'}
    if set(data) - allowed:
        fail('unknown_fields', 'Unknown Schedule fields are not allowed.')
    return idempotency_key, revision, preview_generated_at, scheduled_for, expires_at


def schedule_campaign(campaign_id, data, actor=None):
    idempotency_key, revision, preview_generated_at, scheduled_for, expires_at = _validate_schedule_request(data)
    campaign = get_campaign(campaign_id)
    request_hash = _schedule_request_hash(campaign.id, data)

    existing_request = NotificationSendNowRequest.query.filter_by(
        campaign_id=campaign.id, idempotency_key=idempotency_key).first()
    if existing_request is not None:
        if existing_request.request_hash != request_hash:
            fail('idempotency_conflict', 'This idempotency key was already used for a different Schedule request.', 409)
        return existing_request.response_body, existing_request.response_status

    if campaign.state != 'DRAFT':
        fail('invalid_state', 'Only a DRAFT campaign can be scheduled.', 409)
    if revision != campaign.revision:
        fail('stale_revision', 'Draft changed in another tab. Reload before scheduling.', 409)
    if _now() - preview_generated_at > PREVIEW_MAX_AGE:
        fail('preview_stale', 'Recipient preview is more than 15 minutes old. Refresh the preview and try again.', 409)

    audience_row, criteria, digest = audience_definition(campaign.saved_audience_id, require_active=True)
    # Authoritative backend resolution -- becomes the persisted baseline.
    # Never the client's own counts (N5.8's explicit correction of the
    # weakness that is only safe for N4's immediate Send Now).
    resolution = _resolve_live(campaign.saved_audience_id)
    matched, eligible = resolution.matched_user_count, resolution.eligible_recipient_count

    if resolution.is_all_users:
        if data.get('confirmation_phrase') != ALL_USERS_PHRASE:
            fail('all_users_confirmation_required',
                 f'Type exactly "{ALL_USERS_PHRASE}" to confirm scheduling to All Users.', 400)
        all_users_confirmed = True
    else:
        all_users_confirmed = False

    large_audience = max(matched, eligible) >= LARGE_AUDIENCE_THRESHOLD
    if large_audience:
        if data.get('large_audience_acknowledged') is not True:
            fail('large_audience_acknowledgement_required',
                 'Acknowledge the large-audience warning to continue.', 400)
        large_audience_acknowledged = True
    else:
        large_audience_acknowledged = False

    now = _now()
    execution = NotificationCampaignExecution(
        campaign_id=campaign.id,
        state='SCHEDULED',
        approved_saved_audience_id=audience_row.id,
        approved_criteria=criteria, approved_criteria_version=criteria['version'], approved_criteria_hash=digest,
        approved_title=campaign.title, approved_body=campaign.body, approved_action=campaign.action,
        all_users_confirmed=all_users_confirmed, large_audience_acknowledged=large_audience_acknowledged,
        # Baseline == this same authoritative resolution -- resolved and
        # recorded are identical at creation; they diverge only once a
        # later (due-time or reconfirm) resolution runs.
        baseline_generated_at=now, baseline_matched_user_count=matched, baseline_eligible_recipient_count=eligible,
        baseline_recorded_at=now,
        resolved_matched_user_count=matched, resolved_eligible_recipient_count=eligible,
        resolved_excluded_recipient_count=resolution.excluded_recipient_count,
        resolved_exclusion_counts=dict(resolution.exclusion_counts),
        resolver_policy_version='N1-P1-v1',
        scheduled_for=scheduled_for, expires_at=expires_at,
        created_by=actor, created_at=now, updated_at=now,
    )
    db.session.add(execution)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return _lost_schedule_race(campaign.id, idempotency_key, request_hash)

    campaign.state = 'SCHEDULED'
    campaign.hold_reason = None
    campaign.updated_at = now
    # N5.4 -- deliberately NO delivery rows here. Membership is not
    # materialized at schedule time, only the definition is frozen.

    response_body = serialize_execution(execution)
    response_status = 202
    db.session.add(NotificationSendNowRequest(
        campaign_id=campaign.id, idempotency_key=idempotency_key, request_hash=request_hash,
        execution_id=execution.id, response_status=response_status, response_body=response_body, created_at=now,
    ))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _lost_schedule_race(campaign.id, idempotency_key, request_hash)
    return response_body, response_status


def _lost_schedule_race(campaign_id, idempotency_key, request_hash):
    winner = NotificationSendNowRequest.query.filter_by(
        campaign_id=campaign_id, idempotency_key=idempotency_key).first()
    if winner is not None and winner.request_hash == request_hash:
        return winner.response_body, winner.response_status
    fail('execution_already_exists', 'A scheduled execution already exists for this campaign.', 409)


def reschedule(execution_id, data, actor=None):
    """N5.23 v1 rule: only scheduled_for/expires_at may change, and only
    while state=SCHEDULED (never yet claimed/due/processing). Title,
    body, action, audience definition and baseline are untouched -- if
    those need to change, the existing flow is cancel + new draft, not
    a mutation of an approved scheduled definition."""
    if not isinstance(data, dict):
        fail('invalid_input', 'Expected a JSON object.')
    allowed = {'scheduled_for', 'expires_at'}
    if not set(data) or set(data) - allowed:
        fail('unknown_fields', 'Reschedule accepts only scheduled_for and optional expires_at.')

    execution = db.session.get(NotificationCampaignExecution, str(execution_id))
    if execution is None:
        fail('not_found', 'Execution not found.', 404)
    if execution.state != 'SCHEDULED':
        fail('invalid_state', 'Only a SCHEDULED (not yet due/claimed) execution can be rescheduled.', 409)

    now = _now()
    scheduled_for = _parse_utc(data.get('scheduled_for'), 'scheduled_for')
    if scheduled_for < now + MIN_SCHEDULE_LEAD:
        fail('invalid_schedule_time', 'scheduled_for must be at least 60 seconds in the future.')
    if 'expires_at' in data and data['expires_at'] is not None:
        expires_at = _parse_utc(data['expires_at'], 'expires_at')
        if expires_at <= scheduled_for:
            fail('invalid_expiry', 'expires_at must be after scheduled_for.')
        if expires_at > scheduled_for + DEFAULT_EXPIRY_WINDOW:
            fail('invalid_expiry', 'expires_at cannot exceed scheduled_for + 24 hours.')
    else:
        expires_at = scheduled_for + DEFAULT_EXPIRY_WINDOW

    execution.scheduled_for = scheduled_for
    execution.expires_at = expires_at
    execution.updated_at = now
    db.session.commit()
    return serialize_execution(execution), 200


def cancel(execution_id, actor=None):
    """N5.24 (pre-freeze) + P4.5 (post-freeze, provably-unsent FROZEN --
    see _cancel_unsent_frozen()'s own docstring for that narrower
    contract). Idempotent either way: cancelling an already-CANCELLED
    execution is a no-op success. Once SENDING or any terminal state
    other than CANCELLED, cancellation is refused outright rather than
    returning a misleading success that does not actually guarantee no
    send -- a FROZEN execution with even one recorded attempt falls
    into this same refusal, not the P4.5 path.

    Row-locks `execution` (SELECT ... FOR UPDATE) before deciding
    anything -- belt-and-suspenders against two concurrent cancel calls
    racing each other; _cancel_unsent_frozen() below takes its OWN,
    separate lock on the delivery rows, which is the lock that actually
    matters against a concurrently-running worker (see that function's
    own docstring)."""
    execution = (
        db.session.query(NotificationCampaignExecution)
        .filter_by(id=str(execution_id))
        .with_for_update()
        .first()
    )
    if execution is None:
        fail('not_found', 'Execution not found.', 404)
    if execution.state == 'CANCELLED':
        return serialize_execution(execution), 200
    if execution.state in ('SCHEDULED', 'PAUSED'):
        return _cancel_prefreeze(execution)
    if execution.state == 'FROZEN':
        return _cancel_unsent_frozen(execution)
    fail('invalid_state',
         'Only a SCHEDULED/PAUSED (pre-freeze) execution, or a FROZEN execution with zero '
         'transport attempts, can be cancelled.', 409)


def _cancel_prefreeze(execution):
    now = _now()
    execution.state = 'CANCELLED'
    execution.hold_reason = None
    execution.completed_at = now
    execution.updated_at = now
    campaign = get_campaign(execution.campaign_id)
    campaign.state = 'CANCELLED'
    campaign.hold_reason = None
    campaign.updated_at = now
    db.session.commit()
    return serialize_execution(execution), 200


def _cancel_unsent_frozen(execution):
    """P4.5 -- cancels a FROZEN execution that is PROVABLY unsent: no
    transport attempt has ever been made for any of its targets. A much
    narrower contract than _cancel_prefreeze() above -- once ANY attempt
    has occurred, cancellation is refused outright, exactly like the
    pre-freeze path already refuses once FROZEN/SENDING/terminal (never
    a misleading success that doesn't actually guarantee nothing was
    sent). Required, jointly, before this may proceed:
      - execution.started_at IS NULL -- process_execution() sets this,
        together with flipping state to SENDING, the moment it
        successfully claims ANY delivery (campaign_worker.py); if this
        is set, a send attempt has begun and cancellation is refused.
      - every delivery.status == 'PENDING'
      - every delivery.attempt_count == 0
      - no delivery currently has a live lease (lease_owner set, or
        lease_until in the future) -- a worker may be mid-claim
      - zero NotificationCampaignAttempt rows across every delivery

    Concurrency: the caller (cancel() above) already holds a row lock
    on `execution` itself, which does NOT by itself block
    campaign_worker.py's own _claim_batch() -- that locks DELIVERY
    rows, not the execution row. This function additionally takes its
    own FOR UPDATE lock on every delivery row belonging to this
    execution before making its decision. _claim_batch() locks those
    exact same rows with FOR UPDATE SKIP LOCKED, so whichever side
    acquires the delivery locks first genuinely wins the race: if a
    worker got there first, its deliveries are no longer all-PENDING/
    unleased by the time this function's own check runs, so
    cancellation is correctly refused; if this function gets there
    first, the worker's SKIP LOCKED claim simply sees zero claimable
    rows this pass and moves on -- it never blocks waiting on us.

    On success: execution/campaign -> CANCELLED (an existing, already-
    valid state for both -- no migration needed), every delivery ->
    SUPPRESSED with suppression_reason='ADMIN_CANCELLED' (a new, freely
    allowed string value -- suppression_reason has no CHECK constraint),
    and every still-visible Bell row for this execution is dismissed
    (presentation-only, see dismiss_bell_items_for_execution()'s own
    docstring) -- all in ONE commit. Nothing is ever deleted: campaign,
    execution, delivery, attempt, and Bell rows all remain exactly as
    they are for audit/history/monitoring -- only their state/visibility
    changes."""
    now = _now()
    if execution.started_at is not None:
        fail('invalid_state', 'This execution has already started sending -- it can no longer be cancelled.', 409)

    deliveries = (
        db.session.query(NotificationCampaignDelivery)
        .filter(NotificationCampaignDelivery.execution_id == execution.id)
        .with_for_update()
        .all()
    )
    for delivery in deliveries:
        if delivery.status != 'PENDING':
            fail('invalid_state',
                 'This execution has at least one non-PENDING delivery -- it can no longer be cancelled.', 409)
        if delivery.attempt_count != 0:
            fail('invalid_state',
                 'This execution has at least one delivery with a recorded attempt -- it can no longer be cancelled.', 409)
        if delivery.lease_owner is not None or (delivery.lease_until is not None and delivery.lease_until > now):
            fail('invalid_state',
                 'This execution has a delivery currently claimed by a worker -- try again shortly.', 409)

    delivery_ids = [delivery.id for delivery in deliveries]
    if delivery_ids:
        attempt_count = (
            db.session.query(NotificationCampaignAttempt)
            .filter(NotificationCampaignAttempt.delivery_id.in_(delivery_ids))
            .count()
        )
        if attempt_count != 0:
            fail('invalid_state',
                 'This execution has recorded transport attempts -- it can no longer be cancelled.', 409)

    execution.state = 'CANCELLED'
    execution.hold_reason = None
    execution.completed_at = now
    execution.updated_at = now
    campaign = get_campaign(execution.campaign_id)
    campaign.state = 'CANCELLED'
    campaign.hold_reason = None
    campaign.updated_at = now
    for delivery in deliveries:
        delivery.status = 'SUPPRESSED'
        delivery.suppression_reason = 'ADMIN_CANCELLED'
        delivery.lease_owner = None
        delivery.lease_until = None

    dismiss_bell_items_for_execution(execution.id, now)

    db.session.commit()
    return serialize_execution(execution), 200
