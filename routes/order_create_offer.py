from flask import Blueprint, request, jsonify
from config.pricing import PRODUCT_PRICES
from flask import Blueprint, request, jsonify
from full_kundali_api import calculate_full_kundali
from prompt_engine import build_prompt_from_product, build_transit_summary_text
from report_writer import get_openai_response, generate_pdf_and_email
from transit_engine import get_current_positions, get_all_planets_next_12


generate_report_bp = Blueprint("generate_report", __name__)

@generate_report_bp.route("/api/generate-report", methods=["POST"])
def generate_report():
    try:
        data = request.get_json()

        # 1. Extract user info
        name = data.get("name")
        email = data.get("email")
        product = data.get("product")
        dob = data.get("dob")
        tob = data.get("tob")
        language = data.get("language", "en")

        if not all([name, email, product, dob, tob]):
            return jsonify({"error": "Missing required fields"}), 400

        # 2. Parse lat/lon with error handling
        try:
            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))
        except (TypeError, ValueError):
            return jsonify({"error": "Latitude and Longitude must be valid numbers"}), 400

        # 3. Kundali generation
        kundali = calculate_full_kundali(
            name=name,
            dob=dob,
            tob=tob,
            lat=latitude,
            lon=longitude,
            language=language
        )

        # 4. Transit data (merged into prompt)
        transit_data = {
            "positions": get_current_positions(),
            "future_transits": get_all_planets_next_12()
        }
        kundali["transit_summary"] = build_transit_summary_text(transit_data)

        # 5. Build prompt from template
        prompt = build_prompt_from_product(product, kundali, transit_data, language)
        print("✅ FINAL PROMPT:\n", prompt)

        # 6. Get OpenAI response
        report_text = get_openai_response(prompt)

        # 7. Generate PDF and Email
        pdf_url = generate_pdf_and_email(name, email, product, report_text, kundali, language)

        # 8. Return success
        return jsonify({
            "status": "success",
            "pdf_url": pdf_url,
            "message": f"Report for {name} has been sent to {email}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
from config.razorpay_config import razorpay_client

order_offer_bp = Blueprint('order_offer', __name__)

@order_offer_bp.route("/api/razorpay-order", methods=["POST"])
def create_discounted_order():
    data = request.get_json()
    product_id = data.get("product")

    if product_id not in PRODUCT_PRICES:
        return jsonify({"error": "Invalid product selected"}), 400

    base_price = PRODUCT_PRICES[product_id]
    #active_offer = get_active_offer()
    active_offer = None

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

