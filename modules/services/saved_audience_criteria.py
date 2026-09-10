# modules/services/saved_audience_criteria.py

"""
U6A -- Saved Audience criteria validation.

ONE validator, reused identically at:
  (a) authoring time (POST/PATCH /admin/api/audiences) -- full
      validation including the one dynamic, live check (ask_now_concern
      must reference a currently ACTIVE category), and
  (b) resolve time (GET/POST .../preview) -- the SAME structural/type/
      canonical-set validation, but WITHOUT the currently-active check
      for ask_now_concern (U6.0's own frozen distinction -- see
      validate_criteria()'s own docstring).

This is deliberately NOT a second, independently-typed copy of
routes_admin_users.py's own validation: every canonical VALUE SET here
is imported directly from its one true source (modules/services/
admin_users_service.py's own CANONICAL_* constants, and
static_astrology_extractor.py's own CANONICAL_YOG_KEYS/
CANONICAL_DOSH_KEYS) -- never re-derived, never hand-copied. The SHAPE
of the input genuinely differs (typed JSON values here; comma-separated
query-string values in routes_admin_users.py), so the parsing functions
themselves are new, but the values they check against are the exact
same single source of truth used by the live GET /admin/api/users
endpoint.

Security contract (U6A Sections 9/19): criteria is declarative data
only. There is no slot anywhere in this schema for a nested/arbitrary
JSON structure, an operator, an expression, or a raw string that could
ever be interpolated into SQL -- every filter key maps to one of a
fixed, small set of primitive/array-of-primitive shapes, checked
against either a fixed Python set (moon_sign, lagna, ...) or resolved
by list_users()/resolve_user_ids() through the exact same parameterized
SQLAlchemy query-building admin_users_service.py already uses for live
Admin Users requests. Rejecting bad input never means "sanitize and
continue" -- it always means "reject the whole criteria object with a
structured 400," matching routes_admin_users.py's own existing
convention exactly.
"""

from modules.services import admin_users_service as _admin
from modules.services.static_astrology_extractor import (
    CANONICAL_YOG_KEYS,
    CANONICAL_DOSH_KEYS,
)
from modules.services.asknow_category_service import get_active_category_names

CRITERIA_VERSION = 1

_VALID_STATUSES = frozenset({"active", "inactive", "unknown"})
_VALID_CUSTOMER_TYPES = frozenset({"free", "paying"})


class CriteriaValidationError(ValueError):
    """Raised for any structurally/semantically invalid criteria object.
    `code` is a stable, machine-readable error code (e.g.
    "unknown_filter_key", "invalid_criteria_version") -- the route layer
    turns this into {"error": code, "message": str(self)}, 400, matching
    routes_admin_users.py's own {"error": "invalid_<field>", ...}
    convention exactly."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _require(condition: bool, code: str, message: str):
    if not condition:
        raise CriteriaValidationError(code, message)


def _validate_string(key, value):
    _require(isinstance(value, str), "invalid_filter_value", f"{key} must be a JSON string.")


def _validate_bool(key, value):
    # bool is a subclass of int in Python -- isinstance(value, bool) is
    # the only check that actually distinguishes true/false from 0/1.
    _require(isinstance(value, bool), "invalid_filter_value", f"{key} must be a JSON boolean (true/false).")


def _validate_int(key, value):
    _require(isinstance(value, int) and not isinstance(value, bool), "invalid_filter_value",
              f"{key} must be a JSON integer.")


def _validate_enum_single(key, value, canonical_set):
    _validate_string(key, value)
    _require(value in canonical_set, "invalid_filter_value",
              f"{key} must be one of {sorted(canonical_set)}.")


def _validate_enum_multi(key, value, canonical_set):
    _require(isinstance(value, list) and len(value) > 0, "invalid_filter_value",
              f"{key} must be a non-empty JSON array.")
    for v in value:
        _require(isinstance(v, str), "invalid_filter_value", f"{key} values must be strings.")
    _require(set(value).issubset(canonical_set), "invalid_filter_value",
              f"{key} values must be a subset of {sorted(canonical_set)}.")


def _validate_int_enum_multi(key, value, canonical_set):
    _require(isinstance(value, list) and len(value) > 0, "invalid_filter_value",
              f"{key} must be a non-empty JSON array.")
    for v in value:
        _require(isinstance(v, int) and not isinstance(v, bool), "invalid_filter_value",
                  f"{key} values must be integers.")
    _require(set(value).issubset(canonical_set), "invalid_filter_value",
              f"{key} values must be a subset of {sorted(canonical_set)}.")


def _validate_ask_now_concern(value):
    # Structural check only -- NEVER a live "is this currently active"
    # check here (that is authoring-only, applied separately below in
    # validate_criteria() -- see U6A Section 10). ask_now_concern is a
    # plain EXISTS filter against ask_now_intent_history at resolve
    # time (_admin._ask_now_concern_expr()), which has no active-only
    # constraint of its own either -- a category name that never
    # existed at all simply matches zero rows, never crashes.
    _require(isinstance(value, list) and len(value) > 0, "invalid_filter_value",
              "ask_now_concern must be a non-empty JSON array.")
    for v in value:
        _require(isinstance(v, str) and v.strip() != "", "invalid_filter_value",
                  "ask_now_concern values must be non-empty strings.")


# U6A Section 7 -- the canonical Saved Audience v1 filter allowlist.
# Every key maps 1:1 to a keyword argument of admin_users_service.py::
# list_users()/resolve_user_ids() -- verified against that file's own
# CURRENT signature before being frozen here (U6A audit step). An
# unknown key is ALWAYS rejected in validate_criteria() below, never
# silently dropped.
_FILTER_VALIDATORS = {
    "language": lambda v: _validate_enum_multi("language", v, {"en", "hi"}),
    "search": lambda v: _validate_string("search", v),
    "age_min": lambda v: _validate_int("age_min", v),
    "age_max": lambda v: _validate_int("age_max", v),
    "status": lambda v: _validate_enum_single("status", v, _VALID_STATUSES),
    "signup_from": lambda v: _validate_string("signup_from", v),
    "signup_to": lambda v: _validate_string("signup_to", v),
    "customer_type": lambda v: _validate_enum_single("customer_type", v, _VALID_CUSTOMER_TYPES),
    "ask_now_buyer": lambda v: _validate_bool("ask_now_buyer", v),
    "active_subscription": lambda v: _validate_bool("active_subscription", v),
    "moon_sign": lambda v: _validate_enum_multi("moon_sign", v, set(_admin.CANONICAL_SIGNS)),
    "lagna": lambda v: _validate_enum_multi("lagna", v, set(_admin.CANONICAL_SIGNS)),
    "nakshatra": lambda v: _validate_enum_multi("nakshatra", v, set(_admin.CANONICAL_NAKSHATRAS)),
    "nakshatra_pada": lambda v: _validate_int_enum_multi("nakshatra_pada", v, set(_admin.CANONICAL_NAKSHATRA_PADAS)),
    "yog": lambda v: _validate_enum_multi("yog", v, CANONICAL_YOG_KEYS),
    "dosh": lambda v: _validate_enum_multi("dosh", v, CANONICAL_DOSH_KEYS),
    "mahadasha": lambda v: _validate_enum_multi("mahadasha", v, set(_admin.CANONICAL_DASHA_LORDS)),
    "antardasha": lambda v: _validate_enum_multi("antardasha", v, set(_admin.CANONICAL_DASHA_LORDS)),
    "sade_sati_active": lambda v: _validate_bool("sade_sati_active", v),
    "sade_sati_phase": lambda v: _validate_enum_multi("sade_sati_phase", v, set(_admin.CANONICAL_SADE_SATI_PHASES)),
    "jupiter_house": lambda v: _validate_int_enum_multi("jupiter_house", v, set(_admin.CANONICAL_TRANSIT_HOUSES)),
    "saturn_house": lambda v: _validate_int_enum_multi("saturn_house", v, set(_admin.CANONICAL_TRANSIT_HOUSES)),
    "rahu_house": lambda v: _validate_int_enum_multi("rahu_house", v, set(_admin.CANONICAL_TRANSIT_HOUSES)),
    "ketu_house": lambda v: _validate_int_enum_multi("ketu_house", v, set(_admin.CANONICAL_TRANSIT_HOUSES)),
    "ask_now_concern": lambda v: _validate_ask_now_concern(v),
}

# U6A Section 20 -- an explicitly-valid EMPTY filters object ({}) means
# "All Users" -- a legitimate, reusable audience. This is never confused
# with a missing/malformed `filters` key (both of those are rejected
# above, in validate_criteria(), before this allowlist is even
# consulted) -- only a genuine, present, empty JSON object reaches here
# and passes (the loop below simply has zero keys to validate).
CANONICAL_FILTER_KEYS = frozenset(_FILTER_VALIDATORS.keys())


def validate_criteria(criteria, *, authoring: bool) -> dict:
    """
    Validates a full criteria object ({"version": 1, "filters": {...}})
    and returns the validated `filters` dict, unchanged, ready to be
    passed straight into list_users(**filters)/resolve_user_ids(**filters)
    (after adding page/page_size, for list_users()).

    Raises CriteriaValidationError (never a bare/uncaught exception) for
    any structural/type/value problem -- the route layer turns this
    into {"error": exc.code, "message": str(exc)}, 400.

    `authoring=True` (create/update an audience, or the direct-criteria
    preview endpoint before an audience is ever saved) additionally
    requires every ask_now_concern value to be a CURRENTLY ACTIVE
    category (one live DB read via get_active_category_names()).
    `authoring=False` (resolving/previewing an ALREADY-SAVED audience by
    id) skips that one check -- U6.0's own frozen distinction: a
    category disabled after an audience was saved must never retroactively
    break that audience's ability to resolve against its own historical
    ask_now_intent_history rows. Every OTHER filter key is validated
    identically regardless of `authoring`, because every other canonical
    set here is static (never changes at runtime) -- only ask_now_concern
    has this special DB-backed-master property."""
    _require(isinstance(criteria, dict), "invalid_criteria", "criteria must be a JSON object.")

    version = criteria.get("version")
    _require(version == CRITERIA_VERSION, "invalid_criteria_version",
              f"criteria.version must be {CRITERIA_VERSION}; got {version!r}.")

    _require(set(criteria.keys()) <= {"version", "filters"}, "invalid_criteria",
              "criteria must contain only 'version' and 'filters'.")

    filters = criteria.get("filters")
    _require(isinstance(filters, dict), "invalid_criteria",
              "criteria.filters must be a JSON object (not an array or scalar).")

    unknown_keys = set(filters.keys()) - CANONICAL_FILTER_KEYS
    _require(not unknown_keys, "unknown_filter_key",
              f"Unknown filter key(s): {sorted(unknown_keys)}. Allowed keys: {sorted(CANONICAL_FILTER_KEYS)}.")

    for key, value in filters.items():
        _FILTER_VALIDATORS[key](value)

    if authoring and "ask_now_concern" in filters:
        try:
            active_categories = set(get_active_category_names())
        except Exception as exc:
            raise CriteriaValidationError(
                "asknow_concern_unavailable",
                "Could not verify Ask Now concern categories right now.",
            ) from exc
        requested = set(filters["ask_now_concern"])
        invalid = requested - active_categories
        _require(not invalid, "invalid_ask_now_concern",
                  f"ask_now_concern values must be a subset of the currently active categories: "
                  f"{sorted(active_categories)}. Invalid/inactive: {sorted(invalid)}.")

    if "language" in filters:
        filters = {**filters, "language": sorted(set(filters["language"]))}
    return filters


def validate_fixed_member_ids(value) -> list:
    """Saved Audience V2 -- structural validation for a FIXED audience's
    member_user_ids input, at authoring time (create_audience()). Pure
    structure/type checks only, same division of labor as every other
    validator in this module -- the actual users.id EXISTENCE check
    (fail closed on any nonexistent id) is a live DB read, done by the
    caller (modules/services/saved_audience_service.py::create_audience()),
    matching where every other live/DB-backed check in this codebase's
    Saved Audience validation already lives.

    Returns a sorted, deduplicated list of positive ints -- the database
    itself also enforces no-duplicate-members (saved_audience_members'
    own UNIQUE constraint), but deduping here means a caller sending the
    same id twice is never even attempted twice, and the returned order
    is always deterministic."""
    _require(isinstance(value, list) and len(value) > 0, "invalid_member_ids",
              "member_user_ids must be a non-empty JSON array.")
    for v in value:
        _require(isinstance(v, int) and not isinstance(v, bool) and v > 0, "invalid_member_ids",
                  "member_user_ids values must be positive integers.")
    return sorted(set(value))
