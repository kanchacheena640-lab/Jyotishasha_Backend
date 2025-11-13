from flask import Blueprint, request, jsonify
import requests
from services.daily_horoscope_generator import generate_daily_horoscope

personalized_daily = Blueprint("personalized_daily", __name__)

TRANSIT_API = "https://jyotishasha-backend.onrender.com/api/transits?days=1"

@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def get_personalized_daily():
    try:
        body = request.get_json()
        if not body or "lagna" not in body:
            return jsonify({"error": "Missing lagna"}), 400

        lagna = body["lagna"].lower()

        # 1) Fetch today's transit from Render backend
        r = requests.get(TRANSIT_API)
        if r.status_code != 200:
            return jsonify({"error": "Transit fetch failed"}), 500

        transit = r.json()
        today = transit["transits"][0]

        # 2) Build user profile dynamically
        profile = {
            "moon_rashi": today["moon"]["rashi"],
            "nakshatra": today["moon"]["nakshatra"],
            "moon_house": today["moon"]["house_map"][lagna],
            "fast_planet": today.get("fast_planet"),
            "paksha": today.get("paksha", "Shukla")
        }

        # 3) Generate Horoscope
        result = generate_daily_horoscope(profile)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
