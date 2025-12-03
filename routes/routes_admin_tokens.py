# routes/routes_admin_tokens.py

from flask import Blueprint, request, jsonify
from extensions import db
from modules.models_user import AppUser   

routes_admin_tokens = Blueprint("routes_admin_tokens", __name__)

@routes_admin_tokens.route("/admin/add-tokens", methods=["POST"])
def admin_add_tokens():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    tokens = data.get("tokens")

    if not user_id or not tokens:
        return jsonify({"success": False, "error": "Missing user_id or tokens"}), 400

    user = AppUser.query.get(user_id)
    if not user:
        return jsonify({"success": False, "error": "User not found"}), 404

    user.asknow_tokens += int(tokens)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": f"Added {tokens} tokens to user {user_id}",
        "new_total": user.asknow_tokens,
    }), 200
