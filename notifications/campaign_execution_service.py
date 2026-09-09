"""N4 Send Now: approval freeze, drift-gated target freeze, idempotent
execution creation. No transport/network call happens anywhere in this
module -- see notifications/campaign_worker.py for the only code that
ever calls a Transport.send().

TOKEN SNAPSHOT DECISION (N4.13): this module never writes a raw or
encrypted FCM token anywhere. A frozen NotificationCampaignDelivery
row identifies its recipient by (user_id, app_user_id) only. The
current token is re-resolved fresh, in-memory, by campaign_worker.py
immediately before each transport attempt (never persisted) -- this is
simpler than a stored/encrypted snapshot, has no cleanup-deadline
subsystem to build or forget, and is actually MORE compliant with N1
Section 7's own "revalidate ... current token fingerprint" requirement
than a stale stored snapshot would be. Recipient IDENTITY is frozen
durably (N1's actual retry requirement); the TOKEN is not, by design.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from notifications.campaign_service import CampaignError, fail, get_campaign, audience_definition
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationSendNowRequest,
)
from notifications.saved_audience_recipient_resolver import (
    resolve_saved_audience_recipients, RecipientResolutionError,
)
from notifications.campaign_bell_service import create_bell_items_for_targets

PREVIEW_MAX_AGE = timedelta(minutes=15)
LARGE_AUDIENCE_THRESHOLD = 1000
ALL_USERS_PHRASE = 'SEND TO ALL USERS'
MAX_IDEMPOTENCY_KEY_LENGTH = 128


def _now():
    return datetime.now(timezone.utc)


def _parse_utc(value, field):
    if not isinstance(value, str):
        fail('invalid_input', f'{field} must be an ISO-8601 string.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        fail('invalid_input', f'{field} is not a valid ISO-8601 timestamp.')
    if parsed.tzinfo is None:
        fail('invalid_input', f'{field} must include a UTC offset.')
    return parsed.astimezone(timezone.utc)


def _drift_threshold(baseline):
    return max(10, math.ceil(0.2 * baseline))


def _drifted(baseline, current):
    """N1 P7 / N4.11 exactly: 0 -> positive always drifts; otherwise
    drift strictly greater than max(10, ceil(20% of baseline)) in
    either direction drifts. Exactly-at-threshold does NOT drift."""
    if baseline == 0:
        return current > 0
    return abs(current - baseline) > _drift_threshold(baseline)


def _request_hash(campaign_id, data):
    # Never hashes the literal All Users phrase (N4.8: "do not store
    # this phrase ... unnecessarily") -- only whether it was supplied
    # correctly, as a boolean, alongside the other request-shaping
    # fields that make two Send Now attempts "the same request".
    canonical = {
        'campaign_id': campaign_id,
        'revision': data.get('revision'),
        'baseline': data.get('baseline'),
        'all_users_phrase_correct': data.get('confirmation_phrase') == ALL_USERS_PHRASE,
        'large_audience_acknowledged': data.get('large_audience_acknowledged') is True,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _iso_utc(dt):
    """N5.2: 'API contract must make timezone explicit' -- every
    timestamp this API returns is normalized to an explicit UTC offset
    before serialization, never left at whatever the DB session's own
    display timezone happens to be (TIMESTAMPTZ is stored as a UTC
    instant regardless, but psycopg2 can hand back a tz-aware datetime
    tagged with the session's configured zone -- same instant, different
    string). This makes every execution timestamp field byte-comparable
    across responses instead of incidentally environment-dependent."""
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def serialize_execution(execution):
    counts = dict(
        db.session.query(NotificationCampaignDelivery.status, func.count(NotificationCampaignDelivery.id))
        .filter(NotificationCampaignDelivery.execution_id == execution.id)
        .group_by(NotificationCampaignDelivery.status).all()
    )
    target_count = sum(counts.values())
    return {
        'id': execution.id,
        'campaign_id': execution.campaign_id,
        'state': execution.state,
        'hold_reason': execution.hold_reason,
        'approved_saved_audience_id': execution.approved_saved_audience_id,
        'baseline': {
            'generated_at': _iso_utc(execution.baseline_generated_at),
            'matched_user_count': execution.baseline_matched_user_count,
            'eligible_recipient_count': execution.baseline_eligible_recipient_count,
            'recorded_at': _iso_utc(execution.baseline_recorded_at),
        },
        'resolved': {
            'matched_user_count': execution.resolved_matched_user_count,
            'eligible_recipient_count': execution.resolved_eligible_recipient_count,
            'excluded_recipient_count': execution.resolved_excluded_recipient_count,
            'exclusion_counts': execution.resolved_exclusion_counts,
        },
        'all_users_confirmed': execution.all_users_confirmed,
        'large_audience_acknowledged': execution.large_audience_acknowledged,
        'target_count': target_count,
        'delivery_counts': {
            'PENDING': counts.get('PENDING', 0),
            'ACCEPTED': counts.get('ACCEPTED', 0),
            'FAILED_RETRYABLE': counts.get('FAILED_RETRYABLE', 0),
            'FAILED_PERMANENT': counts.get('FAILED_PERMANENT', 0),
            'UNKNOWN': counts.get('UNKNOWN', 0),
            'SUPPRESSED': counts.get('SUPPRESSED', 0),
        },
        'scheduled_for': _iso_utc(execution.scheduled_for),
        'expires_at': _iso_utc(execution.expires_at),
        'dispatch_started_at': _iso_utc(execution.dispatch_started_at),
        'frozen_at': _iso_utc(execution.frozen_at),
        'started_at': _iso_utc(execution.started_at),
        'completed_at': _iso_utc(execution.completed_at),
        'created_at': _iso_utc(execution.created_at),
        'updated_at': _iso_utc(execution.updated_at),
    }


def get_execution(execution_id):
    execution = db.session.get(NotificationCampaignExecution, str(execution_id))
    if execution is None:
        fail('not_found', 'Execution not found.', 404)
    return serialize_execution(execution)


def _resolve_live(saved_audience_id, *, approved_criteria=None):
    """Authoritative live resolution -- never trusts a browser-supplied
    count for any safety decision (N4.7). Raises CampaignError for a
    resolver-reported dependency failure or the 50K ceiling (N4.10) --
    never a successful zero/blocked result an unaware caller could
    mistake for "nobody matches".

    `approved_criteria`: forwarded to the N2 resolver's own same-named
    keyword (N5 Section 5.36). reconfirm() below passes the execution's
    frozen approved_criteria so membership is evaluated against the
    APPROVED definition even if the underlying SavedAudience was edited
    between approval and reconfirmation -- omitted (send_now()'s own
    call, where approval and resolution happen in the same request, so
    there is no edit window) resolves against the audience's current
    criteria exactly as before."""
    try:
        return resolve_saved_audience_recipients(saved_audience_id, approved_criteria=approved_criteria)
    except RecipientResolutionError as exc:
        if exc.code == 'SAFETY_CEILING_EXCEEDED':
            fail('safety_ceiling_exceeded',
                 f'Matched users ({exc.matched_user_count}) exceed the 50,000 safety ceiling. '
                 'This cannot be sent until reviewed.', 422)
        fail('recipient_resolution_unavailable',
             'Live recipient resolution is unavailable. Check the selected audience and retry.', 503)


def _validate_send_now_request(data):
    if not isinstance(data, dict):
        fail('invalid_input', 'Expected a JSON object.')
    idempotency_key = data.get('idempotency_key')
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        fail('invalid_input', 'idempotency_key is required and must be a bounded non-empty string.')
    revision = data.get('revision')
    if type(revision) is not int or revision <= 0:
        fail('invalid_input', 'revision must be a positive integer.')
    baseline = data.get('baseline')
    if not isinstance(baseline, dict) or set(baseline) != {'generated_at', 'matched_user_count', 'eligible_recipient_count'}:
        fail('invalid_input', 'baseline must contain exactly generated_at, matched_user_count, eligible_recipient_count.')
    for key in ('matched_user_count', 'eligible_recipient_count'):
        if type(baseline[key]) is not int or baseline[key] < 0:
            fail('invalid_input', f'baseline.{key} must be a non-negative integer.')
    if baseline['eligible_recipient_count'] > baseline['matched_user_count']:
        fail('invalid_input', 'baseline.eligible_recipient_count cannot exceed baseline.matched_user_count.')
    generated_at = _parse_utc(baseline['generated_at'], 'baseline.generated_at')
    # No forged-recipient-ID/token/criteria override fields are accepted
    # anywhere in this payload (N4.22) -- only the allowlisted keys above
    # plus the two optional confirmation fields validated by the caller.
    allowed = {'idempotency_key', 'revision', 'baseline', 'confirmation_phrase', 'large_audience_acknowledged'}
    if set(data) - allowed:
        fail('unknown_fields', 'Unknown Send Now fields are not allowed.')
    return idempotency_key, revision, baseline, generated_at


def send_now(campaign_id, data, actor=None):
    idempotency_key, revision, baseline, baseline_generated_at = _validate_send_now_request(data)
    campaign = get_campaign(campaign_id)
    request_hash = _request_hash(campaign.id, data)

    existing_request = NotificationSendNowRequest.query.filter_by(
        campaign_id=campaign.id, idempotency_key=idempotency_key).first()
    if existing_request is not None:
        if existing_request.request_hash != request_hash:
            fail('idempotency_conflict',
                 'This idempotency key was already used for a different Send Now request.', 409)
        return existing_request.response_body, existing_request.response_status

    if campaign.state != 'DRAFT':
        fail('invalid_state', 'Only a DRAFT campaign can Send Now.', 409)
    if revision != campaign.revision:
        fail('stale_revision', 'Draft changed in another tab. Reload before sending.', 409)
    if _now() - baseline_generated_at > PREVIEW_MAX_AGE:
        fail('preview_stale', 'Recipient preview is more than 15 minutes old. Refresh the preview and try again.', 409)

    audience_row, criteria, digest = audience_definition(campaign.saved_audience_id, require_active=True)
    resolution = _resolve_live(campaign.saved_audience_id)
    matched, eligible = resolution.matched_user_count, resolution.eligible_recipient_count

    if resolution.is_all_users:
        if data.get('confirmation_phrase') != ALL_USERS_PHRASE:
            fail('all_users_confirmation_required',
                 f'Type exactly "{ALL_USERS_PHRASE}" to confirm sending to All Users.', 400)
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

    paused = _drifted(baseline['matched_user_count'], matched) or _drifted(baseline['eligible_recipient_count'], eligible)
    now = _now()

    execution = NotificationCampaignExecution(
        campaign_id=campaign.id,
        state='PAUSED' if paused else 'FROZEN',
        hold_reason='DRIFT' if paused else None,
        approved_saved_audience_id=audience_row.id,
        approved_criteria=criteria, approved_criteria_version=criteria['version'], approved_criteria_hash=digest,
        approved_title=campaign.title, approved_body=campaign.body, approved_action=campaign.action,
        all_users_confirmed=all_users_confirmed, large_audience_acknowledged=large_audience_acknowledged,
        baseline_generated_at=baseline_generated_at,
        baseline_matched_user_count=baseline['matched_user_count'],
        baseline_eligible_recipient_count=baseline['eligible_recipient_count'],
        baseline_recorded_at=now,
        resolved_matched_user_count=matched, resolved_eligible_recipient_count=eligible,
        resolved_excluded_recipient_count=resolution.excluded_recipient_count,
        resolved_exclusion_counts=dict(resolution.exclusion_counts),
        resolver_policy_version='N1-P1-v1',
        frozen_at=None if paused else now,
        created_by=actor, created_at=now, updated_at=now,
    )
    db.session.add(execution)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return _lost_creation_race(campaign.id, idempotency_key, request_hash)

    campaign.state = 'PROCESSING'
    campaign.hold_reason = 'DRIFT' if paused else None
    campaign.updated_at = now

    if not paused:
        _freeze_targets(execution, resolution, now)

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
        return _lost_creation_race(campaign.id, idempotency_key, request_hash)
    return response_body, response_status


def _freeze_targets(execution, resolution, now):
    """The ONE place delivery rows are ever created from a resolution --
    shared by send_now(), reconfirm() and (N5) campaign_schedule_service's
    dispatch path, so target-freeze semantics can never drift between
    them. Never called while paused; never called twice for the same
    execution (the executions table's own unique(campaign_id) plus each
    caller's own state guard make a double-freeze structurally
    unreachable).

    N6 addition: also creates each target's Bell presentation row, in
    this SAME transaction, via campaign_bell_service.py -- the isolated
    Campaign C Bell table only; see that module's docstring for why this
    never touches UserNotification/attention_policy/event_scheduler."""
    for recipient in resolution.recipients:
        db.session.add(NotificationCampaignDelivery(
            execution_id=execution.id, user_id=recipient.user_id, app_user_id=recipient.app_user_id,
            status='PENDING', created_at=now,
        ))
    create_bell_items_for_targets(execution, resolution, now)


def _lost_creation_race(campaign_id, idempotency_key, request_hash):
    """Another concurrent request committed first (N4.5/N4.20 -- DB
    uniqueness, not a Python lock, is what actually prevents the
    duplicate here). If it was the SAME idempotency key, replay its
    result; otherwise this really is a second execution attempt for an
    already-executing campaign, and the DB-authoritative unique(campaign_id)
    on the executions table is what makes that impossible -- report it
    as a conflict rather than a fabricated success."""
    winner = NotificationSendNowRequest.query.filter_by(
        campaign_id=campaign_id, idempotency_key=idempotency_key).first()
    if winner is not None and winner.request_hash == request_hash:
        return winner.response_body, winner.response_status
    fail('execution_already_exists', 'A Send Now execution already exists for this campaign.', 409)


def reconfirm(execution_id, data, actor=None):
    if not isinstance(data, dict) or set(data) - {'revision'}:
        fail('invalid_input', 'Unknown reconfirm fields are not allowed.')
    execution = db.session.get(NotificationCampaignExecution, str(execution_id))
    if execution is None:
        fail('not_found', 'Execution not found.', 404)
    if execution.state != 'PAUSED':
        fail('invalid_state', 'Only a PAUSED execution can be reconfirmed.', 409)

    # N5 fix (Section 5.36): resolve against the execution's own frozen
    # approved_criteria, never the SavedAudience row's current criteria --
    # closes a latent N4 gap where an audience edited between approval
    # and a (possibly much later, e.g. N5 scheduled) reconfirmation would
    # otherwise have been silently adopted.
    resolution = _resolve_live(execution.approved_saved_audience_id, approved_criteria=execution.approved_criteria)
    matched, eligible = resolution.matched_user_count, resolution.eligible_recipient_count
    now = _now()

    still_paused = _drifted(execution.resolved_matched_user_count, matched) or \
        _drifted(execution.resolved_eligible_recipient_count, eligible)

    # New explicit, auditable baseline: what the Admin was actually
    # shown (the previous resolution) before clicking Reconfirm -- never
    # silently carried forward unchanged (N4.11's own requirement).
    execution.baseline_generated_at = now
    execution.baseline_matched_user_count = execution.resolved_matched_user_count
    execution.baseline_eligible_recipient_count = execution.resolved_eligible_recipient_count
    execution.baseline_recorded_at = now
    execution.resolved_matched_user_count = matched
    execution.resolved_eligible_recipient_count = eligible
    execution.resolved_excluded_recipient_count = resolution.excluded_recipient_count
    execution.resolved_exclusion_counts = dict(resolution.exclusion_counts)
    execution.updated_at = now
    if max(matched, eligible) >= LARGE_AUDIENCE_THRESHOLD:
        execution.large_audience_acknowledged = True

    campaign = get_campaign(execution.campaign_id)
    if still_paused:
        execution.state = 'PAUSED'
        execution.hold_reason = 'DRIFT'
        campaign.hold_reason = 'DRIFT'
    else:
        execution.state = 'FROZEN'
        execution.hold_reason = None
        execution.frozen_at = now
        campaign.hold_reason = None
        _freeze_targets(execution, resolution, now)
    campaign.updated_at = now
    db.session.commit()
    return serialize_execution(execution), 200
