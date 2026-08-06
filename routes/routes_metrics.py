# routes/routes_metrics.py

"""
Backend-only observability endpoints for the payment/report lifecycle
(Payment Hardening Phase 8). No UI -- these exist for direct calls
(curl/Postman/a future admin tool) and follow the exact same
convention as routes/admin_orders.py and routes/routes_reconciliation.py:
same "/admin/api" prefix.

Bucket A -- Critical Fix #7: every route below is now gated by
@admin_required (JWT + ADMIN_USER_IDS allowlist), reusing the same
mechanism notifications/notification_routes.py already used -- no new
auth mechanism, no RBAC. (Previously this docstring claimed some other
layer already fronted these routes; Critical Verification #6
independently confirmed no such layer existed anywhere in this
codebase -- that claim was wrong, and is corrected here rather than
left in place.)

Every route is read-only -- none of them can mutate an Order or a
ProcessedPayment row.
"""

from dataclasses import asdict

from flask import Blueprint, jsonify

from modules.payments.metrics_service import MetricsService
from notifications.notification_routes import admin_required

routes_metrics = Blueprint("routes_metrics", __name__)


@routes_metrics.route("/admin/api/metrics/payments", methods=["GET"])
@admin_required
def metrics_payments():
    return jsonify(asdict(MetricsService().payments_metrics())), 200


@routes_metrics.route("/admin/api/metrics/reports", methods=["GET"])
@admin_required
def metrics_reports():
    return jsonify(asdict(MetricsService().report_metrics())), 200


@routes_metrics.route("/admin/api/metrics/retries", methods=["GET"])
@admin_required
def metrics_retries():
    return jsonify(asdict(MetricsService().retry_metrics())), 200


@routes_metrics.route("/admin/api/metrics/general", methods=["GET"])
@admin_required
def metrics_general():
    return jsonify(asdict(MetricsService().general_metrics())), 200


@routes_metrics.route("/admin/api/metrics", methods=["GET"])
@admin_required
def metrics_full():
    """Combined snapshot -- all four sections plus the explicit
    `limitations` list explaining every metric that is `null` rather
    than a number."""
    return jsonify(asdict(MetricsService().full_snapshot())), 200
