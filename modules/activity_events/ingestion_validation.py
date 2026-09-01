# modules/activity_events/ingestion_validation.py

"""
Boundary hardening for POST /api/activity-events (Phase 3) -- the
external-client-facing checks Phase 3 Step 1's audit found Phase-2's
event_schemas.py validator does not (and, per Locked Decision, should
not) provide: scalar-only values, size/count/length limits, NaN/
Infinity rejection, identifier charset, and timestamp skew bounds.

This module does NOT replace or duplicate modules/activity_events/
event_schemas.py's sanitize_* functions -- it runs FIRST, as a
structural gate ("is this even shaped like a legal request"), and the
survivors are then handed to Phase 2's existing, committed, unmodified
sanitize_properties/sanitize_campaign_context/sanitize_notification_
context for the final key-allowlist + defense-in-depth pass (see
ingestion_service.py). Two distinct policies, deliberately not merged:

  - A structural violation (non-dict context, a nested dict/list value,
    an oversized string/key-count, NaN/Infinity) is a REJECT -- the
    whole request fails with a 400, because a well-behaved client
    should never produce one of these; silently coping with it would
    hide a real client bug.
  - A content-policy hit inside an otherwise well-formed scalar value
    (an embedded email/phone/JWT-shaped string) is a DROP, not a
    reject -- matching Phase 2's own established philosophy (S3's
    "never fail loudly for this"). The offending key is removed and
    reported, the request still succeeds.

Not a generic schema framework -- five narrow, named checks, nothing
declarative, nothing per-event beyond what ingestion_policy.py already
decides.
"""

import math
import re
from datetime import datetime, timedelta, timezone

MAX_PROPERTIES_KEYS = 20
MAX_CAMPAIGN_CONTEXT_KEYS = 10
MAX_NOTIFICATION_CONTEXT_KEYS = 6
MAX_STRING_VALUE_LENGTH = 256
MAX_IDENTIFIER_LENGTH = 64

MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_HISTORICAL_AGE = timedelta(days=7)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Reused conceptually from event_schemas.py's own approach, not the
# same instances -- this file does not import from that committed
# module's internals. Phase 3 Step 2 flagged that Phase 2's phone check
# (.fullmatch()) misses a phone number embedded inside a longer string;
# fixed here, in new code, per Locked Decision #6 (do not edit the
# committed validator).
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# Phase 3 Step 4 audit found the first phone heuristic
# (`(?:\+?\d[\s-]?){8,15}`) empirically false-positives on ordinary
# UUIDs and short numeric identifiers (e.g. "20260901") -- a UUID's
# last hex group is 12 characters and not infrequently pure digits (no
# a-f letters), which satisfied that pattern's old 8-15 digit range,
# and hyphens were already an accepted separator. Retuned, verified
# against every required case (see test_activity_events_ingestion.py's
# PII REGRESSION section) rather than patched blindly:
#   1. A value that is itself a canonical UUID (8-4-4-4-12 hex groups)
#      is excluded outright -- this is the concrete shape that was
#      colliding, addressed directly rather than by loosening the
#      digit-count check alone (which cannot distinguish a UUID's
#      12-digit segment from a 12-digit phone number with country
#      code -- both are "12 digits", so the fix has to be shape-based,
#      not just a threshold change).
#   2. The minimum digit count is raised from 8 to 10 -- an 8-digit
#      run (e.g. a date-like "20260901") is common as an ordinary
#      analytics identifier and is not a plausible bare phone number;
#      10 is the shortest real phone number length this product's
#      audience (India) uses, and every required MUST-flag example
#      still clears 10.
# Implemented as a digit-counting scan over candidate digit/separator
# runs, not a single dense regex -- easier to verify correct than the
# previous `(?:\+?\d[\s-]?){N,M}` repetition style, which is fragile
# to reason about by hand (a separator can optionally merge with either
# neighboring digit, making manual verification error-prone).
_UUID_SHAPE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_PHONE_CANDIDATE_RE = re.compile(r"[\d\s\-+]{10,}")
_MIN_PHONE_DIGITS = 10
_MAX_PHONE_DIGITS = 15

# Three dot-separated base64url-ish segments -- a plain structural
# shape check for "looks like a JWT", not a real JWT parser.
_JWT_SHAPE_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def _looks_like_phone(value: str) -> bool:
    if _UUID_SHAPE_RE.match(value.strip()):
        return False
    for candidate in _PHONE_CANDIDATE_RE.finditer(value):
        digit_count = sum(ch.isdigit() for ch in candidate.group())
        if _MIN_PHONE_DIGITS <= digit_count <= _MAX_PHONE_DIGITS:
            return True
    return False


class ValidationError(Exception):
    """Raised for a structural violation -- caller (ingestion_service)
    catches this and maps it to a 400 invalid_field response. Never
    raised for a content-policy hit (those are silent drops)."""

    def __init__(self, field: str, reason: str):
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def validate_identifier(name: str, value) -> None:
    """anonymous_id / session_id / idempotency_key. Raises
    ValidationError on any violation; returns None (no-op) if value is
    None -- these are all optional fields."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ValidationError(name, "must be a string")
    if not value or len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValidationError(name, f"must be 1-{MAX_IDENTIFIER_LENGTH} characters")
    if not _IDENTIFIER_RE.match(value):
        raise ValidationError(name, "must match [A-Za-z0-9_-]+")


def validate_occurred_at(raw) -> datetime:
    """Returns the parsed, timezone-aware datetime, or raises
    ValidationError. Missing, malformed, missing-timezone, or
    out-of-[-7d, +5min] are all the same controlled failure from the
    caller's point of view (400 invalid_occurred_at)."""
    if not raw or not isinstance(raw, str):
        raise ValidationError("occurred_at", "required")

    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationError("occurred_at", "not a valid ISO-8601 timestamp")

    if parsed.tzinfo is None:
        raise ValidationError("occurred_at", "timezone is required")

    now = datetime.now(timezone.utc)
    delta = parsed - now
    if delta > MAX_FUTURE_SKEW:
        raise ValidationError("occurred_at", "more than 5 minutes in the future")
    if -delta > MAX_HISTORICAL_AGE:
        raise ValidationError("occurred_at", "more than 7 days old")

    return parsed


def _value_is_structurally_valid_scalar(value) -> bool:
    """dict/list are the structural violation this function exists to
    catch -- everything else (str/int/float/bool/None) passes this
    check; NaN/Infinity is checked separately (it's still technically
    a float, just not a value Postgres jsonb accepts)."""
    return value is None or isinstance(value, (str, int, float, bool))


def _value_is_nan_or_infinite(value) -> bool:
    return isinstance(value, float) and (math.isnan(value) or math.isinf(value))


def _value_content_policy_hit(value) -> bool:
    """True if a string value looks like an embedded email, an
    embedded phone number, or a JWT-shaped token. Non-string values
    never hit this (there's nothing to search)."""
    if not isinstance(value, str):
        return False
    if _EMAIL_RE.search(value):
        return True
    if _looks_like_phone(value):
        return True
    if _JWT_SHAPE_RE.match(value.strip()):
        return True
    return False


def validate_context_dict(field_name: str, raw, max_keys: int) -> tuple:
    """properties / campaign_context / notification_context. Returns
    (structurally_clean_dict, dropped_keys) -- structurally_clean_dict
    still needs to go through Phase 2's sanitize_* afterward (this
    function does not apply any event-specific allowlist). Raises
    ValidationError for anything structural (not a dict, too many
    keys, a nested value, an oversized string, NaN/Infinity). Silently
    drops (does not raise) a key whose value merely looks like PII/a
    token -- consistent with Phase 2's own drop-not-reject philosophy."""
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        raise ValidationError(field_name, "must be a JSON object")
    if len(raw) > max_keys:
        raise ValidationError(field_name, f"at most {max_keys} keys")

    clean = {}
    dropped = []
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValidationError(field_name, "keys must be strings")

        if not _value_is_structurally_valid_scalar(value):
            raise ValidationError(field_name, f"key {key!r}: nested values are not allowed")

        if _value_is_nan_or_infinite(value):
            raise ValidationError(field_name, f"key {key!r}: NaN/Infinity is not a valid value")

        if isinstance(value, str) and len(value) > MAX_STRING_VALUE_LENGTH:
            raise ValidationError(field_name, f"key {key!r}: value exceeds {MAX_STRING_VALUE_LENGTH} characters")

        if _value_content_policy_hit(value):
            # Drop, don't reject -- matches Phase 2's philosophy.
            dropped.append(key)
            continue

        clean[key] = value

    return clean, dropped
