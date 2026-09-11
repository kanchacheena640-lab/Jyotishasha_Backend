# routes/routes_admin_notifications.py

"""
NOTIFICATIONS N3 -- Admin Campaign Composer API.

Gated by the SAME admin_or_bridge_required decorator every other Admin
route already uses (routes_app_version.py) -- accepts either the Next.js
Admin BFF's X-Admin-Bridge-Key secret or a real admin JWT. No new auth
mechanism, matching routes_admin_audiences.py/routes_admin_users.py.

Endpoints (frozen shape, N1 Section 25 -- DRAFT-only subset; send/
schedule/cancel/reapprove/clone/metrics/deliveries remain N4+):
  GET   /admin/api/notifications           -- DRAFT campaign list
  POST  /admin/api/notifications           -- create DRAFT
  GET   /admin/api/notifications/<id>      -- read one DRAFT
  PATCH /admin/api/notifications/<id>      -- edit DRAFT (optimistic revision)
  POST  /admin/api/notifications/preview   -- live N2 recipient preview

This file never imports a sender/transport module, never writes
NotificationExecution/NotificationDelivery rows (they do not exist yet),
and never accepts a state other than DRAFT from the client -- state is
always server-assigned via notifications/campaign_service.py, which in
turn never invokes anything under services/event_scheduler.py or
modules/alerts/ (N1 Section 23 -- automatic pipeline isolation).
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

from routes.routes_app_version import admin_or_bridge_required
from notifications.campaign_service import (
    CampaignError,
    list_campaigns,
    save_campaign,
    get_campaign,
    serialize,
    preview,
)
from notifications.campaign_execution_service import send_now, reconfirm, get_execution
from notifications.campaign_schedule_service import schedule_campaign, reschedule, cancel
from notifications.campaign_history_service import (
    list_history, get_campaign_execution_detail, list_deliveries, list_attempts,
)
from datetime import datetime, timezone

routes_admin_notifications = Blueprint("routes_admin_notifications", __name__)


def _resolve_admin_identity():
    """Same best-effort resolution as routes_admin_audiences.py's own
    _resolve_admin_identity() -- None whenever no real admin JWT was
    presented (the bridge-key path), never a fabricated identity."""
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        return int(identity) if identity is not None else None
    except Exception:
        return None


def _parse_int(raw, default=None):
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _campaign_error_response(exc: CampaignError):
    return jsonify({"error": exc.code, "message": exc.message}), exc.status


@routes_admin_notifications.route("/admin/api/notifications", methods=["GET"])
@admin_or_bridge_required
def admin_list_notifications():
    args = request.args
    page = max(1, _parse_int(args.get("page"), 1))
    page_size = _parse_int(args.get("page_size"), 20)
    search = args.get("search") or None
    try:
        result = list_campaigns(page=page, page_size=page_size, search=search)
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(result), 200


@routes_admin_notifications.route("/admin/api/notifications", methods=["POST"])
@admin_or_bridge_required
def admin_create_notification():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_input", "message": "Expected a JSON object."}), 400
    try:
        result = save_campaign(data, campaign_id=None, actor=_resolve_admin_identity())
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(result), 201


@routes_admin_notifications.route("/admin/api/notifications/<campaign_id>", methods=["GET"])
@admin_or_bridge_required
def admin_get_notification(campaign_id):
    try:
        row = get_campaign(campaign_id)
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(serialize(row)), 200


@routes_admin_notifications.route("/admin/api/notifications/<campaign_id>", methods=["PATCH"])
@admin_or_bridge_required
def admin_update_notification(campaign_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_input", "message": "Expected a JSON object."}), 400
    try:
        result = save_campaign(data, campaign_id=campaign_id, actor=_resolve_admin_identity())
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(result), 200


@routes_admin_notifications.route("/admin/api/notifications/preview", methods=["POST"])
@admin_or_bridge_required
def admin_preview_notification():
    """Live N2 recipient preview -- never a persistent member list, never
    a send. Works both before a draft exists (audience-only) and against
    an existing draft (campaign_id + revision), matching
    notifications/campaign_service.py::preview()'s own dual contract."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_input", "message": "Expected a JSON object."}), 400
    try:
        result = preview(data)
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(result), 200


@routes_admin_notifications.route("/admin/api/notifications/<campaign_id>/send-now", methods=["POST"])
@admin_or_bridge_required
def admin_send_now(campaign_id):
    """N4 -- validates, captures the approved definition, resolves live,
    enforces every N1 safety gate, and either freezes durable delivery
    targets or enters a PAUSED drift hold. Never calls transport/FCM
    (see notifications/campaign_worker.py's own module docstring for
    why that is a strictly separate boundary) -- returns 202 with the
    execution's current state, not a claim of anything having sent."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_input", "message": "Expected a JSON object."}), 400
    try:
        body, status = send_now(campaign_id, data, actor=_resolve_admin_identity())
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(body), status


@routes_admin_notifications.route("/admin/api/notifications/executions/<execution_id>/reconfirm", methods=["POST"])
@admin_or_bridge_required
def admin_reconfirm_execution(execution_id):
    """N4.11 -- clears a drift-pause hold only via a fresh live
    resolution and an explicit new recorded baseline; never a silent
    re-authorization of stale counts."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_input", "message": "Expected a JSON object."}), 400
    try:
        body, status = reconfirm(execution_id, data, actor=_resolve_admin_identity())
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(body), status


@routes_admin_notifications.route("/admin/api/notifications/executions/<execution_id>", methods=["GET"])
@admin_or_bridge_required
def admin_get_execution(execution_id):
    try:
        body = get_execution(execution_id)
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(body), 200


@routes_admin_notifications.route("/admin/api/notifications/<campaign_id>/schedule", methods=["POST"])
@admin_or_bridge_required
def admin_schedule_notification(campaign_id):
    """N5 -- validates, captures the approved definition, resolves live
    (authoritative baseline, never client-supplied), enforces every N1
    safety gate, and persists a SCHEDULED execution. Never materializes
    recipient deliveries and never calls transport/FCM -- membership is
    resolved live only at due dispatch (notifications/campaign_scheduler.py)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_input", "message": "Expected a JSON object."}), 400
    try:
        body, status = schedule_campaign(campaign_id, data, actor=_resolve_admin_identity())
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(body), status


@routes_admin_notifications.route("/admin/api/notifications/executions/<execution_id>/reschedule", methods=["POST"])
@admin_or_bridge_required
def admin_reschedule_execution(execution_id):
    """N5.23 -- scheduled_for/expires_at only, and only pre-claim."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_input", "message": "Expected a JSON object."}), 400
    try:
        body, status = reschedule(execution_id, data, actor=_resolve_admin_identity())
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(body), status


@routes_admin_notifications.route("/admin/api/notifications/executions/<execution_id>/cancel", methods=["POST"])
@admin_or_bridge_required
def admin_cancel_execution(execution_id):
    """N5.24 (pre-freeze: SCHEDULED or PAUSED) + P4.5 (post-freeze: a
    FROZEN execution provably unsent -- zero transport attempts).
    Idempotent. See notifications/campaign_schedule_service.py::cancel()
    for the full, narrower-for-FROZEN contract."""
    try:
        body, status = cancel(execution_id, actor=_resolve_admin_identity())
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(body), status


def _parse_date(raw):
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@routes_admin_notifications.route("/admin/api/notifications/history", methods=["GET"])
@admin_or_bridge_required
def admin_notification_history():
    """N6 -- paginated, filterable campaign history across every state
    (unlike GET /admin/api/notifications, which is DRAFT-only)."""
    args = request.args
    try:
        result = list_history(
            page=_parse_int(args.get("page"), 1),
            page_size=_parse_int(args.get("page_size"), 20),
            state=args.get("state") or None,
            search=args.get("search") or None,
            date_from=_parse_date(args.get("date_from")),
            date_to=_parse_date(args.get("date_to")),
        )
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(result), 200


@routes_admin_notifications.route("/admin/api/notifications/<campaign_id>/monitor", methods=["GET"])
@admin_or_bridge_required
def admin_notification_monitor(campaign_id):
    """N6 -- campaign + execution + metrics detail view. See
    notifications/campaign_metrics_service.py's module docstring for the
    exact numerator/denominator of every metric returned here."""
    try:
        body = get_campaign_execution_detail(campaign_id)
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(body), 200


@routes_admin_notifications.route("/admin/api/notifications/executions/<execution_id>/deliveries", methods=["GET"])
@admin_or_bridge_required
def admin_notification_deliveries(execution_id):
    """N6 -- paginated per-recipient delivery list. user_id/app_user_id
    only -- no token, no contact detail."""
    args = request.args
    try:
        result = list_deliveries(
            execution_id, page=_parse_int(args.get("page"), 1),
            page_size=_parse_int(args.get("page_size"), 20), status=args.get("status") or None,
        )
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(result), 200


@routes_admin_notifications.route("/admin/api/notifications/deliveries/<delivery_id>/attempts", methods=["GET"])
@admin_or_bridge_required
def admin_notification_delivery_attempts(delivery_id):
    """N6 -- full attempt history for one delivery, real error codes only."""
    try:
        result = list_attempts(delivery_id)
    except CampaignError as exc:
        return _campaign_error_response(exc)
    return jsonify(result), 200
