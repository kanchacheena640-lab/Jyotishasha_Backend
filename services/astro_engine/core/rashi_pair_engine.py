from datetime import datetime
from services.astro_engine.data_provider.ephemeris_provider import (
    get_planet_rashi,
    get_planet_longitude
)


# -----------------------------
# SAME RASHI CHECK
# -----------------------------

def is_same_rashi(planet1: str, planet2: str, dt: datetime) -> bool:
    r1 = get_planet_rashi(planet1, dt)
    r2 = get_planet_rashi(planet2, dt)
    return r1 == r2


# -----------------------------
# FULL STATUS (debug / UI use)
# -----------------------------

def get_pair_status(planet1: str, planet2: str, dt: datetime):
    r1 = get_planet_rashi(planet1, dt)
    r2 = get_planet_rashi(planet2, dt)

    lon1 = get_planet_longitude(planet1, dt)
    lon2 = get_planet_longitude(planet2, dt)

    return {
        "planet1": planet1,
        "planet2": planet2,
        "rashi1": r1,
        "rashi2": r2,
        "same_rashi": r1 == r2,
        "degree1": round(lon1 % 30, 2),
        "degree2": round(lon2 % 30, 2)
    }


# -----------------------------
# TEST
# -----------------------------

if __name__ == "__main__":
    from services.astro_engine.data_provider.ephemeris_provider import get_current_datetime_ist

    now = get_current_datetime_ist()

    result = get_pair_status("Jupiter", "Saturn", now)

    print("\nPair Status:\n")
    for k, v in result.items():
        print(f"{k}: {v}")