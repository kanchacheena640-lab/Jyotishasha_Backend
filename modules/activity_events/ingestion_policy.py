# modules/activity_events/ingestion_policy.py

"""
Client-ingestion ownership policy for POST /api/activity-events (Phase 3).

This is deliberately a SEPARATE, NEW module from modules/activity_events/
event_schemas.py -- the frozen Phase-2 canonical registry (34 events,
committed in 94a39cf) is not modified to add this concept. "Known to the
ledger" (event_schemas.is_known_event) and "acceptable from an external
HTTP client" (this module) are different questions with different
answers -- payment_verified, every subscription_* lifecycle event, and
both Ask Now delivery/failure events are all perfectly valid, frozen,
KNOWN events that must never be reachable through this endpoint, because
nothing a client posts here can ever become backend-authoritative
business truth (Phase 3 Step 1 audit, event ownership table).

The original 10 client-ingestible events frozen in Phase 3 Step 2:
session_start, app_download_intent, cta_click, feature_used,
asknow_entry_viewed, report_discovery_viewed, report_viewed,
report_downloaded, subscription_discovery_viewed, notification_opened.

Phase 5D.2 -- one narrowly-scoped addition, its own explicit design-
freeze pass (Phase 5D's ownership audit determined login_completed is
Flutter-owned: "a real interactive authentication successfully
completed by the user," a fact only the client can observe -- see that
phase's own report for the full reasoning): login_completed. Its
sibling signup_completed (same "I. Core" section of EVENT_SCHEMAS,
same {property} shape) was explicitly audited and determined to be
BACKEND-owned instead (Phase 5D.1) -- the first durable AppUser/profile
creation is a fact only the backend's own bootstrap commit can prove,
never a client claim -- and deliberately remains OUT of this set.

Exactly these 11 client-ingestible events as of Phase 5D.2:
session_start, login_completed, app_download_intent, cta_click,
feature_used, asknow_entry_viewed, report_discovery_viewed,
report_viewed, report_downloaded, subscription_discovery_viewed,
notification_opened. page_view stays GA4/Firebase-only (not even
ledger-eligible, per event_schemas.is_ledger_eligible). Every other
canonical event -- including every one of these 11's own event_version
variants beyond 1, should Phase 2 ever add one -- is rejected here, not
silently allowed because event_schemas.is_known_event() happens to say
yes.

entity_type/entity_id policy (Phase 3 Step 2, S7): only report_viewed
and report_downloaded may carry entity_type="ai_report" (Order-based
purchased-PDF reports are explicitly NOT supported in this v1 --
Order has no account/profile linkage column to verify ownership
against). Every other client-ingestible event must not carry
entity_type/entity_id at all.
"""

# Frozen set -- do not add without a new design-freeze pass. Deliberately
# a plain frozenset of names, not reusing/extending event_schemas.
# EVENT_SCHEMAS's shape, so this file can be read on its own without
# implying it modifies that committed registry.
#
# Phase 5D.2: "login_completed" added -- the one authorized addition
# past the original Phase 3 Step 2 set (see this module's own docstring
# for the ownership reasoning). Placed immediately after "session_start"
# to keep both of EVENT_SCHEMAS's "I. Core" client-ingestible members
# grouped together, matching this set's existing section-grouped order.
CLIENT_INGESTIBLE_EVENTS = frozenset({
    "session_start",
    "login_completed",
    "app_download_intent",
    "cta_click",
    "feature_used",
    "asknow_entry_viewed",
    "report_discovery_viewed",
    "report_viewed",
    "report_downloaded",
    "subscription_discovery_viewed",
    "notification_opened",
})

# Only these two events may carry an entity_type/entity_id pair, and only
# this one entity_type value -- Order-based reports are out of scope for
# v1 (Phase 3 Step 2, S7: Order has no owner column to verify against).
REPORT_ENTITY_EVENTS = frozenset({"report_viewed", "report_downloaded"})
ALLOWED_ENTITY_TYPE = "ai_report"


def is_client_ingestible(event_name: str) -> bool:
    return event_name in CLIENT_INGESTIBLE_EVENTS


def requires_entity_ownership(event_name: str) -> bool:
    return event_name in REPORT_ENTITY_EVENTS


def entity_fields_allowed(event_name: str) -> bool:
    """False for every client-ingestible event except the two report
    ones -- entity_type/entity_id must be entirely absent from the
    request for anything else (Phase 3 Step 2, S7's closing rule)."""
    return event_name in REPORT_ENTITY_EVENTS


def parse_entity_id(raw) -> int:
    """entity_id must be a string of digits parsing to a positive int
    (AIReport.id is a plain Integer PK). Raises ValueError on any other
    shape -- caller (ingestion_service) maps that to 400 invalid_field."""
    if not isinstance(raw, str) or not raw.isdigit():
        raise ValueError("entity_id must be a positive integer string")
    value = int(raw)
    if value <= 0:
        raise ValueError("entity_id must be a positive integer string")
    return value


def verify_ai_report_ownership(entity_id_int: int, profile_id) -> bool:
    """Read-only. True only if an AIReport with this id exists AND its
    profile_id matches the resolved (server-side, JWT-derived)
    profile_id. profile_id=None always returns False -- ownership
    cannot be established for an identity with no resolved profile
    (Phase 3 Step 3, S7). Order-based purchased-PDF reports are not
    supported here at all -- Order has no owner column to check
    against (Phase 3 Step 2, S7)."""
    if profile_id is None:
        return False

    from modules.models_ai_reports import AIReport

    report = AIReport.query.filter_by(id=entity_id_int, profile_id=profile_id).first()
    return report is not None
