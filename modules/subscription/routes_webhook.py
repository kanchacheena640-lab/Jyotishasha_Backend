from flask import Blueprint, request, jsonify
from extensions import db
from modules.subscription.models import Subscription
from modules.auth.models import User as AuthUser  # ✅ avoid name conflict
from datetime import datetime, timedelta

# Subscription Migration Phase 1 -- temporary dual-write, see
# modules/subscription/dual_write_adapter.py for what this is and why.
from modules.subscription.dual_write_adapter import (
    mirror_subscription_activation,
    resolve_profile_id_from_account_user_id,
)

webhook_bp = Blueprint("webhook", __name__)

@webhook_bp.route("/webhook/subscription", methods=["POST"])
def handle_subscription_webhook():
    try:
        payload = request.get_json()
        print("Received webhook:", payload)

        # Razorpay Notes Extraction
        notes = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("notes", {})
        user_id = notes.get("user_id")
        plan = notes.get("plan", "monthly")

        if not user_id:
            return jsonify({"error": "user_id missing in Razorpay notes"}), 400

        user_id = int(user_id)

        # ✅ Avoid registry conflict
        user = db.session.query(AuthUser).filter_by(id=user_id).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        now = datetime.utcnow()
        end_at = now + timedelta(days=30)

        # Create or update subscription
        subscription = Subscription.query.filter_by(user_id=user_id).first()
        now = datetime.utcnow()

        # ⛔ Already has active subscription → skip updating
        if subscription and subscription.status == "active" and subscription.end_at > now:
            print("Subscription already active — skipping update")
            return jsonify({"message": "Already active"}), 200

        # ✅ Otherwise update/create
        if not subscription:
            subscription = Subscription(user_id=user_id)

        subscription.plan = "personalized_horoscope"
        subscription.status = "active"
        subscription.start_at = now
        subscription.end_at = now + timedelta(days=30)

        db.session.add(subscription)
        db.session.commit()

        # Phase 1 dual-write: mirror this activation into System C.
        # Best-effort -- cannot affect the response below, which has
        # already succeeded.
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        profile_id = resolve_profile_id_from_account_user_id(user_id)
        if profile_id is not None:
            mirror_subscription_activation(
                profile_id,
                plan="personalized_horoscope",
                expires_at=subscription.end_at,
                transaction_reference=payment_entity.get("id"),
            )

        return jsonify({"message": "Subscription updated", "user_id": user_id}), 200

    except Exception as e:
        print("Webhook error:", str(e))
        return jsonify({"error": "Webhook failed"}), 500
