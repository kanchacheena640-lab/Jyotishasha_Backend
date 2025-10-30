"""
routes/routes_asknow.py
-----------------------
Endpoints for ₹99 AskNow Token Pack.
"""

from flask import Blueprint, request, jsonify
from modules.services.asknow_service import (
    create_asknow_order,
    verify_asknow_payment,
    deduct_token,
)
from modules.user_service import get_user_by_id

routes_asknow = Blueprint("routes_asknow", __name__)


# ✅ 1. Create ₹99 Razorpay order
@routes_asknow.route("/asknow/order", methods=["POST"])
def asknow_create_order():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        order = create_asknow_order(user_id)
        return jsonify({"success": True, "order": order}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ✅ 2. Verify payment & add 10 tokens
@routes_asknow.route("/asknow/verify", methods=["POST"])
def asknow_verify_payment():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        order_id = data.get("order_id")
        payment_id = data.get("payment_id")

        if not all([user_id, order_id, payment_id]):
            return jsonify({"error": "Missing required fields"}), 400

        result = verify_asknow_payment(order_id, payment_id, user_id)
        return jsonify({"success": True, "result": result}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ✅ 3. Deduct one token (for ad-free question use)
@routes_asknow.route("/asknow/use-token", methods=["POST"])
def asknow_use_token():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        result = deduct_token(user_id)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ✅ 4. Check remaining tokens (optional)
@routes_asknow.route("/asknow/tokens/<int:user_id>", methods=["GET"])
def asknow_check_tokens(user_id):
    user = get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"success": True, "asknow_tokens": user.asknow_tokens})
