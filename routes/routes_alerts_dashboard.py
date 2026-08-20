# routes/routes_alerts_dashboard.py

"""
Alerts & Opportunities Subscription API.

The smallest clean, authenticated endpoint the "Alerts & Opportunities"
premium subscription section (the sixth selectable section -- see
modules/entitlement/subscription_sections.py) needs to show a profile
its own CURRENT alerts. This file has exactly three responsibilities:

    1. Authenticate + resolve profile_id -- same proven pattern as
       modules/auth/routes_profile.py::subscription_info() and
       routes/routes_premium_report.py::get_premium_report()
       (@jwt_required() + get_jwt_identity() +
       resolve_profile_id_from_account_user_id()). No new auth
       mechanism.
    2. Verify Alerts entitlement via modules/alerts/entitlement_gate.py
       ::has_alerts_access() -- unmodified, reused exactly.
    3. Call the EXISTING hardened
       modules/alerts/user_alert_selection_service.py
       ::get_user_facing_alerts_for_profile() -- THE single source of
       truth for "what should this profile see today", per that
       module's own docstring, which already anticipated this exact
       endpoint ("A future Alerts app API endpoint... MUST call this
       same function"). No confidence/severity/conflict-suppression/
       category-diversity/cooldown/max-alert-selection logic is
       duplicated here -- the Engine remains the sole authority, this
       file only shapes its output into an HTTP response.

Freshness semantics (deliberately NOT reinvented here): this endpoint
does not apply N4's global daily push cap at all -- that cap only
gates whether a push notification is actually SENT
(modules/alerts/alerts_scheduler.py), never what
get_user_facing_alerts_for_profile() itself selected. So an alert
suppressed from push delivery by N4 (recorded bell-only, N5) still
shows here, unchanged. The per-event cooldown
(delivery_eligibility_policy.py, inside the selection function) is
left exactly as-is too: it is what makes this endpoint agree with
what push delivery itself would show, by the selection service's own
design -- not something this file second-guesses or re-implements.

Response contract (Gate 5, extended by the AI-Written Personalized
Alert Content addition): stable minimal fields only. Confidence,
DOB/TOB/POB, raw Kundali/rule internals, and any detection-debug
metadata are NEVER serialized -- this file only reads
event_id/category/severity/priority/active_from/active_until off the
selected AlertMicroEvent rows, plus title/body/(optional) action from
the EXISTING modules/alerts/notification_content_adapter.py
::build_alert_notification_content() -- this route makes no OpenAI
call itself; it only passes through the row's already-persisted
ai_insight/ai_action (generated once, at detection time, by
modules/alerts/alert_ai_content_service.py) or that same file's
original deterministic per-category fallback when absent. Raw detected
alerts (the full candidate pool) are never returned -- only the
already-selected, at-most-2 rows get_user_facing_alerts_for_profile()
itself narrowed to.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from modules.alerts.alert_ai_content_service import ensure_ai_content_for_selected_rows
from modules.alerts.entitlement_gate import has_alerts_access
from modules.alerts.notification_content_adapter import (
    AlertContentError,
    build_alert_notification_content,
)
from modules.alerts.user_alert_selection_service import get_user_facing_alerts_for_profile
from modules.subscription.dual_write_adapter import resolve_profile_id_from_account_user_id

routes_alerts_dashboard = Blueprint("routes_alerts_dashboard", __name__)


def _serialize_alert(row):
    """One selected AlertMicroEvent row -> the minimal public contract.
    Never includes confidence, state, or any other detection-internal
    field."""
    content = build_alert_notification_content(
        event_id=row.event_id, category=row.category, severity=row.severity,
        ai_insight=row.ai_insight, ai_action=row.ai_action,
    )
    result = {
        "alert_id": row.id,
        "event_id": row.event_id,
        "title": content["title"],
        "message": content["body"],
        "category": row.category,
        "severity": row.severity,
        "priority": row.priority,
        "valid_from": row.active_from.isoformat() if row.active_from else None,
        "valid_until": row.active_until.isoformat() if row.active_until else None,
    }
    # AI-Written Personalized Alert Content addition -- present only
    # when this row actually has AI-generated action guidance (a
    # genuine new/reactivated occurrence that generated successfully).
    # Never an empty string -- see build_alert_notification_content()'s
    # own docstring on this contract.
    if "action" in content:
        result["action"] = content["action"]
    return result


@routes_alerts_dashboard.route("/api/alerts/current", methods=["GET"])
@jwt_required()
def get_current_alerts():
    user_id = get_jwt_identity()
    authenticated_profile_id = resolve_profile_id_from_account_user_id(user_id)
    if authenticated_profile_id is None:
        return jsonify({
            "status": "no_profile",
            "message": "No profile is associated with this account.",
        }), 403

    profile_id_raw = request.args.get("profile_id")
    if profile_id_raw is not None:
        try:
            requested_profile_id = int(profile_id_raw)
        except ValueError:
            return jsonify({
                "status": "invalid_request", "message": "profile_id must be an integer.",
            }), 400
        if requested_profile_id != authenticated_profile_id:
            return jsonify({
                "status": "forbidden",
                "message": "profile_id does not belong to the authenticated account.",
            }), 403

    profile_id = authenticated_profile_id

    gate_result = has_alerts_access(profile_id)
    if not gate_result.entitled:
        return jsonify({
            "status": "locked",
            "message": "Alerts & Opportunities is not included in your current plan.",
        }), 403

    try:
        result = get_user_facing_alerts_for_profile(profile_id)
    except Exception:
        return jsonify({
            "status": "error",
            "message": "Unable to load your alerts right now. Please try again.",
        }), 500

    # Architectural gate: AI generation happens HERE, ONLY for the
    # FINAL selected set -- never for a raw detected event that this
    # narrowing excluded. See
    # alert_ai_content_service.ensure_ai_content_for_selected_rows()'s
    # own docstring. A failure here (OpenAI down, etc.) never breaks
    # this endpoint -- it just leaves ai_insight/ai_action NULL for the
    # affected row(s), and _serialize_alert() below already falls back
    # to the deterministic template via build_alert_notification_content().
    ensure_ai_content_for_selected_rows(result.selected)

    try:
        alerts = [_serialize_alert(row) for row in result.selected]
    except AlertContentError:
        # A selected row's event_id has no catalog content entry --
        # fails loudly server-side (matches this adapter's own "fail
        # rather than send blank/garbled content" discipline) rather
        # than silently fabricating a title/body.
        return jsonify({
            "status": "error",
            "message": "Unable to load your alerts right now. Please try again.",
        }), 500

    return jsonify({
        "status": "success",
        "alerts": alerts,
    }), 200
