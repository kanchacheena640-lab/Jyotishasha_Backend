# routes/routes_metrics.py

"""
Backend-only observability endpoints for the payment/report lifecycle
(Payment Hardening Phase 8). No UI -- these exist for direct calls
(curl/Postman/a future admin tool) and follow the exact same
convention as routes/admin_orders.py and routes/routes_reconciliation.py:
same "/admin/api" prefix, no additional auth layer beyond whatever
already fronts every other /admin/api/* route (adding one here would
be an authentication redesign, out of scope for this phase, same as
Phase 7).

Every route is read-only -- none of them can mutate an Order or a
ProcessedPayment row.
"""

from dataclasses import asdict

from flask import Blueprint, jsonify

from modules.payments.metrics_service import MetricsService

routes_metrics = Blueprint("routes_metrics", __name__)


@routes_metrics.route("/admin/api/metrics/payments", methods=["GET"])
def metrics_payments():
    return jsonify(asdict(MetricsService().payments_metrics())), 200


@routes_metrics.route("/admin/api/metrics/reports", methods=["GET"])
def metrics_reports():
    return jsonify(asdict(MetricsService().report_metrics())), 200


@routes_metrics.route("/admin/api/metrics/retries", methods=["GET"])
def metrics_retries():
    return jsonify(asdict(MetricsService().retry_metrics())), 200


@routes_metrics.route("/admin/api/metrics/general", methods=["GET"])
def metrics_general():
    return jsonify(asdict(MetricsService().general_metrics())), 200


@routes_metrics.route("/admin/api/metrics", methods=["GET"])
def metrics_full():
    """Combined snapshot -- all four sections plus the explicit
    `limitations` list explaining every metric that is `null` rather
    than a number."""
    return jsonify(asdict(MetricsService().full_snapshot())), 200
