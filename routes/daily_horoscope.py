from flask import Blueprint, request, jsonify
from datetime import datetime
from scripts.daily_rotation_engine import run_daily_rotation_runtime

daily_bp = Blueprint("daily_bp", __name__)

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


@daily_bp.route("/api/daily-horoscope", methods=["GET"])
def get_daily_horoscope():
    sign = request.args.get("sign", "").lower()
    lang = request.args.get("lang", "en").lower()

    if sign not in ZODIACS:
        return jsonify({"error": "Invalid zodiac sign"}), 400

    # 🔁 Runtime rotation (DB-based)
    data_en, data_hi = run_daily_rotation_runtime()
    data = data_hi if lang == "hi" else data_en

    result = data.get(sign)
    if not result:
        return jsonify({"error": "Horoscope not found"}), 404

    now = datetime.now()

    if lang == "hi":
        today_date = f"{now.day} {MONTH_HI[now.month]} {now.year}"
        sign_name = SIGN_HI.get(sign, sign)
        heading = f"आज का राशिफल {sign_name} – {today_date}"
    else:
        today_date = now.strftime("%d %B %Y")
        sign_name = sign.capitalize()
        heading = f"Today's Daily Horoscope for {sign_name} – {today_date}"

    # Final response
    response = {
        **result,
        "heading": heading,
        "sign": sign,
        "date": today_date,
        "lang": lang
    }

    for k in ("intro", "paragraph", "tips"):
        if k in response and isinstance(response[k], str):
            response[k] = (
                response[k]
                .replace("{SIGN}", sign_name)
                .replace("{DATE}", today_date)
            )

    return jsonify(response), 200
