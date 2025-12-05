# personalized_daily.py
# FINAL PERSONALIZED DAILY HOROSCOPE (with per-user daily caching)

from flask import Blueprint, request, jsonify
from services.personalized.personalized_daily_engine import build_personalized_daily_profile
from services.personalized.personalized_daily_text_builder import (
    build_transit_sentence,
    build_aspect_sentence,
    build_remedy_sentence
)

# NEW IMPORTS (for caching)
from modules.models_daily_cache import DailyPersonalizedCache
from extensions import db
from datetime import date

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

        # 2) Location
        lat = float(body.get("lat", 28.6))
        lon = float(body.get("lon", 77.2))

        # 3) Language
        lang = body.get("lang", "en").lower()
        if lang not in ["en", "hi"]:
            lang = "en"

        # 4) User & Profile IDs
        user_id = body.get("backend_user_id")
        profile_id = body.get("backendProfileId")

        # 5) Build transit data
        profile = build_personalized_daily_profile(lagna, lat=lat, lon=lon)
        today = profile["today"]
        today["lang"] = lang

        # ------------------------------------------------------------
        #       CACHE CHECK — SAME USER, SAME PROFILE, SAME DAY
        # ------------------------------------------------------------
        if user_id and profile_id:
            cache = DailyPersonalizedCache.query.filter_by(
                user_id=user_id,
                profile_id=profile_id,
                date=date.today()
            ).first()

            if cache:
                # return locked planet result
                aspect = cache.aspect_line_en if lang == "en" else cache.aspect_line_hi
                remedy = cache.remedy_en if lang == "en" else cache.remedy_hi

                combined = (aspect + "\n" + remedy).strip()

                return jsonify({
                    "status": "success",
                    "day": "today",
                    "lagna": lagna,
                    "moon": today["moon"],
                    "lang": lang,
                    "result": {
                        "main_line": "",
                        "aspect_line": aspect,
                        "remedy_line": remedy,
                        "combined_text": combined
                    }
                }), 200

        # ------------------------------------------------------------
        #     NO CACHE → GENERATE NEW RANDOM RESULT (Today's Planet)
        # ------------------------------------------------------------
        main_line = build_transit_sentence(today) or ""
        aspect_line = build_aspect_sentence(today) or ""
        remedy_line = build_remedy_sentence(today) or ""

        combined = "\n".join([main_line, aspect_line, remedy_line]).strip()

        # ------------------------------------------------------------
        #      SAVE **BOTH LANGUAGES** FIXED OUTPUT TO CACHE
        # ------------------------------------------------------------
        if user_id and profile_id:
            # generate EN + HI versions with SAME planet
            aspect_en = build_aspect_sentence({**today, "lang": "en"}) or ""
            aspect_hi = build_aspect_sentence({**today, "lang": "hi"}) or ""

            remedy_en = build_remedy_sentence({**today, "lang": "en"}) or ""
            remedy_hi = build_remedy_sentence({**today, "lang": "hi"}) or ""

            cache = DailyPersonalizedCache(
                user_id=user_id,
                profile_id=profile_id,
                date=date.today(),

                aspect_line_en=aspect_en,
                aspect_line_hi=aspect_hi,

                remedy_en=remedy_en,
                remedy_hi=remedy_hi
            )

            db.session.add(cache)
            db.session.commit()

        # ------------------------------------------------------------

        return jsonify({
            "status": "success",
            "day": "today",
            "lagna": lagna,
            "moon": today["moon"],
            "lang": lang,
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

        lang = body.get("lang", "en").lower()
        if lang not in ["en", "hi"]:
            lang = "en"

        profile = build_personalized_daily_profile(lagna, lat=lat, lon=lon)
        tomorrow = profile["tomorrow"]
        tomorrow["lang"] = lang

        main_line = build_transit_sentence(tomorrow) or ""
        aspect_line = build_aspect_sentence(tomorrow) or ""
        remedy_line = build_remedy_sentence(tomorrow) or ""

        combined = "\n".join([main_line, aspect_line, remedy_line]).strip()

        return jsonify({
            "status": "success",
            "day": "tomorrow",
            "lagna": lagna,
            "moon": tomorrow["moon"],
            "lang": lang,
            "result": {
                "main_line": main_line,
                "aspect_line": aspect_line,
                "remedy_line": remedy_line,
                "combined_text": combined
            }
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
