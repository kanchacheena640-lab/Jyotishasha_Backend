from datetime import datetime, timedelta
import swisseph as swe

# Swiss setup
swe.set_sid_mode(swe.SIDM_LAHIRI)
FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH


# -------------------------------------------------
# Time Conversion
# -------------------------------------------------
def _to_ut_julday(dt_ist):
    utc = dt_ist - timedelta(hours=5, minutes=30)
    return swe.julday(
        utc.year,
        utc.month,
        utc.day,
        utc.hour + utc.minute / 60 + utc.second / 3600,
    )


# -------------------------------------------------
# Core Longitudes
# -------------------------------------------------
def _sidereal_longitudes(dt_ist):
    jd_ut = _to_ut_julday(dt_ist)
    sun = swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360
    moon = swe.calc_ut(jd_ut, swe.MOON, FLAGS)[0][0] % 360
    return sun, moon


# -------------------------------------------------
# Panchang Mathematical Limbs
# -------------------------------------------------
def _tithi_from_longitudes(sun, moon):
    diff = (moon - sun) % 360
    num = int(diff // 12) + 1
    paksha = "Shukla" if num <= 15 else "Krishna"
    return num, paksha


def _nakshatra_from_moon(moon):
    span = 360.0 / 27.0
    idx = int(moon // span)
    pada = int(((moon % span) // (span / 4.0)) + 1)
    return idx + 1, pada


def _yoga_from_lons(sun, moon):
    total = (sun + moon) % 360
    idx = int(total // (360 / 27))
    return idx + 1


def _karan_from_tithi(tithi_num):
    slot = (tithi_num * 2) - 1
    return slot


# -------------------------------------------------
# Direct Queries (Used by Higher Engines)
# -------------------------------------------------
def _tithi_number_at(dt_ist):
    sun, moon = _sidereal_longitudes(dt_ist)
    diff = (moon - sun) % 360
    return int(diff // 12) + 1


def _karan_slot_at(dt_ist):
    sun, moon = _sidereal_longitudes(dt_ist)
    diff = (moon - sun) % 360
    return int(diff // 6) + 1

def sidereal_longitudes(dt_ist):
    jd_ut = _to_ut_julday(dt_ist)
    sun = swe.calc_ut(jd_ut, swe.SUN, FLAGS)[0][0] % 360
    moon = swe.calc_ut(jd_ut, swe.MOON, FLAGS)[0][0] % 360
    return sun, moon