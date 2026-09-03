from flask import Blueprint, request, jsonify
from modules.services.subscription_service import (
    create_subscription_order,
    verify_subscription_payment,
    PLAN_PRICES,
)

routes_subscription = Blueprint("routes_subscription", __name__)

# ✅ 1. Available plans
@routes_subscription.route("/subscriptions/plans", methods=["GET"])
def get_subscription_plans():
    plans = [
        {"id": k, "price": v, "currency": "INR"} for k, v in PLAN_PRICES.items()
    ]
    return jsonify({"success": True, "plans": plans})


# ✅ 2. Create Razorpay order
@routes_subscription.route("/subscriptions/order", methods=["POST"])
def create_order():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        plan_type = data.get("plan_type")

        if not user_id or not plan_type:
            return jsonify({"error": "user_id and plan_type required"}), 400

        order = create_subscription_order(user_id, plan_type)
        return jsonify({"success": True, "order": order}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ✅ 3. Verify payment and activate plan
@routes_subscription.route("/subscriptions/verify", methods=["POST"])
def verify_payment():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        order_id = data.get("order_id")
        payment_id = data.get("payment_id")
        # Task 17C -- the Razorpay Checkout.js-provided signature is now
        # REQUIRED, matching every other Razorpay verification entry
        # point in this codebase (report purchase, Ask Now ChatPack).
        # Without it, verify_subscription_payment() cannot cryptographically
        # confirm the claimed payment is real and will fail closed.
        signature = data.get("razorpay_signature")

        if not all([user_id, order_id, payment_id, signature]):
            return jsonify({"error": "Missing required fields"}), 400

        result = verify_subscription_payment(order_id, payment_id, user_id, signature)
        return jsonify({"success": True, "result": result}), 200
    except Exception as e:
        # Task 17C -- unchanged shape/behavior from before this fix: the
        # existing controlled-failure response (400, {"error": str(e)}).
        # ValueError messages raised by verify_subscription_payment()
        # (Order not found / User not found / Payment verification
        # failed: <RazorpayProvider's own safe message>) never contain
        # credentials or raw provider internals -- RazorpayProvider.verify()
        # itself only ever returns its own short, safe message strings.
        return jsonify({"error": str(e)}), 400
