from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from modules.auth.models import User
from modules.subscription.utils import subscription_required



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
    user_id = get_jwt_identity()
    from modules.subscription.models import Subscription  # ✅ safe import here

    subscription = Subscription.query.filter_by(user_id=user_id).first()

    if not subscription:
        return jsonify({
            "plan": "free",
            "status": "inactive",
            "is_active": False,
            "message": "No active subscription"
        }), 200

    return jsonify({
        "plan": subscription.plan,
        "status": subscription.status,
        "is_active": subscription.is_active(),  # ✅ call the method
        "start_at": subscription.start_at.isoformat() if subscription.start_at else None,
        "end_at": subscription.end_at.isoformat() if subscription.end_at else None
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