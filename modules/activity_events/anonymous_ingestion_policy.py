# modules/activity_events/anonymous_ingestion_policy.py

"""
Task 2B -- the anonymous WEBSITE ingestion allowlist for
POST /api/activity-events/anonymous.

Deliberately a SEPARATE, NEW, and SMALLER allowlist from
modules/activity_events/ingestion_policy.py's CLIENT_INGESTIBLE_EVENTS
(the 11 events an authenticated JWT-bearing client may submit). Being
in CLIENT_INGESTIBLE_EVENTS does NOT imply membership here -- the two
answer different questions ("may an authenticated app/website client
submit this" vs "may a completely unauthenticated, unverified website
visitor submit this"), and this file's set is intentionally the
stricter of the two.

ANONYMOUS_WEBSITE_EVENTS = exactly 5 events, each individually checked
against modules/activity_events/event_schemas.py's frozen EVENT_SCHEMAS
before being added here (Task 2B S2's explicit "STOP and report the
exact mismatch" instruction -- no mismatch was found for any of the 5,
recorded below):

  cta_click (v1)                  -- properties {cta_id, screen_name}.
    Both free-form-but-short UI identifiers, no PII shape, no entity
    fields required (entity_fields_allowed("cta_click") is False).
  feature_used (v1)               -- properties {feature_name}. Same
    reasoning as cta_click.
  app_download_intent (v1)        -- properties {cta_location}. Same
    reasoning; campaign_context (utm_source/utm_medium/utm_campaign) is
    the envelope's own existing carrier for its acquisition UTM data,
    already reused as-is, no schema change needed.
  report_discovery_viewed (v1)    -- properties {report_type}. A
    category label (e.g. "love"/"career"), not report content itself;
    no entity fields required.
  subscription_discovery_viewed (v1) -- properties {plan, placement}.
    Plan/placement labels only, no entity fields required.

Every one of these 5 is already ledger-eligible (event_schemas.
is_ledger_eligible), requires no entity_type/entity_id
(ingestion_policy.entity_fields_allowed() is False for all 5 -- only
report_viewed/report_downloaded, both explicitly EXCLUDED here, ever
carry entity fields), and requires no identity/ownership resolution.

Explicitly, permanently excluded from this set (Task 2B S2, verbatim):
  page_view                 -- not even ledger-eligible; GA4/Firebase-only.
  login_completed            -- authenticated-client-owned (Phase 5D.3).
  signup_completed            -- backend-authoritative (Phase 5D.1).
  session_start                -- authenticated-app-session concept,
                                   not part of this task's website
                                   acquisition/engagement journey; not
                                   requested by Task 2B S2's initial list.
  every Ask Now event          -- backend-authoritative delivery facts.
  every payment event          -- backend-authoritative business truth.
  every report_generation_* event -- backend-authoritative.
  report_viewed / report_downloaded -- authenticated-owner-verified only
                                   (require entity_type=ai_report +
                                   profile-ownership check); an anonymous
                                   visitor has no profile to verify
                                   ownership against.
  every subscription_* lifecycle event (other than *_discovery_viewed)
                                -- backend-authoritative.
  every notification_* event   -- backend-authoritative.

Do not add a new event to this set without the same per-event schema
check recorded above, applied and documented the same way.
"""

ANONYMOUS_WEBSITE_EVENTS = frozenset({
    "cta_click",
    "feature_used",
    "app_download_intent",
    "report_discovery_viewed",
    "subscription_discovery_viewed",
})


def is_anonymous_website_ingestible(event_name: str) -> bool:
    return event_name in ANONYMOUS_WEBSITE_EVENTS
