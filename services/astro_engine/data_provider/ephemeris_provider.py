import swisseph as swe
import datetime
import pytz

# -----------------------------
# CONFIG
# -----------------------------

# 👉 IMPORTANT: apne ephemeris path set karo
swe.set_ephe_path('./ephe')

# Lahiri Ayanamsa (Vedic)
swe.set_sid_mode(swe.SIDM_LAHIRI)

IST = pytz.timezone("Asia/Kolkata")

RASHIS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

PLANETS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE
}


# -----------------------------
# INTERNAL UTILS
# -----------------------------

def _to_julian_day(dt: datetime.datetime) -> float:
    """Convert datetime to Julian Day (UTC)"""
    dt_utc = dt.astimezone(pytz.UTC)
    hour = dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)


def _get_ayanamsa(jd: float) -> float:
    return swe.get_ayanamsa_ut(jd)


# -----------------------------
# CORE FUNCTIONS
# -----------------------------

def get_planet_longitude(planet: str, dt: datetime.datetime) -> float:
    """
    Returns sidereal longitude (0–360°)
    """
    jd = _to_julian_day(dt)
    ay = _get_ayanamsa(jd)

    if planet == "Ketu":
        rahu_lon = swe.calc_ut(jd, swe.MEAN_NODE)[0][0]
        sid = (rahu_lon - ay + 180) % 360
    else:
        pid = PLANETS[planet]
        lon = swe.calc_ut(jd, pid)[0][0]
        sid = (lon - ay) % 360

    return sid


def get_planet_rashi(planet: str, dt: datetime.datetime) -> str:
    """
    Returns rashi name
    """
    lon = get_planet_longitude(planet, dt)
    return RASHIS[int(lon // 30)]


def get_planet_degree(planet: str, dt: datetime.datetime) -> float:
    """
    Degree within rashi (0–30)
    """
    lon = get_planet_longitude(planet, dt)
    return round(lon % 30, 2)


def get_current_datetime_ist() -> datetime.datetime:
    """
    Current IST datetime
    """
    return datetime.datetime.now(IST)

if __name__ == "__main__":
    now = get_current_datetime_ist()

    print("Jupiter:", get_planet_rashi("Jupiter", now))
    print("Saturn:", get_planet_rashi("Saturn", now))