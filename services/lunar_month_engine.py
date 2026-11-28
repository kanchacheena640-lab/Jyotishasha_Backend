"""Lunar month names (Amanta and Purnimanta) with Adhik / Kshaya detection.

Rules (sidereal Sun, Lahiri; validated against Drik Panchang 2025-2030):
* A lunar month (Amanta) runs from one new moon (end of Amavasya, tithi
  30 -> 1) to the next.
* Amanta name = the month named for (Sun's sign at the STARTING new moon + 1):
  Sun in Meena at the starting new moon -> Chaitra.
* Adhik: the Sun is in the same sign at both bounding new moons (no Sankranti
  in the month). The Adhik month carries the name of the month it precedes.
* Kshaya: the Sun changes sign twice within the month. It is only FLAGGED
  (``is_kshaya``); the name returned is the same rule as above and the naming
  of Kshaya months is not resolved here.
* Purnimanta (North India): Shukla Paksha keeps the Amanta name; Krishna Paksha
  takes the NEXT month's name, except inside an Adhik month, whose Krishna
  Paksha keeps the Adhik name (Nija X Krishna -> Adhik X -> Nija X Shukla).

New moons are found by stepping at most 6 hours at a time (every tithi lasts
more than ~19 hours, so none can be skipped) from a start point derived from
the current Sun-Moon elongation, then bisecting to ~1 second.

Public API (names and keys unchanged; ``is_kshaya`` is additive):
  get_amanta_month(dt)  -> {"name", "is_adhik", "index", "is_kshaya"}
  get_lunar_month(dt)   -> {"name", "is_adhik", "amanta_index", "is_kshaya"}  (Purnimanta)
  get_shivratri_type(dt)
``dt`` is a naive IST datetime (as everywhere in astro_core).
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from services.astro_core import _tithi_number_at, sidereal_longitudes

IST = ZoneInfo("Asia/Kolkata")

HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwin", "Kartik",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]

AMAVASYA = 30
STEP = timedelta(hours=6)              # < shortest tithi: a whole tithi can never be skipped
MAX_ELONGATION_RATE = 15.5             # degrees/day; the Moon gains at most ~15.4 deg/day on the Sun
_LUNATION_CACHE = []                   # [(start_new_moon, end_new_moon)], bounded
_LUNATION_CACHE_SIZE = 64


def _sun_rashi_index(dt_ist):
    sun, _ = sidereal_longitudes(dt_ist)
    return int(sun // 30) % 12


def _elongation(dt_ist):
    sun, moon = sidereal_longitudes(dt_ist)
    return (moon - sun) % 360


def _bisect_new_moon(before, after):
    """`before` is inside Amavasya, `after` is not: return the transition (~1 s)."""
    while (after - before) > timedelta(seconds=1):
        mid = before + (after - before) / 2
        if _tithi_number_at(mid) == AMAVASYA:
            before = mid
        else:
            after = mid
    return after


def _new_moon_at_or_before(dt_ist):
    """End of the Amavasya at or before dt_ist (the start of its lunar month)."""
    # At least elongation / max_rate days have passed since the new moon; start
    # there (minus a little) so the start point is always AFTER the new moon.
    probe = dt_ist - timedelta(days=max(0.0, _elongation(dt_ist) / MAX_ELONGATION_RATE - 0.25))
    if probe > dt_ist:
        probe = dt_ist
    for _ in range(200):                                   # <= 50 days in 6-hour steps
        prev = probe - STEP
        if _tithi_number_at(prev) == AMAVASYA and _tithi_number_at(probe) != AMAVASYA:
            return _bisect_new_moon(prev, probe)
        probe = prev
    raise ValueError(f"no new moon found before {dt_ist}")


def _new_moon_after(dt_ist):
    """End of the next Amavasya strictly after dt_ist (the end of its lunar month)."""
    remaining = (360 - _elongation(dt_ist)) % 360
    probe = dt_ist + timedelta(days=max(0.0, remaining / MAX_ELONGATION_RATE - 0.25))
    for _ in range(200):
        nxt = probe + STEP
        if _tithi_number_at(probe) == AMAVASYA and _tithi_number_at(nxt) != AMAVASYA:
            return _bisect_new_moon(probe, nxt)
        probe = nxt
    raise ValueError(f"no new moon found after {dt_ist}")


def _lunation(dt_ist):
    """(start, end) new moons bounding dt_ist; cached (bounded) because many
    callers ask about instants in the same month."""
    for start, end in _LUNATION_CACHE:
        if start <= dt_ist < end:
            return start, end
    start = _new_moon_at_or_before(dt_ist)
    end = _new_moon_after(start + timedelta(days=1))
    _LUNATION_CACHE.append((start, end))
    if len(_LUNATION_CACHE) > _LUNATION_CACHE_SIZE:
        _LUNATION_CACHE.pop(0)
    return start, end


def _naive_ist(dt):
    """Callers pass naive IST (astro_core convention) or tz-aware datetimes (e.g. the
    Panchang's sunrise); compare everything as naive IST wall-clock time."""
    if getattr(dt, "tzinfo", None) is not None:
        return dt.astimezone(IST).replace(tzinfo=None)
    return dt


def _month_facts(dt_ist):
    dt_ist = _naive_ist(dt_ist)
    start, end = _lunation(dt_ist)
    s0 = _sun_rashi_index(start + timedelta(minutes=1))
    s1 = _sun_rashi_index(end - timedelta(minutes=1))
    step = (s1 - s0) % 12
    return {"amanta_index": (s0 + 1) % 12, "is_adhik": step == 0, "is_kshaya": step >= 2}


def get_amanta_month(dt_ist):
    f = _month_facts(dt_ist)
    return {
        "name": HINDU_MONTHS[f["amanta_index"]],
        "is_adhik": f["is_adhik"],
        "index": f["amanta_index"],
        "is_kshaya": f["is_kshaya"],
    }


def get_lunar_month(dt_ist):
    """Purnimanta month (North India) for dt_ist."""
    f = _month_facts(dt_ist)
    tithi = _tithi_number_at(_naive_ist(dt_ist))
    if tithi <= 15 or f["is_adhik"]:
        # Shukla Paksha, or Krishna Paksha inside an Adhik month: Amanta name
        month_index, is_adhik = f["amanta_index"], f["is_adhik"]
    else:
        # Krishna Paksha belongs to the next month (Purnimanta); the next month is Nija
        month_index, is_adhik = (f["amanta_index"] + 1) % 12, False
    return {
        "name": HINDU_MONTHS[month_index],
        "is_adhik": is_adhik,
        "amanta_index": f["amanta_index"],
        "is_kshaya": f["is_kshaya"],
    }


def get_shivratri_type(dt_ist):
    tithi_number = _tithi_number_at(dt_ist)
    if tithi_number != 29:
        return None, None

    lunar_month = get_lunar_month(dt_ist)
    # Maha Shivratri Phalguna Krishna Chaturdashi ko hoti hai (Purnimanta context)
    if lunar_month["name"] == "Phalguna" and not lunar_month["is_adhik"]:
        return "maha_shivratri", lunar_month

    return "masik_shivratri", lunar_month
