from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from modules.auth.models import User
from modules.subscription.utils import subscription_required
from firebase_admin import auth as firebase_auth
from modules.user_service import get_or_create_app_user



profile_bp = Blueprint("profile_bp", __name__)


@profile_bp.get("/api/profile")
@jwt_required()
def get_profile():
    uid = get_jwt_identity()
    user = User.query.get(uid)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": user.to_public()}), 200


@profile_bp.put("/api/profile")
@jwt_required()
def update_profile():
    uid = get_jwt_identity()
    user = User.query.get(uid)

    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    user.name = data.get("name") or user.name
    user.dob = data.get("dob") or user.dob
    user.tob = data.get("tob") or user.tob
    user.pob = data.get("pob") or user.pob
    user.phone = data.get("phone") or user.phone

    db.session.commit()
    return jsonify({"message": "Profile updated", "user": user.to_public()}), 200

@profile_bp.route('/premium-content', methods=["POST"])
@jwt_required()
@subscription_required  # ✅ This is your custom decorator
def premium_content():
    return jsonify({"message": "You have access to premium content!"})


@profile_bp.route("/api/profile/subscription-info", methods=["GET"])
@jwt_required()
def subscription_info():
    # Subscription Migration Phase 3 -- this consumer is confirmed
    # READY per the approved Migration Plan (read-only, no external
    # dependency, no other code depends on this route's side effects
    # since it never had any). Reads now come from the Entitlement
    # Engine (System C) via its existing read API -- reusing the same
    # identity resolution Phase 1's dual-write adapter already uses --
    # rather than the legacy Subscription table. No new business logic:
    # this is purely reshaping an already-computed EntitlementSnapshot
    # into the same response shape this endpoint already returned.
    from modules.entitlement import EntitlementService
    from modules.subscription.dual_write_adapter import (
        resolve_profile_id_from_account_user_id,
    )

    user_id = get_jwt_identity()
    profile_id = resolve_profile_id_from_account_user_id(user_id)

    if profile_id is None:
        return jsonify({
            "plan": "free",
            "status": "inactive",
            "is_active": False,
            "message": "No active subscription",
            "is_trial": False,
            "auto_renew": None,
            "in_grace_period": False,
            "selected_segment": None,
            "accessible_segments": [],
            # membership_state/remaining_days (S-Trial.1) -- no profile
            # exists at all here, so there is no EntitlementSnapshot to
            # derive these from; NONE/None is this branch's own literal
            # equivalent of what EntitlementSnapshot.membership_state
            # would return for "nothing ever provisioned".
            "membership_state": "NONE",
            "remaining_days": None,
            # trial_available (Manual Trial Activation) -- no profile
            # exists at all here (not even resolvable), so there is
            # nothing to activate a trial FOR yet. False, not True --
            # this is a distinct case from "profile exists, never
            # trialed" (which IS True below).
            "trial_available": False,
        }), 200

    snapshot = EntitlementService().get_current_entitlement(profile_id)

    if snapshot.status == "PENDING":
        return jsonify({
            "plan": "free",
            "status": "inactive",
            "is_active": False,
            "message": "No active subscription",
            "is_trial": False,
            "auto_renew": None,
            "in_grace_period": False,
            "selected_segment": snapshot.selected_segment,
            "accessible_segments": [],
            # membership_state/remaining_days (S-Trial.1) -- reused from
            # the snapshot already fetched above, not recalculated.
            "membership_state": snapshot.membership_state,
            "remaining_days": snapshot.remaining_trial_days,
            # trial_available (Manual Trial Activation) -- reused from
            # the same snapshot, not recalculated.
            "trial_available": snapshot.trial_available,
        }), 200

    is_trial = False
    auto_renew = None
    if snapshot.trial.is_active:
        plan, is_active = "free", True
        start_at, end_at = snapshot.trial.started_at, snapshot.trial.expires_at
        is_trial = True
    elif snapshot.subscription.is_active:
        plan, is_active = snapshot.plan, True
        start_at, end_at = snapshot.subscription.started_at, snapshot.subscription.expires_at
        auto_renew = snapshot.subscription.auto_renew
    else:
        plan = snapshot.plan or "free"
        is_active = False
        start_at = snapshot.trial.started_at or snapshot.subscription.started_at
        end_at = snapshot.trial.expires_at or snapshot.subscription.expires_at

    return jsonify({
        "plan": plan,
        "status": "active" if is_active else "inactive",
        "is_active": is_active,
        "start_at": start_at.isoformat() if start_at else None,
        "end_at": end_at.isoformat() if end_at else None,
        # Additive fields (S5.X) -- EntitlementSnapshot already computes
        # these; this route previously just didn't serialize them. No
        # existing field above changed shape or meaning.
        "is_trial": is_trial,
        "auto_renew": auto_renew,
        "in_grace_period": snapshot.status == "GRACE",
        "selected_segment": snapshot.selected_segment,
        "accessible_segments": snapshot.accessible_segments,
        # membership_state/remaining_days (S-Trial.1) -- first-class
        # trial state so a client never needs to infer "on trial" vs
        # "no subscription" from `plan` (which is "free" for both).
        # Both are properties on the same `snapshot` already fetched
        # above -- reused, not recalculated.
        "membership_state": snapshot.membership_state,
        "remaining_days": snapshot.remaining_trial_days,
        # trial_available (Manual Trial Activation) -- lets Flutter show
        # the FREE badge / activation card without inferring eligibility
        # from membership_state=="NONE" alone (see EntitlementSnapshot.
        # trial_available's own docstring for why that would disagree
        # with start_trial() in edge cases).
        "trial_available": snapshot.trial_available,
    })


@profile_bp.route("/api/profile/activate-trial", methods=["POST"])
@jwt_required()
def activate_trial():
    """
    Manual Trial Activation -- the ONLY place a 7-day free trial is
    ever started, now that automatic provisioning has been removed
    from AppUser creation (bootstrap / update-fcm / register-or-update
    no longer call provision_trial_for_new_profile()). This is a thin
    controller in front of the SAME, unmodified trial engine those
    call sites already used -- SubscriptionService.start_trial() ->
    EntitlementWriteService.start_trial() -> CurrentEntitlement -- no
    new business rule is introduced here.

    Identity: resolves the authenticated profile the exact same way
    /api/profile/subscription-info already does (JWT identity ->
    resolve_profile_id_from_account_user_id()) -- never trusts a
    client-supplied profile_id, matching this route file's existing
    convention.

    Server-authoritative + one-time, by construction, not by any new
    logic here: EntitlementWriteService.start_trial() already refuses
    (TRIAL_SKIPPED, success=True, no write) whenever trial_started_at
    was ever set before OR the profile is currently ACTIVE/GRACE -- the
    exact same check CurrentEntitlement.profile_id's DB-level UNIQUE
    constraint backs for any genuine concurrent double-tap. This route
    only calls that method once and reshapes its result; it never
    re-implements eligibility.

    Response is always built from a FRESH EntitlementService read taken
    AFTER the write attempt, never from the write result's own
    (possibly stale-relative-to-live-timestamp) fields -- so
    membership_state/remaining_days/trial_available in the response are
    always the true, current, live-computed state, exactly like
    /api/profile/subscription-info's own contract.
    """
    from modules.entitlement import EntitlementService
    from modules.subscription.dual_write_adapter import (
        resolve_profile_id_from_account_user_id,
    )
    from modules.subscription.subscription_service import SubscriptionService

    user_id = get_jwt_identity()
    profile_id = resolve_profile_id_from_account_user_id(user_id)

    if profile_id is None:
        return jsonify({
            "success": False,
            "activated": False,
            "reason": "no_profile",
            "message": "No profile could be resolved for this account.",
        }), 404

    entitlement_service = EntitlementService()
    before = entitlement_service.get_current_entitlement(profile_id)

    # Short-circuit an already-active trial as a pure read -- never
    # calls start_trial() again for a case that's already exactly the
    # target state. (Calling it anyway would also be safe/no-op per
    # its own eligibility check; this just avoids an unnecessary write
    # attempt for the single most common repeat-tap case.)
    if before.trial.is_active:
        return jsonify({
            "success": True,
            "activated": False,
            "reason": "already_active",
            "message": "Trial is already active.",
            "membership_state": before.membership_state,
            "remaining_days": before.remaining_trial_days,
            "accessible_segments": before.accessible_segments,
            "trial_available": before.trial_available,
        }), 200

    if before.subscription.is_active:
        return jsonify({
            "success": False,
            "activated": False,
            "reason": "already_subscribed",
            "message": "This profile already has an active paid subscription.",
            "membership_state": before.membership_state,
            "remaining_days": before.remaining_trial_days,
            "accessible_segments": before.accessible_segments,
            "trial_available": before.trial_available,
        }), 400

    if not before.trial_available:
        # Never had an active trial or paid subscription right now, but
        # trial_started_at was set at some point in the past -- a
        # previously-claimed, now-expired trial. No second trial, ever.
        return jsonify({
            "success": False,
            "activated": False,
            "reason": "trial_already_used",
            "message": "This profile has already used its free trial.",
            "membership_state": before.membership_state,
            "remaining_days": before.remaining_trial_days,
            "accessible_segments": before.accessible_segments,
            "trial_available": before.trial_available,
        }), 400

    result = SubscriptionService().start_trial(profile_id)

    after = entitlement_service.get_current_entitlement(profile_id)
    activated = result.action == "TRIAL_STARTED"

    return jsonify({
        "success": True,
        "activated": activated,
        "reason": None if activated else "already_active",
        "message": result.message,
        "membership_state": after.membership_state,
        "remaining_days": after.remaining_trial_days,
        "accessible_segments": after.accessible_segments,
        "trial_available": after.trial_available,
    }), 200


@profile_bp.route('/personalized-horoscope', methods=["POST"])
@jwt_required()
@subscription_required
def personalized_horoscope():
    uid = get_jwt_identity()
    user = User.query.get(uid)

    if not user:
        return jsonify({"error": "User not found"}), 404

    # 🔮 Placeholder response — replace with actual GPT/OpenAI result later
    horoscope = {
        "message": f"Dear {user.name}, based on your birth details, this is your personalized horoscope for today. 🌟",
        "lucky_color": "Blue",
        "lucky_number": 7,
        "tip": "Stay focused on your goals. Avoid unnecessary distractions."
    }

    return jsonify(horoscope), 200


# ---------------------------------------------------------
# 🔔 UPDATE FCM TOKEN (Firebase ID Token based auth)
# ---------------------------------------------------------
@profile_bp.route("/api/users/update-fcm", methods=["POST"])
def update_fcm_token():
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    id_token = auth_header.replace("Bearer ", "").strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
        firebase_uid = decoded.get("uid")

        if not firebase_uid:
            return jsonify({"error": "Invalid Firebase token"}), 401

        data = request.get_json() or {}
        fcm_token = data.get("fcm_token")

        if not fcm_token:
            return jsonify({"error": "Missing fcm_token"}), 400

        # 🔥 EXISTING SYSTEM (SAFE)
        user = User.query.filter_by(firebase_uid=firebase_uid).first()
        if user:
            user.fcm_token = fcm_token

        # 🔥 NEW SYSTEM (ALWAYS ENSURE) -- routed through the shared
        # identity-resolution service (modules/user_service.py) instead
        # of constructing AppUser() inline, so this endpoint can never
        # produce a second, disconnected AppUser row.
        #
        # Manual Trial Activation: this endpoint used to also start the
        # free trial automatically the first time it created a brand-new
        # AppUser row (`created=True`). That auto-provisioning is REMOVED
        # by product decision -- the trial must now only ever start via
        # the user's own explicit POST /api/profile/activate-trial call.
        # A new profile created here is intentionally left with no
        # CurrentEntitlement row at all (status effectively "PENDING",
        # trial_available=True) until the user activates it themselves.
        app_user, created = get_or_create_app_user(firebase_uid)

        app_user.fcm_token = fcm_token

        # 🔥 SINGLE COMMIT (IMPORTANT)
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "FCM token updated",
            "user_id": user.id if user else None
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500