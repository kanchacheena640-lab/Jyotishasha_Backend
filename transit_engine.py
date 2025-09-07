# transit_engine_v3.py
# Current + next 12 rashi transits with motion, IST based

import swisseph as swe
import datetime
from datetime import timedelta
import pytz

# Swiss Ephemeris setup
swe.set_ephe_path('/usr/share/ephe')
swe.set_sid_mode(swe.SIDM_LAHIRI)

RASHIS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

PLANET_IDS = {
    0:'Sun', 1:'Moon', 2:'Mercury', 3:'Venus', 4:'Mars',
    5:'Jupiter', 6:'Saturn', swe.MEAN_NODE:'Rahu'
}
NAME_TO_ID = {v:k for k,v in PLANET_IDS.items()}

def _ist_now():
    return datetime.datetime.now(pytz.timezone("Asia/Kolkata"))

def _to_julday_utc(dt_any_tz: datetime.datetime) -> float:
    dt_utc = dt_any_tz.astimezone(pytz.UTC)
    hour = dt_utc.hour + dt_utc.minute/60.0 + dt_utc.second/3600.0
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)

def _rashi_from_sidereal_lon(sid_lon: float) -> str:
    return RASHIS[int(sid_lon // 30) % 12]

def get_current_positions():
    now_ist = _ist_now()
    jd = _to_julday_utc(now_ist)
    ay = swe.get_ayanamsa_ut(jd)

    out = {}
    for pid, name in PLANET_IDS.items():
        res, _ = swe.calc_ut(jd, pid)
        lon = res[0]
        speed = res[3] if len(res) > 3 else 0.0
        sid_lon = (lon - ay) % 360
        out[name] = {
            "rashi": _rashi_from_sidereal_lon(sid_lon),
            "degree": round(sid_lon % 30, 2),
            "motion": "Retrograde" if speed < 0 else "Direct"
        }

    rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
    ketu_sid = (rahu_sid + 180.0) % 360
    out["Ketu"] = {
        "rashi": _rashi_from_sidereal_lon(ketu_sid),
        "degree": round(ketu_sid % 30, 2),
        "motion": "Retrograde"
    }

    return {
        "timestamp_ist": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "positions": out
    }

def _planet_rashi_on_day(planet_name: str, day_ist: datetime.datetime) -> str:
    jd = _to_julday_utc(day_ist)
    ay = swe.get_ayanamsa_ut(jd)
    if planet_name == "Ketu":
        rahu_sid = (swe.calc_ut(jd, swe.MEAN_NODE)[0][0] - ay) % 360
        sid = (rahu_sid + 180.0) % 360
    else:
        pid = swe.MEAN_NODE if planet_name == "Rahu" else NAME_TO_ID[planet_name]
        sid = (swe.calc_ut(jd, pid)[0][0] - ay) % 360
    return _rashi_from_sidereal_lon(sid)

def _planet_motion_on_day(planet_name: str, day_ist: datetime.datetime) -> str:
    jd = _to_julday_utc(day_ist)
    pid = swe.MEAN_NODE if planet_name in ("Rahu", "Ketu") else NAME_TO_ID[planet_name]
    speed = swe.calc_ut(jd, pid)[0][3]
    return "Retrograde" if speed < 0 else "Direct"

def get_next_12_rashi_segments(planet_name: str):
    if planet_name not in NAME_TO_ID and planet_name not in ("Rahu","Ketu"):
        raise ValueError(f"Invalid planet: {planet_name}")

    ist = pytz.timezone("Asia/Kolkata")
    start = _ist_now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_cap = start + timedelta(days=365*40)

    current_rashi = _planet_rashi_on_day(planet_name, start)

    events = []
    prev_rashi = current_rashi
    day = start + timedelta(days=1)
    while day <= end_cap and len(events) < 12:
        r = _planet_rashi_on_day(planet_name, day)
        if r != prev_rashi:
            motion = _planet_motion_on_day(planet_name, day)
            events.append({
                "planet": planet_name,
                "from_rashi": prev_rashi,
                "to_rashi": r,
                "entering_date": day.strftime("%Y-%m-%d"),
                "motion": motion
            })
            prev_rashi = r
        day += timedelta(days=1)

    for i in range(len(events)):
        if i < len(events) - 1:
            nd = ist.localize(datetime.datetime.strptime(events[i+1]["entering_date"], "%Y-%m-%d"))
            exit_dt = nd - timedelta(days=1)
        else:
            probe = ist.localize(datetime.datetime.strptime(events[i]["entering_date"], "%Y-%m-%d")) + timedelta(days=1)
            while probe <= end_cap:
                r_now = _planet_rashi_on_day(planet_name, probe)
                if r_now != events[i]["to_rashi"]:
                    exit_dt = probe - timedelta(days=1)
                    break
                probe += timedelta(days=1)
        events[i]["exit_date"] = exit_dt.strftime("%Y-%m-%d")

    return events

def get_all_planets_next_12():
    planets = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Rahu","Ketu"]
    return {p: get_next_12_rashi_segments(p) for p in planets}
