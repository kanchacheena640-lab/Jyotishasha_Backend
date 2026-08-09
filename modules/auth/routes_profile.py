from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from modules.auth.models import User
from modules.subscription.utils import subscription_required
from firebase_admin import auth as firebase_auth
from modules.user_service import get_or_create_app_user, provision_trial_for_new_profile



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
    })

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
        # produce a second, disconnected AppUser row, and so a profile
        # first created here also gets its initial trial provisioned.
        app_user, created = get_or_create_app_user(firebase_uid)

        app_user.fcm_token = fcm_token

        # 🔥 SINGLE COMMIT (IMPORTANT)
        db.session.commit()

        if created:
            provision_trial_for_new_profile(app_user.id)

        return jsonify({
            "status": "success",
            "message": "FCM token updated",
            "user_id": user.id if user else None
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500