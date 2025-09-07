# smart_transit_engine.py

import swisseph as swe
from datetime import datetime, timedelta
import pytz

swe.set_sid_mode(swe.SIDM_LAHIRI)

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

def get_next_transits(planet_name: str, count: int = 12) -> list:
    return _get_rashi_transits(planet_name, direction="forward", count=count)

def get_prev_transits(planet_name: str, count: int = 12) -> list:
    return _get_rashi_transits(planet_name, direction="backward", count=count)

def _get_rashi_transits(planet_name: str, direction="forward", count=12) -> list:
    if planet_name not in PLANET_IDS:
        raise ValueError("Invalid planet")

    ist = pytz.timezone("Asia/Kolkata")
    today = datetime.now(ist).replace(hour=0, minute=0, second=0, microsecond=0)
    day = today + timedelta(days=1) if direction == "forward" else today - timedelta(days=1)
    end_cap = today + timedelta(days=365*40) if direction == "forward" else today - timedelta(days=365*40)

    def get_rashi_on(d: datetime):
        pos = get_planet_position_on(d.strftime("%Y-%m-%d"), planet_name)
        return pos["rashi"]

    def get_motion_on(d: datetime):
        pos = get_planet_position_on(d.strftime("%Y-%m-%d"), planet_name)
        return pos["motion"]

    prev_rashi = get_rashi_on(today)
    events = []

    while ((direction == "forward" and day <= end_cap) or (direction == "backward" and day >= end_cap)) and len(events) < count:
        r = get_rashi_on(day)
        if r != prev_rashi:
            motion = get_motion_on(day)
            events.append({
                "planet": planet_name,
                "from_rashi": prev_rashi,
                "to_rashi": r,
                "entering_date": day.strftime("%Y-%m-%d"),
                "motion": motion
            })
            prev_rashi = r
        day += timedelta(days=1) if direction == "forward" else timedelta(days=-1)

    # Add exit dates
    for i in range(len(events)):
        probe_day = datetime.strptime(events[i]["entering_date"], "%Y-%m-%d") + timedelta(days=1)
        while True:
            r_now = get_rashi_on(probe_day)
            if r_now != events[i]["to_rashi"]:
                events[i]["exit_date"] = (probe_day - timedelta(days=1)).strftime("%Y-%m-%d")
                break
            probe_day += timedelta(days=1)

    return events

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
