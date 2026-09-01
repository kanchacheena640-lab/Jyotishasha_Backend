# routes/routes_activity_events.py

"""
POST /api/activity-events -- Phase 3's authenticated client-event
ingestion endpoint. Thin route: verify auth, enforce the body-size cap,
parse JSON, hand off to modules/activity_events/ingestion_service.py
for every real decision, map its outcome to a stable, minimal HTTP
response. No persistence logic lives here.

V1 scope (Phase 3 Step 2/3, locked): authenticated only
(@jwt_required()), one event per request, no batching, no anonymous
ingestion.

Response contract (frozen, do not add ad hoc fields):
  written                       -> 201 {"status":"written","event_id":"<uuid>"}
  duplicate                     -> 200 {"status":"duplicate"}
  unknown event                 -> 400 {"error":"unknown_event"}
  known but non-client event    -> 400 {"error":"event_not_client_ingestible"}
  malformed request             -> 400 {"error":"malformed_request"}
  invalid timestamp             -> 400 {"error":"invalid_occurred_at"}
  invalid field                 -> 400 {"error":"invalid_field","field":"..."}
  forbidden backend field       -> 400 {"error":"forbidden_field","field":"..."}
  report ownership failure      -> 403 {"error":"entity_not_owned"}
  authentication failure        -> 401 {"error":"authentication_failed"}
  identity integrity anomaly    -> 409 {"error":"identity_integrity_anomaly"}
    (409 Conflict, not 401/403/500: the request itself is well-formed
    and the caller IS authenticated -- what's wrong is a server-side
    data-integrity conflict (>1 AppUser row for one firebase_uid) that
    prevents this specific request from being safely processed. 401/403
    would misleadingly imply a client auth problem; a bare 500 would
    look like an unhandled crash rather than a deliberately-detected,
    logged condition. 409 is the smallest status that means "the
    request is fine, current server-side state conflicts with
    processing it.")
  ledger write failure          -> 503 {"error":"temporarily_unavailable"}
  oversized body                -> 413 {"error":"request_too_large"}

Never exposes exception text or DB error detail in any response body.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from werkzeug.exceptions import RequestEntityTooLarge

from modules.activity_events.ingestion_service import ingest_client_event

routes_activity_events = Blueprint("routes_activity_events", __name__)

MAX_BODY_BYTES = 8 * 1024  # 8 KB, Phase 3 Step 2/3 locked limit


@routes_activity_events.before_request
def _enforce_body_size_limit():
    """Phase 3 Step 4 correction: the previous check read the entire
    body via request.get_data() and only THEN compared its length --
    Werkzeug buffers the full body before that comparison ever runs, so
    it provided no actual protection against an oversized body being
    read into memory. Setting request.max_content_length here, before
    any body access happens anywhere in this view, makes Werkzeug
    itself enforce the cap while reading (or reject outright from the
    Content-Length header before reading anything) -- raising
    RequestEntityTooLarge, caught explicitly below.

    Scoped via this blueprint's own before_request -- not
    app.config["MAX_CONTENT_LENGTH"] -- so no other route in this
    application is affected."""
    request.max_content_length = MAX_BODY_BYTES

_STATUS_TO_RESPONSE = {
    "duplicate": (200, {"status": "duplicate"}),
    "unknown_event": (400, {"error": "unknown_event"}),
    "event_not_client_ingestible": (400, {"error": "event_not_client_ingestible"}),
    "malformed_request": (400, {"error": "malformed_request"}),
    "invalid_occurred_at": (400, {"error": "invalid_occurred_at"}),
    "entity_not_owned": (403, {"error": "entity_not_owned"}),
    "auth_failed": (401, {"error": "authentication_failed"}),
    "identity_integrity_anomaly": (409, {"error": "identity_integrity_anomaly"}),
    "write_failed": (503, {"error": "temporarily_unavailable"}),
}


@routes_activity_events.route("/api/activity-events", methods=["POST"])
@jwt_required()
def track_activity_event():
    try:
        body = request.get_json(silent=True)
    except RequestEntityTooLarge:
        return jsonify({"error": "request_too_large"}), 413

    if body is None:
        return jsonify({"error": "malformed_request"}), 400

    outcome = ingest_client_event(body)

    if outcome.status == "written":
        return jsonify({"status": "written", "event_id": outcome.event_id}), 201

    if outcome.status in ("invalid_field", "forbidden_field"):
        status_code = 400
        return jsonify({"error": outcome.status, "field": outcome.field}), status_code

    status_code, response_body = _STATUS_TO_RESPONSE.get(
        outcome.status, (503, {"error": "temporarily_unavailable"})
    )
    return jsonify(response_body), status_code
