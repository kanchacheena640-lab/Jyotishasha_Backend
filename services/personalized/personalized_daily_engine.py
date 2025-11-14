# personalized_daily_engine.py
# (Transit Engine for Personalized Daily Horoscope)

from smart_transit_engine import get_planet_position_on
from services.panchang_engine import calculate_panchang
import datetime

# ---------------------------------------
# Constants
# ---------------------------------------
RASHIS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira",
    "Ardra","Punarvasu","Pushya","Ashlesha","Magha",
    "Purva_Phalguni","Uttara_Phalguni","Hasta","Chitra",
    "Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva_Ashadha","Uttara_Ashadha","Shravana","Dhanishta",
    "Shatabhisha","Purva_Bhadrapada","Uttara_Bhadrapada","Revati"
]

PLANETS_FOR_ASPECT = ["Sun","Mercury","Venus","Mars","Jupiter","Saturn","Rahu","Ketu"]


# ---------------------------------------
# Nakshatra finder using 0–360 degree logic
# ---------------------------------------
def get_nakshatra(rashi_idx, degree_in_sign):
    """
    rashi_idx = 0–11
    degree_in_sign = 0–30
    """
    sidereal_lon = (rashi_idx * 30) + degree_in_sign
    idx = int(sidereal_lon // (360 / 27))
    return NAKSHATRAS[idx]


# ---------------------------------------
# House calculation
# ---------------------------------------
def get_house(lagna: str, planet_rashi: str):
    base = RASHIS.index(lagna.capitalize())
    target = RASHIS.index(planet_rashi.capitalize())
    return (target - base) % 12 + 1


# ---------------------------------------
# Conjunction check
# ---------------------------------------
def has_conjunction(r1, r2):
    return r1 == r2


# ---------------------------------------
# Full Vedic Aspect Logic
# ---------------------------------------
def planet_aspects_moon(planet_name, planet_house, moon_house):

    delta = (moon_house - planet_house) % 12

    if delta == 0:
        return False  # conjunction not aspect

    name = planet_name.lower()

    # sab planets → 7th aspect
    aspect_offsets = {6}

    # special aspects
    if name == "mars":
        aspect_offsets.update({3, 7})
    elif name == "jupiter":
        aspect_offsets.update({4, 8})
    elif name == "saturn":
        aspect_offsets.update({2, 9})
    elif name in ("rahu","ketu"):
        aspect_offsets.update({4, 8})

    return delta in aspect_offsets


# ---------------------------------------
# Build Today Positions
# ---------------------------------------
def get_today_positions(date_str, lagna, lat, lon):
    out = {}

    # -------------------------
    # MOON
    # -------------------------
    moon = get_planet_position_on(date_str, "Moon")
    moon_rashi = moon["rashi"]
    moon_deg = moon["degree"]
    moon_house = get_house(lagna, moon_rashi)

    rashi_idx = RASHIS.index(moon_rashi)
    nak = get_nakshatra(rashi_idx, moon_deg)

    out["moon"] = {
        "rashi": moon_rashi,
        "degree": moon_deg,
        "nakshatra": nak,
        "motion": moon["motion"],
        "house": moon_house
    }

    # -------------------------
    # ALL OTHER PLANETS
    # -------------------------
    planets_out = {}

    for p in PLANETS_FOR_ASPECT:
        pos = get_planet_position_on(date_str, p)

        r = pos["rashi"]
        h = get_house(lagna, r)

        planets_out[p.lower()] = {
            "rashi": r,
            "degree": pos["degree"],
            "motion": pos["motion"],
            "house": h,
            "conjunction_with_moon": has_conjunction(r, moon_rashi),
            "aspect_on_moon": planet_aspects_moon(p, h, moon_house)
        }

    out["planets"] = planets_out

    # -------------------------
    # PANCHANG PAKSHA
    # -------------------------
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    panchang = calculate_panchang(date_obj, lat, lon)
    out["paksha"] = panchang["tithi"]["paksha"]

    return out


# ---------------------------------------
# Tomorrow
# ---------------------------------------
def get_tomorrow_positions(lagna, lat, lon):
    tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    return get_today_positions(tomorrow, lagna, lat, lon)


# ---------------------------------------
# MASTER ENGINE
# ---------------------------------------
def build_personalized_daily_profile(lagna, lat=28.6, lon=77.2):
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    return {
        "today": get_today_positions(today, lagna, lat, lon),
        "tomorrow": get_tomorrow_positions(lagna, lat, lon)
    }
