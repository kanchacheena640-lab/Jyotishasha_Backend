from flask import Blueprint, request, jsonify
from services.daily_horoscope_generator import generate_daily_horoscope

personalized_daily = Blueprint("personalized_daily", __name__)

@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def get_personalized_daily():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing JSON body"}), 400

        result = generate_daily_horoscope(data)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
