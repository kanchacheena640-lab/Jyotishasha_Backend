# routes/routes_reconciliation.py

"""
Backend-only entry point for the Admin Reconciliation Foundation
(Payment Hardening Phase 7). No Admin UI is built here -- these two
routes exist so a future admin tool (or a manual curl/Postman call
during an incident) has something to call; this phase intentionally
stops at that boundary.

Follows this codebase's existing admin-route convention exactly (see
routes/admin_orders.py, routes/routes_admin_tokens.py) -- same
"/admin/api" prefix.

Bucket A -- Critical Fix #7: both routes below are now gated by
@admin_required (JWT + ADMIN_USER_IDS allowlist), reusing the same
mechanism notifications/notification_routes.py already used -- no new
auth mechanism, no RBAC. (Previously this docstring claimed some other
layer already fronted these routes; Critical Verification #6
independently confirmed no such layer existed anywhere in this
codebase -- that claim was wrong, and is corrected here rather than
left in place.)
"""

from flask import Blueprint, jsonify

from modules.payments.reconciliation_service import ReconciliationService
from notifications.notification_routes import admin_required

routes_reconciliation = Blueprint("routes_reconciliation", __name__)


def _decision_json(decision):
    return {
        "order_id": decision.order_id,
        "report_stage": decision.report_stage,
        "action": decision.action,
        "reason": decision.reason,
    }


@routes_reconciliation.route("/admin/api/reconciliation/order/<int:order_id>", methods=["GET"])
@admin_required
def inspect_order(order_id):
    """Read-only: classify this Order's recovery state. Never mutates
    anything -- safe to call any number of times."""
    decision = ReconciliationService().inspect(order_id)
    return jsonify(_decision_json(decision)), 200


@routes_reconciliation.route("/admin/api/reconciliation/order/<int:order_id>/resume", methods=["POST"])
@admin_required
def resume_order(order_id):
    """Only actually resumes when the Order's report_stage is
    'Failed'. Never creates a new Order, never re-verifies payment --
    re-dispatches report generation for this exact existing Order.
    Concurrency-safe: two simultaneous calls for the same order_id can
    never both dispatch (see ReconciliationService._try_acquire_
    resume_ownership)."""
    result = ReconciliationService().resume(order_id)
    return jsonify({
        "order_id": result.order_id,
        "resumed": result.resumed,
        "task_id": result.task_id,
        "decision": _decision_json(result.decision),
    }), 200
