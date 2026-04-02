from datetime import timedelta
from services.astro_engine.core.rashi_pair_engine import is_same_rashi
from services.astro_engine.data_provider.ephemeris_provider import (
    get_planet_rashi,
    get_current_datetime_ist
)
from services.astro_engine.core.refine_engine import (
    refine_same_rashi_entry,
    refine_same_rashi_exit
)


# -----------------------------
# LAST WINDOW (past) - FIXED
# -----------------------------

def find_last_same_rashi_window(planet1, planet2, start_date):
    date = start_date
    step = -timedelta(days=1)

    # 🔹 Step 1: find ANY TRUE going backward
    for _ in range(10000):
        date += step
        if is_same_rashi(planet1, planet2, date):
            break
    else:
        return None, None

    # 🔹 Step 2: go backward to find FIRST FALSE (start boundary)
    while is_same_rashi(planet1, planet2, date):
        date += step

    # 🔹 Step 3: move forward 1 step → actual entry zone
    date -= step

    # 🔹 refine entry
    entry = refine_same_rashi_entry(planet1, planet2, date)


    # 🔹 track full window forward from entry
    temp = entry
    last_valid = temp

    while is_same_rashi(planet1, planet2, temp):
        last_valid = temp
        temp += timedelta(hours=6)  # 🔥 high precision step

    exit_time = refine_same_rashi_exit(planet1, planet2, last_valid)

    return entry, exit_time


# -----------------------------
# NEXT WINDOW (future) - FIXED
# -----------------------------

def find_next_same_rashi_window(planet1, planet2, start_date):
    date = start_date
    step = timedelta(days=1)

    # Step 1: find ANY TRUE forward
    for _ in range(10000):
        date += step
        if is_same_rashi(planet1, planet2, date):
            break
    else:
        return None, None

    # Step 2: go backward to find entry boundary
    temp = date
    while is_same_rashi(planet1, planet2, temp - timedelta(days=1)):
        temp -= timedelta(days=1)

    # Step 3: refine entry
    entry = refine_same_rashi_entry(planet1, planet2, temp)

    # 🔹 track full continuous window
    temp = entry
    last_valid = temp

    while is_same_rashi(planet1, planet2, temp):
        last_valid = temp
        temp += timedelta(hours=6)  # 🔥 same precision

    exit_time = refine_same_rashi_exit(planet1, planet2, last_valid)

    return entry, exit_time


# -----------------------------
# MAIN ENGINE
# -----------------------------

def get_full_timeline(planet1, planet2):
    now = get_current_datetime_ist()

    current = is_same_rashi(planet1, planet2, now)

    current_rashi = None
    if current:
        current_rashi = get_planet_rashi(planet1, now)

    last_entry, last_exit = find_last_same_rashi_window(planet1, planet2, now)
    next_entry, next_exit = find_next_same_rashi_window(planet1, planet2, now)

    def build_calendar(entry, exit):
        if not entry or not exit:
            return None

        duration = exit - entry
        days = round(duration.total_seconds() / 86400, 2)

        return {
            "start_date": entry.date(),
            "end_date": exit.date(),
            "days": days
        }

    return {
        "current": {
            "is_conjunction": current,
            "rashi": current_rashi
        },

        "last_conjunction": {
            "rashi": get_planet_rashi(planet1, last_entry) if last_entry else None,
            "calendar": build_calendar(last_entry, last_exit),
            "exact": {
                "entry": last_entry,
                "exit": last_exit
            }
        },

        "next_conjunction": {
            "rashi": get_planet_rashi(planet1, next_entry) if next_entry else None,
            "calendar": build_calendar(next_entry, next_exit),
            "exact": {
                "entry": next_entry,
                "exit": next_exit
            }
        }
    }

# -----------------------------
# MODE 1 → Current Transit
# -----------------------------
def get_current_transit(planet):
    now = get_current_datetime_ist()
    return {
        "planet": planet,
        "rashi": get_planet_rashi(planet, now),
        "date": now
    }


# -----------------------------
# MODE 2 → Planet in Rashi (next/previous)
# -----------------------------
def find_planet_in_rashi(planet, target_rashi, direction="next"):
    date = get_current_datetime_ist()
    step = timedelta(days=1) if direction == "next" else -timedelta(days=1)

    for _ in range(10000):
        date += step
        if get_planet_rashi(planet, date) == target_rashi:
            return {
                "planet": planet,
                "rashi": target_rashi,
                "date": date.date()
            }

    return None


# -----------------------------
# MODE 3 → Same Rashi (2 planets)
# -----------------------------
def check_same_rashi(p1, p2):
    now = get_current_datetime_ist()
    return {
        "same_rashi": is_same_rashi(p1, p2, now),
        "rashi": get_planet_rashi(p1, now) if is_same_rashi(p1, p2, now) else None
    }


# -----------------------------
# MODE 4 → Same Rashi + specific rashi
# -----------------------------
def find_same_rashi_in_target(p1, p2, target_rashi, direction="next"):
    date = get_current_datetime_ist()
    step = timedelta(days=1) if direction == "next" else -timedelta(days=1)

    for _ in range(10000):
        date += step

        if (
            get_planet_rashi(p1, date) == target_rashi and
            get_planet_rashi(p2, date) == target_rashi
        ):
            return {
                "p1": p1,
                "p2": p2,
                "rashi": target_rashi,
                "date": date.date()
            }

    return None


# -----------------------------
if __name__ == "__main__":
    from services.astro_engine.interface.cli import run_cli
    run_cli()