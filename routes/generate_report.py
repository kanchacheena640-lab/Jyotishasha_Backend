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
