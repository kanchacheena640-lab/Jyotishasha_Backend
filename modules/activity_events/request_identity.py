# modules/activity_events/request_identity.py

"""
Read-only identity resolution for POST /api/activity-events (Phase 3).

JWT -> users.id -> User.firebase_uid -> read-only AppUser lookup.
Mirrors the pattern already proven in production by
notifications/user_notification_routes.py::get_app_user_id() (JWT ->
User -> AppUser by firebase_uid) -- reimplemented here as its own small,
activity-events-scoped function rather than importing that
notification-specific module, to keep this file's only dependency on
User/AppUser, nothing notification-related.

This module NEVER writes. It calls only .query.filter_by(...)/.get() --
never AppUser(...)/db.session.add(...), and never
modules.user_service.get_or_create_app_user() (that function's create
side effect must never run from an analytics path). Client-supplied
firebase_uid/profile_id are never read by this module at all -- the
request body is not even passed in; identity comes exclusively from the
verified JWT.

Locked correction (Phase 3 Step 3): a firebase_uid resolving to more
than one AppUser row is NOT resolved with .first() or any other
deterministic pick -- see resolve_identity()'s IDENTITY_INTEGRITY_
ANOMALY branch. That would silently paper over a real data-integrity
problem; here it fails the whole request closed instead.
"""

import logging

from flask_jwt_extended import get_jwt_identity

from modules.auth.models import User
from modules.models_user import AppUser

logger = logging.getLogger("activity_events")

AUTH_FAILED = "auth_failed"
IDENTITY_INTEGRITY_ANOMALY = "identity_integrity_anomaly"
OK = "ok"


class IdentityResolution:
    """status is one of OK / AUTH_FAILED / IDENTITY_INTEGRITY_ANOMALY.
    firebase_uid/profile_id are only meaningful when status == OK (both
    may still individually be None even then -- see module docstring's
    truth table). user_id (users.id, the JWT-verified account) is set
    whenever status != AUTH_FAILED -- it is the one identity fact that
    is always trustworthy and non-null once authentication itself has
    succeeded, independent of whether firebase_uid/profile_id further
    resolve. ingestion_service uses it (never firebase_uid/profile_id,
    which can be None) to namespace idempotency-key derivation."""

    __slots__ = ("status", "user_id", "firebase_uid", "profile_id")

    def __init__(self, status, user_id=None, firebase_uid=None, profile_id=None):
        self.status = status
        self.user_id = user_id
        self.firebase_uid = firebase_uid
        self.profile_id = profile_id

    @property
    def ok(self) -> bool:
        return self.status == OK


def resolve_identity() -> IdentityResolution:
    """Call only after @jwt_required() has already verified the request
    (this function does not itself enforce authentication -- the route
    decorator does). Reads get_jwt_identity() fresh every call; never
    caches across requests."""

    raw_identity = get_jwt_identity()
    try:
        user_id = int(raw_identity)
    except (TypeError, ValueError):
        # Malformed JWT identity -- not the shape every other route in
        # this codebase produces (str(int)). Fail closed, not a 500.
        return IdentityResolution(status=AUTH_FAILED)

    user = User.query.get(user_id)
    if not user:
        # Valid, well-formed JWT, but the account it names no longer
        # exists (or never did) -- nothing to record an event under.
        return IdentityResolution(status=AUTH_FAILED)

    firebase_uid = user.firebase_uid
    if not firebase_uid:
        # Real, existing case: User.provider == "password" accounts can
        # have no firebase_uid at all. Authenticated via users.id is
        # still sufficient for v1 -- record with both identity fields
        # null rather than treating this as a failure.
        return IdentityResolution(status=OK, user_id=user_id, firebase_uid=None, profile_id=None)

    # Read-only multiplicity-aware lookup -- NOT .first(). See module
    # docstring's locked correction.
    matches = AppUser.query.filter_by(firebase_uid=firebase_uid).all()

    if len(matches) == 0:
        return IdentityResolution(status=OK, user_id=user_id, firebase_uid=firebase_uid, profile_id=None)

    if len(matches) == 1:
        return IdentityResolution(status=OK, user_id=user_id, firebase_uid=firebase_uid, profile_id=matches[0].id)

    # >1 AppUser rows sharing one firebase_uid -- a real data-integrity
    # anomaly (should be prevented going forward by the partial unique
    # index added in Phase 2 Step 2A, but pre-existing duplicates are
    # not ruled out). Fail closed: no activity_events row, no arbitrary
    # pick. firebase_uid is not email/phone/name/token (Rule 11's
    # ALLOWED list) -- safe to log for investigation; the matched
    # AppUser ids are logged too, nothing about the request body is.
    logger.error(
        "activity_events: identity integrity anomaly -- firebase_uid=%r "
        "resolves to %d AppUser rows (ids=%r); failing this ingestion "
        "request closed rather than picking one",
        firebase_uid, len(matches), [m.id for m in matches],
    )
    return IdentityResolution(status=IDENTITY_INTEGRITY_ANOMALY, user_id=user_id, firebase_uid=firebase_uid)
