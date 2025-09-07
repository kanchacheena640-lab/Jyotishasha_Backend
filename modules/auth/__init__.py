from flask import Blueprint, jsonify
from .routes_password import password_bp
from .routes_profile import profile_bp


def register_auth(app):
    bp = Blueprint("auth_module", __name__)
    bp.register_blueprint(password_bp) 
    bp.register_blueprint(profile_bp)

    @bp.get("/api/auth/health")
    def auth_health():
        return jsonify({"ok": True, "module": "auth", "status": "wired"}), 200

    app.register_blueprint(bp)

