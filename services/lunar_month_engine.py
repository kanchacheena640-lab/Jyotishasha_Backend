# services/lunar_month_engine.py

from datetime import datetime
import swisseph as swe
from services.panchang_engine import _to_ut_julday

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwin", "Kartik",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]

FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH


def get_lunar_month(dt_ist):
    """
    Returns correct lunar month based on Sun's sidereal position
    at exact given IST datetime.
    """

    jd_ut = _to_ut_julday(dt_ist)
    sun_long = swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360

    month_index = int(sun_long // 30) % 12
    return HINDU_MONTHS[month_index]
