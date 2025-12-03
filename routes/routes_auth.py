# routes/routes_auth.py

from flask import Blueprint, request, jsonify
from extensions import db
from modules.models_user import User   # ⭐ CORRECT IMPORT (your actual file)

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
