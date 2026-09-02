# routes/routes_activity_events_anonymous.py

"""
Task 2B -- POST /api/activity-events/anonymous, a SEPARATE, unauthenticated
ingestion path for anonymous website visitors, tightly restricted to
the 5-event ANONYMOUS_WEBSITE_EVENTS allowlist (see
modules/activity_events/anonymous_ingestion_policy.py).

This file, and this blueprint, are entirely SEPARATE from
routes/routes_activity_events.py's POST /api/activity-events -- that
route's @jwt_required() is untouched, unweakened, and unaffected by
this one existing. Nothing here conditionally disables or bypasses it;
the two routes share no view function and no decorator.

Thin route, same discipline as the authenticated one: parse JSON,
enforce the body-size cap, hand off to
modules/activity_events/anonymous_ingestion_service.py for every real
decision, map its outcome to a stable, minimal HTTP response. No
persistence logic, no identity resolution, and no business logic lives
here.

Response contract (mirrors routes_activity_events.py's shape, its own
distinct status vocabulary):
  written                            -> 201 {"status":"written","event_id":"<uuid>"}
  unknown event                      -> 400 {"error":"unknown_event"}
  known but not anonymous-ingestible -> 400 {"error":"event_not_anonymous_ingestible"}
  malformed request                  -> 400 {"error":"malformed_request"}
  invalid timestamp                  -> 400 {"error":"invalid_occurred_at"}
  invalid field                      -> 400 {"error":"invalid_field","field":"..."}
  forbidden field (incl. platform)   -> 400 {"error":"forbidden_field","field":"..."}
  ledger write failure               -> 503 {"error":"temporarily_unavailable"}
  oversized body                     -> 413 {"error":"request_too_large"}

No 429: this endpoint has no real rate limiter behind it in v1 -- see
the module docstring below and the Task 2B final report's "Abuse/rate-
limit decision" section for why one was deliberately not added here.

Never exposes exception text or DB error detail in any response body.
"""

from flask import Blueprint, request, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from modules.activity_events.anonymous_ingestion_service import ingest_anonymous_website_event

routes_activity_events_anonymous = Blueprint("routes_activity_events_anonymous", __name__)

# Reuses the authenticated endpoint's own 8KB cap (routes_activity_events.
# MAX_BODY_BYTES) rather than inventing a new, untested number: the same
# MAX_PROPERTIES_KEYS(20) / MAX_STRING_VALUE_LENGTH(256) / MAX_CAMPAIGN_
# CONTEXT_KEYS(10) limits from ingestion_validation.py apply to this
# endpoint's `properties`/`campaign_context` fields (this endpoint's
# accepted-field set is a strict SUBSET of the authenticated endpoint's
# -- no entity_type/entity_id, no notification_context, no source, no
# idempotency_key -- so 8KB was already sized to cover a superset of
# what a request here can legally contain).
MAX_BODY_BYTES = 8 * 1024


@routes_activity_events_anonymous.before_request
def _enforce_body_size_limit():
    """Same technique as routes_activity_events.py's own guard, scoped
    to this blueprint only via before_request (not app.config
    ["MAX_CONTENT_LENGTH"]) -- setting request.max_content_length before
    any body access happens anywhere in this view makes Werkzeug itself
    enforce the cap while reading, raising RequestEntityTooLarge, caught
    explicitly below."""
    request.max_content_length = MAX_BODY_BYTES


_STATUS_TO_RESPONSE = {
    "unknown_event": (400, {"error": "unknown_event"}),
    "event_not_anonymous_ingestible": (400, {"error": "event_not_anonymous_ingestible"}),
    "malformed_request": (400, {"error": "malformed_request"}),
    "invalid_occurred_at": (400, {"error": "invalid_occurred_at"}),
    "write_failed": (503, {"error": "temporarily_unavailable"}),
}


@routes_activity_events_anonymous.route("/api/activity-events/anonymous", methods=["POST"])
def track_anonymous_website_event():
    # Deliberately no @jwt_required() -- this is the one, sole
    # unauthenticated ingestion path, and its safety comes entirely from
    # the narrow allowlist + strict validation in
    # anonymous_ingestion_service.py, not from any auth check.
    try:
        body = request.get_json(silent=True)
    except RequestEntityTooLarge:
        return jsonify({"error": "request_too_large"}), 413

    if body is None:
        return jsonify({"error": "malformed_request"}), 400

    outcome = ingest_anonymous_website_event(body)

    if outcome.status == "written":
        return jsonify({"status": "written", "event_id": outcome.event_id}), 201

    if outcome.status in ("invalid_field", "forbidden_field"):
        return jsonify({"error": outcome.status, "field": outcome.field}), 400

    status_code, response_body = _STATUS_TO_RESPONSE.get(
        outcome.status, (503, {"error": "temporarily_unavailable"})
    )
    return jsonify(response_body), status_code
