# Path: modules/love/moon_only.py
from __future__ import annotations
from typing import Dict
from datetime import datetime, timedelta
import swisseph as swe


def derive_moon_from_dob(dob: str) -> Dict[str, str]:
    """
    DOB-only Moon derivation (Lahiri)
    Time assumed: 12:00 noon IST to reduce edge errors
    """

    year, month, day = map(int, dob.split("-"))
    local_dt = datetime(year, month, day, 12, 0)
    utc_dt = local_dt - timedelta(hours=5, minutes=30)

    jd_ut = swe.julday(
        utc_dt.year, utc_dt.month, utc_dt.day,
        utc_dt.hour + utc_dt.minute / 60
    )

    swe.set_sid_mode(swe.SIDM_LAHIRI)

    moon_long = swe.calc_ut(jd_ut, swe.MOON)[0][0]
    ayanamsa = swe.get_ayanamsa_ut(jd_ut)
    sid_long = (moon_long - ayanamsa) % 360

    rashi_index = int(sid_long // 30)
    rashis = [
        "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
        "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
    ]

    nak_size = 13 + 1/3
    nak_index = int(sid_long // nak_size)
    nakshatras = [
        "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra",
        "Punarvasu","Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni",
        "Hasta","Chitra","Swati","Vishakha","Anuradha","Jyeshtha",
        "Mula","Purva Ashadha","Uttara Ashadha","Shravana","Dhanishta","Shatabhisha",
        "Purva Bhadrapada","Uttara Bhadrapada","Revati"
    ]

    return {
        "rashi": rashis[rashi_index],
        "nakshatra": nakshatras[nak_index],
        "degree": round(sid_long % 30, 2),
    }
