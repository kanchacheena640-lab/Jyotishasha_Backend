# modules/activity_events/anonymous_ingestion_service.py

"""
Task 2B -- orchestrator for POST /api/activity-events/anonymous.

Mirrors modules/activity_events/ingestion_service.py's shape (request
contract -> event ownership -> boundary hardening -> record_event()),
deliberately kept as a SEPARATE module rather than extended into the
authenticated one -- the two endpoints must never share a code path
that could let a change meant for one silently loosen the other. This
module:

  - performs NO identity resolution at all (no JWT, no
    request_identity.resolve_identity(), no User/AppUser/AIReport
    lookup of any kind) -- firebase_uid and profile_id are always
    literal None, never looked up, never guessed.
  - forces platform="website" server-side, always -- the request body
    has no "platform" field in its accepted contract at all, and one is
    a hard reject (FORBIDDEN_FIELDS) if present, so a client can never
    claim app_android/app_ios/backend_internal here.
  - forces anonymous_id=None and dedupe_key=None always -- Task 2B S5's
    documented decision: session_id alone is the v1 identity surface
    for anonymous website events; no persistent cross-session anonymous
    visitor identifier is introduced by this task (that belongs to the
    future website attribution/session-foundation work Task 2B's brief
    explicitly defers). S13's documented decision: ordinary CTA/feature
    events must remain individually countable, so no durable dedupe
    semantics are invented for them -- every accepted request becomes
    its own row.
  - delegates the actual ledger write to the SAME, unmodified
    modules/activity_events/service.py::record_event() the authenticated
    path uses -- no duplicated persistence/transaction-isolation logic.

Only reuses -- never forks -- the authenticated path's own boundary-
hardening building blocks (validate_identifier, validate_occurred_at,
validate_context_dict, sanitize_properties, sanitize_campaign_context)
from ingestion_validation.py / event_schemas.py. The one genuinely new
piece of logic here is _normalize_referrer() (S10): those shared
sanitizers apply an allowlist + PII-value-shape check to
campaign_context.referrer, but neither one strips a query string or
fragment from an otherwise well-formed URL string -- an incoming
referrer URL is exactly the kind of value that can legitimately carry
tracking/session query parameters a site sends to another (or that a
malicious caller could stuff with something sensitive-looking), so this
module normalizes it to origin+path ONLY before campaign_context ever
reaches the shared sanitizer, which then still runs on top as
defense-in-depth. This normalization is intentionally anonymous-endpoint-
only -- the authenticated endpoint's own campaign_context handling is
untouched by this file.
"""

from urllib.parse import urlsplit

from modules.activity_events.anonymous_ingestion_policy import is_anonymous_website_ingestible
from modules.activity_events.ingestion_validation import (
    ValidationError,
    validate_identifier,
    validate_occurred_at,
    validate_context_dict,
    validate_page_path,
    MAX_PROPERTIES_KEYS,
    MAX_CAMPAIGN_CONTEXT_KEYS,
    MAX_STRING_VALUE_LENGTH,
)
from modules.activity_events.event_schemas import (
    is_known_event,
    sanitize_properties,
    sanitize_campaign_context,
)
from modules.activity_events.service import record_event

WEBSITE_PLATFORM = "website"

# The narrowest contract Task 2B S7 asks for -- deliberately excludes
# platform (server-forced, never client-supplied), source, anonymous_id,
# entity_type/entity_id, notification_context, and idempotency_key: none
# of the 5 ANONYMOUS_WEBSITE_EVENTS need any of them (see
# anonymous_ingestion_policy.py's per-event schema notes).
ACCEPTED_FIELDS = frozenset({
    "event_name", "event_version", "occurred_at", "session_id",
    "properties", "campaign_context",
})

# Same trust-boundary rationale as the authenticated endpoint's own
# FORBIDDEN_FIELDS (ingestion_service.py) -- presence is a hard reject,
# not a silent ignore -- PLUS "platform" here specifically, since this
# endpoint's one defining guarantee is that platform can never be
# client-asserted at all (Task 2B S3).
FORBIDDEN_FIELDS = frozenset({
    "event_id", "recorded_at", "environment", "firebase_uid",
    "profile_id", "correlation_id", "dedupe_key", "platform",
    "anonymous_id", "entity_type", "entity_id", "source",
    "notification_context", "idempotency_key",
})


def _normalize_referrer(raw: str):
    """origin + path ONLY -- never a query string or fragment (Task 2B
    S10: campaign_context.referrer must not become a new PII leakage
    channel; an incoming referrer URL can legitimately carry another
    site's own tracking/session query parameters). Returns None if the
    value isn't a plausible absolute http(s) URL at all -- the caller
    drops the key entirely in that case rather than persisting an
    unparseable string verbatim; this mirrors this codebase's own
    established "drop, don't reject the whole request" philosophy for a
    content-level (not structural) concern."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return normalized[:MAX_STRING_VALUE_LENGTH]


class AnonymousIngestionOutcome:
    """status is one of: written, unknown_event,
    event_not_anonymous_ingestible, malformed_request,
    invalid_occurred_at, invalid_field, forbidden_field, write_failed.
    `field` is set only for invalid_field/forbidden_field. `event_id` is
    set only for written."""

    __slots__ = ("status", "field", "event_id")

    def __init__(self, status, field=None, event_id=None):
        self.status = status
        self.field = field
        self.event_id = event_id


def ingest_anonymous_website_event(body) -> AnonymousIngestionOutcome:
    # ---- request contract ------------------------------------------------
    if not isinstance(body, dict):
        return AnonymousIngestionOutcome(status="malformed_request")

    for field in FORBIDDEN_FIELDS:
        if field in body:
            return AnonymousIngestionOutcome(status="forbidden_field", field=field)

    unknown = sorted(set(body.keys()) - ACCEPTED_FIELDS)
    if unknown:
        return AnonymousIngestionOutcome(status="invalid_field", field=unknown[0])

    event_name = body.get("event_name")
    if not isinstance(event_name, str) or not event_name:
        return AnonymousIngestionOutcome(status="invalid_field", field="event_name")

    # ---- event ownership ---------------------------------------------------
    event_version = body.get("event_version", 1)
    if not isinstance(event_version, int) or isinstance(event_version, bool):
        return AnonymousIngestionOutcome(status="invalid_field", field="event_version")

    if not is_known_event(event_name, event_version):
        return AnonymousIngestionOutcome(status="unknown_event")

    # Deliberately NOT "is this known" alone -- must also be in the
    # anonymous website allowlist specifically (Task 2B S8: "Do NOT
    # trust event_name merely because it is canonical"). A canonical,
    # authenticated-client-ingestible, or even backend-only event that
    # is not one of the 5 ANONYMOUS_WEBSITE_EVENTS is rejected here.
    if not is_anonymous_website_ingestible(event_name):
        return AnonymousIngestionOutcome(status="event_not_anonymous_ingestible")

    # ---- timestamp validation --------------------------------------------
    try:
        occurred_at = validate_occurred_at(body.get("occurred_at"))
    except ValidationError:
        return AnonymousIngestionOutcome(status="invalid_occurred_at")

    # ---- boundary hardening -----------------------------------------------
    # session_id is REQUIRED for this endpoint (Task 2B S5) -- unlike the
    # authenticated endpoint, where it's optional.
    session_id = body.get("session_id")
    if session_id is None:
        return AnonymousIngestionOutcome(status="invalid_field", field="session_id")
    try:
        validate_identifier("session_id", session_id)
    except ValidationError as exc:
        return AnonymousIngestionOutcome(status="invalid_field", field=exc.field)

    try:
        struct_properties, _ = validate_context_dict("properties", body.get("properties"), MAX_PROPERTIES_KEYS)
        struct_campaign, _ = validate_context_dict("campaign_context", body.get("campaign_context"), MAX_CAMPAIGN_CONTEXT_KEYS)
        # Task 9A -- page_path gets its own dedicated format contract on
        # top of validate_context_dict's generic string/length check
        # above: malformed (not a bare pathname) is a REJECT -- the
        # whole event fails to write -- never a silent drop, per Task
        # 9A's explicit "do not store arbitrary URLs" instruction. A
        # request that never includes page_path at all is completely
        # unaffected (validate_page_path(None) is a no-op).
        validate_page_path(struct_properties.get("page_path"))
    except ValidationError as exc:
        return AnonymousIngestionOutcome(status="invalid_field", field=exc.field)

    # Anonymous-only referrer normalization (S10) -- runs on the
    # structurally-clean dict, BEFORE the shared sanitizer. A referrer
    # value that isn't a plausible absolute http(s) URL is dropped
    # entirely, not persisted verbatim.
    if "referrer" in struct_campaign:
        normalized = _normalize_referrer(struct_campaign["referrer"])
        if normalized is None:
            struct_campaign = {k: v for k, v in struct_campaign.items() if k != "referrer"}
        else:
            struct_campaign = {**struct_campaign, "referrer": normalized}

    # Phase 2's own, unmodified, committed sanitizers -- the final
    # per-event allowlist + PII-value-shape pass, run AFTER this file's
    # own structural gate and referrer normalization. Same defense-in-
    # depth reuse the authenticated path already relies on.
    clean_properties, _ = sanitize_properties(event_name, event_version, struct_properties)
    clean_campaign, _ = sanitize_campaign_context(struct_campaign)

    # ---- existing Phase-2 record_event() -- unmodified -----------------------
    # platform is hard-coded "website" here -- never read from `body` at
    # all (Task 2B S3). firebase_uid/profile_id/anonymous_id/
    # correlation_id/entity_type/entity_id/source/notification_context/
    # dedupe_key are all left at record_event()'s own None defaults --
    # never fabricated, never looked up (Task 2B S4/S5/S13).
    result = record_event(
        event_name=event_name,
        event_version=event_version,
        occurred_at=occurred_at,
        platform=WEBSITE_PLATFORM,
        session_id=session_id,
        properties=clean_properties,
        campaign_context=clean_campaign,
    )

    if result.status == "written":
        return AnonymousIngestionOutcome(status="written", event_id=str(result.event.event_id))
    # skipped_duplicate_dedupe_key is architecturally unreachable here --
    # dedupe_key is never passed (always None) -- kept unmapped
    # deliberately rather than faking a "duplicate" branch that can
    # never actually be reached in this endpoint's v1.
    # write_failed, or (should not occur -- both anonymous events are
    # ledger-eligible) skipped_not_ledger_eligible.
    return AnonymousIngestionOutcome(status="write_failed")
