"""N6 -- Admin campaign history/monitoring reads. Read-only throughout:
no function here ever calls db.session.add/update/delete. Reuses
campaign_execution_service.serialize_execution() and
campaign_metrics_service.execution_metrics() rather than re-deriving
either -- one source of truth for what an execution/its metrics look
like, whether reached via the N4/N5 single-execution endpoint or this
history list.

Only ever reads notification_campaigns / notification_campaign_executions
/ notification_campaign_deliveries / notification_campaign_attempts --
Campaign C's own tables. Never reads UserNotification, AlertMicroEvent,
or any A/B table; A/B campaigns/jobs are not in scope for this history
(N1 Section 2/28 -- separate namespace)."""
from __future__ import annotations

from notifications.campaign_service import CampaignError, fail
from notifications.campaign_models import NotificationCampaign
from notifications.campaign_execution_models import (
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
)
from notifications.campaign_execution_service import serialize_execution, _iso_utc
from notifications.campaign_metrics_service import execution_metrics
from extensions import db

CAMPAIGN_STATES = ('DRAFT', 'SCHEDULED', 'PROCESSING', 'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED')
DELIVERY_STATUSES = ('PENDING', 'ACCEPTED', 'FAILED_RETRYABLE', 'FAILED_PERMANENT', 'UNKNOWN', 'SUPPRESSED')


def _paginate(query, page, page_size):
    page = max(1, page if isinstance(page, int) else 1)
    page_size = min(max(1, page_size if isinstance(page_size, int) else 20), 100)
    total = query.order_by(None).count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, dict(page=page, page_size=page_size, total_count=total,
                       total_pages=max(1, -(-total // page_size)) if total else 1)


def _campaign_summary(campaign, execution):
    return {
        'id': campaign.id, 'title': campaign.title, 'state': campaign.state,
        'hold_reason': campaign.hold_reason, 'audience_name': None,
        'saved_audience_id': campaign.saved_audience_id,
        'execution_id': execution.id if execution else None,
        'execution_state': execution.state if execution else None,
        'scheduled_for': _iso_utc(execution.scheduled_for) if execution else None,
        'target_count': None if execution is None else db.session.query(NotificationCampaignDelivery.id)
            .filter(NotificationCampaignDelivery.execution_id == execution.id).count(),
        'created_at': campaign.created_at.isoformat(), 'updated_at': campaign.updated_at.isoformat(),
        'created_by': campaign.created_by,
    }


def list_history(*, page=1, page_size=20, state=None, search=None, date_from=None, date_to=None):
    """Admin campaign history list -- every state (unlike campaign_service.
    list_campaigns()'s DRAFT-only list), newest-first. `state` restricts
    to one campaign state; `date_from`/`date_to` are already-parsed
    tz-aware datetimes filtering campaign.created_at (a half-open
    [from, to) window, consistent with the activity_events analytics
    repository's own convention)."""
    if state is not None and state not in CAMPAIGN_STATES:
        fail('invalid_input', f'state must be one of {CAMPAIGN_STATES}.')
    query = db.session.query(NotificationCampaign)
    if state is not None:
        query = query.filter(NotificationCampaign.state == state)
    if search:
        query = query.filter(NotificationCampaign.title.ilike(f'%{search.strip()}%'))
    if date_from is not None:
        query = query.filter(NotificationCampaign.created_at >= date_from)
    if date_to is not None:
        query = query.filter(NotificationCampaign.created_at < date_to)
    query = query.order_by(NotificationCampaign.created_at.desc(), NotificationCampaign.id.desc())
    rows, pagination = _paginate(query, page, page_size)

    campaign_ids = [r.id for r in rows]
    executions_by_campaign = {
        e.campaign_id: e for e in
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.campaign_id.in_(campaign_ids)).all()
    } if campaign_ids else {}
    return dict(
        campaigns=[_campaign_summary(r, executions_by_campaign.get(r.id)) for r in rows],
        pagination=pagination,
    )


def get_campaign_execution_detail(campaign_id):
    """Full campaign + execution + metrics detail, for the Admin history
    detail view. 404s (via CampaignError) if no execution exists yet
    (a DRAFT campaign has nothing to monitor)."""
    campaign = db.session.get(NotificationCampaign, str(campaign_id))
    if campaign is None:
        fail('not_found', 'Campaign not found.', 404)
    execution = NotificationCampaignExecution.query.filter_by(campaign_id=campaign.id).first()
    if execution is None:
        fail('not_found', 'This campaign has not been sent or scheduled -- nothing to monitor yet.', 404)
    body = serialize_execution(execution)
    body['campaign'] = {
        'id': campaign.id, 'title': campaign.title, 'body': campaign.body,
        'state': campaign.state, 'created_by': campaign.created_by,
    }
    body['metrics'] = execution_metrics(execution)
    return body


def list_deliveries(execution_id, *, page=1, page_size=20, status=None):
    """Paginated per-recipient delivery list -- user_id/app_user_id only,
    never a token or contact detail (matches N4's own no-PII-leakage
    posture for this table)."""
    if status is not None and status not in DELIVERY_STATUSES:
        fail('invalid_input', f'status must be one of {DELIVERY_STATUSES}.')
    execution = db.session.get(NotificationCampaignExecution, str(execution_id))
    if execution is None:
        fail('not_found', 'Execution not found.', 404)
    query = NotificationCampaignDelivery.query.filter_by(execution_id=execution.id)
    if status is not None:
        query = query.filter(NotificationCampaignDelivery.status == status)
    query = query.order_by(NotificationCampaignDelivery.created_at.asc(), NotificationCampaignDelivery.id.asc())
    rows, pagination = _paginate(query, page, page_size)
    return dict(
        deliveries=[{
            'id': d.id, 'user_id': d.user_id, 'app_user_id': d.app_user_id, 'status': d.status,
            'suppression_reason': d.suppression_reason, 'attempt_count': d.attempt_count,
            'next_attempt_at': _iso_utc(d.next_attempt_at),
            'first_attempted_at': _iso_utc(d.first_attempted_at),
            'last_attempted_at': _iso_utc(d.last_attempted_at),
            'accepted_at': _iso_utc(d.accepted_at),
        } for d in rows],
        pagination=pagination,
    )


def list_attempts(delivery_id):
    """Full attempt history for one delivery -- safe aggregate
    error-reason exposure using only the actual error_code/error_class
    values campaign_worker.py itself records; nothing invented."""
    delivery = db.session.get(NotificationCampaignDelivery, str(delivery_id))
    if delivery is None:
        fail('not_found', 'Delivery not found.', 404)
    rows = (NotificationCampaignAttempt.query.filter_by(delivery_id=delivery.id)
            .order_by(NotificationCampaignAttempt.attempt_number.asc()).all())
    return dict(
        delivery_id=delivery.id, status=delivery.status,
        attempts=[{
            'attempt_number': a.attempt_number, 'started_at': _iso_utc(a.started_at),
            'finished_at': _iso_utc(a.finished_at), 'outcome': a.outcome,
            'provider': a.provider, 'error_code': a.error_code, 'error_class': a.error_class,
        } for a in rows],
    )
