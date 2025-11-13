# ---------------------------------------------------------
#  Personalized Daily Horoscope API (Moon + House + Nakshatra)
#  File: personalized_daily_horoscope.py
#  Blueprint: personal_daily_bp
# ---------------------------------------------------------

from flask import Blueprint, request, jsonify
from services.daily_horoscope_generator import generate_daily_horoscope

personal_daily_bp = Blueprint("personal_daily_bp", __name__)

@personal_daily_bp.route("/api/personal-daily", methods=["POST"])
def get_personal_daily():
    """
    Input JSON example:
    {
      "moon_rashi": "Aries",
      "nakshatra": "Ashwini",
      "moon_house": 5,
      "paksha": "Shukla",
      "fast_planet": "venus"   # optional
    }
    """

    data = request.get_json(silent=True) or {}

    required = ["moon_rashi", "nakshatra", "moon_house", "paksha"]
    missing = [key for key in required if key not in data]

    if missing:
        return jsonify({
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    try:
        result = generate_daily_horoscope(data)
        return jsonify({
            "status": "ok",
            "type": "personalized",
            "data": result
        }), 200

    except Exception as e:
        return jsonify({
            "error": "Internal error while generating horoscope",
            "details": str(e)
        }), 500
