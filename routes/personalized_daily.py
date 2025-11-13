from flask import Blueprint, request, jsonify
import requests
import datetime
import pytz
from transit_engine import (
    _to_julday_utc,
    _rashi_from_sidereal_lon,
    PLANET_IDS,
    swe,
)
from services.daily_horoscope_generator import generate_daily_horoscope


personalized_daily = Blueprint("personalized_daily", __name__)

# -------------------------
#  CONSTANTS
# -------------------------
TRANSIT_API = "https://jyotishasha-backend.onrender.com/api/transit/current"
PANCHANG_API = "https://jyotishasha-backend.onrender.com/api/panchang"

NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira",
    "Ardra","Punarvasu","Pushya","Ashlesha","Magha",
    "Purva_Phalguni","Uttara_Phalguni","Hasta","Chitra",
    "Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva_Ashadha","Uttara_Ashadha","Shravana","Dhanishta",
    "Shatabhisha","Purva_Bhadrapada","Uttara_Bhadrapada",
    "Revati"
]


# -------------------------
#  Nakshatra Calculator
# -------------------------
def get_nakshatra_from_longitude(sid_lon):
    nak = int(sid_lon // (360 / 27))
    return NAKSHATRAS[nak]


# -------------------------
#  Build Transit for ANY Date (TOMORROW)
# -------------------------
def build_transit_for_date(dt_ist):
    jd = _to_julday_utc(dt_ist)
    ay = swe.get_ayanamsa_ut(jd)

    out = {}
    for pid, name in PLANET_IDS.items():
        res, _ = swe.calc_ut(jd, pid)
        lon = res[0]
        speed = res[3] if len(res) > 3 else 0.0
        sid = (lon - ay) % 360

        out[name] = {
            "rashi": _rashi_from_sidereal_lon(sid),
            "degree": round(sid % 30, 2),
            "sidereal_longitude": sid,
            "motion": "Retrograde" if speed < 0 else "Direct",
        }

    # Rahu-Ketu
    rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
    ketu_sid = (rahu_sid + 180) % 360

    out["Rahu"] = {
        "rashi": _rashi_from_sidereal_lon(rahu_sid),
        "degree": round(rahu_sid % 30, 2),
        "sidereal_longitude": rahu_sid,
        "motion": "Retrograde",
    }

    out["Ketu"] = {
        "rashi": _rashi_from_sidereo

    }

    return out


# -------------------------
#  House Mapping (Lagna-based)
# -------------------------
def build_house_map(moon_rashi):
    rashis = [
        "aries","taurus","gemini","cancer","leo","virgo",
        "libra","scorpio","sagittarius","capricorn","aquarius","pisces"
    ]
    base = rashis.index(moon_rashi.lower()) + 1

    mapping = {}
    for i, r in enumerate(rashis):
        mapping[r] = ((i + 1) - base) % 12 + 1
    return mapping


# -------------------------
#  Panchang Hook → Paksha
# -------------------------
def get_paksha():
    try:
        r = requests.get(PANCHANG_API)
        if r.status_code == 200:
            return r.json()["selected_date"]["tithi"]["paksha"]
    except:
        pass
    return "Shukla"


# -------------------------
#  FAST PLANETS (check Mars, Venus, Mercury position)
# -------------------------
def detect_fast_planet(transit):
    fast = []
    for name in ["Mars", "Venus", "Mercury"]:
        if name in transit:
            fast.append(name.lower())
    return fast


# -------------------------
#  BUILD PROFILE for Horoscope Generator
# -------------------------
def build_profile(lagna, moon_obj, paksha, fast_planets):
    sid = moon_obj["sidereal_longitude"]
    nak = get_nakshatra_from_longitude(sid)
    rashi = moon_obj["rashi"]

    house_map = build_house_map(rashi)
    moon_house_num = house_map[lagna.lower()]

    return {
        "moon_rashi": rashi,
        "nakshatra": nak,
        "moon_house": moon_house_num,
        "fast_planet": fast_planets[0] if fast_planets else None,
        "paksha": paksha,
    }


# -------------------------
#  TODAY
# -------------------------
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def get_daily():
    try:
        req = request.get_json()
        lagna = req.get("lagna", "").lower()
        if not lagna:
            return jsonify({"error": "Missing 'lagna'"}), 400

        # → Get TODAY from API
        r = requests.get(TRANSIT_API)
        if r.status_code != 200:
            return jsonify({"error": "Transit API failed"}), 500

        today = r.json()["positions"]
        moon = today["Moon"]

        paksha = get_paksha()
        fast_planets = detect_fast_planet(today)

        profile = build_profile(lagna, moon, paksha, fast_planets)
        result = generate_daily_horoscope(profile)
        result["day"] = "today"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------
#  TOMORROW
# -------------------------
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def get_tomorrow():
    try:
        req = request.get_json()
        lagna = req.get("lagna", "").lower()
        if not lagna:
            return jsonify({"error": "Missing 'lagna'"}), 400

        # tomorrow IST
        tomo_ist = datetime.datetime.now(
            pytz.timezone("Asia/Kolkata")
        ) + datetime.timedelta(days=1)

        # compute tomorrow transit internally
        tomo = build_transit_for_date(tomo_ist)
        moon = tomo["Moon"]

        paksha = get_paksha()
        fast_planets = detect_fast_planet(tomo)

        profile = build_profile(lagna, moon, paksha, fast_planets)
        result = generate_daily_horoscope(profile)
        result["day"] = "tomorrow"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
