"""Kharmas (खरमास) periods -- a SOLAR period, computed from Sun ingresses.

Definition used here
--------------------
Kharmas is the time the (sidereal, Lahiri) Sun spends in Dhanu (Sagittarius)
or Meena (Pisces):

    Dhanu Kharmas: Sun enters Dhanu  (Dhanu Sankranti)  -> Sun enters Makar (Makar Sankranti)
    Meena Kharmas: Sun enters Meena  (Meena Sankranti)  -> Sun enters Mesha (Mesha Sankranti)

Each period is the half-open interval [start ingress, end ingress): the start
instant is inside Kharmas, the end instant is not. Dhanu Kharmas crosses the
calendar year (mid-December -> mid-January); a period is identified by the
IST calendar year in which it STARTS ("dhanu-2026" ends in January 2027).

Kharmas is NOT Adhik Maas. Adhik Maas (services/adhik_maas_engine.py) is a
LUNAR intercalary month (a lunation with no Sankranti); Kharmas is purely the
Sun's position and occurs twice every year. Nothing here reads lunar months.

Two different "dates" per boundary -- kept separate on purpose
--------------------------------------------------------------
* ``ingress``          -- the astronomical instant the Sun crosses the sign
                          boundary (location-independent), ISO 8601 IST.
* ``observance_date``  -- the civil day the Sankranti is observed, using the
                          site's EXISTING Punya Kaal rule
                          (sankranti_engine._calculate_punya_kaal: ingress
                          before local sunset -> same day, otherwise the next
                          day's sunrise). Depends on latitude/longitude. None
                          outside OBSERVANCE_LAT_RANGE / OBSERVANCE_LON_RANGE
                          (where the IST-based sunrise model is not valid) and
                          wherever the rule cannot run (no sunrise/sunset).
The Kharmas status always uses the ingress instants, never observance dates.

Two independent inputs
----------------------
* ``year``  -- selects WHICH periods are listed: the two periods that start
               in that IST calendar year. Supported: MIN_YEAR..MAX_YEAR.
* ``at``    -- the reference instant ("as of") that every ``status`` and the
               previous/current/upcoming selection are evaluated against.
               Default: now. Supported: AS_OF_MIN_YEAR..AS_OF_MAX_YEAR (IST),
               one year narrower than ``year`` because previous/upcoming need
               the neighbouring years. Neither input changes the other's meaning.

Calculation source (no duplicated astronomy)
--------------------------------------------
Ingress instants come from services.sankranti_engine._find_exact_ingress /
_get_sun_sign_index (the same code behind /api/events/sankranti and the
Panchang), so Kharmas can never disagree with the site's Sankranti times.

Resolution vs accuracy (two different things)
---------------------------------------------
* Numerical search resolution: the Sankranti engine's bisection stops when the
  bracket is <= 1 second, so the returned instant is within 1 s of where THIS
  model crosses the boundary.
* Ephemeris accuracy: the repository ships no Swiss Ephemeris data files, so
  Swiss Ephemeris silently uses its built-in Moshier ephemeris (the returned
  calculation flags carry FLG_MOSEPH; reported per response). Measured against
  the DE441-based sepl_18.se1 file for 40 Kharmas boundaries 1900-2100, the
  ingress instants differed by at most 2.0 s.
* Convention: published Panchangs can place the same Sankranti several minutes
  apart. Against Drik Panchang (New Delhi) the existing engine is 2-7 minutes
  earlier for 2025-2028; the cause has not been established. The ayanamsha
  (Swiss Ephemeris SIDM_LAHIRI) is intentionally unchanged here.

Ayanamsha / thread safety
-------------------------
Swiss Ephemeris sidereal mode is THREAD-LOCAL (see lahiri_mode.py). Every
public function calls ensure_lahiri_mode() on the calling thread first.

Caching and cost
----------------
Only time-independent results are cached, in bounded LRU caches:
  * the periods (and observed ephemeris) per start year   -- maxsize 64
  * observance dates per (ingress, lat/lon rounded 0.01)  -- maxsize 256
Live status is recomputed against ``at`` on every call and never cached.
Per call the work is bounded: at most 4 yearly scans (~410 one-day checks
each) and at most 10 observance calculations.
"""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import swisseph as swe

from lahiri_mode import ensure_lahiri_mode
from services.panchang_engine import _to_ut_julday
from services.sankranti_engine import (
    FLAGS as SANKRANTI_FLAGS,
    RASHI_NAMES_EN,
    RASHI_NAMES_HI,
    _calculate_punya_kaal,
    _find_exact_ingress,
    _get_sun_sign_index,
)

IST = ZoneInfo("Asia/Kolkata")

MIN_YEAR = 1900                 # supported start years for `year`
MAX_YEAR = 2100
AS_OF_MIN_YEAR = MIN_YEAR + 1   # supported IST years for `at`
AS_OF_MAX_YEAR = MAX_YEAR - 1
SEARCH_RESOLUTION_SECONDS = 1

DHANU, MAKAR, MEENA, MESHA = 8, 9, 11, 0

KINDS = {
    "dhanu": (DHANU, MAKAR),
    "meena": (MEENA, MESHA),
}
START_SIGN_TO_KIND = {start: kind for kind, (start, _end) in KINDS.items()}

SANKRANTI_NAMES = {
    "en": {DHANU: "Dhanu Sankranti", MAKAR: "Makar Sankranti", MEENA: "Meena Sankranti", MESHA: "Mesha Sankranti"},
    "hi": {DHANU: "धनु संक्रांति", MAKAR: "मकर संक्रांति", MEENA: "मीन संक्रांति", MESHA: "मेष संक्रांति"},
}
KHARMAS_NAMES = {
    "en": {"dhanu": "Dhanu Kharmas", "meena": "Meena Kharmas"},
    "hi": {"dhanu": "धनु खरमास", "meena": "मीन खरमास"},
}
STATUS_LABELS = {
    "en": {"completed": "Completed", "active": "Ongoing", "upcoming": "Upcoming"},
    "hi": {"completed": "समाप्त", "active": "जारी", "upcoming": "आगामी"},
}

SUPPORTED_LANGUAGES = ("en", "hi")
DEFAULT_LATITUDE = 28.61   # same defaults as /api/events/sankranti
DEFAULT_LONGITUDE = 77.23


class KharmasInputError(ValueError):
    """Invalid caller input (maps to HTTP 400)."""


# ----------------------------------------------------------------------------
# Ephemeris actually used (from the calculation's own return flags)
# ----------------------------------------------------------------------------

def _ephemeris_label(retflags):
    if retflags & swe.FLG_MOSEPH:
        return "moshier_builtin"
    if retflags & swe.FLG_JPLEPH:
        return "jpl_files"
    if retflags & swe.FLG_SWIEPH:
        return "swiss_ephemeris_files"
    return "unknown"


def _ephemeris_at(dt_ist_naive):
    """The ephemeris Swiss Ephemeris actually used for the Sankranti engine's
    own Sun call (same flags, same instant)."""
    _pos, retflags = swe.calc_ut(_to_ut_julday(dt_ist_naive), swe.SUN, SANKRANTI_FLAGS)
    return _ephemeris_label(retflags)


# ----------------------------------------------------------------------------
# Yearly calculations (cached, time-independent)
# ----------------------------------------------------------------------------

def _scan_ingresses(start_day, end_day):
    """Sun ingresses whose IST calendar day is in [start_day, end_day], as
    (naive IST datetime, sign index entered). Uses the existing engine."""
    ensure_lahiri_mode()
    found = []
    d = start_day
    while d <= end_day:
        ingress = _find_exact_ingress(d)
        if ingress is not None:
            found.append((ingress, _get_sun_sign_index(ingress)))
        d += timedelta(days=1)
    return found


@lru_cache(maxsize=64)
def _periods_starting_in(year):
    """((kind, start, start_sign, end, end_sign), ...) for the periods whose
    START ingress is in IST calendar year `year`, plus the ephemeris labels
    observed at those ingress instants. start/end are aware IST datetimes."""
    ensure_lahiri_mode()
    # Scan the year plus 45 days: a Dhanu period starting in December always
    # ends by mid-January (a sign lasts at most ~31.5 days); asserted below.
    ingresses = _scan_ingresses(date(year, 1, 1), date(year + 1, 2, 14))
    periods, ephemerides = [], set()
    for i, (dt, sign) in enumerate(ingresses):
        if dt.year != year or sign not in START_SIGN_TO_KIND:
            continue
        kind = START_SIGN_TO_KIND[sign]
        nxt = ingresses[i + 1] if i + 1 < len(ingresses) else None
        if nxt is None or nxt[1] != KINDS[kind][1]:
            raise RuntimeError(f"Could not find the {kind} Kharmas end ingress after {dt.isoformat()}")
        ephemerides.add(_ephemeris_at(dt))
        ephemerides.add(_ephemeris_at(nxt[0]))
        periods.append((kind, dt.replace(tzinfo=IST), sign, nxt[0].replace(tzinfo=IST), nxt[1]))
    if sorted(p[0] for p in periods) != ["dhanu", "meena"]:
        raise RuntimeError(f"Expected one Dhanu and one Meena Kharmas starting in {year}, got {[p[0] for p in periods]}")
    return tuple(periods), tuple(sorted(ephemerides))


def _round_coord(value):
    return round(float(value), 2)   # ~1 km: sunset differs by well under a minute


# The Punya Kaal rule uses the Panchang's IST-based sunrise/sunset model, which
# searches fixed IST day windows. It was verified to give sane sunrise/sunset
# (solar noon between them) on 5 dates across the year for every 5-degree grid
# point in this box, and to be WRONG west of ~0 deg E. Observance dates are
# therefore only produced inside this conservative region; elsewhere they are
# None rather than silently wrong. Ingress instants are valid everywhere.
OBSERVANCE_LAT_RANGE = (-45.0, 45.0)
OBSERVANCE_LON_RANGE = (25.0, 140.0)


def observance_supported(lat, lon):
    return (OBSERVANCE_LAT_RANGE[0] <= lat <= OBSERVANCE_LAT_RANGE[1]
            and OBSERVANCE_LON_RANGE[0] <= lon <= OBSERVANCE_LON_RANGE[1])


@lru_cache(maxsize=256)
def _observance_date(ingress_iso, lat, lon):
    """Sankranti observance (civil) date via the existing Punya Kaal rule."""
    ensure_lahiri_mode()
    ingress_naive = datetime.fromisoformat(ingress_iso).astimezone(IST).replace(tzinfo=None)
    try:
        punya_start, _punya_end = _calculate_punya_kaal(ingress_naive, lat, lon)
    except Exception:
        # No sunrise/sunset that day (polar latitudes): the Sankranti engine
        # cannot place a Punya Kaal. The ingress instant -- and so the Kharmas
        # window itself -- is unaffected; only the observance date is unknown.
        return None
    return punya_start.date().isoformat()


# ----------------------------------------------------------------------------
# Input handling (live, never cached)
# ----------------------------------------------------------------------------

def _validate_year(year):
    if isinstance(year, bool) or not isinstance(year, int):
        raise KharmasInputError("year must be an integer")
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise KharmasInputError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")


def _as_ist(at):
    if at is None:
        at = datetime.now(timezone.utc)
    if not isinstance(at, datetime):
        raise KharmasInputError("at must be a datetime")
    if at.tzinfo is None:                      # naive input is interpreted as IST
        at = at.replace(tzinfo=IST)
    try:
        at = at.astimezone(IST)
    except (OverflowError, ValueError):
        raise KharmasInputError(f"at must be between {AS_OF_MIN_YEAR} and {AS_OF_MAX_YEAR}")
    if not AS_OF_MIN_YEAR <= at.year <= AS_OF_MAX_YEAR:
        raise KharmasInputError(f"at must be between {AS_OF_MIN_YEAR} and {AS_OF_MAX_YEAR} (IST)")
    return at


def _coord(value, default, name, low, high):
    if value is None:
        value = default
    if isinstance(value, bool):
        raise KharmasInputError(f"{name} must be a number")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise KharmasInputError(f"{name} must be a number")
    if value != value or not low <= value <= high:
        raise KharmasInputError(f"{name} must be between {low} and {high}")
    return _round_coord(value)


def _normalise(language, latitude, longitude):
    if language is None:
        language = "en"
    if not isinstance(language, str) or language.strip().lower() not in SUPPORTED_LANGUAGES:
        raise KharmasInputError("language must be 'en' or 'hi'")
    lat = _coord(latitude, DEFAULT_LATITUDE, "latitude", -90, 90)
    lon = _coord(longitude, DEFAULT_LONGITUDE, "longitude", -180, 180)
    return language.strip().lower(), lat, lon


def _status(start, end, at):
    if at < start:
        return "upcoming"
    if at < end:                               # start inclusive, end exclusive
        return "active"
    return "completed"


def _iso(dt):
    return dt.astimezone(IST).isoformat(timespec="seconds")


def _boundary(dt, sign, lat, lon, language):
    names = RASHI_NAMES_HI if language == "hi" else RASHI_NAMES_EN
    return {
        "ingress": _iso(dt),
        "sun_enters": {"index": sign, "name": names[sign]},
        "sankranti": SANKRANTI_NAMES[language][sign],
        "observance_date": _observance_date(dt.isoformat(), lat, lon) if observance_supported(lat, lon) else None,
    }


def _period_dict(p, at, lat, lon, language):
    kind, start, s_sign, end, e_sign = p
    status = _status(start, end, at)
    names = RASHI_NAMES_HI if language == "hi" else RASHI_NAMES_EN
    return {
        "id": f"{kind}-{start.year}",
        "kind": kind,
        "name": KHARMAS_NAMES[language][kind],
        "sun_sign": {"index": s_sign, "name": names[s_sign]},
        "start": _boundary(start, s_sign, lat, lon, language),
        "end": _boundary(end, e_sign, lat, lon, language),
        "duration_days": round((end - start).total_seconds() / 86400, 2),
        "status": status,
        "status_label": STATUS_LABELS[language][status],
    }


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def get_kharmas_periods(year, language="en", latitude=None, longitude=None, at=None):
    """Both Kharmas periods that START in `year`; each `status` is relative to
    `at` (default now). `year` and `at` are independent."""
    ensure_lahiri_mode()
    _validate_year(year)
    language, lat, lon = _normalise(language, latitude, longitude)
    at = _as_ist(at)
    periods, _eph = _periods_starting_in(year)
    return [_period_dict(p, at, lat, lon, language) for p in periods]


def get_kharmas_status(at=None, language="en", latitude=None, longitude=None):
    """Previous, current and upcoming Kharmas relative to `at` (default now).

    current is None when `at` is outside Kharmas; previous is the most recent
    completed period; upcoming is the next period that has not started.
    ``ephemeris`` lists the ephemerides observed for the periods consulted."""
    ensure_lahiri_mode()
    language, lat, lon = _normalise(language, latitude, longitude)
    at = _as_ist(at)

    candidates, ephemerides = [], set()
    for y in (at.year - 1, at.year, at.year + 1):
        periods, eph = _periods_starting_in(y)
        candidates.extend(periods)
        ephemerides.update(eph)
    candidates.sort(key=lambda p: p[1])

    previous = current = upcoming = None
    for p in candidates:
        st = _status(p[1], p[3], at)
        if st == "completed":
            previous = p
        elif st == "active":
            current = p
        elif upcoming is None:
            upcoming = p

    fmt = lambda p: _period_dict(p, at, lat, lon, language) if p else None
    return {
        "as_of": _iso(at),
        "is_kharmas": current is not None,
        "previous": fmt(previous),
        "current": fmt(current),
        "upcoming": fmt(upcoming),
        "ephemeris": sorted(ephemerides),
    }


def ephemeris_for_year(year):
    """Ephemerides observed for the periods starting in `year`."""
    ensure_lahiri_mode()
    _validate_year(year)
    return list(_periods_starting_in(year)[1])


def ephemeris_in_use():
    """Diagnostic: what Swiss Ephemeris uses right now for the Sankranti
    engine's flags (probe at J2000)."""
    ensure_lahiri_mode()
    return _ephemeris_at(datetime(2000, 1, 1, 17, 30))


def get_kharmas_intervals(start, end):
    """Kharmas periods overlapping the half-open window [start, end), oldest
    first, as plain dicts with exact (sub-second) aware IST datetimes:
    {id, kind, start, end, start_sign, end_sign}. No status, no observance
    dates, no location -- the cheap building block for annotations. Naive
    inputs are interpreted as IST. Uses the cached yearly calculation."""
    ensure_lahiri_mode()
    if start.tzinfo is None:
        start = start.replace(tzinfo=IST)
    if end.tzinfo is None:
        end = end.replace(tzinfo=IST)
    start, end = start.astimezone(IST), end.astimezone(IST)
    out = []
    # A period starting in year Y-1 (Dhanu) can still be running in year Y.
    for y in range(max(MIN_YEAR, start.year - 1), min(MAX_YEAR, end.year) + 1):
        for kind, s, s_sign, e, e_sign in _periods_starting_in(y)[0]:
            if s < end and e > start:
                out.append({"id": f"{kind}-{s.year}", "kind": kind, "start": s, "end": e,
                            "start_sign": s_sign, "end_sign": e_sign})
    out.sort(key=lambda p: p["start"])
    return out


def clear_caches():
    """For tests: drop the yearly caches."""
    _periods_starting_in.cache_clear()
    _observance_date.cache_clear()
