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

Task 5A -- one further narrowly-scoped addition, its own explicit
design-freeze pass: "app_install_attributed". Represents "Google Play
install attribution was captured by the Android app and later
associated with an authenticated app lifecycle" -- a fact only the
Android app (which alone possesses the Play Install Referrer evidence)
can observe, exactly the same ownership reasoning already established
for login_completed above. It is NOT GA4 first_open, NOT a raw install
counter, NOT the website's own app_download_intent, and NOT proof of a
user-level website-to-install conversion -- see
modules/activity_events/event_schemas.py's own registration comment
for the full frozen meaning. Placed in EVENT_PLATFORM_RESTRICTIONS
below because -- uniquely among this set -- it must never be
producible from any platform other than app_android (Task 5A's own
explicit platform-safety requirement: this fact currently only has
meaning for a Google Play install).

Exactly these 12 client-ingestible events as of Task 5A.

entity_type/entity_id policy (Phase 3 Step 2, S7): only report_viewed
and report_downloaded may carry entity_type="ai_report" (Order-based
purchased-PDF reports are explicitly NOT supported in this v1 --
Order has no account/profile linkage column to verify ownership
against). Every other client-ingestible event must not carry
entity_type/entity_id at all.

Platform-restriction policy (Task 5A): the authenticated endpoint's own
ALLOWED_CLIENT_PLATFORMS (ingestion_service.py) is a single, GLOBAL
allowlist ({app_android, app_ios, website}) shared by every client-
ingestible event -- there is no per-event platform concept there. Some
events are legitimately producible from any of those platforms (e.g.
cta_click, feature_used); app_install_attributed is not one of them.
EVENT_PLATFORM_RESTRICTIONS below is a second, narrower, OPT-IN gate --
most events have no entry and are unrestricted (any globally-allowed
platform), exactly mirroring how REPORT_ENTITY_EVENTS above is an
opt-in restriction most events never trigger. This is deliberately the
smallest addition that closes the gap, not a new architecture: one
more frozenset-keyed lookup, checked by ingestion_service.py right
after its own existing global platform check.
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
    "app_install_attributed",
})

# Only these two events may carry an entity_type/entity_id pair, and only
# this one entity_type value -- Order-based reports are out of scope for
# v1 (Phase 3 Step 2, S7: Order has no owner column to verify against).
REPORT_ENTITY_EVENTS = frozenset({"report_viewed", "report_downloaded"})
ALLOWED_ENTITY_TYPE = "ai_report"

# Task 5A -- opt-in per-event platform restriction, checked IN ADDITION
# TO (never instead of) ingestion_service.py's own existing global
# ALLOWED_CLIENT_PLATFORMS check. An event with no entry here is
# unrestricted (any globally-allowed platform may produce it) -- see
# this module's own docstring for the full reasoning.
EVENT_PLATFORM_RESTRICTIONS = {
    "app_install_attributed": frozenset({"app_android"}),
}


def is_client_ingestible(event_name: str) -> bool:
    return event_name in CLIENT_INGESTIBLE_EVENTS


def is_platform_allowed_for_event(event_name: str, platform: str) -> bool:
    """True if this event has no platform restriction at all, or if
    `platform` is one of its restricted set. Callers must have already
    checked `platform` against the global ALLOWED_CLIENT_PLATFORMS --
    this function only ever narrows further, never widens."""
    restriction = EVENT_PLATFORM_RESTRICTIONS.get(event_name)
    return restriction is None or platform in restriction


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
