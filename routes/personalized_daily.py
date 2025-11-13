# personalized_daily.py
# FINAL PRODUCTION VERSION (NO API CALLS)

from flask import Blueprint, request, jsonify
from services.personalized.personalized_daily_engine import (
    build_personalized_daily_profile
)
from services.daily_horoscope_generator import generate_daily_horoscope

personalized_daily = Blueprint("personalized_daily", __name__)


# ====================================================
#           TODAY PERSONALIZED HOROSCOPE
# ====================================================
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def personalized_daily_today():
    try:
        body = request.get_json() or {}

        # -----------------------------
        # Required Input
        # -----------------------------
        lagna = body.get("lagna", "").strip().capitalize()
        if not lagna:
            return jsonify({"error": "Missing or invalid lagna"}), 400

        # -----------------------------
        # Optional Location
        # -----------------------------
        lat = float(body.get("lat", 28.6))     # Default: Delhi
        lon = float(body.get("lon", 77.2))

        # -----------------------------
        # Build full transit profile
        # -----------------------------
        profile = build_personalized_daily_profile(lagna, lat=lat, lon=lon)

        today = profile["today"]

        # -----------------------------
        # Map to horoscope generator input
        # -----------------------------
        generator_input = {
            "moon_rashi": today["moon"]["rashi"],
            "nakshatra": today["moon"]["nakshatra"],
            "moon_house": today["moon"]["house"],
            "fast_planet": today["fast_planet"],
            "paksha": today["paksha"]
        }

        # -----------------------------
        # Generate horoscope text
        # -----------------------------
        final_text = generate_daily_horoscope(generator_input)

        return jsonify({
            "day": "today",
            "input_used": generator_input,
            "horoscope": final_text
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ====================================================
#           TOMORROW PERSONALIZED HOROSCOPE
# ====================================================
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def personalized_daily_tomorrow():
    try:
        body = request.get_json() or {}

        lagna = body.get("lagna", "").strip().capitalize()
        if not lagna:
            return jsonify({"error": "Missing or invalid lagna"}), 400

        lat = float(body.get("lat", 28.6))
        lon = float(body.get("lon", 77.2))

        # Build full transit (today + tomorrow)
        profile = build_personalized_daily_profile(lagna, lat=lat, lon=lon)

        tomorrow = profile["tomorrow"]

        # Generator Input
        generator_input = {
            "moon_rashi": tomorrow["moon"]["rashi"],
            "nakshatra": tomorrow["moon"]["nakshatra"],
            "moon_house": tomorrow["moon"]["house"],
            "fast_planet": tomorrow["fast_planet"],
            "paksha": tomorrow["paksha"]
        }

        final_text = generate_daily_horoscope(generator_input)

        return jsonify({
            "day": "tomorrow",
            "input_used": generator_input,
            "horoscope": final_text
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
