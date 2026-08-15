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
"""

from extensions import db
from modules.models_user import AppUser


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


# ---------- Automatic initial-trial provisioning ----------
def provision_trial_for_new_profile(profile_id: int) -> None:
    """
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

    user.dob = data.get("dob", user.dob)
    user.tob = data.get("tob", user.tob)
    user.pob = data.get("pob", user.pob)
    user.lat = data.get("lat", user.lat)
    user.lng = data.get("lng", user.lng)
    user.tz = data.get("tz", user.tz or "+05:30")

    # N3 -- same content-language preference routes/routes_profile_bootstrap.py
    # persists, accepted here too for symmetry (this is the other AppUser
    # write path). Only "en"/"hi" recognized; anything else/missing leaves
    # the existing value untouched rather than guessing.
    incoming_lang = str(data.get("lang", "")).strip().lower()
    if incoming_lang in ("en", "hi"):
        user.lang = incoming_lang
    # Security fix: subscription state must be server-controlled only --
    # never read from client-supplied request data (that previously let
    # any caller set their own subscription tier with no payment
    # involved). Only ever preserves the existing value, defaulting to
    # "free" for a brand-new profile.
    user.subscription = user.subscription or "free"

    # 🔥 6. FCM token
    if data.get("fcm_token"):
        user.fcm_token = data["fcm_token"]

    db.session.commit()

    if created:
        provision_trial_for_new_profile(user.id)

    return user

# ---------- Fetch by ID ----------
def get_user_by_id(user_id: int) -> AppUser | None:
    """Fetch a user by id"""
    return AppUser.query.get(user_id)
