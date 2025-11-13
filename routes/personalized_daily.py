from flask import Blueprint, request, jsonify
from services.daily_horoscope_generator import generate_daily_horoscope
from transit_engine import get_current_positions, get_next_positions   # ← BOTH USED

personalized_daily = Blueprint("personalized_daily", __name__)


# -----------------------------------------------------------
#  Helper: Build profile from transit + lagna
# -----------------------------------------------------------
def make_profile(transit_day, lagna):
    moon = transit_day["Moon"]

    return {
        "moon_rashi": moon["rashi"],
        "nakshatra": moon["nakshatra"],
        "moon_house": moon["house_map"][lagna],
        "fast_planet": transit_day.get("fast_planet"),   # mercury / venus / mars / None
        "paksha": transit_day.get("paksha", "Shukla")
    }



# -----------------------------------------------------------
#  TODAY → /api/personalized/daily
# -----------------------------------------------------------
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def get_personalized_daily():
    try:
        data = request.get_json()
        if not data or "lagna" not in data:
            return jsonify({"error": "Missing lagna"}), 400

        lagna = data["lagna"].lower()

        # 1) Today’s Transit
        today = get_current_positions()["positions"]

        # 2) Build Profile
        profile = make_profile(today, lagna)

        # 3) Generate Horoscope
        result = generate_daily_horoscope(profile)
        result["day"] = "today"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# -----------------------------------------------------------
#  TOMORROW → /api/personalized/tomorrow
# -----------------------------------------------------------
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def get_personalized_tomorrow():
    try:
        data = request.get_json()
        if not data or "lagna" not in data:
            return jsonify({"error": "Missing lagna"}), 400

        lagna = data["lagna"].lower()

        # 1) Tomorrow’s Transit — internal engine
        tomorrow = get_next_positions(1)["positions"]

        # 2) Build Profile
        profile = make_profile(tomorrow, lagna)

        # 3) Generate Horoscope
        result = generate_daily_horoscope(profile)
        result["day"] = "tomorrow"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
