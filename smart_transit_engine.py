# smart_transit_engine.py

import swisseph as swe
from datetime import datetime, timedelta
import pytz

from lahiri_mode import ensure_lahiri_mode

swe.set_sid_mode(swe.SIDM_LAHIRI)
# U4C.2B -- this import-time call alone is NOT sufficient (U4C.2A
# proved swe.set_sid_mode() is thread-local); get_planet_position_on()
# below -- the only function in this file that actually calls
# swe.calc_ut()/swe.get_ayanamsa_ut() -- now calls ensure_lahiri_mode()
# itself, immediately before use, so it is correct on any thread
# regardless of whether this import has ever run on that thread.

RASHIS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

PLANET_IDS = {
    "Sun": 0, "Moon": 1, "Mercury": 2, "Venus": 3,
    "Mars": 4, "Jupiter": 5, "Saturn": 6,
    "Rahu": swe.MEAN_NODE, "Ketu": "ketu"
}

def get_planet_position_on(date_str: str, planet_name: str) -> dict:
    if planet_name not in PLANET_IDS:
        raise ValueError("Invalid planet name")

    ensure_lahiri_mode()  # U4C.2B -- must be safe on a completely fresh thread; never assumes transit_engine ran first

    # Convert date to IST datetime
    dt = datetime.strptime(date_str, "%Y-%m-%d") if len(date_str) == 10 else datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    dt_ist = pytz.timezone("Asia/Kolkata").localize(dt)
    dt_utc = dt_ist.astimezone(pytz.UTC)
    jd = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour + dt_utc.minute / 60.0)

    ayanamsa = swe.get_ayanamsa_ut(jd)

    if planet_name == "Ketu":
        rahu = swe.calc_ut(jd, swe.MEAN_NODE)[0][0]
        lon = (rahu + 180) % 360
        speed = -1  # Always retro
    else:
        pid = PLANET_IDS[planet_name]
        res = swe.calc_ut(jd, pid)[0]
        lon = res[0]
        speed = res[3]

    sidereal_lon = (lon - ayanamsa) % 360
    rashi_index = int(sidereal_lon // 30)
    degree = round(sidereal_lon % 30, 2)

    return {
        "planet": planet_name,
        "date": date_str,
        "rashi": RASHIS[rashi_index],
        "degree": degree,
        "motion": "Retrograde" if speed < 0 else "Direct"
    }

# U4C.1 -- CONSOLIDATION. This file previously duplicated its own
# independent day-stepping ingress-detection algorithm here (same
# structure, same +1-day-late bug as transit_engine.py's own copy --
# see U4C.0's audit). Per U4C.1's explicit instruction not to leave two
# independently-maintained copies of the SAME corrected boundary
# algorithm, get_next_transits()/get_prev_transits() now delegate
# entirely to transit_engine._get_rashi_transits() -- the ONE canonical
# implementation (see transit_engine.py's own "U4C.1 -- CANONICAL
# INGRESS-BOUNDARY DETECTION" section). Nothing else in this file
# changes: get_planet_position_on() (current-position, date-only --
# what services/current_saturn_resolver.py and services/sadhesati_
# report_generator.py's OWN current-state read both call) and
# get_planet_in_rashi() are untouched, byte-for-byte, since neither one
# is part of the confirmed date-boundary-detection defect.
from transit_engine import _get_rashi_transits as _canonical_rashi_transits
from transit_engine import get_current_sign_residency as _canonical_current_residency

def get_next_transits(planet_name: str, count: int = 12) -> list:
    if planet_name not in PLANET_IDS:
        raise ValueError("Invalid planet")
    return _canonical_rashi_transits(planet_name, direction="forward", count=count)

def get_prev_transits(planet_name: str, count: int = 12) -> list:
    if planet_name not in PLANET_IDS:
        raise ValueError("Invalid planet")
    return _canonical_rashi_transits(planet_name, direction="backward", count=count)

# U4C.1A -- same delegation pattern as get_next_transits/get_prev_transits
# above: the CURRENT-residency primitive lives ONLY in transit_engine.py
# (see its own "U4C.1A" docstring); this is a thin, signature-preserving
# forwarder so services/sadhesati_report_generator.py can keep importing
# everything it needs from this one module, exactly as before.
def get_current_sign_residency(planet_name: str, as_of=None) -> dict:
    if planet_name not in PLANET_IDS:
        raise ValueError("Invalid planet")
    return _canonical_current_residency(planet_name, as_of=as_of)

def get_planet_in_rashi(rashi: str, planet: str = "Saturn", when="future") -> dict:
    transits = get_next_transits(planet) if when == "future" else get_prev_transits(planet)
    for t in transits:
        if t["to_rashi"] == rashi:
            return t
    return {
        "status": "Not found",
        "planet": planet,
        "rashi": rashi,
        "direction": when
    }
