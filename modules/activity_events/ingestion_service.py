# modules/activity_events/ingestion_service.py

"""
Orchestrator for POST /api/activity-events (Phase 3). The one place
that ties together ingestion_policy (event ownership + report
ownership), request_identity (JWT -> firebase_uid -> profile_id), and
ingestion_validation (boundary hardening) before handing off to the
existing, unmodified modules/activity_events/service.py::record_event().

This module never touches db.session or ActivityEvent directly -- it
only ever calls record_event(), exactly once, at the very end, after
every check below has passed. It does not duplicate Phase 2's
persistence, dedupe, or transaction-isolation logic in any way.

Orchestration order (Phase 3 Step 3, fixed):
  request contract -> event ownership -> identity context ->
  timestamp validation -> boundary hardening -> report ownership (when
  applicable) -> dedupe derivation -> record_event().

Identity is resolved BEFORE the rest of the body is validated,
deliberately -- an unauthenticated or identity-broken request should
short-circuit before any effort is spent validating the remainder of
the payload.
"""

from modules.activity_events.ingestion_policy import (
    is_client_ingestible,
    is_platform_allowed_for_event,
    requires_entity_ownership,
    entity_fields_allowed,
    parse_entity_id,
    verify_ai_report_ownership,
    ALLOWED_ENTITY_TYPE,
)
from modules.activity_events.ingestion_validation import (
    ValidationError,
    validate_identifier,
    validate_occurred_at,
    validate_context_dict,
    MAX_PROPERTIES_KEYS,
    MAX_CAMPAIGN_CONTEXT_KEYS,
    MAX_NOTIFICATION_CONTEXT_KEYS,
)
from modules.activity_events.request_identity import (
    resolve_identity,
    AUTH_FAILED,
    IDENTITY_INTEGRITY_ANOMALY,
)
from modules.activity_events.event_schemas import (
    is_known_event,
    sanitize_properties,
    sanitize_campaign_context,
    sanitize_notification_context,
)
from modules.activity_events.service import record_event

ALLOWED_CLIENT_PLATFORMS = frozenset({"app_android", "app_ios", "website"})
# backend_internal is a real envelope value (S4/S5) but is never
# accepted on this HTTP-facing path -- a client asserting it would be
# spoofing a producer category that only internal callers may use.

ACCEPTED_FIELDS = frozenset({
    "event_name", "event_version", "occurred_at", "platform", "source",
    "anonymous_id", "session_id", "entity_type", "entity_id",
    "properties", "campaign_context", "notification_context",
    "idempotency_key",
})

# Client must never assert these -- always BACKEND_DERIVED/BACKEND_ONLY
# per the frozen trust matrix (Phase 3 Step 1, S4). Presence of any one
# of these in the request body is a hard reject, not a silent ignore.
FORBIDDEN_FIELDS = frozenset({
    "event_id", "recorded_at", "environment", "firebase_uid",
    "profile_id", "correlation_id", "dedupe_key",
})

MAX_SOURCE_LENGTH = 64  # matches ActivityEvent.source's column length


class IngestionOutcome:
    """status is one of: written, duplicate, unknown_event,
    event_not_client_ingestible, malformed_request, invalid_occurred_at,
    invalid_field, forbidden_field, entity_not_owned, auth_failed,
    identity_integrity_anomaly, write_failed. `field` is set only for
    invalid_field/forbidden_field. `event_id` is set only for written."""

    __slots__ = ("status", "field", "event_id")

    def __init__(self, status, field=None, event_id=None):
        self.status = status
        self.field = field
        self.event_id = event_id


def ingest_client_event(body) -> IngestionOutcome:
    # ---- request contract ------------------------------------------------
    if not isinstance(body, dict):
        return IngestionOutcome(status="malformed_request")

    for field in FORBIDDEN_FIELDS:
        if field in body:
            return IngestionOutcome(status="forbidden_field", field=field)

    unknown = sorted(set(body.keys()) - ACCEPTED_FIELDS)
    if unknown:
        return IngestionOutcome(status="invalid_field", field=unknown[0])

    event_name = body.get("event_name")
    if not isinstance(event_name, str) or not event_name:
        return IngestionOutcome(status="invalid_field", field="event_name")

    # ---- event ownership ---------------------------------------------------
    event_version = body.get("event_version", 1)
    if not isinstance(event_version, int) or isinstance(event_version, bool):
        return IngestionOutcome(status="invalid_field", field="event_version")

    if not is_known_event(event_name, event_version):
        return IngestionOutcome(status="unknown_event")

    if not is_client_ingestible(event_name):
        return IngestionOutcome(status="event_not_client_ingestible")

    # ---- identity context ----------------------------------------------
    identity = resolve_identity()
    if identity.status == AUTH_FAILED:
        return IngestionOutcome(status="auth_failed")
    if identity.status == IDENTITY_INTEGRITY_ANOMALY:
        return IngestionOutcome(status="identity_integrity_anomaly")

    # ---- timestamp validation --------------------------------------------
    try:
        occurred_at = validate_occurred_at(body.get("occurred_at"))
    except ValidationError:
        return IngestionOutcome(status="invalid_occurred_at")

    # ---- boundary hardening -----------------------------------------------
    platform = body.get("platform")
    if platform not in ALLOWED_CLIENT_PLATFORMS:
        return IngestionOutcome(status="invalid_field", field="platform")

    # Task 5A -- a second, narrower, opt-in gate on top of the global
    # allowlist just above: most events reach here unrestricted (no
    # entry in EVENT_PLATFORM_RESTRICTIONS), but app_install_attributed
    # is restricted to platform=app_android specifically -- see
    # ingestion_policy.py's own docstring. Same 400 invalid_field shape
    # as the global check above, so a caller cannot distinguish "unknown
    # platform" from "wrong platform for this specific event."
    if not is_platform_allowed_for_event(event_name, platform):
        return IngestionOutcome(status="invalid_field", field="platform")

    source = body.get("source")
    if source is not None and (not isinstance(source, str) or len(source) > MAX_SOURCE_LENGTH):
        return IngestionOutcome(status="invalid_field", field="source")

    try:
        validate_identifier("anonymous_id", body.get("anonymous_id"))
        validate_identifier("session_id", body.get("session_id"))
        validate_identifier("idempotency_key", body.get("idempotency_key"))
    except ValidationError as exc:
        return IngestionOutcome(status="invalid_field", field=exc.field)

    anonymous_id = body.get("anonymous_id")
    session_id = body.get("session_id")
    idempotency_key = body.get("idempotency_key")

    entity_type_raw = body.get("entity_type")
    entity_id_raw = body.get("entity_id")
    entity_id_int = None

    if entity_fields_allowed(event_name):
        # report_viewed / report_downloaded -- REQUIRED, not optional.
        if entity_type_raw != ALLOWED_ENTITY_TYPE:
            return IngestionOutcome(status="invalid_field", field="entity_type")
        try:
            entity_id_int = parse_entity_id(entity_id_raw)
        except ValueError:
            return IngestionOutcome(status="invalid_field", field="entity_id")
    else:
        if entity_type_raw is not None:
            return IngestionOutcome(status="invalid_field", field="entity_type")
        if entity_id_raw is not None:
            return IngestionOutcome(status="invalid_field", field="entity_id")

    try:
        struct_properties, _ = validate_context_dict("properties", body.get("properties"), MAX_PROPERTIES_KEYS)
        struct_campaign, _ = validate_context_dict("campaign_context", body.get("campaign_context"), MAX_CAMPAIGN_CONTEXT_KEYS)
        struct_notification, _ = validate_context_dict("notification_context", body.get("notification_context"), MAX_NOTIFICATION_CONTEXT_KEYS)
    except ValidationError as exc:
        return IngestionOutcome(status="invalid_field", field=exc.field)

    # Phase 2's own, unmodified, committed sanitizers -- the final
    # per-event allowlist pass, run AFTER this file's structural gate.
    clean_properties, _ = sanitize_properties(event_name, event_version, struct_properties)
    clean_campaign, _ = sanitize_campaign_context(struct_campaign)
    clean_notification, _ = sanitize_notification_context(struct_notification)

    # ---- report ownership (only when applicable) ---------------------------
    entity_type_final = None
    entity_id_final = None
    if requires_entity_ownership(event_name):
        if not verify_ai_report_ownership(entity_id_int, identity.profile_id):
            return IngestionOutcome(status="entity_not_owned")
        entity_type_final = ALLOWED_ENTITY_TYPE
        entity_id_final = str(entity_id_int)

    # ---- dedupe derivation --------------------------------------------------
    # Namespaced by the JWT-verified user_id (always present on an OK
    # identity resolution, unlike firebase_uid/profile_id which can be
    # None) -- so one account can never collide with another's
    # idempotency-key keyspace, even if they independently choose the
    # same raw idempotency_key value. Bounded well under VARCHAR(255)
    # by construction (see module docstring's size reasoning); the
    # slice is a defensive backstop, not a load-bearing truncation.
    dedupe_key = None
    if idempotency_key:
        dedupe_key = f"user:{identity.user_id}:{event_name}:{idempotency_key}"[:255]

    # ---- existing Phase-2 record_event() -- unmodified -----------------------
    result = record_event(
        event_name=event_name,
        event_version=event_version,
        occurred_at=occurred_at,
        platform=platform,
        firebase_uid=identity.firebase_uid,
        profile_id=identity.profile_id,
        anonymous_id=anonymous_id,
        session_id=session_id,
        source=source,
        entity_type=entity_type_final,
        entity_id=entity_id_final,
        properties=clean_properties,
        campaign_context=clean_campaign,
        notification_context=clean_notification,
        dedupe_key=dedupe_key,
    )

    if result.status == "written":
        return IngestionOutcome(status="written", event_id=str(result.event.event_id))
    if result.status == "skipped_duplicate_dedupe_key":
        return IngestionOutcome(status="duplicate")
    # write_failed, or (should not occur -- every client-ingestible
    # event is ledger-eligible) skipped_not_ledger_eligible.
    return IngestionOutcome(status="write_failed")
