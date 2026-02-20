# services/lunar_month_engine.py

from datetime import datetime, timedelta
import swisseph as swe
from services.astro_core import _tithi_number_at
from services.astro_core import sidereal_longitudes

FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwin", "Kartik",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]


def _sun_rashi_index(dt_ist):
    sun, _ = sidereal_longitudes(dt_ist)
    return int(sun // 30) % 12


def _find_last_amavasya(dt_ist):
    """
    Find exact END boundary of last Amavasya (tithi 30).
    Uses backward bracket + binary refine.
    """

    step = timedelta(hours=3)
    t1 = dt_ist
    t0 = t1 - step

    # --- Find bracket where tithi changes to 30 ---
    for _ in range(200):  # safety ~25 days
        if _tithi_number_at(t0) == 30 and _tithi_number_at(t1) != 30:
            break
        t1 = t0
        t0 = t0 - step
    else:
        return dt_ist  # fallback safety

    # --- Now refine END boundary of Amavasya ---
    for _ in range(30):
        mid = t0 + (t1 - t0) / 2
        if _tithi_number_at(mid) == 30:
            t0 = mid
        else:
            t1 = mid

    return t1.replace(second=0, microsecond=0)


def get_lunar_month(dt_ist):
    """
    True Amanta lunar month calculation.
    """

    last_amavasya = _find_last_amavasya(dt_ist)

    # Sun rashi at moment AFTER Amavasya
    rashi_index = _sun_rashi_index(last_amavasya)

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
