# personalized_daily.py
# FINAL PERSONALIZED DAILY HOROSCOPE (3-LINE VERSION)

from flask import Blueprint, request, jsonify
from services.personalized.personalized_daily_engine import build_personalized_daily_profile
from services.personalized.personalized_daily_text_builder import (
    build_transit_sentence,
    build_aspect_sentence,
    build_remedy_sentence
)

personalized_daily = Blueprint("personalized_daily", __name__)

# ------------------------------------------------
# LAGNA NORMALIZATION MAP
# ------------------------------------------------
LAGNA_MAP = {
    "aries": "Aries", "mesh": "Aries",
    "taurus": "Taurus", "vrishabh": "Taurus",
    "gemini": "Gemini", "mithun": "Gemini",
    "cancer": "Cancer", "kark": "Cancer",
    "leo": "Leo", "singh": "Leo",
    "virgo": "Virgo", "kanya": "Virgo",
    "libra": "Libra", "tula": "Libra",
    "scorpio": "Scorpio", "vrishchik": "Scorpio",
    "sagittarius": "Sagittarius", "dhanu": "Sagittarius",
    "capricorn": "Capricorn", "makar": "Capricorn",
    "aquarius": "Aquarius", "kumbh": "Aquarius",
    "pisces": "Pisces", "meen": "Pisces"
}

# ====================================================
#               TODAY — PERSONALIZED
# ====================================================
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def personalized_daily_today():
    try:
        body = request.get_json() or {}

        # 1) Lagna
        raw_lagna = body.get("lagna", "").strip().lower()
        lagna = LAGNA_MAP.get(raw_lagna)
        if not lagna:
            return jsonify({"error": "Invalid or missing lagna"}), 400

        # 2) Optional location
        lat = float(body.get("lat", 28.6))
        lon = float(body.get("lon", 77.2))

        # 3) Transit data
        profile = build_personalized_daily_profile(lagna, lat=lat, lon=lon)
        today = profile["today"]

        # 4) Build text
        main_line = build_transit_sentence(today) or ""
        aspect_line = build_aspect_sentence(today) or ""
        remedy_line = build_remedy_sentence(today) or ""

        combined = "\n".join([main_line, aspect_line, remedy_line]).strip()

        return jsonify({
            "status": "success",
            "day": "today",
            "lagna": lagna,
            "moon": today["moon"],
            "result": {
                "main_line": main_line,
                "aspect_line": aspect_line,
                "remedy_line": remedy_line,
                "combined_text": combined
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ====================================================
#               TOMORROW — PERSONALIZED
# ====================================================
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def personalized_daily_tomorrow():
    try:
        body = request.get_json() or {}

        raw_lagna = body.get("lagna", "").strip().lower()
        lagna = LAGNA_MAP.get(raw_lagna)
        if not lagna:
            return jsonify({"error": "Invalid or missing lagna"}), 400

        lat = float(body.get("lat", 28.6))
        lon = float(body.get("lon", 77.2))

        profile = build_personalized_daily_profile(lagna, lat=lat, lon=lon)
        tomorrow = profile["tomorrow"]

        main_line = build_transit_sentence(tomorrow) or ""
        aspect_line = build_aspect_sentence(tomorrow) or ""
        remedy_line = build_remedy_sentence(tomorrow) or ""

        combined = "\n".join([main_line, aspect_line, remedy_line]).strip()

        return jsonify({
            "status": "success",
            "day": "tomorrow",
            "lagna": lagna,
            "moon": tomorrow["moon"],
            "result": {
                "main_line": main_line,
                "aspect_line": aspect_line,
                "remedy_line": remedy_line,
                "combined_text": combined
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
