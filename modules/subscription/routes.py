from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db
from modules.subscription.models import Subscription
from config.razorpay_config import razorpay_client
from datetime import datetime, timedelta

subscription_bp = Blueprint("subscription_bp", __name__)

# -------------------- GET Subscription Status -------------------- #
@subscription_bp.get("/api/subscription")
@jwt_required()
def get_subscription():
    uid = get_jwt_identity()
    sub = Subscription.query.filter_by(user_id=uid).first()

    if not sub:
        # auto-create 15-day free plan
        sub = Subscription(
            user_id=uid,
            plan="free",
            status="active",
            start_at=datetime.utcnow(),
            end_at=datetime.utcnow() + timedelta(days=15)
        )
        db.session.add(sub)
        db.session.commit()

    return jsonify({"subscription": sub.to_dict()}), 200

# -------------------- Create Razorpay Order for Subscription -------------------- #
@subscription_bp.post("/api/subscription/create-order")
@jwt_required()
def create_subscription_order():
    uid = get_jwt_identity()
    data = request.get_json() or {}
    plan = data.get("plan", "monthly")

    amount = 9900 if plan == "monthly" else 55100  # in paise
    notes = {
        "user_id": str(uid),
        "plan": plan,
    }

    razorpay_order = razorpay_client.order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": f"sub_{uid}_{plan}_{datetime.utcnow().timestamp()}",
        "payment_capture": 1,
        "notes": notes
    })

    return jsonify({
        "order_id": razorpay_order["id"],
        "amount": razorpay_order["amount"],
        "currency": razorpay_order["currency"],
        "plan": plan
    }), 200
