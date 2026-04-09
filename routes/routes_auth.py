# routes/routes_auth.py

from flask import Blueprint, request, jsonify
from extensions import db
from modules.auth.models import User
from flask_jwt_extended import create_access_token


routes_auth = Blueprint("routes_auth", __name__)


# ----------------------------------------------------------
# REGISTER / LINK FIREBASE USER → BACKEND USER
# ----------------------------------------------------------
@routes_auth.route("/api/auth/register", methods=["POST"])
def register_user():
    data = request.get_json() or {}

    firebase_uid = data.get("firebase_uid")
    phone = data.get("phone")
    email = data.get("email")
    name = data.get("name")

    if not firebase_uid:
        return jsonify({"success": False, "error": "firebase_uid missing"}), 400

    # -----------------------------------------
    # CHECK IF USER ALREADY EXISTS
    # -----------------------------------------
    user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if user:
        return jsonify({
            "success": True,
            "user_id": user.id,   # existing backend_user_id
            "new": False
        }), 200

    # -----------------------------------------
    # CREATE NEW USER
    # -----------------------------------------
    new_user = User(
        firebase_uid=firebase_uid,
        phone=phone,
        email=email,
        name=name,
        provider="firebase"
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "success": True,
        "user_id": new_user.id,   # new backend_user_id
        "new": True
    }), 200


# ----------------------------------------------------------
# ISSUE BACKEND JWT (IMPORTANT)
# ----------------------------------------------------------
@routes_auth.route("/api/auth/token", methods=["POST"])
def get_backend_token():
    data = request.get_json() or {}

    firebase_uid = data.get("firebase_uid")

    if not firebase_uid:
        return jsonify({"error": "firebase_uid required"}), 400

    user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if not user:
        return jsonify({"error": "user not found"}), 404

    # 🔥 MAIN FIX
    token = create_access_token(identity=user.id)

    return jsonify({
        "token": token,
        "user_id": user.id
    })