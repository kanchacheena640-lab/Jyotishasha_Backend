# services/lunar_month_engine.py

from datetime import datetime, timedelta
import swisseph as swe
from services.panchang_engine import _to_ut_julday, _tithi_number_at

FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwin", "Kartik",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]


def _sun_rashi_index(dt_ist):
    jd_ut = _to_ut_julday(dt_ist)
    sun_long = swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360
    return int(sun_long // 30) % 12


def _find_last_amavasya(dt_ist):
    """
    Walk backward to find last Amavasya moment.
    """
    step = timedelta(hours=6)
    t = dt_ist

    while True:
        if _tithi_number_at(t) == 30:
            # move forward until tithi changes from 30 → exact boundary
            forward = t
            while _tithi_number_at(forward) == 30:
                forward += timedelta(minutes=30)
            return forward
        t -= step


def get_lunar_month(dt_ist):
    """
    True Amanta lunar month calculation.
    """

    last_amavasya = _find_last_amavasya(dt_ist)

    # Sun rashi at moment AFTER Amavasya
    rashi_index = _sun_rashi_index(last_amavasya + timedelta(hours=1))

    # Month name is next rashi in traditional mapping
    month_index = (rashi_index + 1) % 12

    return HINDU_MONTHS[month_index]


def get_shivratri_type(dt_ist):
    """
    Returns:
    None
    masik_shivratri
    maha_shivratri
    """

    tithi_number = _tithi_number_at(dt_ist)

    if tithi_number != 29:
        return None, None

    lunar_month = get_lunar_month(dt_ist)

    if lunar_month == "Magha":
        return "maha_shivratri", lunar_month

    return "masik_shivratri", lunar_month
