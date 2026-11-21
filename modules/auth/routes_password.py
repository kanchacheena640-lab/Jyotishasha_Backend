from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)
from extensions import db
from modules.auth.models import User


password_bp = Blueprint("password_auth", __name__)


# PR #8: POST /api/auth/signup removed. It created accounts for any email
# without proving the caller owned it (email squatting / pre-registration
# account takeover). No backend, website or Flutter build ever called it.
# /api/auth/login and /api/auth/refresh stay for any pre-existing password
# accounts (production count unverified); routes/routes_auth.py quarantines
# such an account when the email's Firebase-verified owner signs in.


@password_bp.post("/api/auth/login")
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email, provider="password").first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    return jsonify({
        "access_token": create_access_token(identity=str(user.id)),
        "refresh_token": create_refresh_token(identity=str(user.id)),
        "user": user.to_public()
    }), 200


@password_bp.post("/api/auth/refresh")
@jwt_required(refresh=True)
def refresh_token():
    user_id = get_jwt_identity()
    access_token = create_access_token(identity=user_id)
    return jsonify({"access_token": access_token}), 200
