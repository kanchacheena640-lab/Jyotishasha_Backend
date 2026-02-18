from flask import Blueprint, request, jsonify
from datetime import datetime
from services.festivals.holi_engine import detect_holi
from services.festivals.holi_rashi_tips import generate_holi_rashi_tips

routes_festivals = Blueprint("routes_festivals", __name__)

@routes_festivals.route("/holi", methods=["POST"])
def api_holi():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))

        year = int(data.get("year")) if data.get("year") else datetime.now().year
        user_moon = data.get("user_moon_sign")  # optional (for app)

        # 🔹 Base Holi Info
        holi_info = detect_holi(year, lat, lon, "en")

        # 🔹 Rashi Tips
        rashi_data = generate_holi_rashi_tips(year, lat, lon, "en")

        response = holi_info or {}

        # Website ke liye – full rashi data
        if rashi_data:
            response["moon_sign_on_holi"] = rashi_data["moon_sign_on_holi"]
            response["rashi_tips"] = rashi_data["tips"]

        # App ke liye – personalized only
        if user_moon and rashi_data:
            sign = user_moon.lower()
            if sign in rashi_data["tips"]:
                response["personal_rashi_tip"] = rashi_data["tips"][sign]

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
