# ============================================================
# File: services/moon_calc.py
# Purpose: Moonrise and Moonset calculation service
# Used in: Panchang API, Vrat logic, Event alerts
# ============================================================

import swisseph as swe
from datetime import datetime, timedelta

# ------------------------------------------------------------
# SET EPHEMERIS PATH (Ensure ./ephe folder exists)
# ------------------------------------------------------------
swe.set_ephe_path("./ephe")


def _convert_jd_to_local_datetime(jd, tz_offset):
    """Convert Julian Day to localized datetime."""
    y, mo, d, ut = swe.revjul(jd)

    hour = int(ut)
    minute = int((ut - hour) * 60)
    second = int((((ut - hour) * 60) - minute) * 60)

    utc_dt = datetime(y, mo, d, hour, minute, second)
    return utc_dt + timedelta(hours=tz_offset)


def get_moon_rise_set(date_obj, lat, lon, tz_offset=5.5):
    """
    Production-ready Moonrise + Moonset calculator.

    Args:
        date_obj (datetime.date or datetime)
        lat (float)
        lon (float)
        tz_offset (float) default IST = 5.5

    Returns:
        dict:
        {
            "moonrise": "05:57 AM" or None,
            "moonset": "05:48 PM" or None
        }
    """

    try:
        jd_ut = swe.julday(date_obj.year, date_obj.month, date_obj.day, 0.0) - (tz_offset / 24.0)

        geopos = (lon, lat, 0)

        result = {
            "moonrise": None,
            "moonset": None
        }

        # 🌙 MOONRISE
        retflag_rise, tret_rise = swe.rise_trans(
            jd_ut,
            swe.MOON,
            swe.CALC_RISE,
            geopos,
            1013.25,
            15
        )

        if retflag_rise >= 0:
            rise_dt = _convert_jd_to_local_datetime(
                tret_rise[0], tz_offset
            )
            result["moonrise"] = rise_dt.strftime("%I:%M %p")

        # 🌙 MOONSET
        retflag_set, tret_set = swe.rise_trans(
            jd_ut,
            swe.MOON,
            swe.CALC_SET,
            geopos,
            1013.25,
            15
        )

        if retflag_set >= 0:
            set_dt = _convert_jd_to_local_datetime(
                tret_set[0], tz_offset
            )
            result["moonset"] = set_dt.strftime("%I:%M %p")

        return result

    except Exception:
        return {
            "moonrise": None,
            "moonset": None
        }
