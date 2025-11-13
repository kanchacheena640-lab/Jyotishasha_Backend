from flask import Blueprint, request, jsonify
import requests
import datetime
import pytz

from services.daily_horoscope_generator import generate_daily_horoscope


# -----------------------------------------------------
# BLUEPRINT
# -----------------------------------------------------
personalized_daily = Blueprint("personalized_daily", __name__)

TRANSIT_URL = "https://jyotishasha-backend.onrender.com/api/transits?days=1"
PANCHANG_URL = "https://jyotishasha-backend.onrender.com/api/panchang"


# -----------------------------------------------------
# Nakshatra List (index = floor(longitude / 13.3333))
# -----------------------------------------------------
NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira",
    "Ardra","Punarvasu","Pushya","Ashlesha","Magha",
    "Purva_Phalguni","Uttara_Phalguni","Hasta","Chitra",
    "Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva_Ashadha","Uttara_Ashadha","Shravana","Dhanishta",
    "Shatabhisha","Purva_Bhadrapada","Uttara_Bhadrapada",
    "Revati"
]

def calc_nakshatra_from_degree(deg):
    size = 360 / 27
    index = int(deg // size)
    return NAKSHATRAS[index]


# -----------------------------------------------------
# HOUSE MAP (lagna based)
# -----------------------------------------------------
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


# -----------------------------------------------------
# Fast Planet Detection (only Mercury/Venus/Mars)
# Using → position difference 3 houses or conjunction
# -----------------------------------------------------
def detect_fast_planet(moon_house, planet_house_map):
    fast_list = ["mercury", "venus", "mars"]

    for p in fast_list:
        if p not in planet_house_map:
            continue

        ph = planet_house_map[p]

        diff = abs(ph - moon_house)

        # Conjunction (same house)
        if diff == 0:
            return p

        # 7th aspect (180-degree)
        if diff == 6:
            return p

        # Close influence
        if diff == 1 or diff == 2:
            return p

    return None


# -----------------------------------------------------
# CALL TRANSIT API
# -----------------------------------------------------
def fetch_transit():
    r = requests.get(TRANSIT_URL)
    return r.json()["transits"][0]   # always first day (today)


# -----------------------------------------------------
# CALL PANCHANG API
# -----------------------------------------------------
def fetch_panchang():
    r = requests.get(PANCHANG_URL)
    data = r.json()
    return data["selected_date"]["tithi"]["paksha"]


# -----------------------------------------------------
# PROCESS TRANSIT RESPONSE
# -----------------------------------------------------
def parse_transit(transit, lagna):
    moon = transit["positions"]["Moon"]

    moon_rashi = moon["rashi"]
    moon_deg = moon["degree"]
    nakshatra = calc_nakshatra_from_degree(moon_deg)

    house_map = build_house_map(moon_rashi)
    moon_house = house_map[lagna]

    # Build planet house map
    planet_house_map = {}
    for planet, info in transit["positions"].items():
        rashi = info["rashi"]
        if rashi:
            planet_house_map[planet.lower()] = house_map[rashi.lower()]

    fast_planet = detect_fast_planet(moon_house, planet_house_map)

    return {
        "moon_rashi": moon_rashi,
        "nakshatra": nakshatra,
        "moon_house": moon_house,
        "fast_planet": fast_planet
    }


# -----------------------------------------------------
# TODAY HOROSCOPE
# -----------------------------------------------------
@personalized_daily.route("/api/personalized/daily", methods=["POST"])
def get_today():
    try:
        data = request.get_json()
        if not data or "lagna" not in data:
            return jsonify({"error": "Missing lagna"}), 400

        lagna = data["lagna"].lower()

        transit = fetch_transit()
        parsed = parse_transit(transit, lagna)

        paksha = fetch_panchang()

        profile = {
            **parsed,
            "paksha": paksha
        }

        result = generate_daily_horoscope(profile)
        result["day"] = "today"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# -----------------------------------------------------
# TOMORROW HOROSCOPE
# -----------------------------------------------------
@personalized_daily.route("/api/personalized/tomorrow", methods=["POST"])
def get_tomorrow():
    try:
        data = request.get_json()
        if not data or "lagna" not in data:
            return jsonify({"error": "Missing lagna"}), 400

        lagna = data["lagna"].lower()

        # Tomorrow = days=2
        r = requests.get("https://jyotishasha-backend.onrender.com/api/transits?days=2")
        transit = r.json()["transits"][1]

        parsed = parse_transit(transit, lagna)

        paksha = fetch_panchang()

        profile = {
            **parsed,
            "paksha": paksha
        }

        result = generate_daily_horoscope(profile)
        result["day"] = "tomorrow"

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
