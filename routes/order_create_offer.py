from flask import Blueprint, request, jsonify
from config.pricing import PRODUCT_PRICES
from config.offer_engine import get_active_offer
from config.razorpay_config import razorpay_client

order_offer_bp = Blueprint('order_offer', __name__)

@order_offer_bp.route("/api/razorpay-order", methods=["POST"])
def create_discounted_order():
    data = request.get_json()
    product_id = data.get("product")

    if product_id not in PRODUCT_PRICES:
        return jsonify({"error": "Invalid product selected"}), 400

    base_price = PRODUCT_PRICES[product_id]
    active_offer = get_active_offer()

    if active_offer:
        discount = int((active_offer["discount_percent"] / 100) * base_price)
        final_price = max(base_price - discount, 1)  # never below 1
        offer_name = active_offer["name"]
    else:
        final_price = base_price
        offer_name = None

    # 👉 If just checking price (no "create_order" flag), return safe JSON
    if not data.get("create_order", False):
        return jsonify({
            "product": product_id,
            "offer": offer_name,
            "base_price": base_price,
            "final_price": final_price,
            "discount_percent": active_offer["discount_percent"] if active_offer else 0
        })

    # 👉 Only then call Razorpay
    try:
        razorpay_order = razorpay_client.order.create({
            "amount": final_price * 100,
            "currency": "INR",
            "receipt": f"rcpt_{product_id}_{final_price}",
            "payment_capture": 1,
            "notes": {"product": product_id, "offer": offer_name or "None"}
        })

        return jsonify({
            "order_id": razorpay_order["id"],
            "currency": razorpay_order["currency"],
            "amount": razorpay_order["amount"],
            "product": product_id,
            "offer": offer_name,
            "base_price": base_price,
            "final_price": final_price,
            "discount_percent": active_offer["discount_percent"] if active_offer else 0
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

