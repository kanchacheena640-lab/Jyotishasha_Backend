from flask import Blueprint, request, jsonify
from services.daily_horoscope_generator import generate_daily_horoscope
from transit_engine import (
    get_current_positions,
    _to_julday_utc,
    _rashi_from_sidereal_lon,
    PLANET_IDS,
    swe,
    pytz,
    datetime,
)

personalized_daily = Blueprint("personalized_daily", __name__)


# -----------------------------------------------------------
#  Nakshatra Calculator (Do NOT modify transit_engine)
# -----------------------------------------------------------
NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira",
    "Ardra","Punarvasu","Pushya","Ashlesha","Magha",
    "Purva_Phalguni","Uttara_Phalguni","Hasta","Chitra",
    "Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva_Ashadha","Uttara_Ashadha","Shravana","Dhanishta",
    "Shatabhisha","Purva_Bhadrapada","Uttara_Bhadrapada",
    "Revati"
]

def get_nakshatra_from_longitude(sidereal_lon):
    # Each nakshatra = 13°20' = 13.333333 degrees
    return NAKSHATRAS[int(sidereal_lon // (360/27))]


# -----------------------------------------------------------
# Build full transit for ANY IST date (Tomorrow)
# -----------------------------------------------------------
def build_transit_for_date(dt_ist):
    jd = _to_julday_utc(dt_ist)
    ay = swe.get_ayanamsa_ut(jd)

    out = {}
    for pid, name in PLANET_IDS.items():
        res, _ = swe.calc_ut(jd, pid)
        lon = res[0]
        speed = res[3] if len(res) > 3 else 0.0
        sid_lon = (lon - ay) % 360

        out[name] = {
            "rashi": _rashi_from_sidereal_lon(sid_lon),
            "degree": round(sid_lon % 30, 2),
            "sidereal_longitude": sid_lon,
            "motion": "Retrograde" if speed < 0 else "Direct",
        }

    # Rahu / Ketu
    rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
    ketu_sid = (rahu_sid + 180) % 360

    out["Rahu"] = {
        "rashi": _rashi_from_sidereal_lon(rahu_sid),
        "degree": round(rahu_sid % 30, 2),
        "sidereal_longitude": rahu_sid,
        "motion": "Retrograde",
    }

    out["Ketu"] = {
        "rashi": _rashi_from_sidereal_lon(ketu_sid),
        "degree": round(ketu_sid % 30, 2),
        "sidereal_longitude": ketu_sid,
        "motion": "Retrograde",
    }

    return out


# -----------------------------------------------------------
# House-map logic (Same as Kundali)
# -----------------------------------------------------------
def build_house_map(moon_rashi):
    rashis = [
        "aries","taurus","gemini","cancer","leo","virgo",
        "libra","scorpio","sagittarius","capricorn","aquarius","pisces"
    ]
    base = rashis.index(moon_rashi.lower()) + 1

    mapping = {}
    for idx, r in enumerate(rashis):
        mapping[r] = ((idx + 1) - base) % 12 + 1

    return mapping



# -----------------------------------------------------------
# TODAY HOROSCOPE
# -----------------------------------------------------------
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def get_daily():
    try:
        data = request.get_json()
        if not data or "lagna" not in data:
            return jsonify({"error": "Missing lagna"}), 400

        lagna = data["lagna"].lower()

        # 1) Today transit (already fully working engine)
        today = get_current_positions()["positions"]
        moon = today["Moon"]

        # 2) Compute Nakshatra from longitude
        moon_nakshatra = get_nakshatra_from_longitude(moon["sidereal_longitude"])

        # 3) Compute House number
        house_map = build_house_map(moon["rashi"])

        profile = {
            "moon_rashi": moon["rashi"],
            "nakshatra": moon_nakshatra,
            "moon_house": house_map[lagna],
            "fast_planet": today.get("fast_planet"),
            "paksha": today.get("paksha", "Shukla"),
        }

        result = generate_daily_horoscope(profile)
        result["day"] = "today"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# -----------------------------------------------------------
# TOMORROW HOROSCOPE
# -----------------------------------------------------------
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def get_tomorrow():
    try:
        data = request.get_json()
        if not data or "lagna" not in data:
            return jsonify({"error": "Missing lagna"}), 400

        lagna = data["lagna"].lower()

        # 1) Tomorrow in IST
        tomo_ist = datetime.datetime.now(
            pytz.timezone("Asia/Kolkata")
        ) + datetime.timedelta(days=1)

        # 2) Build transit for tomorrow
        tomo = build_transit_for_date(tomo_ist)
        moon = tomo["Moon"]

        # 3) Compute Nakshatra
        moon_nakshatra = get_nakshatra_from_longitude(moon["sidereal_longitude"])

        # 4) Compute House number
        house_map = build_house_map(moon["rashi"])

        profile = {
            "moon_rashi": moon["rashi"],
            "nakshatra": moon_nakshatra,
            "moon_house": house_map[lagna],
            "fast_planet": tomo.get("fast_planet"),
            "paksha": tomo.get("paksha", "Shukla"),
        }

        result = generate_daily_horoscope(profile)
        result["day"] = "tomorrow"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
