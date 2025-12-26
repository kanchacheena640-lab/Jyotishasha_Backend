from flask import Blueprint, request, jsonify
import json
import os

daily_bp = Blueprint("daily_bp", __name__)

DAILY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "daily_fixed.json")

ZODIACS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"
]

@daily_bp.route("/api/daily-horoscope", methods=["GET"])
def get_daily_horoscope():
    sign = request.args.get("sign", "").lower()

    if sign not in ZODIACS:
        return jsonify({"error": "Invalid zodiac sign"}), 400

    if not os.path.exists(DAILY_FILE):
        return jsonify({"error": "Daily horoscope not ready."}), 503

    with open(DAILY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if sign not in data:
        return jsonify({"error": "Horoscope not found for given sign."}), 404

    result = data[sign]

    # 🔁 Replace placeholders
    sign_title = sign.capitalize()
    if isinstance(result, dict):
        for key, value in result.items():
            if isinstance(value, str):
                result[key] = value.replace("{SIGN}", sign_title)

    return jsonify(result), 200
