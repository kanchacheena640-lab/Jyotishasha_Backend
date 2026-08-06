# routes/routes_auth.py

from flask import Blueprint, request, jsonify
from extensions import db
from modules.auth.models import User
from flask_jwt_extended import create_access_token
from firebase_admin import auth as firebase_auth


routes_auth = Blueprint("routes_auth", __name__)


# ----------------------------------------------------------
# REGISTER / LINK FIREBASE USER → BACKEND USER
# ----------------------------------------------------------
@routes_auth.route("/api/auth/register", methods=["POST"])
def register_user():
    # Bucket A -- Critical Fix #2. This endpoint previously trusted
    # firebase_uid directly from the request body, with no proof the
    # caller actually owns that Firebase identity -- independently
    # verified as exploitable (a forged UID could pre-create/claim a
    # User record for an identity the caller doesn't own). Fixed by
    # reusing the exact same Firebase verification pattern already
    # used by modules/auth/routes_profile.py::update_fcm_token() and
    # this file's own, just-fixed get_backend_token() -- Authorization:
    # Bearer <firebase_id_token> + firebase_auth.verify_id_token(). No
    # new authentication mechanism was introduced. Any firebase_uid the
    # client sends in the request body is now ignored entirely; the
    # UID used below always comes from the verified token.
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    id_token = auth_header.replace("Bearer ", "").strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception:
        return jsonify({"error": "Invalid or expired Firebase token"}), 401

    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        return jsonify({"error": "Invalid Firebase token"}), 401

    data = request.get_json() or {}

    phone = data.get("phone")
    email = data.get("email")
    name = data.get("name")

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
    # Bucket A -- Critical Fix #1. This endpoint previously trusted
    # firebase_uid directly from the request body, with no proof the
    # caller actually owns that Firebase identity -- independently
    # verified as exploitable (a forged UID minted a valid backend JWT
    # for any account). Fixed by reusing this repository's existing,
    # already-proven Firebase verification pattern -- Authorization:
    # Bearer <firebase_id_token> + firebase_auth.verify_id_token() --
    # the same mechanism already used by
    # modules/auth/routes_profile.py::update_fcm_token(). No new
    # authentication mechanism was introduced. Any firebase_uid the
    # client sends in the request body is now ignored entirely; the
    # UID used below always comes from the verified token.
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    id_token = auth_header.replace("Bearer ", "").strip()

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception:
        return jsonify({"error": "Invalid or expired Firebase token"}), 401

    firebase_uid = decoded.get("uid")
    if not firebase_uid:
        return jsonify({"error": "Invalid Firebase token"}), 401

    user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if not user:
        return jsonify({"error": "user not found"}), 404

    # 🔥 MAIN FIX -- unchanged: JWT generation, identity, and response
    # schema are exactly as before.
    token = create_access_token(identity=str(user.id))

    return jsonify({
        "token": token,
        "user_id": user.id
    })