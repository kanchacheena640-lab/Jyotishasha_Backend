from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from modules.services.subscription_service import (
    create_subscription_order,
    verify_subscription_payment,
    PLAN_PRICES,
)
# Task 17D -- the SAME already-existing, already-proven identity
# resolution this exact subscription domain already uses elsewhere
# (modules/subscription/routes.py's own start_trial()): JWT identity
# (a genuine users.id) -> AppUser.id via the firebase_uid join. Reused,
# not reimplemented -- no new authentication infrastructure. Returns
# None (never raises) whenever the chain can't be completed; treated
# below as "reject the request," never as "fall back to trusting the
# client."
from modules.subscription.dual_write_adapter import resolve_profile_id_from_account_user_id

routes_subscription = Blueprint("routes_subscription", __name__)


def _authenticated_profile_id():
    """
    Task 17D -- the ONE place this blueprint derives the entitlement-
    owner identity, from the authenticated JWT alone. Never reads
    user_id from the request body -- that was the exact vulnerability
    this task fixes (Task 17C secured payment authenticity; the
    entitlement TARGET was still client-supplied). Returns the resolved
    profile_id, or None if resolution fails for any reason -- callers
    must treat None as "reject", never as "proceed with no owner".
    """
    jwt_user_id = get_jwt_identity()
    return resolve_profile_id_from_account_user_id(jwt_user_id)


# ✅ 1. Available plans -- public, unauthenticated (a price list, no
# entitlement/purchase action; unchanged by this task).
@routes_subscription.route("/subscriptions/plans", methods=["GET"])
def get_subscription_plans():
    plans = [
        {"id": k, "price": v, "currency": "INR"} for k, v in PLAN_PRICES.items()
    ]
    return jsonify({"success": True, "plans": plans})


# ✅ 2. Create Razorpay order
# Task 17D -- SECURITY FIX: now requires authentication. The entitlement
# owner (profile_id) is derived from the authenticated JWT identity,
# never from a client-supplied user_id -- a client can no longer create
# a pending SubscriptionOrder for an arbitrary account. plan_type
# remains client-selected (a real product choice, not an identity/
# amount claim) but is validated against the fixed, server-side
# PLAN_PRICES catalog exactly as before -- amount was, and remains,
# derived server-side only; the client never supplies or influences it.
@routes_subscription.route("/subscriptions/order", methods=["POST"])
@jwt_required()
def create_order():
    try:
        profile_id = _authenticated_profile_id()
        if profile_id is None:
            return jsonify({"error": "Could not resolve authenticated profile"}), 401

        data = request.get_json() or {}
        plan_type = data.get("plan_type")

        if not plan_type:
            return jsonify({"error": "plan_type required"}), 400

        order = create_subscription_order(profile_id, plan_type)
        return jsonify({"success": True, "order": order}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ✅ 3. Verify payment and activate plan
# Task 17D -- SECURITY FIX: now requires authentication. The entitlement
# owner is derived from the authenticated JWT identity, never from a
# client-supplied user_id -- a valid payment can therefore only ever
# activate the entitlement of the SAME authenticated identity that
# holds the persisted SubscriptionOrder (verify_subscription_payment()'s
# own razorpay_order_id + user_id lookup already requires an exact
# match -- see Task 17C's own binding proof); it can never be redirected
# to a different account by changing a request-body field. Task 17C's
# own cryptographic signature requirement is unchanged and still
# mandatory.
@routes_subscription.route("/subscriptions/verify", methods=["POST"])
@jwt_required()
def verify_payment():
    try:
        profile_id = _authenticated_profile_id()
        if profile_id is None:
            return jsonify({"error": "Could not resolve authenticated profile"}), 401

        data = request.get_json() or {}
        order_id = data.get("order_id")
        payment_id = data.get("payment_id")
        # Task 17C -- the Razorpay Checkout.js-provided signature is
        # REQUIRED, matching every other Razorpay verification entry
        # point in this codebase (report purchase, Ask Now ChatPack).
        # Without it, verify_subscription_payment() cannot cryptographically
        # confirm the claimed payment is real and will fail closed.
        signature = data.get("razorpay_signature")

        if not all([order_id, payment_id, signature]):
            return jsonify({"error": "Missing required fields"}), 400

        result = verify_subscription_payment(order_id, payment_id, profile_id, signature)
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
