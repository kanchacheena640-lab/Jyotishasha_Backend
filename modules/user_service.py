"""
modules/user_service.py
------------------------
Service layer for AppUser model.

Handles creation, update, and retrieval of app-specific user records.
This isolates ORM logic from route logic, keeping the API clean.

This module is the single source of truth for AppUser resolution --
every code path that needs to find-or-create an AppUser for a given
firebase_uid should go through get_or_create_app_user() (directly, or
indirectly via register_or_update_user()) rather than constructing
AppUser() itself, so a person can never end up with two disconnected
AppUser rows.

Functions:
- get_or_create_app_user(firebase_uid)
- provision_trial_for_new_profile(profile_id)
- register_or_update_user(data)
- get_user_by_id(user_id)

U3B.1 -- register_or_update_user() previously could change
dob/tob/pob/lat/lng without ever recalculating/invalidating the
already-stored lagna/moon_sign/nakshatra (the U3B architecture audit's
own confirmed "staleness gap": this was the ONLY birth-detail write
path that didn't do this, unlike routes/routes_profile_bootstrap.py).
Fixed here by change-detecting the 5 astrology-affecting fields and,
on an ACTUAL change, either recalculating once (if the resulting data
is complete) or fully invalidating (if it isn't) -- see
_ASTROLOGY_AFFECTING_FIELDS / _has_complete_birth_details /
_recalculate_or_invalidate_static_astrology below.
"""

from extensions import db
from modules.models_user import AppUser

# U3B.1 -- the exact fields whose value change can make previously
# stored static astrology stale. Reused, not duplicated, across the
# change-detection and completeness checks below.
_ASTROLOGY_AFFECTING_FIELDS = ("dob", "tob", "pob", "lat", "lng")


def _has_complete_birth_details(user: AppUser) -> bool:
    """Same completeness contract modules/auth/routes_profile.py's own
    /api/profile/completeness already uses (dob/tob/pob/lat/lng all
    non-None/non-empty) -- not a new definition invented here."""
    return all(
        getattr(user, field, None) not in (None, "")
        for field in _ASTROLOGY_AFFECTING_FIELDS
    )


def _recalculate_or_invalidate_static_astrology(user: AppUser) -> None:
    """Called ONLY when an actual change to one of the 5 astrology-
    affecting fields was just detected on `user` (already assigned,
    not yet committed). Exactly ONE calculate_full_kundali() call when
    the resulting birth data is complete; a full invalidation
    (build_not_calculated_snapshot()) otherwise or if the calculation
    itself fails -- never a partial/half-calculated snapshot, and
    never old astrology left attached to the new birth details."""
    from full_kundali_api import calculate_full_kundali
    from modules.services.static_astrology_extractor import (
        build_static_astrology_snapshot,
        build_not_calculated_snapshot,
        apply_snapshot_to_app_user,
    )

    if not _has_complete_birth_details(user):
        apply_snapshot_to_app_user(user, build_not_calculated_snapshot())
        return

    try:
        kundali = calculate_full_kundali(
            name=user.name,
            dob=user.dob,
            tob=user.tob,
            lat=user.lat,
            lon=user.lng,
            user_id=None,
            language=(user.lang or "en"),
        )
        snapshot = build_static_astrology_snapshot(kundali)
    except Exception as exc:
        # Calculation failed against structurally-present-but-malformed
        # birth data (e.g. an unparseable dob string) -- never commit a
        # half-calculated snapshot, and never silently leave the OLD
        # astrology attached to these NEW (broken) birth details. The
        # rest of this profile update (name/email/phone/fcm sync) must
        # still succeed -- this failure is scoped to astrology only.
        print(f"⚠️ Static astrology recalculation failed for firebase_uid="
              f"{user.firebase_uid!r}: {exc}")
        apply_snapshot_to_app_user(user, build_not_calculated_snapshot())
        return

    apply_snapshot_to_app_user(user, snapshot)


def _resync_dasha_timeline(user: AppUser) -> None:
    """U4A.1 -- called at the SAME trigger point as
    _recalculate_or_invalidate_static_astrology() above (an actual
    change to one of the 5 astrology-affecting fields), immediately
    after it. Delegates entirely to
    modules/services/dasha_timeline_service.py::
    sync_dasha_timeline_for_user() -- that service owns its own
    completeness gate (reusing this same module's
    _has_complete_birth_details, not a second definition) and its own
    delete-then-regenerate-or-invalidate contract; this function is
    just the wiring. No commit happens here -- the delete+insert this
    triggers is staged into the SAME session this function's own caller
    (register_or_update_user) commits once, at the end, alongside the
    profile fields and the static-astrology snapshot -- one atomic
    write, never two."""
    from modules.services.dasha_timeline_service import sync_dasha_timeline_for_user

    sync_dasha_timeline_for_user(user)


# ---------- Identity resolution (Single Source of Truth) ----------
def get_or_create_app_user(firebase_uid: str) -> tuple[AppUser, bool]:
    """
    Find the AppUser for this firebase_uid, creating one only if it
    doesn't already exist. Never creates a duplicate for an identity
    that already has a row. Touches no field other than firebase_uid --
    callers that need to set profile data do so on the returned row.

    Returns (user, created). `created` is True only on the call that
    actually instantiated a brand-new row (still pending/unflushed at
    that point) -- callers use this to run anything that must happen
    exactly once per new profile, such as
    provision_trial_for_new_profile(), without re-deriving "is this
    new?" themselves.
    """
    if not firebase_uid:
        raise ValueError("firebase_uid is required")

    user = AppUser.query.filter_by(firebase_uid=firebase_uid).first()
    created = False

    if not user:
        user = AppUser(firebase_uid=firebase_uid)
        db.session.add(user)
        created = True

    return user, created


# ---------- Automatic initial-trial provisioning (NO LONGER CALLED) ----------
def provision_trial_for_new_profile(profile_id: int) -> None:
    """
    NOT CALLED ANYWHERE as of Manual Trial Activation: the trial must
    now only ever start via the user's own explicit
    POST /api/profile/activate-trial (modules/auth/routes_profile.py::
    activate_trial()), which calls SubscriptionService.start_trial()
    directly so success/failure can be surfaced to the caller -- this
    function's own swallow-every-exception, return-None contract is
    exactly wrong for that use case. Kept defined, unused, rather than
    deleted: it was not identified as part of the trial engine itself
    (SubscriptionService/EntitlementWriteService/DEFAULT_TRIAL_
    DURATION_DAYS), only as one of its former best-effort callers.

    Original docstring, preserved for history:

    Best-effort side effect for brand-new profiles only: start the
    initial free trial via SubscriptionService.start_trial(). Callers
    must invoke this AFTER the AppUser row has been committed (a real,
    persisted profile_id is required as the FK target for
    CurrentEntitlement), and only when get_or_create_app_user() reported
    created=True.

    Transaction/rollback note: by the time this runs, the AppUser row
    is already durably committed in its own transaction. EntitlementWr
    iteService.start_trial() commits its own, separate transaction
    internally -- these two writes were never in a shared transaction
    to begin with, and this task does not permit modifying
    EntitlementWriteService to change that. So there is nothing to roll
    back here: a failure below cannot and does not undo the profile
    that was just created.

    Accordingly, failures are logged and swallowed, never re-raised --
    reusing this codebase's existing pattern (print + continue) rather
    than failing the whole signup/bootstrap request over a trial that
    can be granted later. Known limitation: if this one attempt fails
    (e.g. a transient DB error), the profile is left without a trial
    and nothing here automatically retries it later -- a created=True
    event fires exactly once, at creation. Backfilling missed trials
    for such profiles would need a separate reconciliation job; that is
    out of scope for this task.
    """
    from modules.subscription.subscription_service import SubscriptionService

    try:
        SubscriptionService().start_trial(profile_id)
    except Exception as exc:
        print(f"⚠️ Trial provisioning failed for profile_id={profile_id}: {exc}")


# ---------- Register or Update ----------
def register_or_update_user(data: dict) -> AppUser:
    from modules.auth.models import User

    firebase_uid = data.get("firebase_uid")

    # 🚨 1. HARD RULE: firebase_uid must exist
    if not firebase_uid:
        raise ValueError("firebase_uid is required")

    # 🔥 2-3. Resolve (find-or-create) via the single source of truth
    user, created = get_or_create_app_user(firebase_uid)

    # 🔥 4. Sync from User table (IMPORTANT)
    main_user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if main_user:
        user.name = main_user.name
        user.email = main_user.email
        user.phone = main_user.phone

    # 🔥 5. Override from incoming data (if provided)
    if data.get("name"):
        user.name = data["name"]

    if data.get("email"):
        user.email = data["email"]

    if data.get("phone"):
        user.phone = data["phone"]

    # U3B.1 -- capture the astrology-affecting fields BEFORE they are
    # overwritten below, so an ACTUAL value change (not merely "this
    # endpoint was called") can be detected. Harmless representation
    # differences are not a concern here: this codebase has never
    # normalized these fields on this write path (no type coercion
    # existed before this change either), so a plain equality compare
    # matches the repository's own existing canonical representation.
    _old_birth_details = tuple(getattr(user, f) for f in _ASTROLOGY_AFFECTING_FIELDS)

    user.dob = data.get("dob", user.dob)
    user.tob = data.get("tob", user.tob)
    user.pob = data.get("pob", user.pob)
    user.lat = data.get("lat", user.lat)
    user.lng = data.get("lng", user.lng)
    user.tz = data.get("tz", user.tz or "+05:30")

    _new_birth_details = tuple(getattr(user, f) for f in _ASTROLOGY_AFFECTING_FIELDS)
    _birth_details_changed = _old_birth_details != _new_birth_details

    # Account language is written only by the language preference API.
    # Security fix: subscription state must be server-controlled only --
    # never read from client-supplied request data (that previously let
    # any caller set their own subscription tier with no payment
    # involved). Only ever preserves the existing value, defaulting to
    # "free" for a brand-new profile.
    user.subscription = user.subscription or "free"

    # 🔥 6. FCM token
    if data.get("fcm_token"):
        user.fcm_token = data["fcm_token"]

    # U3B.1 -- ONLY on an ACTUAL change to dob/tob/pob/lat/lng: either
    # recalculate once (data now complete) or fully invalidate (data
    # now incomplete, or calculation failed). Never triggered merely
    # because this endpoint was called -- name/email/phone/fcm_token/
    # tz/lang-only updates, or birth details submitted unchanged, do
    # not touch calculate_full_kundali() or any static astrology field
    # at all.
    # U4A.1 -- Dasha timeline resync reuses the EXACT SAME
    # _birth_details_changed signal, right alongside static astrology --
    # one trigger, two independent effects, neither blocking the other.
    if _birth_details_changed:
        _recalculate_or_invalidate_static_astrology(user)
        _resync_dasha_timeline(user)

    db.session.commit()

    # Manual Trial Activation: this call site used to auto-provision the
    # initial free trial for a just-created profile (`created=True`).
    # That auto-start is REMOVED by product decision -- a brand-new
    # profile is now intentionally left with no CurrentEntitlement row
    # (trial_available=True) until the user explicitly activates it via
    # POST /api/profile/activate-trial. `created` is intentionally
    # unused for that purpose now; kept as a return-relevant local only
    # incidentally (it's still exactly what get_or_create_app_user()
    # reports, unchanged).

    return user

# ---------- Fetch by ID ----------
def get_user_by_id(user_id: int) -> AppUser | None:
    """Fetch a user by id"""
    return AppUser.query.get(user_id)
