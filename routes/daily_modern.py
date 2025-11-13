# routes/daily_modern.py
# Modern 4-Block Daily Horoscope API
# mood + energy + alert + tip

from flask import Blueprint, request, jsonify
from services.personalized.personalized_daily_engine import build_personalized_daily_profile
from services.daily_engine_modern import generate_modern_daily

daily_modern_bp = Blueprint("daily_modern_bp", __name__)

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
#        TODAY — MODERN PERSONALIZED DAILY
# ====================================================
@daily_modern_bp.route("/api/modern/daily", methods=["POST"])
def modern_daily_today():
    try:
        body = request.get_json() or {}

        # 1) Lagna
        raw_lagna = body.get("lagna", "").strip().lower()
        lagna = LAGNA_MAP.get(raw_lagna)
        if not lagna:
            return jsonify({"error": "Invalid or missing lagna"}), 400

        # 2) Location (optional)
        lat = float(body.get("lat", 28.6))
        lon = float(body.get("lon", 77.2))

        # 3) Build transit profile
        profile = build_personalized_daily_profile(lagna, lat=lat, lon=lon)
        today = profile["today"]

        moon_house = today["moon"]["house"]

        # 4) UNIVERSAL ASPECT DETECTION (NEW UPDATED)
        aspects = []

        for pname, pdata in today["planets"].items():
            pname = pname.lower()

            # 1) Direct flags
            if pdata.get("aspect_on_moon") is True:
                aspects.append(pname)
                continue

            if pdata.get("conjunction_with_moon") is True:
                aspects.append(pname)
                continue

            # 2) aspects list
            if isinstance(pdata.get("aspects"), list):
                if "moon" in [x.lower() for x in pdata["aspects"]]:
                    aspects.append(pname)
                    continue

            # 3) drishti / aspect lists
            if isinstance(pdata.get("drishti"), list):
                if "moon" in [x.lower() for x in pdata["drishti"]]:
                    aspects.append(pname)
                    continue

            if isinstance(pdata.get("aspect"), list):
                if "moon" in [x.lower() for x in pdata["aspect"]]:
                    aspects.append(pname)
                    continue

            # 4) Nested values (fail-safe)
            if isinstance(pdata, dict):
                for key, val in pdata.items():
                    if isinstance(val, list):
                        if "moon" in [str(v).lower() for v in val]:
                            aspects.append(pname)
                            break

        # 5) Language
        lang = body.get("lang", "en").lower()
        if lang not in ["en", "hi"]:
            lang = "en"

        # 6) Generate modern daily
        modern = generate_modern_daily(moon_house, aspects, lang)

        return jsonify({
            "status": "success",
            "day": "today",
            "input": {
                "lagna": lagna,
                "moon_house": moon_house,
                "aspects": aspects,
                "lang": lang
            },
            "result": modern
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
