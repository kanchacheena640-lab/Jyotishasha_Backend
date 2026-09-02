# routes/routes_analytics.py

"""
Phase 6B.4 -- backend-only Admin analytics API. Same convention as
routes/routes_metrics.py (Payment Hardening Phase 8): read-only
`/admin/api/...` endpoints, no UI, gated by the exact same
`admin_required` (JWT + ADMIN_USER_IDS allowlist,
notifications/notification_routes.py) every other admin route in this
codebase already reuses -- no new auth mechanism.

This file is THIN by design (Phase 6A/6B "Frozen Architecture"):

    activity_events
        -> ActivityEventsAnalyticsRepository (SQL mechanics)
        -> AnalyticsService (metric semantics)
        -> this file (auth + parse + validate + serialize)

Routes below do exactly five things and nothing else: authenticate
(admin_required), parse start/end/platform from the query string,
construct a frozen AnalyticsWindow (which self-validates), call ONE
AnalyticsService method, and serialize its frozen dataclass result to
JSON via dataclasses.asdict() -- the exact same serialization idiom
routes/routes_metrics.py already uses for its own dataclass responses.

No route here queries ActivityEvent, uses db.session, calculates a
metric or a rate, or reads any business table (Order/Subscription/
User/AppUser/AIReport/etc.) -- every fact returned comes from calling
AnalyticsService, which itself only ever calls
ActivityEventsAnalyticsRepository.

environment is never a request input. AnalyticsService's own public
methods have no `environment` parameter at all (Phase 6B.1/6B.3,
frozen) -- there is nothing here to forget to omit or that a caller
could override via `?environment=...`; any such query parameter is
simply never read (Flask ignores unrecognized query args by default).

No raw-event endpoint exists here (no /events, /raw-events, /query,
/export) -- these are six fixed metric-domain summaries only, matching
the frozen Admin API contract (Phase 6A section 27), never a generic
ledger browser.
"""

from dataclasses import asdict
from datetime import datetime

from flask import Blueprint, jsonify, request

from modules.activity_events.analytics_contract import InvalidPlatformFilter
from modules.activity_events.analytics_models import AnalyticsWindow, InvalidAnalyticsWindow
from modules.activity_events.analytics_service import AnalyticsService
from notifications.notification_routes import admin_required

routes_analytics = Blueprint("routes_analytics", __name__)

# One shared instance -- AnalyticsService itself is stateless (each
# call takes its own window/platform); a module-level default keeps
# this file simple, matching Phase 6B.3's own "prefer one simple
# default, no service locator" guidance. Tests substitute this via
# routes_analytics._service, the same monkeypatch seam
# routes/routes_metrics.py's own MetricsService() instantiation
# implicitly offers (there, a fresh instance per request; here, one
# shared instance is equivalent since AnalyticsService holds no
# request-scoped state).
_service = AnalyticsService()


def _parse_iso_datetime(raw, field_name: str) -> datetime:
    """Missing or malformed -> InvalidAnalyticsWindow (mapped to 400 by
    every route below). Timezone-awareness and start<end are NOT
    checked here -- AnalyticsWindow's own constructor (frozen, Phase
    6B.1) already enforces both; duplicating that here would be exactly
    the "two competing validation vocabularies" this phase's own brief
    warns against."""
    if not raw or not isinstance(raw, str):
        raise InvalidAnalyticsWindow(f"{field_name} is required")
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise InvalidAnalyticsWindow(f"{field_name} is not a valid ISO-8601 timestamp")


def _parse_window() -> AnalyticsWindow:
    start = _parse_iso_datetime(request.args.get("start"), "start")
    end = _parse_iso_datetime(request.args.get("end"), "end")
    # Raises InvalidAnalyticsWindow itself for a naive datetime or
    # start >= end -- the one, single place either check happens.
    return AnalyticsWindow(start=start, end=end)


def _run(get_metrics):
    """Shared request handling for all six endpoints: parse -> call ONE
    AnalyticsService method -> serialize. `platform` is passed through
    completely unvalidated here -- AnalyticsService.validate_platform()
    is the one place that rejects an unknown value (InvalidPlatformFilter),
    translated to 400 below exactly like InvalidAnalyticsWindow is.
    Any other exception is NOT caught here -- it propagates to Flask's
    own default error handling (this codebase's existing convention;
    routes_metrics.py/routes_activity_events.py do the same), never
    silently turned into a fake successful analytics result."""
    try:
        window = _parse_window()
    except InvalidAnalyticsWindow as exc:
        return jsonify({"error": "invalid_analytics_window", "message": str(exc)}), 400

    platform = request.args.get("platform")
    try:
        dto = get_metrics(window, platform)
    except InvalidPlatformFilter as exc:
        return jsonify({"error": "invalid_platform", "message": str(exc)}), 400

    return jsonify({"data": asdict(dto)}), 200


@routes_analytics.route("/admin/api/analytics/overview", methods=["GET"])
@admin_required
def analytics_overview():
    return _run(_service.get_overview)


@routes_analytics.route("/admin/api/analytics/engagement", methods=["GET"])
@admin_required
def analytics_engagement():
    return _run(_service.get_engagement)


@routes_analytics.route("/admin/api/analytics/asknow", methods=["GET"])
@admin_required
def analytics_asknow():
    return _run(_service.get_asknow_metrics)


@routes_analytics.route("/admin/api/analytics/reports", methods=["GET"])
@admin_required
def analytics_reports():
    return _run(_service.get_report_metrics)


@routes_analytics.route("/admin/api/analytics/subscriptions", methods=["GET"])
@admin_required
def analytics_subscriptions():
    return _run(_service.get_subscription_metrics)


@routes_analytics.route("/admin/api/analytics/notifications", methods=["GET"])
@admin_required
def analytics_notifications():
    return _run(_service.get_notification_metrics)
