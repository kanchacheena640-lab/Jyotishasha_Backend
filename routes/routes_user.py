"""
routes/routes_user.py
----------------------
User routes for Jyotishasha App.

Handles register/update and fetch operations for AppUser.
All personalized features (Horoscope, AskNow etc.) will
use user_id context from this table.

Endpoints:
POST /users/register-or-update
GET  /users/<id>
"""

from flask import Blueprint, request, jsonify
from modules.user_service import register_or_update_user, get_user_by_id

routes_user = Blueprint("routes_user", __name__)

# ---------- Register or Update ----------
@routes_user.post("/users/register-or-update")
def register_or_update():
    try:
        data = request.get_json() or {}
        user = register_or_update_user(data)
        return jsonify({
            "success": True,
            "user": user.to_dict()
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        print("Error in register_or_update:", e)
        return jsonify({"error": "Internal Server Error"}), 500


# ---------- Get User by ID ----------
@routes_user.get("/users/<int:user_id>")
def get_user(user_id):
    try:
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify({
            "success": True,
            "user": user.to_dict()
        }), 200
    except Exception as e:
        print("Error in get_user:", e)
        return jsonify({"error": "Internal Server Error"}), 500
