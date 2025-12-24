# Path: modules/love/moon_only.py

from datetime import datetime

SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu",
    "Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni","Hasta",
    "Chitra","Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva Ashadha","Uttara Ashadha","Shravana","Dhanishta","Shatabhisha",
    "Purva Bhadrapada","Uttara Bhadrapada","Revati"
]

NAK_LEN = 360 / 27  # 13.333...

def derive_moon_from_dob(dob: str) -> dict:
    """
    DOB-only Moon approximation (LOCKED for fallback use)
    No lat/lng, no timezone, no swe
    """

    date = datetime.strptime(dob, "%Y-%m-%d")

    # Astronomical approximation
    days = (date - datetime(1900, 1, 1)).days
    moon_deg = (days * 13.176396) % 360

    sign = SIGNS[int(moon_deg // 30)]
    nakshatra = NAKSHATRAS[int(moon_deg // NAK_LEN)]

    return {
        "rashi": sign,
        "degree": moon_deg % 30,
        "nakshatra": nakshatra,
        "approx": True
    }
