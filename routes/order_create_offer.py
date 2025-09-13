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
        final_price = base_price - discount
        offer_name = active_offer["name"]
    else:
        final_price = base_price
        offer_name = None

    # Razorpay expects amount in paise
    amount_paise = final_price * 100

    offer_tag = (offer_name or "regular").replace(" ", "")[:10]
    receipt = f"rcpt_{product_id}_{final_price}_{offer_tag}"

    try:
        razorpay_order = razorpay_client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "payment_capture": 1,
            "notes": {
                "product": product_id,
                "offer": offer_name or "None"
            }
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
