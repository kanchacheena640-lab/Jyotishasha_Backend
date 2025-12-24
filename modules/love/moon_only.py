# Path: modules/love/moon_only.py

from datetime import datetime

SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

def derive_moon_from_dob(dob: str) -> dict:
    """
    DOB-only Moon approximation (LOCKED for fallback use)
    No lat/lng, no timezone, no swe
    """
    date = datetime.strptime(dob, "%Y-%m-%d")

    # Simple astronomical approximation (industry-accepted fallback)
    days = (date - datetime(1900, 1, 1)).days
    moon_deg = (days * 13.176396) % 360

    sign = SIGNS[int(moon_deg // 30)]

    return {
        "rashi": sign,
        "degree": moon_deg % 30,
        "nakshatra": None
    }
