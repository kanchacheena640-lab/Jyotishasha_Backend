# personalized_daily_engine.py
# (Helper for Personalized Daily Horoscope)

from smart_transit_engine import get_planet_position_on
from services.panchang_engine import calculate_panchang
import datetime
import pytz

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


# ---------------------------------------
# Nakshatra from sidereal longitude
# ---------------------------------------
def get_nakshatra(sid_lon: float):
    idx = int(sid_lon // (360 / 27))
    return NAKSHATRAS[idx]


# ---------------------------------------
# House calculation
# ---------------------------------------
def get_house(lagna: str, planet_rashi: str):
    lagna = lagna.capitalize()
    planet_rashi = planet_rashi.capitalize()

    base = RASHIS.index(lagna)
    target = RASHIS.index(planet_rashi)

    house = (target - base) % 12 + 1
    return house


# ---------------------------------------
# Aspect check (Venus, Mercury, Mars)
# ---------------------------------------
def has_aspect(h1, h2):
    return (abs(h1 - h2) % 12) == 6    # 7th house distance


# ---------------------------------------
# Conjunction check
# ---------------------------------------
def has_conjunction(r1, r2):
    return r1 == r2


# ---------------------------------------
# FAST PLANET PICKER (aspect > conjunction)
# ---------------------------------------
def pick_fast_planet(planets):
    if planets["mercury"]["aspect_on_moon"] or planets["mercury"]["conjunction_with_moon"]:
        return "mercury"
    if planets["venus"]["aspect_on_moon"] or planets["venus"]["conjunction_with_moon"]:
        return "venus"
    if planets["mars"]["aspect_on_moon"] or planets["mars"]["conjunction_with_moon"]:
        return "mars"
    return None


# ---------------------------------------
# Build Today Data
# ---------------------------------------
def get_today_positions(date_str, lagna, lat, lon):
    out = {}

    # -------------------------
    # Moon today
    # -------------------------
    moon = get_planet_position_on(date_str, "Moon")
    moon_rashi = moon["rashi"]
    moon_house = get_house(lagna, moon_rashi)

    # Nakshatra from Moon degree
    deg = moon["degree"]
    sid_lon = deg + (RASHIS.index(moon_rashi) * 30)
    nak = get_nakshatra(sid_lon)

    out["moon"] = {
        "rashi": moon_rashi,
        "degree": moon["degree"],
        "nakshatra": nak,
        "motion": moon["motion"],
        "house": moon_house
    }

    # -------------------------
    # Mercury, Venus, Mars
    # -------------------------
    others = {}
    for p in ["Mercury", "Venus", "Mars"]:
        pos = get_planet_position_on(date_str, p)
        r = pos["rashi"]
        h = get_house(lagna, r)

        others[p.lower()] = {
            "rashi": r,
            "degree": pos["degree"],
            "motion": pos["motion"],
            "house": h,
            "conjunction_with_moon": has_conjunction(r, moon_rashi),
            "aspect_on_moon": has_aspect(h, moon_house)
        }

    out["planets"] = others

    # -------------------------
    # Paksha from Panchang Engine
    # -------------------------
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    panchang = calculate_panchang(date_obj, lat, lon)
    out["paksha"] = panchang["tithi"]["paksha"]

    # Fast planet final
    out["fast_planet"] = pick_fast_planet(others)

    return out


# ---------------------------------------
# Build Tomorrow Data
# ---------------------------------------
def get_tomorrow_positions(lagna, lat, lon):
    tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    return get_today_positions(tomorrow, lagna, lat, lon)


# ---------------------------------------
# MASTER FUNCTION (FINAL)
# ---------------------------------------
def build_personalized_daily_profile(lagna, lat=28.6, lon=77.2):
    """
    lat & lon → default Delhi (if user location not provided)
    """

    today = datetime.datetime.now().strftime("%Y-%m-%d")

    profile = {
        "today": get_today_positions(today, lagna, lat, lon),
        "tomorrow": get_tomorrow_positions(lagna, lat, lon)
    }

    return profile
