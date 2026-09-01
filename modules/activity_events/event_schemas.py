# modules/activity_events/event_schemas.py

"""
Property schema registry -- the Phase 1 Privacy Contract's enforcement
mechanism (frozen contract, "Privacy Contract" -> "Enforcement
mechanism"). One explicit, per-(event_name, event_version) allowlist of
`properties` keys, plus a single global allowlist each for
`campaign_context` and `notification_context` (their shapes are defined
once, contract-wide, in the frozen envelope -- not per event).

Unknown keys are DROPPED, never inserted, and reported back to the
caller as schema drift (modules/activity_events/service.py logs this --
writes never fail loudly for an unknown key). A denylist regex backstop
additionally strips anything that merely *looks* like PII (an email- or
phone-shaped string, or a key name matching a forbidden term) even if a
future developer mistakenly adds it to an event's own allowlist -- this
is the defense-in-depth layer the frozen contract calls for.

Registry note -- count discrepancy, flagged not silently resolved:
Phase 1's own prose says "33 canonical events," but the frozen
registry's own tables (Master Event Registry, sections I-IX) enumerate
34 distinct event_names once subscription_refunded (mentioned in prose
as "included though not tabled separately") is counted alongside the 9
tabled subscription rows. This file registers all 34 actual, frozen,
already-enumerated event names -- none invented, none dropped to force
a round number. Flagged here for the record; not something this file's
author has the authority to resolve by silently omitting one.

Property-vs-envelope-column note: the frozen registry's "Required
properties" column is a business-level list of what an event needs, not
a literal JSONB-key assignment -- several listed items are already
first-class envelope columns (firebase_uid, profile_id, platform,
entity_type, entity_id) and are excluded from the `properties`
allowlists below to avoid storing the same fact twice. Two further
judgment calls, made explicitly rather than silently:
  - app_download_intent's "utm_source, utm_medium, utm_campaign" are
    routed to `campaign_context` (the column the envelope defines
    exactly for UTM data), not `properties`.
  - notification_sent/notification_opened's "notification_id[, slot]"
    are routed to `notification_context`, whose frozen shape is
    literally {notification_id, campaign_id, slot} (envelope, S4).

Ask Now `source` naming collision, flagged not silently resolved: the
envelope's first-class `source` column means "which screen/service
fired this event" (S4). Ask Now's required property also named
`source` (free|pack) means something entirely different. Both are kept
exactly as the frozen contract names them -- this file stores Ask Now's
`source` as a `properties` key (its plain meaning is a business value,
not a producer-context value) and simply notes the collision here
rather than renaming anything not in this author's authority to rename.

`category` (Ask Now): the frozen contract's callout says it is
"reserved... on both Ask Now events." Which two, out of four Ask Now
events, is not stated unambiguously. Read narrowly here as the two
lifecycle events closest to "question" and "answer"
(asknow_question_submitted, asknow_answer_delivered) -- flagged as an
interpretation, not a certainty.

Subscription events: the frozen table for section VII has no "Required
properties" column at all. `plan` and `store` are allowed (optional,
not required) on every subscription_* event solely because S4's own
closing note names `plan` as a field that "lives in properties instead"
of being a column -- subscription events are the only family it could
plausibly belong to. Flagged as an inference, not a literal per-event
specification.
"""

import re

# ---------------------------------------------------------------------
# Global denylist backstop -- applies to every properties/context blob
# regardless of that event's own allowlist. Rule 11 (frozen Privacy
# Contract, FORBIDDEN): full birth details, email, phone, person names,
# auth tokens, payment credentials, report content, OpenAI prompts/
# responses, Ask Now question/answer text, raw IP.
# ---------------------------------------------------------------------
_FORBIDDEN_KEY_SUBSTRINGS = (
    "email", "phone", "mobile", "dob", "tob", "pob",
    "lat", "lng", "latitude", "longitude", "birth",
    "token", "password", "secret", "auth", "jwt", "credential",
    "card", "cvv", "upi", "account_number",
    "question", "answer", "prompt", "response_text", "report_content",
    "ip_address", "ip",
)

# Deliberately separate from the generic substring list above: a bare
# "name" would also match this codebase's own legitimate keys
# (screen_name, feature_name) -- narrowed to the actual person-name
# shapes Rule 11 means to forbid.
_FORBIDDEN_NAME_KEY_SUBSTRINGS = (
    "full_name", "first_name", "last_name", "person_name",
    "customer_name", "contact_name", "display_name", "user_name",
)

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Phase 3 Step 6 correction: lower bound raised from 8 to 10 digits.
# The 8-digit floor made this fullmatch() a bare 8-digit numeric value
# (e.g. a date-like identifier such as "20260901") as phone-shaped --
# demonstrated as a real false positive by Phase 3's client-ingestion
# boundary tests. Confirmed empirically before changing: 10 is the
# smallest floor that still fullmatch()es every required phone example
# (a bare 10-digit number, a +91-prefixed 12-digit number with or
# without a separating space, and both spaced/hyphenated 10-digit
# forms) while excluding the 8-digit case. No UUID-specific handling
# was added -- unnecessary, since fullmatch() over an entire UUID
# string already fails today regardless of this bound (a UUID's fixed
# hyphen positions and typical hex letters don't fit this pattern's
# shape at all), confirmed empirically, not assumed.
_PHONE_RE = re.compile(r"(?:\+?\d[\s-]?){10,15}")


def _key_is_forbidden(key: str) -> bool:
    lowered = key.lower()
    if any(term in lowered for term in _FORBIDDEN_KEY_SUBSTRINGS):
        return True
    return any(term in lowered for term in _FORBIDDEN_NAME_KEY_SUBSTRINGS)


def _value_looks_like_pii(value) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_EMAIL_RE.search(value)) or bool(_PHONE_RE.fullmatch(value.strip()))


# ---------------------------------------------------------------------
# Controlled failure_reason vocabulary -- Rule 11: "never arbitrary
# exception text." Shared across every event family that has a
# failure_reason property (asknow_answer_failed, report_generation_
# failed, payment_failed) rather than a per-event free-text field.
# ---------------------------------------------------------------------
FAILURE_REASONS = frozenset({
    "timeout",
    "upstream_error",
    "invalid_input",
    "rate_limited",
    "insufficient_credits",
    "provider_declined",
    "signature_mismatch",
    "not_found",
    "unknown",
})

# ---------------------------------------------------------------------
# campaign_context / notification_context -- one global shape each,
# per the frozen envelope (S4), not per-event.
# ---------------------------------------------------------------------
CAMPAIGN_CONTEXT_ALLOWED_KEYS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "referrer", "medium",
})

NOTIFICATION_CONTEXT_ALLOWED_KEYS = frozenset({
    "notification_id", "campaign_id", "slot",
})


def _schema(properties_keys, ledger_eligible=True):
    return {
        "properties": frozenset(properties_keys),
        "ledger_eligible": ledger_eligible,
    }


# ---------------------------------------------------------------------
# The 34 frozen canonical events (see module docstring re: the "33" vs
# 34 count). Keyed by (event_name, event_version) -- event_version
# defaults to 1 for every event in this Step 2 foundation; none has
# shipped a v2 shape yet.
# ---------------------------------------------------------------------
EVENT_SCHEMAS = {
    # -- I. Core -------------------------------------------------------
    ("session_start", 1): _schema({"entry_point"}),
    # Deliberately NOT persisted to the ledger (frozen S3.I): stays in
    # GA4/Firebase. Registered here so the write helper can refuse it
    # explicitly rather than silently accepting a firehose event.
    ("page_view", 1): _schema(set(), ledger_eligible=False),
    ("signup_completed", 1): _schema({"provider"}),
    ("login_completed", 1): _schema({"method"}),

    # -- II. Acquisition -------------------------------------------------
    ("app_download_intent", 1): _schema({"cta_location"}),

    # -- III. Engagement -------------------------------------------------
    ("cta_click", 1): _schema({"cta_id", "screen_name"}),
    ("feature_used", 1): _schema({"feature_name"}),

    # -- V. Ask Now --------------------------------------------------------
    ("asknow_entry_viewed", 1): _schema(set()),
    ("asknow_question_submitted", 1): _schema({"source", "category"}),
    ("asknow_answer_delivered", 1): _schema({"source", "latency_ms", "category"}),
    ("asknow_answer_failed", 1): _schema({"source", "failure_reason"}),

    # -- VI. Reports -------------------------------------------------------
    ("report_discovery_viewed", 1): _schema({"report_type"}),
    ("report_generation_started", 1): _schema({"report_type"}),
    ("report_generation_completed", 1): _schema({"report_type"}),
    ("report_generation_failed", 1): _schema({"failure_reason"}),
    ("report_viewed", 1): _schema(set()),
    ("report_downloaded", 1): _schema(set()),

    # -- VII. Subscriptions (mirrors SubscriptionEvent.event_type) ---------
    ("subscription_discovery_viewed", 1): _schema({"plan"}),
    ("subscription_trial_started", 1): _schema({"plan", "store"}),
    ("subscription_trial_expired", 1): _schema({"plan", "store"}),
    ("subscription_pending_created", 1): _schema({"plan", "store"}),
    ("subscription_started", 1): _schema({"plan", "store"}),
    ("subscription_renewed", 1): _schema({"plan", "store"}),
    ("subscription_grace_entered", 1): _schema({"plan", "store"}),
    ("subscription_expired", 1): _schema({"plan", "store"}),
    ("subscription_cancelled", 1): _schema({"plan", "store"}),
    ("subscription_refunded", 1): _schema({"plan", "store"}),

    # -- VIII. Payments (generic, purpose-tagged) ---------------------------
    ("payment_initiated", 1): _schema({"purpose", "provider", "order_reference"}),
    ("payment_verified", 1): _schema({"purpose", "provider", "order_reference", "amount", "currency"}),
    ("payment_failed", 1): _schema({"purpose", "provider", "failure_reason"}),
    ("payment_duplicate_ignored", 1): _schema({"purpose", "provider"}),

    # -- IX. Notifications ---------------------------------------------------
    ("notification_created", 1): _schema({"notification_type", "target_scope"}),
    ("notification_sent", 1): _schema(set()),   # notification_id/slot -> notification_context, not properties
    ("notification_opened", 1): _schema(set()),  # notification_id -> notification_context
}


def is_known_event(event_name: str, event_version: int = 1) -> bool:
    return (event_name, event_version) in EVENT_SCHEMAS


def is_ledger_eligible(event_name: str, event_version: int = 1) -> bool:
    """False only for page_view -- deliberately excluded from the ledger
    per S3.I. Unknown event names are also not ledger-eligible (they
    fail is_known_event first)."""
    schema = EVENT_SCHEMAS.get((event_name, event_version))
    return bool(schema and schema["ledger_eligible"])


def sanitize_properties(event_name: str, event_version: int, raw: dict) -> tuple:
    """Returns (clean_dict, dropped_keys). Never raises on a malformed
    input -- an unknown event_name simply yields an empty allowlist (the
    caller is expected to have already rejected unknown events via
    is_known_event before calling this)."""
    raw = raw or {}
    schema = EVENT_SCHEMAS.get((event_name, event_version))
    allowed = schema["properties"] if schema else frozenset()

    clean = {}
    dropped = []
    for key, value in raw.items():
        if key not in allowed:
            dropped.append(key)
            continue
        if _key_is_forbidden(key) or _value_looks_like_pii(value):
            # Defense-in-depth: even an allowlisted key name is refused
            # if the value itself looks like PII, or if the key itself
            # matches a forbidden term despite being in the allowlist
            # (protects against a future copy-paste mistake).
            dropped.append(key)
            continue
        if key == "failure_reason" and value not in FAILURE_REASONS:
            # Never arbitrary exception text -- Rule 11.
            dropped.append(key)
            continue
        clean[key] = value

    return clean, dropped


def sanitize_campaign_context(raw: dict) -> tuple:
    raw = raw or {}
    clean = {}
    dropped = []
    for key, value in raw.items():
        if key not in CAMPAIGN_CONTEXT_ALLOWED_KEYS:
            dropped.append(key)
            continue
        if _key_is_forbidden(key) or _value_looks_like_pii(value):
            dropped.append(key)
            continue
        clean[key] = value
    return clean, dropped


def sanitize_notification_context(raw: dict) -> tuple:
    raw = raw or {}
    clean = {}
    dropped = []
    for key, value in raw.items():
        if key not in NOTIFICATION_CONTEXT_ALLOWED_KEYS:
            dropped.append(key)
            continue
        if _key_is_forbidden(key) or _value_looks_like_pii(value):
            dropped.append(key)
            continue
        clean[key] = value
    return clean, dropped
