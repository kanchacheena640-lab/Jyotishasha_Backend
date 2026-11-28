"""Pradosh Vrat (प्रदोष व्रत) -- observance dates, Pradosh Kaal and Puja Muhurat.

Calculation convention (Jyotishasha's documented convention)
-------------------------------------------------------------
* Pradosh Vrat is kept on each Trayodashi (Shukla = tithi 13, Krishna = 28).
* Pradosh Kaal of a civil day = local sunset -> sunset + one fifth of the
  night (sunset to next sunrise), i.e. three of the night's fifteen muhurtas
  ("त्रिमुहूर्तः प्रदोषः स्याद्भानावस्तंगते सति"). Classical texts differ on the
  length (two ghatis, three ghatis, three muhurtas, 7½ nadis); this is ONE
  reading, chosen because it reproduces Drik Panchang's published dates and
  Puja windows. It is a convention, not a claim of scriptural uniqueness.
* The observance day is the civil day whose Pradosh Kaal overlaps the
  Trayodashi span the MOST ("maximum overlap").
* Puja Muhurat = Pradosh Kaal ∩ Trayodashi span of that day. It is never
  widened or invented.

Unresolved cases (flagged, never guessed)
-----------------------------------------
* ``no_overlap``  -- Trayodashi touches NO day's Pradosh Kaal (it falls wholly
  between one night's Pradosh Kaal and the next sunset). No classical rule for
  this case was found; in the one New Delhi instance in 2025-2030 Drik Panchang
  lists a date with a Puja window outside Trayodashi. This engine returns ``date: null``,
  ``puja_muhurat: null`` and the candidate days, and does NOT pick one.
* ``near_tie``    -- the two best days' overlaps differ by less than
  TIE_TOLERANCE_SECONDS (below the engine's ~2-minute agreement with published
  Panchangs, so the choice would not be meaningful). Same treatment.
No date is hardcoded anywhere: every case is derived from the ephemeris.

Classification and labels
-------------------------
* Weekday name (all seven): the weekday of the civil observance date --
  Ravi, Soma, Bhauma, Budha, Guru, Shukra, Shani + "Pradosh Vrat".
* Paksha from the tithi number (13 Shukla, 28 Krishna).
* Lunar month: computed HERE, independently of services/lunar_month_engine
  (whose labels did not match published Panchangs in validation; it is shared
  by other features and is deliberately not modified):
    Amanta month   = named for (Sun's sidereal sign at the month's starting new
                     moon + 1); Adhik when the Sun's sign is the same at both
                     bounding new moons (no Sankranti); Kshaya flagged when it
                     changes by two signs.
    Purnimanta     = Amanta name for Shukla Paksha; the NEXT month's name for
                     Krishna Paksha, except inside an Adhik month, whose Krishna
                     Paksha keeps the Adhik name (Nija X Krishna -> Adhik X ->
                     Nija X Shukla).
  Adhik is always labelled explicitly.

Location
--------
Default reference location: New Delhi (DEFAULT_LATITUDE/LONGITUDE, the same
defaults as the existing /api/events/pradosh, /sankranti and /kharmas).
Sunrise/sunset come from services.sun_calc (an IST-date model), which is only
valid inside SUPPORTED_LAT_RANGE / SUPPORTED_LON_RANGE (the same region the
Kharmas engine uses); other coordinates are rejected, never answered wrongly.
Coordinates are rounded to 0.01° (~1 km) for caching.

Caching (time-independent data only)
------------------------------------
* annual calendar per (year, lat, lon)     -- LRU maxsize CALENDAR_CACHE_SIZE,
  behind 32 striped locks so concurrent first requests compute a key once
* sunrise/sunset per (date, lat, lon)      -- LRU maxsize 4096
"today"/"next" depend on the reference date and are recomputed per call from
the cached calendars (never cached themselves).

Swiss Ephemeris sidereal mode is thread-local (lahiri_mode.py): every public
function calls ensure_lahiri_mode() on the calling thread. Returned structures
are fresh copies; cached values are never handed out for mutation.
"""

import copy
import threading
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from lahiri_mode import ensure_lahiri_mode
from services.astro_core import _tithi_number_at, sidereal_longitudes
from services.kharmas_engine import OBSERVANCE_LAT_RANGE, OBSERVANCE_LON_RANGE
from services.sun_calc import calculate_sunrise_sunset

IST = ZoneInfo("Asia/Kolkata")

CONVENTION_VERSION = "pradosh-1"
MIN_YEAR = 1900
MAX_YEAR = 2100
DEFAULT_LATITUDE = 28.61     # New Delhi; same defaults as /api/events/pradosh, /sankranti, /kharmas
DEFAULT_LONGITUDE = 77.23
SUPPORTED_LAT_RANGE = OBSERVANCE_LAT_RANGE      # validity region of the IST-based sunrise model
SUPPORTED_LON_RANGE = OBSERVANCE_LON_RANGE
SUPPORTED_LANGUAGES = ("en", "hi")

PRADOSH_NIGHT_FRACTION = 5          # Pradosh Kaal = night / 5 (three of fifteen night muhurtas)
TIE_TOLERANCE_SECONDS = 120         # below the engine's agreement with published Panchangs
SCAN_STEP = timedelta(hours=8)      # < shortest tithi (~19.5 h): at most one change per step (and checked)
CALENDAR_CACHE_SIZE = 64

SHUKLA_TRAYODASHI, KRISHNA_TRAYODASHI, AMAVASYA = 13, 28, 30

PAKSHA = {
    SHUKLA_TRAYODASHI: {"key": "shukla", "en": "Shukla", "hi": "शुक्ल"},
    KRISHNA_TRAYODASHI: {"key": "krishna", "en": "Krishna", "hi": "कृष्ण"},
}
# Python weekday(): Monday = 0
WEEKDAYS = [
    {"key": "monday", "en": "Monday", "hi": "सोमवार", "pradosh_key": "soma", "pradosh_en": "Soma", "pradosh_hi": "सोम"},
    {"key": "tuesday", "en": "Tuesday", "hi": "मंगलवार", "pradosh_key": "bhauma", "pradosh_en": "Bhauma", "pradosh_hi": "भौम"},
    {"key": "wednesday", "en": "Wednesday", "hi": "बुधवार", "pradosh_key": "budha", "pradosh_en": "Budha", "pradosh_hi": "बुध"},
    {"key": "thursday", "en": "Thursday", "hi": "गुरुवार", "pradosh_key": "guru", "pradosh_en": "Guru", "pradosh_hi": "गुरु"},
    {"key": "friday", "en": "Friday", "hi": "शुक्रवार", "pradosh_key": "shukra", "pradosh_en": "Shukra", "pradosh_hi": "शुक्र"},
    {"key": "saturday", "en": "Saturday", "hi": "शनिवार", "pradosh_key": "shani", "pradosh_en": "Shani", "pradosh_hi": "शनि"},
    {"key": "sunday", "en": "Sunday", "hi": "रविवार", "pradosh_key": "ravi", "pradosh_en": "Ravi", "pradosh_hi": "रवि"},
]
MONTHS = [  # Amanta/Purnimanta month names, index 0 = Chaitra
    ("chaitra", "Chaitra", "चैत्र"), ("vaishakha", "Vaishakha", "वैशाख"), ("jyeshtha", "Jyeshtha", "ज्येष्ठ"),
    ("ashadha", "Ashadha", "आषाढ़"), ("shravana", "Shravana", "श्रावण"), ("bhadrapada", "Bhadrapada", "भाद्रपद"),
    ("ashwina", "Ashwina", "आश्विन"), ("kartika", "Kartika", "कार्तिक"), ("margashirsha", "Margashirsha", "मार्गशीर्ष"),
    ("pausha", "Pausha", "पौष"), ("magha", "Magha", "माघ"), ("phalguna", "Phalguna", "फाल्गुन"),
]


class PradoshInputError(ValueError):
    """Invalid caller input (maps to HTTP 400)."""


# ----------------------------------------------------------------------------
# Input validation
# ----------------------------------------------------------------------------

def _coord(value, default, name, low, high):
    if value is None:
        value = default
    if isinstance(value, bool):
        raise PradoshInputError(f"{name} must be a number")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise PradoshInputError(f"{name} must be a number")
    if value != value or not low <= value <= high:
        raise PradoshInputError(f"{name} must be between {low} and {high}")
    return round(value, 2)


def normalise_location(latitude=None, longitude=None):
    """Validated, rounded (lat, lon); raises PradoshInputError outside the supported region."""
    lat = _coord(latitude, DEFAULT_LATITUDE, "latitude", -90, 90)
    lon = _coord(longitude, DEFAULT_LONGITUDE, "longitude", -180, 180)
    if not (SUPPORTED_LAT_RANGE[0] <= lat <= SUPPORTED_LAT_RANGE[1]
            and SUPPORTED_LON_RANGE[0] <= lon <= SUPPORTED_LON_RANGE[1]):
        raise PradoshInputError(
            f"location not supported: latitude must be within {list(SUPPORTED_LAT_RANGE)} and longitude within "
            f"{list(SUPPORTED_LON_RANGE)} (the sunrise/sunset model is IST-based)")
    return lat, lon


def normalise_language(language):
    if language is None:
        return "en"
    if not isinstance(language, str) or language.strip().lower() not in SUPPORTED_LANGUAGES:
        raise PradoshInputError("language must be 'en' or 'hi'")
    return language.strip().lower()


def validate_year(year):
    if isinstance(year, bool) or not isinstance(year, int):
        raise PradoshInputError("year must be an integer")
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise PradoshInputError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")
    return year


def ist_today(now=None):
    """The current IST civil date (never the server's local date)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(IST).date()


# ----------------------------------------------------------------------------
# Astronomy helpers (naive datetimes are IST wall-clock, as in astro_core)
# ----------------------------------------------------------------------------

def _naive_ist(dt):
    return dt.astimezone(IST).replace(tzinfo=None) if dt.tzinfo else dt


def _iso(dt):
    return dt.replace(tzinfo=IST).isoformat(timespec="seconds")


@lru_cache(maxsize=4096)
def _sun_times(day, lat, lon):
    """(sunrise, sunset) naive IST for a civil date."""
    sunrise, sunset = calculate_sunrise_sunset(day, lat, lon)
    if sunrise is None or sunset is None:
        raise ValueError(f"no sunrise/sunset for {day} at {lat},{lon}")
    return _naive_ist(sunrise), _naive_ist(sunset)


def _pradosh_kaal(day, lat, lon):
    _, sunset = _sun_times(day, lat, lon)
    next_sunrise, _ = _sun_times(day + timedelta(days=1), lat, lon)
    return sunset, sunset + (next_sunrise - sunset) / PRADOSH_NIGHT_FRACTION


def _refine(t0, t1):
    """Instant (within 1 s) where the tithi changes inside (t0, t1]."""
    first = _tithi_number_at(t0)
    while (t1 - t0) > timedelta(seconds=1):
        mid = t0 + (t1 - t0) / 2
        if _tithi_number_at(mid) == first:
            t0 = mid
        else:
            t1 = mid
    return t1.replace(microsecond=0)


def _scan(start, end):
    """One pass over [start, end]: every Trayodashi span (tithi, begin, end)
    fully inside it, and every new moon (end of Amavasya) inside it. Only the
    transitions that matter (into/out of Trayodashi, out of Amavasya) are
    refined to the second; a bracket that ever spans two tithi changes is halved."""
    spans, new_moons = [], []
    t, cur, begin = start, _tithi_number_at(start), None
    while t < end:
        t2 = min(t + SCAN_STEP, end)
        nxt = _tithi_number_at(t2)
        while (nxt - cur) % 30 > 1:            # defensive: never let one bracket hide a tithi
            t2 = t + (t2 - t) / 2
            nxt = _tithi_number_at(t2)
        if nxt != cur and (cur in PAKSHA or nxt in PAKSHA or cur == AMAVASYA):
            edge = _refine(t, t2)
            if cur in PAKSHA and begin is not None:
                spans.append((cur, begin, edge))
                begin = None
            if nxt in PAKSHA:
                begin = edge
            if cur == AMAVASYA:
                new_moons.append(edge)
        cur = nxt
        t = t2
    return spans, new_moons


def _new_moon_at_or_before(t):
    """End of Amavasya (tithi 30 -> 1) at or before t."""
    probe = t
    for _ in range(140):                       # <= 35 days back in 6-hour steps
        if _tithi_number_at(probe) != AMAVASYA and _tithi_number_at(probe - timedelta(hours=6)) == AMAVASYA:
            return _refine(probe - timedelta(hours=6), probe)
        probe -= timedelta(hours=6)
    raise ValueError(f"no new moon found before {t}")


def _sun_sign(t):
    return int(sidereal_longitudes(t)[0] // 30) % 12


def _month_label(index, adhik):
    key, en, hi = MONTHS[index]
    return {"key": key, "en": f"Adhik {en}" if adhik else en, "hi": f"अधिक {hi}" if adhik else hi,
            "base_en": en, "base_hi": hi, "is_adhik": adhik}


def lunar_months_at(t, tithi, new_moons=None):
    """Amanta and Purnimanta labels for instant t (naive IST) in the paksha of
    `tithi`. `new_moons` (sorted) may supply precomputed new moons; the bounding
    pair is searched directly when it does not cover t."""
    start_nm = end_nm = None
    if new_moons:
        before = [m for m in new_moons if m <= t]
        after = [m for m in new_moons if m > t]
        if before and after:
            start_nm, end_nm = before[-1], after[0]
    if start_nm is None:
        start_nm = _new_moon_at_or_before(t)
        end_nm = _new_moon_at_or_before(start_nm + timedelta(days=33))
    s0 = _sun_sign(start_nm + timedelta(minutes=1))
    s1 = _sun_sign(end_nm - timedelta(minutes=1))
    step = (s1 - s0) % 12
    amanta_index, adhik, kshaya = (s0 + 1) % 12, step == 0, step >= 2
    amanta = _month_label(amanta_index, adhik)
    if tithi <= 15 or adhik:                   # Shukla, or Krishna inside an Adhik month
        purnimanta = _month_label(amanta_index, adhik)
    else:
        purnimanta = _month_label((amanta_index + 1) % 12, False)
    out = {"amanta": amanta, "purnimanta": purnimanta, "default_convention": "purnimanta"}
    if kshaya:
        out["kshaya"] = True                   # flagged; naming of Kshaya months is not resolved here
    return out


# ----------------------------------------------------------------------------
# Observance resolution
# ----------------------------------------------------------------------------

def _window(a, b):
    return {"start": _iso(a), "end": _iso(b), "duration_minutes": round((b - a).total_seconds() / 60, 1)}


def resolve_span(tithi, begin, end, lat, lon, new_moons=None):
    """One Pradosh record for a Trayodashi span (pure function of its inputs)."""
    candidates = []
    day = begin.date() - timedelta(days=1)
    while day <= end.date():
        k0, k1 = _pradosh_kaal(day, lat, lon)
        overlap = (min(k1, end) - max(k0, begin)).total_seconds()
        if overlap > 0:
            candidates.append((day, overlap, k0, k1))
        day += timedelta(days=1)

    ranked = sorted(candidates, key=lambda c: -c[1])
    if not ranked:
        resolution = "no_overlap"
    elif len(ranked) > 1 and ranked[0][1] - ranked[1][1] < TIE_TOLERANCE_SECONDS:
        resolution = "near_tie"
    else:
        resolution = "max_overlap"

    mid = begin + (end - begin) / 2
    record = {
        "id": f"pradosh-{begin.date().isoformat()}-{PAKSHA[tithi]['key']}",
        "status": "resolved" if resolution == "max_overlap" else "unresolved",
        "resolution": resolution,
        "paksha": dict(PAKSHA[tithi]),
        "tithi": {"number": tithi, "trayodashi_begins": _iso(begin), "trayodashi_ends": _iso(end)},
        "lunar_month": lunar_months_at(mid, tithi, new_moons),
        "candidates": [
            {"date": c[0].isoformat(), "overlap_minutes": round(c[1] / 60, 1), "pradosh_kaal": _window(c[2], c[3])}
            for c in sorted(candidates, key=lambda c: c[0])
        ],
    }
    if resolution == "max_overlap":
        day, overlap, k0, k1 = ranked[0]
        wd = WEEKDAYS[day.weekday()]
        _, sunset = _sun_times(day, lat, lon)
        record.update({
            "date": day.isoformat(),
            "weekday": {"key": wd["key"], "en": wd["en"], "hi": wd["hi"]},
            "classification": {"key": wd["pradosh_key"], "en": wd["pradosh_en"], "hi": wd["pradosh_hi"]},
            "name": {"en": f"{wd['pradosh_en']} Pradosh Vrat", "hi": f"{wd['pradosh_hi']} प्रदोष व्रत"},
            "sunset": _iso(sunset),
            "pradosh_kaal": _window(k0, k1),
            "puja_muhurat": _window(max(k0, begin), min(k1, end)),
            "overlap_minutes": round(overlap / 60, 1),
            "anchor_date": day.isoformat(),
        })
    else:
        # Not decided: no date, no Puja Muhurat. Anchored to the day Trayodashi ends for listing only.
        record.update({
            "date": None, "weekday": None, "classification": None,
            "name": {"en": "Pradosh Vrat", "hi": "प्रदोष व्रत"},
            "sunset": None, "pradosh_kaal": None, "puja_muhurat": None, "overlap_minutes": None,
            "anchor_date": end.date().isoformat(),
            "note": ("Trayodashi does not overlap the Pradosh Kaal of any day; the observance day is not decided by this convention."
                     if resolution == "no_overlap" else
                     "Two days overlap the Trayodashi almost equally; the observance day is not decided by this convention."),
        })
    return record


_CALENDAR_LOCKS = tuple(threading.Lock() for _ in range(32))   # bounded, striped single-flight locks


def _calendar(year, lat, lon):
    """Cached calendar; concurrent first requests for the same key compute it once."""
    with _CALENDAR_LOCKS[hash((year, lat, lon)) % len(_CALENDAR_LOCKS)]:
        return _calendar_cached(year, lat, lon)


@lru_cache(maxsize=CALENDAR_CACHE_SIZE)
def _calendar_cached(year, lat, lon):
    # Wide enough that every span anchored in `year` is complete and bounded by two scanned new moons.
    start = datetime(year - 1, 11, 20)
    end = datetime(year + 1, 2, 10)
    spans, new_moons = _scan(start, end)
    records = []
    for tithi, begin, end_ in spans:
        rec = resolve_span(tithi, begin, end_, lat, lon, new_moons)
        if rec["anchor_date"][:4] == str(year):
            records.append(rec)
    records.sort(key=lambda r: (r["anchor_date"], r["tithi"]["trayodashi_begins"]))
    return tuple(records)


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def get_pradosh_calendar(year, latitude=None, longitude=None):
    """All Pradosh records anchored in IST calendar `year` (resolved by date,
    unresolved by the day their Trayodashi ends). Fresh copies."""
    ensure_lahiri_mode()
    validate_year(year)
    lat, lon = normalise_location(latitude, longitude)
    return copy.deepcopy(list(_calendar(year, lat, lon)))


def get_pradosh_today_next(on_date=None, latitude=None, longitude=None):
    """Dynamic view for IST date `on_date` (default: IST today): the resolved
    Pradosh on that date (or None), the next resolved one after it, and any
    unresolved Trayodashi between them. Built from cached calendars; never cached."""
    ensure_lahiri_mode()
    if on_date is None:
        on_date = ist_today()
    if not isinstance(on_date, date) or isinstance(on_date, datetime):
        raise PradoshInputError("date must be a calendar date")
    if not MIN_YEAR <= on_date.year <= MAX_YEAR - 1:
        raise PradoshInputError(f"date must be between {MIN_YEAR} and {MAX_YEAR - 1}")
    lat, lon = normalise_location(latitude, longitude)
    records = list(_calendar(on_date.year, lat, lon)) + list(_calendar(on_date.year + 1, lat, lon))
    key = on_date.isoformat()
    today = next((r for r in records if r["date"] == key), None)
    nxt = next((r for r in records if r["date"] is not None and r["date"] > key), None)
    limit = nxt["date"] if nxt else "9999-12-31"
    unresolved = [r for r in records if r["date"] is None and key <= r["anchor_date"] <= limit]
    return {
        "date": key,
        "location": {"latitude": lat, "longitude": lon},
        "today": copy.deepcopy(today),
        "next": copy.deepcopy(nxt),
        "unresolved_before_next": copy.deepcopy(unresolved),
    }


def convention():
    """Machine-readable description of the calculation convention."""
    return {
        "version": CONVENTION_VERSION,
        "observance_rule": "Trayodashi with the maximum overlap of the day's Pradosh Kaal",
        "pradosh_kaal": "local sunset to sunset + 1/5 of the night (three of fifteen night muhurtas)",
        "puja_muhurat": "Pradosh Kaal intersected with the Trayodashi span",
        "unresolved": {
            "no_overlap": "Trayodashi overlaps no day's Pradosh Kaal: date and Puja Muhurat are null",
            "near_tie": f"top two overlaps differ by < {TIE_TOLERANCE_SECONDS} s: date and Puja Muhurat are null",
        },
        "weekday_names": "weekday of the civil observance date (Ravi, Soma, Bhauma, Budha, Guru, Shukra, Shani)",
        "lunar_month": "Amanta = Sun's sign at the starting new moon + 1 (Adhik when no Sankranti); Purnimanta shifts "
                       "Krishna Paksha to the next month except inside an Adhik month",
        "note": "Classical texts give different Pradosh Kaal lengths; this is Jyotishasha's documented convention.",
        "timezone": "Asia/Kolkata",
        "supported_region": {"latitude": list(SUPPORTED_LAT_RANGE), "longitude": list(SUPPORTED_LON_RANGE)},
        "supported_years": [MIN_YEAR, MAX_YEAR],
        "default_location": {"name": "New Delhi", "latitude": DEFAULT_LATITUDE, "longitude": DEFAULT_LONGITUDE},
    }


def clear_caches():
    _calendar_cached.cache_clear()
    _sun_times.cache_clear()
