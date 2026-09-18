# services/birth_timezone_resolver.py

"""
services/birth_timezone_resolver.py -- Canonical birth-timezone resolver
(Foreign Birth Timezone Correctness project, Phase T1/T2).

Two small, pure functions:

    resolve_birth_timezone(lat, lon) -> str
        Coordinates -> the IANA timezone name that geographically
        contains them (e.g. "Asia/Kolkata", "America/New_York").

    resolve_birth_utc_datetime(dob, tob, lat, lon) -> datetime
        DOB + TOB, interpreted as LOCAL CIVIL TIME AT THE BIRTHPLACE
        (never as IST, never as the server's own clock), converted to
        a timezone-aware UTC datetime using the historically-correct
        DST/offset rules for that place and date.

SCOPE (T1/T2 -- read this before extending this file):
    This module answers exactly one question: "given this birth data,
    what is the correct UTC instant?" It has NO knowledge of Swiss
    Ephemeris, planets, Lagna, Moon, houses, or Dasha, and must never
    gain any -- see Section 20 of the governing audit/design task.
    full_kundali_api.py::calculate_planet_positions()/get_moon_
    longitude_lahiri() are NOT modified to call this module yet (that
    is Phase T3, a separate, explicitly-authorized future task) --
    today they still use their own existing hardcoded IST conversion,
    unchanged. Importing this module and calling it has ZERO effect on
    any existing report, API response, or natal calculation until T3
    happens.

DEPENDENCIES: timezonefinder (coordinate -> IANA zone name, offline,
no network call) and pytz (already used throughout this codebase for
Asia/Kolkata; here used for its own historical-DST-aware `.localize()`
behavior, which is what makes AmbiguousTimeError/NonExistentTimeError
detection possible -- see resolve_birth_utc_datetime()'s own
docstring).

FAILURE PHILOSOPHY (locked, matches this codebase's own established
"never silently guess" precedent -- e.g. ReportMetadataError elsewhere
in this repo): every failure mode raises BirthTimezoneError with a
machine-readable `.reason` code. This module NEVER falls back to
Asia/Kolkata, UTC, the server's own clock, or a guessed/nearest
timezone for any reason, for any coordinate -- including Indian
coordinates. A caller that wants "assume India on failure" behavior
must make that decision explicitly and visibly at its own call site;
this module will not make it silently on the caller's behalf.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional, Tuple

import pytz
from timezonefinder import TimezoneFinder

# One instance per process -- TimezoneFinder() loads its own bundled
# timezone-boundary data once at construction; every resolve_birth_
# timezone() call reuses it. No network call, no per-call I/O.
_TIMEZONE_FINDER = TimezoneFinder()

# ---------------------------------------------------------------------
# Reason codes -- machine-readable, stable strings a caller can branch
# on without parsing free-text messages. Never renamed once shipped.
# ---------------------------------------------------------------------
REASON_INVALID_COORDINATES = "INVALID_COORDINATES"
REASON_INVALID_DOB = "INVALID_DOB"
REASON_INVALID_TOB = "INVALID_TOB"
REASON_TIMEZONE_UNRESOLVABLE = "TIMEZONE_UNRESOLVABLE"
REASON_AMBIGUOUS_LOCAL_TIME = "AMBIGUOUS_LOCAL_TIME"
REASON_NONEXISTENT_LOCAL_TIME = "NONEXISTENT_LOCAL_TIME"


class BirthTimezoneError(Exception):
    """Raised for any birth-timezone-resolution failure. Deliberately a
    plain, standalone Exception subclass -- NOT report_structured_
    output.py's ReportMetadataError or any other payments/report-layer
    exception -- this module has no dependency on, and must never be
    coupled to, the paid-report pipeline. A future caller (T3+) decides
    how to translate this into whatever error class its own layer
    uses; this module only ever raises its own type.

    `.reason` is one of the REASON_* constants above -- always present,
    always one of the fixed set, safe to branch on. `.args`/str(exc)
    carries a human-readable message; internal tracebacks/library
    internals are never included in that message (only in Python's own
    exception chaining via `raise ... from exc`, which a caller can
    inspect but which is never itself part of the message string)."""

    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(message)


def _parse_coordinate(value, *, field_name: str, lo: float, hi: float) -> float:
    """Accepts a real number or a numeric string (matching how this
    platform already stores coordinates -- Order.latitude/longitude
    are String columns, AppUser.lat/lng are Float columns; both are
    supported identically here, never assuming one representation).
    Rejects None, empty, non-numeric, NaN, Infinity, and out-of-range
    values -- every rejection raises BirthTimezoneError(
    REASON_INVALID_COORDINATES, ...), never silently clamped or
    defaulted."""
    if value is None:
        raise BirthTimezoneError(
            REASON_INVALID_COORDINATES, f"{field_name} is required and was not provided."
        )
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise BirthTimezoneError(
            REASON_INVALID_COORDINATES, f"{field_name} must be a numeric value; got {value!r}."
        )
    if math.isnan(parsed) or math.isinf(parsed):
        raise BirthTimezoneError(
            REASON_INVALID_COORDINATES, f"{field_name} must be a finite number; got {value!r}."
        )
    if not (lo <= parsed <= hi):
        raise BirthTimezoneError(
            REASON_INVALID_COORDINATES,
            f"{field_name} must be between {lo} and {hi}; got {parsed}.",
        )
    return parsed


def resolve_birth_timezone(lat, lon) -> str:
    """Coordinates -> IANA timezone name. Coordinates are the sole
    authority -- this never consults a client-supplied timezone,
    country code, or current UTC offset, and never approximates from
    longitude/15 (see the governing audit's own explicit prohibitions).

    Raises BirthTimezoneError(REASON_INVALID_COORDINATES, ...) for a
    malformed lat/lon (None, empty, non-numeric, NaN, Infinity, or
    out-of-range -- latitude must be in [-90, 90], longitude in
    [-180, 180]).

    Raises BirthTimezoneError(REASON_TIMEZONE_UNRESOLVABLE, ...) if
    timezonefinder cannot resolve a zone for these (valid) coordinates,
    or resolves a name pytz itself does not recognize. In practice
    timezonefinder's own `timezone_at()` almost always returns SOME
    zone for any valid coordinate (open-ocean points resolve to a
    fixed-offset "Etc/GMT+-XX" zone, which pytz can still localize
    against -- no DST there, which is itself correct for international
    waters), so this path is rare, but is exercised directly in the
    test suite (a mocked resolver returning None) so it is never dead,
    untested code -- and, critically, no code here or anywhere in this
    module ever falls back to Asia/Kolkata/UTC/a guess when it fires.
    """
    lat_f = _parse_coordinate(lat, field_name="latitude", lo=-90.0, hi=90.0)
    lon_f = _parse_coordinate(lon, field_name="longitude", lo=-180.0, hi=180.0)

    try:
        zone_name = _TIMEZONE_FINDER.timezone_at(lat=lat_f, lng=lon_f)
    except Exception as exc:
        raise BirthTimezoneError(
            REASON_TIMEZONE_UNRESOLVABLE,
            f"Timezone lookup failed for latitude={lat_f}, longitude={lon_f}.",
        ) from exc

    if not zone_name:
        raise BirthTimezoneError(
            REASON_TIMEZONE_UNRESOLVABLE,
            f"No timezone could be resolved for latitude={lat_f}, longitude={lon_f}.",
        )

    try:
        pytz.timezone(zone_name)
    except pytz.exceptions.UnknownTimeZoneError as exc:
        raise BirthTimezoneError(
            REASON_TIMEZONE_UNRESOLVABLE,
            f"Resolved zone {zone_name!r} is not a timezone pytz recognizes.",
        ) from exc

    return zone_name


def _parse_dob(dob) -> Tuple[int, int, int]:
    """Accepts exactly the format the natal engine itself already
    accepts (full_kundali_api.py::calculate_planet_positions()'s own
    `dob.split('-')` + `map(int, ...)`) -- never broadened, never
    silently reinterpreted. A malformed value raises BirthTimezoneError
    (REASON_INVALID_DOB, ...)."""
    if not isinstance(dob, str):
        raise BirthTimezoneError(REASON_INVALID_DOB, f"dob must be a string; got {dob!r}.")
    parts = dob.split("-")
    if len(parts) != 3:
        raise BirthTimezoneError(
            REASON_INVALID_DOB, f"dob must be in YYYY-MM-DD format; got {dob!r}."
        )
    try:
        year, month, day = (int(p) for p in parts)
    except ValueError:
        raise BirthTimezoneError(
            REASON_INVALID_DOB, f"dob must be in YYYY-MM-DD format; got {dob!r}."
        )
    return year, month, day


def _parse_tob(tob) -> Tuple[int, int]:
    """Accepts exactly the format the natal engine itself already
    accepts (`tob.split(':')` + `map(int, ...)`, HH:MM, no seconds) --
    never broadened. A malformed value raises BirthTimezoneError
    (REASON_INVALID_TOB, ...)."""
    if not isinstance(tob, str):
        raise BirthTimezoneError(REASON_INVALID_TOB, f"tob must be a string; got {tob!r}.")
    parts = tob.split(":")
    if len(parts) != 2:
        raise BirthTimezoneError(
            REASON_INVALID_TOB, f"tob must be in HH:MM format; got {tob!r}."
        )
    try:
        hour, minute = (int(p) for p in parts)
    except ValueError:
        raise BirthTimezoneError(
            REASON_INVALID_TOB, f"tob must be in HH:MM format; got {tob!r}."
        )
    if not (0 <= hour <= 23):
        raise BirthTimezoneError(
            REASON_INVALID_TOB, f"tob hour must be between 0 and 23; got {tob!r}."
        )
    if not (0 <= minute <= 59):
        raise BirthTimezoneError(
            REASON_INVALID_TOB, f"tob minute must be between 0 and 59; got {tob!r}."
        )
    return hour, minute


def resolve_birth_utc_datetime(dob, tob, lat, lon) -> datetime:
    """DOB + TOB, interpreted as LOCAL CIVIL TIME AT THE BIRTHPLACE
    (resolved from lat/lon via resolve_birth_timezone() above -- never
    from any other source), converted to a timezone-aware UTC
    datetime using the historically-correct offset/DST rule for that
    place and calendar date.

    Returns a datetime whose `.tzinfo` is UTC (timezone-AWARE, never
    naive -- deliberate: a naive result would silently re-introduce
    exactly the ambiguity this module exists to eliminate. A future
    T3 integration converts this explicitly into whatever shape
    swe.julday()/full_kundali_api.py's own helpers expect; that
    conversion is out of this module's own responsibility).

    Failure contract (never silently resolved, never a guessed
    fallback):
      - malformed dob/tob -> BirthTimezoneError(REASON_INVALID_DOB /
        REASON_INVALID_TOB, ...), including a dob/tob pair that parses
        as integers but does not form a real calendar date/time (e.g.
        month=13, day=32, hour=25) -- Python's own datetime()
        constructor is the single source of truth for calendar
        validity here, never re-implemented.
      - malformed/unresolvable coordinates -> see
        resolve_birth_timezone()'s own docstring (same reasons).
      - a LOCAL civil time that occurs twice because of a DST
        "fall back" transition -> BirthTimezoneError
        (REASON_AMBIGUOUS_LOCAL_TIME, ...). Never silently picks the
        standard-time or DST-time interpretation.
      - a LOCAL civil time that never occurs because of a DST
        "spring forward" transition -> BirthTimezoneError
        (REASON_NONEXISTENT_LOCAL_TIME, ...). Never silently shifts it
        forward or backward by an hour.

    Implementation note: pytz's own `tz.localize(naive_dt, is_dst=None)`
    is the mechanism that makes both of the above failure modes
    detectable at all -- passing anything other than None for is_dst
    (or using a fixed-offset conversion, as the code this module is
    designed to eventually replace currently does) would silently
    pick a side instead of raising. This is deliberate and must not be
    "simplified" away in any future edit of this function.
    """
    year, month, day = _parse_dob(dob)
    hour, minute = _parse_tob(tob)

    zone_name = resolve_birth_timezone(lat, lon)
    tz = pytz.timezone(zone_name)

    try:
        naive_local = datetime(year, month, day, hour, minute)
    except ValueError as exc:
        raise BirthTimezoneError(
            REASON_INVALID_DOB,
            f"dob={dob!r} / tob={tob!r} do not form a valid calendar date/time: {exc}",
        ) from exc

    try:
        aware_local = tz.localize(naive_local, is_dst=None)
    except pytz.exceptions.AmbiguousTimeError as exc:
        raise BirthTimezoneError(
            REASON_AMBIGUOUS_LOCAL_TIME,
            f"{tob} on {dob} is ambiguous in {zone_name} -- this local clock time "
            "occurs twice due to a Daylight Saving Time 'fall back' transition.",
        ) from exc
    except pytz.exceptions.NonExistentTimeError as exc:
        raise BirthTimezoneError(
            REASON_NONEXISTENT_LOCAL_TIME,
            f"{tob} on {dob} does not exist in {zone_name} -- this local clock time "
            "is skipped by a Daylight Saving Time 'spring forward' transition.",
        ) from exc

    return aware_local.astimezone(pytz.UTC)
