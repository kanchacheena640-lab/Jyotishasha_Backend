from flask import Blueprint, request, jsonify
import json, os
from datetime import datetime

daily_bp = Blueprint("daily_bp", __name__)

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "..", "data")

DAILY_FILE_EN = os.path.join(DATA_DIR, "daily_fixed.json")
DAILY_FILE_HI = os.path.join(DATA_DIR, "daily_fixed_hi.json")

ZODIACS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"
]

SIGN_HI = {
    "aries": "मेष", "taurus": "वृषभ", "gemini": "मिथुन", "cancer": "कर्क",
    "leo": "सिंह", "virgo": "कन्या", "libra": "तुला",
    "scorpio": "वृश्चिक", "sagittarius": "धनु",
    "capricorn": "मकर", "aquarius": "कुंभ", "pisces": "मीन"
}

@daily_bp.route("/api/daily-horoscope", methods=["GET"])
def get_daily_horoscope():
    sign = request.args.get("sign", "").lower()
    lang = request.args.get("lang", "en").lower()

    if sign not in ZODIACS:
        return jsonify({"error": "Invalid zodiac sign"}), 400

    data_file = DAILY_FILE_HI if lang == "hi" else DAILY_FILE_EN

    if not os.path.exists(data_file):
        return jsonify({"error": "Daily horoscope not ready"}), 503

    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if sign not in data:
        return jsonify({"error": "Horoscope not found"}), 404

    result = dict(data[sign])  # safer than copy()

    today_date = datetime.now().strftime("%d %B %Y")

    if lang == "hi":
        sign_name = SIGN_HI.get(sign, sign)
        heading = f"आज का राशिफल {sign_name} – {today_date}"
    else:
        sign_name = sign.capitalize()
        heading = f"Today's Daily Horoscope for {sign_name} – {today_date}"

    result.update({
        "heading": heading,
        "sign": sign,
        "date": today_date,
        "lang": lang
    })

    # Placeholder replacement
    for k in ("intro", "paragraph", "tips"):
        if k in result and isinstance(result[k], str):
            result[k] = (
                result[k]
                .replace("{SIGN}", sign_name)
                .replace("{DATE}", today_date)
            )

    return jsonify(result), 200
