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
from flask_jwt_extended import jwt_required, get_jwt_identity
from modules.user_service import register_or_update_user, get_user_by_id
from modules.subscription.dual_write_adapter import resolve_profile_id_from_account_user_id
from firebase_admin import auth as firebase_auth

routes_user = Blueprint("routes_user", __name__)

# ---------- Register or Update ----------
@routes_user.post("/users/register-or-update")
def register_or_update():
    # Bucket A -- Critical Fix #4. This endpoint previously trusted
    # firebase_uid directly from the request body, with no proof the
    # caller actually owns that Firebase identity -- independently
    # verified as exploitable (a forged UID could overwrite or
    # register/update another user's profile). Fixed by reusing the
    # exact same Firebase verification pattern already used by
    # update_fcm_token(), get_backend_token(), register_user(), and
    # bootstrap_user_profile() -- Authorization: Bearer
    # <firebase_id_token> + firebase_auth.verify_id_token(). No new
    # authentication mechanism was introduced, and
    # register_or_update_user() (modules/user_service.py) is
    # untouched: any firebase_uid the client sends in the body is
    # overridden here, before the service is ever called, with the
    # verified UID -- the service always resolves the AppUser using
    # only that verified value.
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

    try:
        data = request.get_json() or {}
        data["firebase_uid"] = firebase_uid
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
@jwt_required()
def get_user(user_id):
    # Bucket A -- Critical Fix #5. This endpoint previously required no
    # authentication at all, letting an unauthenticated caller read any
    # user's PII by iterating sequential integer IDs -- independently
    # verified. Fixed by reusing the exact same JWT + profile-resolution
    # pattern already used elsewhere in this repository (e.g.
    # modules/auth/routes_profile.py::subscription_info(),
    # routes/routes_google_purchase_confirm.py,
    # routes/routes_premium_report.py) --
    # resolve_profile_id_from_account_user_id() (modules/subscription/
    # dual_write_adapter.py), not a new authentication mechanism. The
    # caller may only ever read their own AppUser; any other user_id,
    # or an account with no resolvable profile, is rejected with 403.
    account_user_id = get_jwt_identity()
    authenticated_profile_id = resolve_profile_id_from_account_user_id(account_user_id)

    if authenticated_profile_id is None or authenticated_profile_id != user_id:
        return jsonify({"error": "Forbidden"}), 403

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
