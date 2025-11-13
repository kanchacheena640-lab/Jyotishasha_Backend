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

# ------------------ NAKSHATRA LIST ---------------------
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
    return NAKSHATRAS[int(sidereal_lon // (360/27))]


# ------------------ FIXED HOUSE CALCULATION ---------------------
def compute_moon_house(lagna, moon_rashi):
    rashis = [
        "aries","taurus","gemini","cancer","leo","virgo",
        "libra","scorpio","sagittarius","capricorn","aquarius","pisces"
    ]

    moon_index = rashis.index(moon_rashi.lower()) + 1
    lagna_index = rashis.index(lagna.lower()) + 1

    # Correct house mapping
    return ((moon_index - lagna_index) % 12) + 1


# ------------------ Build Transit for ANY Date ------------------
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
            "degree": sid_lon % 30,
            "sidereal_longitude": sid_lon,
            "motion": "Retrograde" if speed < 0 else "Direct",
        }

    rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
    ketu_sid = (rahu_sid + 180) % 360

    out["Rahu"] = {"rashi": _rashi_from_sidereal_lon(rahu_sid), "sidereal_longitude": rahu_sid}
    out["Ketu"] = {"rashi": _rashi_from_sidereal_lon(ketu_sid), "sidereal_longitude": ketu_sid}

    return out


# ------------------ TODAY ------------------
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def get_daily():
    try:
        data = request.get_json()
        lagna = data.get("lagna", "").lower()

        today_raw = get_current_positions()
        moon_raw = today_raw["positions"]["Moon"]

        # Moon longitude (we reconstruct)
        rashi_index = {
            "aries":0,"taurus":1,"gemini":2,"cancer":3,"leo":4,"virgo":5,
            "libra":6,"scorpio":7,"sagittarius":8,"capricorn":9,"aquarius":10,"pisces":11
        }[moon_raw["rashi"].lower()]

        sidereal_lon = (rashi_index * 30) + moon_raw["degree"]
        moon_nakshatra = get_nakshatra_from_longitude(sidereal_lon)

        moon_house = compute_moon_house(lagna, moon_raw["rashi"])

        profile = {
            "moon_rashi": moon_raw["rashi"],
            "nakshatra": moon_nakshatra,
            "moon_house": moon_house,
            "fast_planet": None,
            "paksha": "Shukla",
        }

        out = generate_daily_horoscope(profile)
        out["day"] = "today"
        return jsonify(out), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ TOMORROW ------------------
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def get_tomorrow():
    try:
        data = request.get_json()
        lagna = data.get("lagna", "").lower()

        tomo_ist = datetime.datetime.now(pytz.timezone("Asia/Kolkata")) + datetime.timedelta(days=1)
        tomo = build_transit_for_date(tomo_ist)
        moon = tomo["Moon"]

        moon_nakshatra = get_nakshatra_from_longitude(moon["sidereal_longitude"])
        moon_house = compute_moon_house(lagna, moon["rashi"])

        profile = {
            "moon_rashi": moon["rashi"],
            "nakshatra": moon_nakshatra,
            "moon_house": moon_house,
            "fast_planet": None,
            "paksha": "Shukla",
        }

        out = generate_daily_horoscope(profile)
        out["day"] = "tomorrow"
        return jsonify(out), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
