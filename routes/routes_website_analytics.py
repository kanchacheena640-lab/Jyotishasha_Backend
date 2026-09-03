# routes/routes_website_analytics.py

"""
Task 12 -- backend-only, read-only Admin API exposing Task 11's
WebsiteAnalyticsService. Same convention as routes/routes_analytics.py
(Phase 6B.4) and routes/routes_metrics.py (Payment Hardening Phase 8):
`/admin/api/...` prefix, gated by the exact same admin_required (JWT +
ADMIN_USER_IDS allowlist, notifications/notification_routes.py) every
other admin route in this codebase already reuses -- no new auth
mechanism.

Deliberately a SEPARATE blueprint/file from routes_analytics.py, not an
extension of it -- that file serves the OLD, frozen Phase 6B cross-
platform AnalyticsService (6 fixed metric-domain endpoints, its own
start/end query contract); this file serves the NEW, metric_id-keyed
WebsiteAnalyticsService (Task 11) with its own period vocabulary
(today/yesterday/7d/28d/custom, Task 12 S4 -- intentionally different
from Task 11's own internal window_for_period() 7d/30d/90d/custom,
which stays completely untouched by this file). Neither file imports
or calls into the other.

This file is THIN by design, matching the exact same layering:

    activity_events -> ActivityEventsAnalyticsRepository (Task 11)
                     -> WebsiteAnalyticsService (Task 11, metric meaning)
                     -> this file (auth + parse + validate + serialize)

Routes below do exactly these things and nothing else: authenticate
(admin_required), parse metric_id + period (+ start/end for custom) +
optional dimension/limit from the request, call ONE
WebsiteAnalyticsService.get_metric() per requested metric, and
serialize its frozen result dataclass into ONE stable JSON envelope.
No route here queries ActivityEvent, uses db.session, or computes a
metric itself -- every fact returned comes from calling
WebsiteAnalyticsService, which itself only ever calls
ActivityEventsAnalyticsRepository (Task 11, unmodified by this task).

CRITICAL RULE, enforced structurally (Task 12 S5): a GA4_EXTERNAL or
BLOCKED metric_id never reaches WebsiteAnalyticsService's own
repository call -- WebsiteAnalyticsService.get_metric() itself already
guarantees this (Task 11's own frozen behavior); this file adds no
second gate and removes none -- it only serializes whatever
WebsiteAnalyticsService.get_metric() already, correctly, returned.

No raw-query endpoint exists here (no /events, /query, /export, /sql) --
metric retrieval is the ONLY capability this API exposes, and only for
metric_ids WebsiteAnalyticsService's own closed _DISPATCH table already
recognizes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from flask import Blueprint, jsonify, request

from modules.activity_events.analytics_models import AnalyticsWindow, InvalidAnalyticsWindow
from modules.activity_events.analytics_repository import UnsupportedAnalyticsDimension
from modules.activity_events.website_analytics_models import (
    AttributionCoverageResult,
    GroupedMetricResult,
    MetricValue,
    PageAttributionResult,
    UnavailableMetric,
)
from modules.activity_events.website_analytics_service import (
    MAX_GROUP_LIMIT,
    UnsupportedWebsiteMetric,
    WebsiteAnalyticsService,
    WebsiteMetricNotImplemented,
)
from notifications.notification_routes import admin_required

routes_website_analytics = Blueprint("routes_website_analytics", __name__)

# One shared instance -- WebsiteAnalyticsService itself is stateless
# (each call takes its own window/kwargs), matching routes_analytics.py's
# own established "one simple module-level default, no service locator"
# convention. Tests substitute this via routes_website_analytics._service,
# the same monkeypatch seam that file offers.
_service = WebsiteAnalyticsService()

# ---------------------------------------------------------------------
# Period contract (Task 12 S4) -- a NEW, route-layer-only vocabulary,
# distinct from Task 11's own internal window_for_period() (7d/30d/90d/
# custom), which this file never calls and never modifies. UTC
# calendar-day boundaries for "today"/"yesterday" -- a single [start,
# end) WINDOW each, never a per-day trend bucket, never IST -- Task 11
# explicitly deferred timezone-safe day BUCKETING (a dashboard trend
# array), which this is not; this stays entirely within Task 11's own
# frozen UTC storage/query boundary.
# ---------------------------------------------------------------------
SUPPORTED_PERIODS: Tuple[str, ...] = ("today", "yesterday", "7d", "28d", "custom")

# A reasonable maximum custom range (Task 12 S4) -- generous for any
# realistic dashboard lookback, while still bounding a pathological
# all-time request. Chosen independently of Task 11's own MAX_GROUP_LIMIT
# (a result-size bound, not a time-range bound -- two different concerns).
MAX_CUSTOM_RANGE_DAYS = 366

MAX_BATCH_METRICS = 20


class InvalidPeriod(ValueError):
    """Raised for any period-parsing/validation failure -- mapped to a
    400 invalid_period response by every route below. Never a naive
    ValueError that could be confused with an unrelated failure."""


def _parse_iso_datetime(raw, field_name: str) -> datetime:
    """Same parsing convention as routes_analytics.py's own
    _parse_iso_datetime() -- accepts a 'Z' suffix, requires an explicit
    timezone offset otherwise (AnalyticsWindow's own constructor is the
    single place that actually enforces timezone-awareness -- this
    function only handles the 'Z' convenience, exactly like that file's
    own copy does, kept as a separate, small, duplicated helper rather
    than importing a private function from a sibling routes module)."""
    if not raw or not isinstance(raw, str):
        raise InvalidPeriod(f"{field_name} is required for period=custom")
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise InvalidPeriod(f"{field_name} is not a valid ISO-8601 timestamp")


def _parse_period(args) -> Tuple[AnalyticsWindow, str]:
    """Returns (window, period_label). `args` is a Mapping-like object
    (Flask's request.args, or a plain dict for the batch endpoint's own
    JSON body) so both routes below share this exact one implementation."""
    period = args.get("period") or "7d"
    if period not in SUPPORTED_PERIODS:
        raise InvalidPeriod(f"period must be one of {SUPPORTED_PERIODS}, got {period!r}")

    now = datetime.now(timezone.utc)

    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "yesterday":
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = today_start - timedelta(days=1)
        end = today_start
    elif period == "7d":
        end = now
        start = now - timedelta(days=7)
    elif period == "28d":
        end = now
        start = now - timedelta(days=28)
    else:  # "custom"
        start = _parse_iso_datetime(args.get("start"), "start")
        end = _parse_iso_datetime(args.get("end"), "end")

    try:
        window = AnalyticsWindow(start=start, end=end)
    except InvalidAnalyticsWindow as exc:
        raise InvalidPeriod(str(exc))

    if period == "custom" and (window.end - window.start) > timedelta(days=MAX_CUSTOM_RANGE_DAYS):
        raise InvalidPeriod(f"custom range exceeds the maximum of {MAX_CUSTOM_RANGE_DAYS} days")

    return window, period


def _parse_limit(raw) -> Optional[int]:
    """None if not supplied (callers then omit `limit` from kwargs
    entirely, so a metric's own default applies). Raises InvalidPeriod
    -- reused as the generic "bad request parameter" exception type
    for this small file, matching routes_analytics.py's own single-
    exception-type-per-concern style -- for a non-numeric value. An
    out-of-[1, MAX_GROUP_LIMIT] value is CLAMPED, not rejected --
    preserving Task 11's own established repository-level clamping
    convention exactly, never diverging from it here."""
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise InvalidPeriod(f"limit must be an integer, got {raw!r}")
    return max(1, min(value, MAX_GROUP_LIMIT))


def _build_kwargs(dimension: Optional[str], limit: Optional[int]) -> dict:
    """The ONLY two optional parameters this API ever forwards to
    WebsiteAnalyticsService.get_metric() -- never a raw pass-through of
    arbitrary query/body parameters (Task 12 S3/S7). Both remain
    genuinely optional: a metric that doesn't accept one (e.g. a scalar
    metric given `dimension`) surfaces as a TypeError at the dispatch
    call site, translated to a controlled 400 by the caller of this
    function -- never a silent ignore, never a raw 500."""
    kwargs = {}
    if dimension is not None:
        kwargs["dimension"] = dimension
    if limit is not None:
        kwargs["limit"] = limit
    return kwargs


def _serialize_metric_result(result, period_label: str, window: AnalyticsWindow) -> dict:
    """The ONE stable JSON envelope every route below returns, for
    every one of WebsiteAnalyticsService's 5 possible result shapes
    (Task 12 S6): {metric_id, status, period, start, end, data,
    limitations?, reason?}. `data` is null for an UnavailableMetric --
    a dashboard/UI consumer must never mistake "unavailable" for a real
    0 (Task 11's own frozen distinction, preserved here at the
    serialization boundary, not re-litigated). No raw properties/
    campaign_context/firebase_uid/profile_id/anonymous_id/session_id
    field exists on any of the 5 shapes in the first place (Task 11's
    own guarantee) -- this function does not need to, and does not,
    filter anything out; it only ever reads fields these frozen
    dataclasses actually declare."""
    envelope = {
        "metric_id": result.metric_id,
        "status": result.quality_status,
        "period": period_label,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
    }

    if isinstance(result, UnavailableMetric):
        envelope["data"] = None
        envelope["reason"] = result.reason
        return envelope

    if isinstance(result, MetricValue):
        envelope["data"] = {"value": result.value}
    elif isinstance(result, GroupedMetricResult):
        envelope["data"] = {
            "dimension": result.dimension,
            "rows": [{"dimension_value": r.dimension_value, "count": r.count} for r in result.rows],
            "unknown_count": result.unknown_count,
            "total": result.total,
        }
    elif isinstance(result, PageAttributionResult):
        envelope["data"] = {
            "property_dimension": result.property_dimension,
            "campaign_dimension": result.campaign_dimension,
            "rows": [
                {"page_path": r.page_path, "dimension_value": r.dimension_value, "count": r.count}
                for r in result.rows
            ],
            "incomplete_count": result.incomplete_count,
            "total": result.total,
        }
    elif isinstance(result, AttributionCoverageResult):
        envelope["data"] = {
            "total_eligible": result.total_eligible,
            "attributed": result.attributed,
            "unattributed": result.unattributed,
            "coverage_percent": result.coverage_percent,
        }
    else:
        # Structurally unreachable given WebsiteAnalyticsService's own
        # closed return-type set -- a defensive backstop, not a real
        # branch, kept so a future new result shape fails loudly here
        # rather than silently serializing as {}.
        raise TypeError(f"Unknown WebsiteAnalyticsService result type: {type(result)!r}")

    envelope["limitations"] = list(result.limitations)
    return envelope


def _fetch_one(metric_id: str, window: AnalyticsWindow, period_label: str, dimension, limit):
    """Shared single-metric fetch+serialize, used by both the single-
    metric route and each item of the batch route. Returns
    (status_code, body_dict) -- the batch route uses only `body_dict`
    per item (status_code folded into that item's own shape); the
    single-metric route returns both directly."""
    kwargs = _build_kwargs(dimension, limit)
    try:
        result = _service.get_metric(metric_id, window, **kwargs)
    except UnsupportedWebsiteMetric as exc:
        return 404, {"error": "unknown_metric", "message": str(exc)}
    except UnsupportedAnalyticsDimension as exc:
        return 400, {"error": "unsupported_dimension", "message": str(exc)}
    except WebsiteMetricNotImplemented as exc:
        return 501, {"error": "not_implemented", "message": str(exc)}
    except TypeError as exc:
        # A dimension/limit was supplied for a metric whose own handler
        # signature does not accept it (e.g. `dimension` on a scalar
        # metric) -- a controlled 400, never a raw 500/stack trace.
        return 400, {"error": "unsupported_parameter", "message": "This metric does not accept the given parameter(s)."}

    return 200, _serialize_metric_result(result, period_label, window)


@routes_website_analytics.route("/admin/api/website-analytics/metrics/<metric_id>", methods=["GET"])
@admin_required
def website_analytics_metric(metric_id: str):
    try:
        window, period_label = _parse_period(request.args)
    except InvalidPeriod as exc:
        return jsonify({"error": "invalid_period", "message": str(exc)}), 400

    try:
        limit = _parse_limit(request.args.get("limit"))
    except InvalidPeriod as exc:
        return jsonify({"error": "invalid_limit", "message": str(exc)}), 400

    dimension = request.args.get("dimension")

    try:
        status_code, body = _fetch_one(metric_id, window, period_label, dimension, limit)
    except Exception:
        # Any other, genuinely unexpected failure (a real
        # repository/service exception this route did not anticipate)
        # -- controlled 500 JSON, never a stack trace or raw exception
        # message (which could echo internal SQL/query details) reaching
        # the caller. Flask's own request logging still captures the
        # real traceback server-side, as it already does for every
        # other route in this codebase.
        return jsonify({"error": "internal_error", "message": "An unexpected error occurred while computing this metric."}), 500

    return jsonify(body), status_code


@routes_website_analytics.route("/admin/api/website-analytics/metrics/batch", methods=["POST"])
@admin_required
def website_analytics_metrics_batch():
    """Read-only despite the POST verb -- no state is ever created,
    updated, or deleted by this route (Task 12 S10). POST is used only
    because the request shape is a body-carried LIST of per-metric
    configs, not a single resource lookup a GET path/query string
    fits naturally."""
    payload = request.get_json(silent=True) or {}

    try:
        window, period_label = _parse_period(payload)
    except InvalidPeriod as exc:
        return jsonify({"error": "invalid_period", "message": str(exc)}), 400

    metrics = payload.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        return jsonify({"error": "invalid_batch", "message": "'metrics' must be a non-empty list."}), 400
    if len(metrics) > MAX_BATCH_METRICS:
        return jsonify({
            "error": "batch_too_large",
            "message": f"At most {MAX_BATCH_METRICS} metrics may be requested per batch (got {len(metrics)}).",
        }), 400

    results = []
    for entry in metrics:
        if not isinstance(entry, dict) or not entry.get("metric_id"):
            results.append({"error": "invalid_metric_entry", "message": "Each entry must be an object with a 'metric_id' string."})
            continue

        metric_id = entry["metric_id"]
        try:
            limit = _parse_limit(entry.get("limit"))
        except InvalidPeriod as exc:
            results.append({"metric_id": metric_id, "error": "invalid_limit", "message": str(exc)})
            continue

        dimension = entry.get("dimension")

        try:
            _status_code, body = _fetch_one(metric_id, window, period_label, dimension, limit)
        except Exception:
            results.append({
                "metric_id": metric_id, "error": "internal_error",
                "message": "An unexpected error occurred while computing this metric.",
            })
            continue

        results.append(body)

    return jsonify({"period": period_label, "start": window.start.isoformat(), "end": window.end.isoformat(), "results": results}), 200
