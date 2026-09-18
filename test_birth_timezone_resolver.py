# test_birth_timezone_resolver.py

"""
Permanent regression suite for services/birth_timezone_resolver.py
(Foreign Birth Timezone Correctness project, Phase T1/T2).

This module is NOT integrated into full_kundali_api.py yet (that is a
separate, explicitly-authorized future T3 task) -- these tests only
prove the resolver itself is correct in isolation. Every UTC fixture
value below was independently re-verified via direct pytz computation
before being hardcoded here (not copied from the earlier audit without
re-checking), per this task's own instruction.

Uses the same plain check()-harness/print style already established
by test_report_q3_batch1.py..batch5.py and test_sadhesati_classifier.py
elsewhere in this repo.
"""

from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

import pytz

from services.birth_timezone_resolver import (
    BirthTimezoneError,
    REASON_INVALID_COORDINATES,
    REASON_INVALID_DOB,
    REASON_INVALID_TOB,
    REASON_TIMEZONE_UNRESOLVABLE,
    REASON_AMBIGUOUS_LOCAL_TIME,
    REASON_NONEXISTENT_LOCAL_TIME,
    resolve_birth_timezone,
    resolve_birth_utc_datetime,
)

_PASSED = 0
_FAILED = 0
_FAILURES = []


def check(label, condition):
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"PASS: {label}")
    else:
        _FAILED += 1
        _FAILURES.append(label)
        print(f"FAIL: {label}")


def utc(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


# ---------------------------------------------------------------------
# 1. India equivalence -- proves T1/T2 reproduces the legacy hardcoded
#    -05:30 conversion exactly for genuinely-Indian birthplaces.
# ---------------------------------------------------------------------
INDIA_CITIES = {
    "Lucknow": (26.8467, 80.9462),
    "Delhi": (28.7041, 77.1025),
    "Mumbai": (19.0760, 72.8777),
    "Kolkata": (22.5726, 88.3639),
}
for city, (lat, lon) in INDIA_CITIES.items():
    zone = resolve_birth_timezone(lat, lon)
    check(f"India equivalence: {city} resolves to Asia/Kolkata", zone == "Asia/Kolkata")
    result = resolve_birth_utc_datetime("1990-06-15", "14:30", lat, lon)
    check(
        f"India equivalence: {city} UTC == legacy -05:30 result (1990-06-15 09:00:00+00:00)",
        result == utc(1990, 6, 15, 9, 0),
    )
    check(f"India equivalence: {city} result is timezone-aware", result.tzinfo is not None)

# ---------------------------------------------------------------------
# 2. Nepal -- proves T1/T2 is NOT the old defective +05:30 assumption.
# ---------------------------------------------------------------------
KATHMANDU = (27.7172, 85.3240)
zone = resolve_birth_timezone(*KATHMANDU)
check("Kathmandu resolves to Asia/Kathmandu", zone == "Asia/Kathmandu")
result = resolve_birth_utc_datetime("1990-06-15", "14:30", *KATHMANDU)
check(
    "Kathmandu UTC == 1990-06-15 08:45:00+00:00 (NOT the defective 09:00:00 IST assumption)",
    result == utc(1990, 6, 15, 8, 45),
)
check("Kathmandu UTC != old defective IST-assumption result", result != utc(1990, 6, 15, 9, 0))

# ---------------------------------------------------------------------
# 3. New York DST winter/summer -- same zone, different offset by date.
# ---------------------------------------------------------------------
NEW_YORK = (40.7128, -74.0060)
zone = resolve_birth_timezone(*NEW_YORK)
check("New York resolves to America/New_York", zone == "America/New_York")

ny_winter = resolve_birth_utc_datetime("1990-01-15", "14:30", *NEW_YORK)
check("New York winter (EST, -5:00) UTC == 1990-01-15 19:30:00+00:00", ny_winter == utc(1990, 1, 15, 19, 30))

ny_summer = resolve_birth_utc_datetime("1990-07-15", "14:30", *NEW_YORK)
check("New York summer (EDT, -4:00) UTC == 1990-07-15 18:30:00+00:00", ny_summer == utc(1990, 7, 15, 18, 30))

_ny_tz = pytz.timezone(zone)
_ny_winter_offset = _ny_tz.localize(datetime(1990, 1, 15, 14, 30), is_dst=None).utcoffset()
_ny_summer_offset = _ny_tz.localize(datetime(1990, 7, 15, 14, 30), is_dst=None).utcoffset()
check(
    "New York historical-rule guard: same coords/zone, different UTC offset by season",
    (_ny_winter_offset != _ny_summer_offset) and (ny_winter != ny_summer),
)

# ---------------------------------------------------------------------
# 4. London DST winter/summer.
# ---------------------------------------------------------------------
LONDON = (51.5074, -0.1278)
zone = resolve_birth_timezone(*LONDON)
check("London resolves to Europe/London", zone == "Europe/London")

london_winter = resolve_birth_utc_datetime("1990-01-15", "14:30", *LONDON)
check("London winter (GMT, +0:00) UTC == 1990-01-15 14:30:00+00:00", london_winter == utc(1990, 1, 15, 14, 30))

london_summer = resolve_birth_utc_datetime("1990-07-15", "14:30", *LONDON)
check("London summer (BST, +1:00) UTC == 1990-07-15 13:30:00+00:00", london_summer == utc(1990, 7, 15, 13, 30))

# ---------------------------------------------------------------------
# 5. Sydney / Singapore.
# ---------------------------------------------------------------------
SYDNEY = (-33.8688, 151.2093)
zone = resolve_birth_timezone(*SYDNEY)
check("Sydney resolves to Australia/Sydney", zone == "Australia/Sydney")
sydney_result = resolve_birth_utc_datetime("1990-07-15", "14:30", *SYDNEY)
check("Sydney UTC == 1990-07-15 04:30:00+00:00", sydney_result == utc(1990, 7, 15, 4, 30))

SINGAPORE = (1.3521, 103.8198)
zone = resolve_birth_timezone(*SINGAPORE)
check("Singapore resolves to Asia/Singapore", zone == "Asia/Singapore")
singapore_result = resolve_birth_utc_datetime("1990-06-15", "14:30", *SINGAPORE)
check("Singapore UTC == 1990-06-15 06:30:00+00:00", singapore_result == utc(1990, 6, 15, 6, 30))

# ---------------------------------------------------------------------
# 6. DST-ambiguous local time (America/New_York fall-back, verified
#    directly via pytz: 2023-11-05 01:30 occurs twice).
# ---------------------------------------------------------------------
try:
    resolve_birth_utc_datetime("2023-11-05", "01:30", *NEW_YORK)
    check("Ambiguous local time (2023-11-05 01:30 America/New_York) raises BirthTimezoneError", False)
except BirthTimezoneError as exc:
    check(
        "Ambiguous local time raises BirthTimezoneError with reason AMBIGUOUS_LOCAL_TIME",
        exc.reason == REASON_AMBIGUOUS_LOCAL_TIME,
    )

# Bracketing sanity: times either side of the fall-back transition still resolve normally.
check(
    "Bracket check: 2023-11-05 00:30 America/New_York resolves without error",
    resolve_birth_utc_datetime("2023-11-05", "00:30", *NEW_YORK) is not None,
)
check(
    "Bracket check: 2023-11-05 02:30 America/New_York resolves without error",
    resolve_birth_utc_datetime("2023-11-05", "02:30", *NEW_YORK) is not None,
)

# ---------------------------------------------------------------------
# 7. DST-nonexistent local time (America/New_York spring-forward,
#    verified directly via pytz: 2023-03-12 02:30 never occurs).
# ---------------------------------------------------------------------
try:
    resolve_birth_utc_datetime("2023-03-12", "02:30", *NEW_YORK)
    check("Nonexistent local time (2023-03-12 02:30 America/New_York) raises BirthTimezoneError", False)
except BirthTimezoneError as exc:
    check(
        "Nonexistent local time raises BirthTimezoneError with reason NONEXISTENT_LOCAL_TIME",
        exc.reason == REASON_NONEXISTENT_LOCAL_TIME,
    )

check(
    "Bracket check: 2023-03-12 01:30 America/New_York resolves without error",
    resolve_birth_utc_datetime("2023-03-12", "01:30", *NEW_YORK) is not None,
)
check(
    "Bracket check: 2023-03-12 03:30 America/New_York resolves without error",
    resolve_birth_utc_datetime("2023-03-12", "03:30", *NEW_YORK) is not None,
)

# ---------------------------------------------------------------------
# 8. Invalid-coordinate inputs -- every case must fail explicitly.
# ---------------------------------------------------------------------
INVALID_COORDINATE_CASES = [
    ("lat > 90", 90.0001, 0.0),
    ("lat < -90", -90.0001, 0.0),
    ("lon > 180", 0.0, 180.0001),
    ("lon < -180", 0.0, -180.0001),
    ("lat is NaN", float("nan"), 0.0),
    ("lat is Infinity", float("inf"), 0.0),
    ("lon is -Infinity", 0.0, float("-inf")),
    ("lat is None", None, 0.0),
    ("lon is empty string", 0.0, ""),
    ("lat is non-numeric string", "not-a-number", 0.0),
]
for label, bad_lat, bad_lon in INVALID_COORDINATE_CASES:
    try:
        resolve_birth_timezone(bad_lat, bad_lon)
        check(f"Invalid coordinates ({label}) raises BirthTimezoneError", False)
    except BirthTimezoneError as exc:
        check(
            f"Invalid coordinates ({label}) raises BirthTimezoneError with reason INVALID_COORDINATES",
            exc.reason == REASON_INVALID_COORDINATES,
        )

# Numeric strings ARE accepted (matches Order model's String-typed lat/lon columns).
zone = resolve_birth_timezone("28.7041", "77.1025")
check("Numeric-string coordinates are accepted", zone == "Asia/Kolkata")

# ---------------------------------------------------------------------
# 9. Invalid DOB / TOB inputs.
# ---------------------------------------------------------------------
INVALID_DOB_CASES = ["not-a-date", "1990/06/15", "1990-13-01", "1990-06-32", "", None, 19900615]
for bad_dob in INVALID_DOB_CASES:
    try:
        resolve_birth_utc_datetime(bad_dob, "14:30", *NEW_YORK)
        check(f"Invalid dob ({bad_dob!r}) raises BirthTimezoneError", False)
    except BirthTimezoneError as exc:
        check(
            f"Invalid dob ({bad_dob!r}) raises BirthTimezoneError with reason INVALID_DOB",
            exc.reason == REASON_INVALID_DOB,
        )

INVALID_TOB_CASES = ["not-a-time", "14:30:00", "25:00", "14:70", "", None, 1430]
for bad_tob in INVALID_TOB_CASES:
    try:
        resolve_birth_utc_datetime("1990-06-15", bad_tob, *NEW_YORK)
        check(f"Invalid tob ({bad_tob!r}) raises BirthTimezoneError", False)
    except BirthTimezoneError as exc:
        check(
            f"Invalid tob ({bad_tob!r}) raises BirthTimezoneError with reason INVALID_TOB",
            exc.reason == REASON_INVALID_TOB,
        )

# ---------------------------------------------------------------------
# 10. Unresolvable timezone -- mocked timezonefinder returning None
#     must fail explicitly, with ZERO fallback to IST/UTC.
# ---------------------------------------------------------------------
with patch("services.birth_timezone_resolver._TIMEZONE_FINDER") as mock_finder:
    mock_finder.timezone_at.return_value = None
    try:
        resolve_birth_timezone(28.7041, 77.1025)
        check("Mocked unresolvable timezone raises BirthTimezoneError", False)
    except BirthTimezoneError as exc:
        check(
            "Mocked unresolvable timezone raises BirthTimezoneError with reason TIMEZONE_UNRESOLVABLE",
            exc.reason == REASON_TIMEZONE_UNRESOLVABLE,
        )
    try:
        result = resolve_birth_utc_datetime("1990-06-15", "14:30", 28.7041, 77.1025)
        check("Mocked unresolvable timezone in resolve_birth_utc_datetime raises (no silent IST fallback)", False)
    except BirthTimezoneError as exc:
        check(
            "Mocked unresolvable timezone in resolve_birth_utc_datetime raises TIMEZONE_UNRESOLVABLE (no fallback)",
            exc.reason == REASON_TIMEZONE_UNRESOLVABLE,
        )

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------
print()
print(f"TOTAL PASSED: {_PASSED}")
print(f"TOTAL FAILED: {_FAILED}")
if _FAILURES:
    print("FAILED CHECKS:")
    for f in _FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("ALL BIRTH TIMEZONE RESOLVER TESTS PASSED")
