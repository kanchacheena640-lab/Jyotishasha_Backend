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


@password_bp.post("/api/auth/signup")
def signup():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already exists"}), 409

    user = User(email=email, phone=phone, provider="password")
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    return jsonify({
        "access_token": create_access_token(identity=str(user.id)),
        "refresh_token": create_refresh_token(identity=str(user.id)),
        "user": user.to_public()
    }), 201


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
