from flask import Blueprint, request, jsonify
import json, os
from datetime import datetime

monthly_bp = Blueprint("monthly_bp", __name__)

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "..", "data")

MONTHLY_FILE_EN = os.path.join(DATA_DIR, "monthly_fixed.json")
MONTHLY_FILE_HI = os.path.join(DATA_DIR, "monthly_fixed_hi.json")

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

MONTH_HI = {
    1: "जनवरी", 2: "फ़रवरी", 3: "मार्च", 4: "अप्रैल",
    5: "मई", 6: "जून", 7: "जुलाई", 8: "अगस्त",
    9: "सितंबर", 10: "अक्टूबर", 11: "नवंबर", 12: "दिसंबर"
}

@monthly_bp.route("/api/monthly-horoscope", methods=["GET"])
def get_monthly_horoscope():
    sign = request.args.get("sign", "").lower()
    lang = request.args.get("lang", "en").lower()

    if sign not in ZODIACS:
        return jsonify({"error": "Invalid zodiac sign"}), 400

    data_file = MONTHLY_FILE_HI if lang == "hi" else MONTHLY_FILE_EN

    if not os.path.exists(data_file):
        return jsonify({"error": "Monthly horoscope not ready"}), 503

    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if sign not in data:
        return jsonify({"error": "Horoscope not found"}), 404

    result = dict(data[sign])

    now = datetime.now()
    year = now.year

    if lang == "hi":
        month_name = MONTH_HI[now.month]
        sign_name = SIGN_HI.get(sign, sign)
    else:
        month_name = now.strftime("%B")
        sign_name = sign.capitalize()

    # 🔁 Placeholder replacement (GLOBAL)
    def replace_placeholders(val):
        if isinstance(val, str):
            return (
                val.replace("{MONTH}", month_name)
                   .replace("{YEAR}", str(year))
                   .replace("{SIGN}", sign_name)
            )
        return val

    for key, value in result.items():
        if isinstance(value, list):
            result[key] = [replace_placeholders(v) for v in value]
        else:
            result[key] = replace_placeholders(value)

    result.update({
        "sign": sign,
        "sign_name": sign_name,
        "month": month_name,
        "year": year,
        "lang": lang
    })

    return jsonify(result), 200
