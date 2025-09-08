from flask import Blueprint, request, jsonify
import json
import os

monthly_bp = Blueprint("monthly_bp", __name__)

MONTHLY_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "monthly_fixed.json")

ZODIACS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"
]

@monthly_bp.route("/api/monthly-horoscope")
def get_monthly_horoscope():
    sign = request.args.get("sign", "").lower()

    if sign not in ZODIACS:
        return jsonify({"error": "Invalid zodiac sign"}), 400

    if not os.path.exists(MONTHLY_FILE):
        return jsonify({"error": "Monthly horoscope not ready."}), 503

    with open(MONTHLY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if sign not in data:
        return jsonify({"error": "Horoscope not found for given sign."}), 404

    return jsonify(data[sign]), 200
