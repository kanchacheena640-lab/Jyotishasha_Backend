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


# --------------------------
# NAKSHATRA ARRAY
# --------------------------
NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira",
    "Ardra","Punarvasu","Pushya","Ashlesha","Magha",
    "Purva_Phalguni","Uttara_Phalguni","Hasta","Chitra",
    "Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva_Ashadha","Uttara_Ashadha","Shravana","Dhanishta",
    "Shatabhisha","Purva_Bhadrapada","Uttara_Bhadrapada","Revati"
]


def nak_from_sid_lon(sid):
    idx = int(sid // (360/27))
    return NAKSHATRAS[idx]


# --------------------------
# FAST PLANETS
# --------------------------
def detect_fast(planets):
    out = []
    for p in ["Mercury", "Venus", "Mars"]:
        if p in planets:
            out.append(p.lower())
    return out


# --------------------------
# HOUSE MAP
# --------------------------
def build_house_map(moon_rashi):
    rashis = [
        "aries","taurus","gemini","cancer","leo","virgo",
        "libra","scorpio","sagittarius","capricorn","aquarius","pisces"
    ]

    base = rashis.index(moon_rashi.lower()) + 1
    m = {}
    for idx, r in enumerate(rashis):
        m[r] = ((idx + 1) - base) % 12 + 1
    return m


# --------------------------
# TODAY → Take from LIVE API
# --------------------------
TRANSIT_API = "https://jyotishasha-backend.onrender.com/api/transit/current"
PANCHANG_API = "https://jyotishasha-backend.onrender.com/api/panchang"


def get_paksha():
    try:
        r = requests.get(PANCHANG_API)
        return r.json()["selected_date"]["tithi"]["paksha"]
    except:
        return "Shukla"


# --------------------------
# TOMORROW Swiss calculation
# --------------------------
def swiss_transit_for_date(dt_ist):
    jd = _to_julday_utc(dt_ist)
    ay = swe.get_ayanamsa_ut(jd)

    planets = {}

    for pid, name in PLANET_IDS.items():
        res, _ = swe.calc_ut(jd, pid)
        lon = res[0]
        sid = (lon - ay) % 360

        planets[name] = {
            "rashi": _rashi_from_sidereal_lon(sid),
            "degree": round(sid % 30, 2),
            "sidereal": sid
        }

    # Rahu / Ketu
    rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
    ketu_sid = (rahu_sid + 180) % 360

    planets["Rahu"] = {
        "rashi": _rashi_from_sidereal_lon(rahu_sid),
        "degree": round(rahu_sid % 30, 2),
        "sidereal": rahu_sid
    }
    planets["Ketu"] = {
        "rashi": _rashi_from_sidereal_lon(ketu_sid),
        "degree": round(ketu_sid % 30, 2),
        "sidereal": ketu_sid
    }

    return planets


# --------------------------
# BUILD PROFILE
# --------------------------
def build_profile(lagna, moon_rashi, nak, moon_house, paksha, fast_planet):
    return {
        "moon_rashi": moon_rashi,
        "nakshatra": nak,
        "moon_house": moon_house,
        "fast_planet": fast_planet,
        "paksha": paksha
    }


# ==========================
#       TODAY ROUTE
# ==========================
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def today():
    try:
        body = request.get_json()
        lagna = body.get("lagna", "").lower()

        if not lagna:
            return jsonify({"error": "Missing lagna"}), 400

        # 1 → Get transit from API
        r = requests.get(TRANSIT_API)
        api = r.json()["positions"]

        moon = api["Moon"]

        # API gives sidereal??
        # NO → Calculate manually
        # → Use degree + rashi to reconstruct sidereal
        r_index = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
                   "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"].index(moon["rashi"])
        sid = (r_index * 30) + moon["degree"]

        nak = nak_from_sid_lon(sid)

        house_map = build_house_map(moon["rashi"])
        moon_house = house_map[lagna]

        paksha = get_paksha()
        fast = detect_fast(api)

        profile = build_profile(
            lagna,
            moon["rashi"],
            nak,
            moon_house,
            paksha,
            fast[0] if fast else None
        )

        out = generate_daily_horoscope(profile)
        out["day"] = "today"
        return jsonify(out), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================
#     TOMORROW ROUTE
# ==========================
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def tomorrow():
    try:
        body = request.get_json()
        lagna = body.get("lagna", "").lower()

        if not lagna:
            return jsonify({"error": "Missing lagna"}), 400

        dt = datetime.datetime.now(pytz.timezone("Asia/Kolkata")) + datetime.timedelta(days=1)

        swiss = swiss_transit_for_date(dt)
        moon = swiss["Moon"]

        nak = nak_from_sid_lon(moon["sidereal"])

        house_map = build_house_map(moon["rashi"])
        moon_house = house_map[lagna]

        paksha = get_paksha()
        fast = detect_fast(swiss)

        profile = build_profile(
            lagna,
            moon["rashi"],
            nak,
            moon_house,
            paksha,
            fast[0] if fast else None
        )

        out = generate_daily_horoscope(profile)
        out["day"] = "tomorrow"
        return jsonify(out), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
