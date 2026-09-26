# routes/routes_revenue.py

"""
Reports Revenue Dashboard -- Phase 1 backend API.

Two read-only, additive endpoints, gated by the SAME
`admin_or_bridge_required` (routes/routes_app_version.py) every other
Admin-BFF-connected route family already reuses -- no new auth
mechanism. All business/query logic lives in
modules/payments/revenue_dashboard_service.py; this file only parses
query params, calls that module, and serializes the result.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes.routes_app_version import admin_or_bridge_required
from modules.payments.revenue_dashboard_service import (
    InvalidRevenueFilter,
    build_paid_orders_page,
    build_revenue_summary,
    parse_date_filters,
    parse_platform_filter,
)

routes_revenue = Blueprint("routes_revenue", __name__)

MAX_PER_PAGE = 200
DEFAULT_PER_PAGE = 25


def _parse_pagination():
    page_raw = request.args.get("page", "1")
    per_page_raw = request.args.get("per_page", str(DEFAULT_PER_PAGE))
    try:
        page = int(page_raw)
        per_page = int(per_page_raw)
    except (TypeError, ValueError):
        raise InvalidRevenueFilter("page/per_page must be integers.")
    if page < 1:
        raise InvalidRevenueFilter("page must be a positive integer.")
    if per_page < 1 or per_page > MAX_PER_PAGE:
        raise InvalidRevenueFilter(f"per_page must be between 1 and {MAX_PER_PAGE}.")
    return page, per_page


@routes_revenue.route("/admin/api/revenue/summary", methods=["GET"])
@admin_or_bridge_required
def revenue_summary():
    try:
        platform = parse_platform_filter(request.args.get("platform"))
        start_date, end_date = parse_date_filters(request.args.get("start"), request.args.get("end"))
    except InvalidRevenueFilter as exc:
        return jsonify({"error": "invalid_filter", "message": str(exc)}), 400

    return jsonify(build_revenue_summary(platform, start_date, end_date)), 200


@routes_revenue.route("/admin/api/revenue/orders", methods=["GET"])
@admin_or_bridge_required
def revenue_orders():
    try:
        platform = parse_platform_filter(request.args.get("platform"))
        start_date, end_date = parse_date_filters(request.args.get("start"), request.args.get("end"))
        page, per_page = _parse_pagination()
    except InvalidRevenueFilter as exc:
        return jsonify({"error": "invalid_filter", "message": str(exc)}), 400

    return jsonify(build_paid_orders_page(platform, start_date, end_date, page, per_page)), 200
