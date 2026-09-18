# test_birth_timezone_natal_integration.py

"""
T3 integration regression suite -- proves the canonical birth-timezone
resolver (services/birth_timezone_resolver.py, T1/T2) is correctly
wired into the ONLY two customer-birth conversion points in the
canonical natal engine: full_kundali_api.py::calculate_planet_
positions() and full_kundali_api.py::get_moon_longitude_lahiri().

This file is deliberately separate from test_birth_timezone_resolver.py
(T1/T2's own unit tests, which stay resolver-only) -- everything here
exercises the real, integrated natal engine end to end.

Two proof strategies used throughout:
  1. INDIA EQUIVALENCE -- a `_legacy_utc_time()` replica of the OLD
     hardcoded `local_time - timedelta(hours=5, minutes=30)` formula
     (kept ONLY in this test file, never imported from production
     code) is used to independently recompute what the pre-T3 engine
     would have produced, and compared against the real, integrated
     engine's actual output for genuinely-Indian birthplaces. Since
     Asia/Kolkata's UTC offset is exactly +5:30, these must match
     exactly (bar float noise) -- proving zero regression for Indian
     customers.
  2. FOREIGN CORRECTION -- the same legacy replica proves the OLD
     engine's foreign-birth output was wrong (it diverges from the
     real engine's now-correct output), while the real engine's output
     is checked against values captured directly from the actual,
     currently-integrated engine (never hand-typed/estimated).
"""

from datetime import datetime, timedelta

import swisseph as swe

from full_kundali_api import (
    calculate_planet_positions,
    get_moon_longitude_lahiri,
    calculate_full_kundali,
    SIGNS,
)
from services.birth_timezone_resolver import BirthTimezoneError

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


def close(a, b, tol=0.05):
    return abs(a - b) <= tol


# ---------------------------------------------------------------------
# Legacy replica -- reproduces the EXACT pre-T3 formula, kept only here
# for comparison. Never imported from / never touches production code.
# ---------------------------------------------------------------------
def _legacy_utc_time(dob, tob):
    year, month, day = map(int, dob.split('-'))
    hour, minute = map(int, tob.split(':'))
    local_time = datetime(year, month, day, hour, minute)
    return local_time - timedelta(hours=5, minutes=30)


def _legacy_moon_degree(dob, tob):
    utc_dt = _legacy_utc_time(dob, tob)
    jd_ut = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day,
                        utc_dt.hour + utc_dt.minute / 60.0)
    moon_long = swe.calc_ut(jd_ut, swe.MOON)[0][0]
    ayanamsa = swe.get_ayanamsa_ut(jd_ut)
    return (moon_long - ayanamsa) % 360


def _legacy_lagna_degree(dob, tob, lat, lon):
    utc_dt = _legacy_utc_time(dob, tob)
    jd_ut = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day,
                        utc_dt.hour + utc_dt.minute / 60.0)
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    cusps, ascmc = swe.houses(jd_ut, float(lat), float(lon), b'P')
    tropical_lagna = ascmc[0]
    ayanamsa = swe.get_ayanamsa(jd_ut)
    return (tropical_lagna - ayanamsa) % 360


# ---------------------------------------------------------------------
# 1. India golden regression -- integrated engine vs. legacy replica.
#    Must match (bar float noise): Asia/Kolkata offset == old -05:30.
# ---------------------------------------------------------------------
INDIA_CITIES = {
    "Lucknow": (26.8467, 80.9462),
    "Delhi": (28.7041, 77.1025),
    "Mumbai": (19.0760, 72.8777),
    "Kolkata": (22.5726, 88.3639),
}
DOB, TOB = "1990-06-15", "14:30"

for city, (lat, lon) in INDIA_CITIES.items():
    planets = calculate_planet_positions(DOB, TOB, lat, lon)
    moon = next(p for p in planets if p["name"] == "Moon")
    lagna = next(p for p in planets if "Ascendant" in p["name"])
    moon_lahiri = get_moon_longitude_lahiri(DOB, TOB, lat, lon)

    legacy_moon = _legacy_moon_degree(DOB, TOB)
    legacy_lagna_abs = _legacy_lagna_degree(DOB, TOB, lat, lon)
    legacy_lagna_sign_index = int(legacy_lagna_abs // 30)
    legacy_lagna_deg = legacy_lagna_abs % 30
    legacy_lagna_sign = SIGNS[legacy_lagna_sign_index]

    check(f"India golden ({city}): moon_longitude_lahiri matches legacy formula",
          close(moon_lahiri, legacy_moon, tol=0.01))
    check(f"India golden ({city}): calculate_planet_positions Moon sign matches legacy",
          moon["sign"] == SIGNS[int(legacy_moon // 30)])
    check(f"India golden ({city}): Lagna sign matches legacy", lagna["sign"] == legacy_lagna_sign)
    check(f"India golden ({city}): Lagna degree matches legacy", close(lagna["degree"], legacy_lagna_deg, tol=0.01))

# ---------------------------------------------------------------------
# 2. Nepal correction -- Kathmandu is NOT +5:30, UTC is 08:45 not 09:00.
# ---------------------------------------------------------------------
KATHMANDU = (27.7172, 85.3240)
kathmandu_planets = calculate_planet_positions(DOB, TOB, *KATHMANDU)
kathmandu_moon = next(p for p in kathmandu_planets if p["name"] == "Moon")
kathmandu_lagna = next(p for p in kathmandu_planets if "Ascendant" in p["name"])

check("Nepal correction: Kathmandu Moon sign == Aquarius (captured engine value)",
      kathmandu_moon["sign"] == "Aquarius")
check("Nepal correction: Kathmandu Moon degree == 19.82 (captured engine value)",
      close(kathmandu_moon["degree"], 19.82, tol=0.01))
check("Nepal correction: Kathmandu Lagna sign == Libra (captured engine value)",
      kathmandu_lagna["sign"] == "Libra")
check("Nepal correction: Kathmandu Lagna degree == 2.72 (captured engine value)",
      close(kathmandu_lagna["degree"], 2.72, tol=0.01))
check("Nepal correction: Kathmandu Lagna degree DIFFERS from legacy (+5:30-assumption) Lagna degree",
      not close(kathmandu_lagna["degree"], _legacy_lagna_degree(DOB, TOB, *KATHMANDU) % 30, tol=0.01)
      or SIGNS[int(_legacy_lagna_degree(DOB, TOB, *KATHMANDU) // 30)] != kathmandu_lagna["sign"])

# ---------------------------------------------------------------------
# 3. New York winter/summer correction.
# ---------------------------------------------------------------------
NEW_YORK = (40.7128, -74.0060)

ny_winter_planets = calculate_planet_positions("1990-01-15", "14:30", *NEW_YORK)
ny_winter_moon = next(p for p in ny_winter_planets if p["name"] == "Moon")
ny_winter_lagna = next(p for p in ny_winter_planets if "Ascendant" in p["name"])
check("NY winter: Moon sign == Leo (captured engine value)", ny_winter_moon["sign"] == "Leo")
check("NY winter: Moon degree == 27.66 (captured engine value)", close(ny_winter_moon["degree"], 27.66, tol=0.01))
check("NY winter: Lagna sign == Gemini (captured engine value)", ny_winter_lagna["sign"] == "Gemini")

ny_summer_planets = calculate_planet_positions("1990-07-15", "14:30", *NEW_YORK)
ny_summer_moon = next(p for p in ny_summer_planets if p["name"] == "Moon")
ny_summer_lagna = next(p for p in ny_summer_planets if "Ascendant" in p["name"])
ny_summer_moon_lahiri = get_moon_longitude_lahiri("1990-07-15", "14:30", *NEW_YORK)

# Task-specified independently-audited correction target:
# legacy (wrong): Moon ~357.78 deg, Pisces, Revati
# correct:        Moon ~3.33 deg, Aries, Ashwini
check("NY summer: Moon sign == Aries (matches independently-audited correction target)",
      ny_summer_moon["sign"] == "Aries")
check("NY summer: Moon degree ~= 3.33 (matches independently-audited correction target)",
      close(ny_summer_moon["degree"], 3.33, tol=0.05))
check("NY summer: Nakshatra == Ashwini (matches independently-audited correction target)",
      ny_summer_moon["nakshatra"] == "Ashwini")
check("NY summer: Lagna sign == Libra (captured engine value)", ny_summer_lagna["sign"] == "Libra")

legacy_ny_summer_moon = _legacy_moon_degree("1990-07-15", "14:30")
check("NY summer: legacy (buggy IST-assumption) Moon sign == Pisces (proves old code was wrong)",
      SIGNS[int(legacy_ny_summer_moon // 30)] == "Pisces")
check("NY summer: corrected Moon sign DIFFERS from legacy buggy Moon sign",
      SIGNS[int(legacy_ny_summer_moon // 30)] != ny_summer_moon["sign"])
check("NY summer: corrected moon_longitude_lahiri DIFFERS from legacy by more than a few degrees",
      abs(ny_summer_moon_lahiri - legacy_ny_summer_moon) > 5.0)

# ---------------------------------------------------------------------
# 4. London winter/summer correction.
# ---------------------------------------------------------------------
LONDON = (51.5074, -0.1278)

london_winter_planets = calculate_planet_positions("1990-01-15", "14:30", *LONDON)
london_winter_moon = next(p for p in london_winter_planets if p["name"] == "Moon")
check("London winter: Moon sign == Leo (captured engine value)", london_winter_moon["sign"] == "Leo")
check("London winter: Moon degree == 25.07 (captured engine value)", close(london_winter_moon["degree"], 25.07, tol=0.01))

london_summer_planets = calculate_planet_positions("1990-07-15", "14:30", *LONDON)
london_summer_moon = next(p for p in london_summer_planets if p["name"] == "Moon")
check("London summer: Moon sign == Aries (captured engine value)", london_summer_moon["sign"] == "Aries")
check("London summer: Moon degree == 0.40 (captured engine value)", close(london_summer_moon["degree"], 0.40, tol=0.01))
check("London winter/summer: same coordinates produce DIFFERENT Moon degrees by season (historical-rule guard)",
      not close(london_winter_moon["degree"] + 120, london_summer_moon["degree"], tol=0.01) and
      (london_winter_moon["sign"], round(london_winter_moon["degree"], 2)) !=
      (london_summer_moon["sign"], round(london_summer_moon["degree"], 2)))

# ---------------------------------------------------------------------
# 5. UTC date-rollover test -- local dob 1990-01-15, but 23:30 in
#    America/New_York (EST, -5:00) rolls over to UTC 1990-01-16.
#    Guards against a subtle bug: "correct UTC hour + original local
#    DOB" (i.e. forgetting the date can also change) would still be
#    astronomically wrong -- this proves the actual engine output
#    matches the TRUE rolled-over-date computation, not that shape.
# ---------------------------------------------------------------------
ROLLOVER_DOB, ROLLOVER_TOB = "1990-01-15", "23:30"
rollover_planets = calculate_planet_positions(ROLLOVER_DOB, ROLLOVER_TOB, *NEW_YORK)
rollover_moon = next(p for p in rollover_planets if p["name"] == "Moon")
rollover_moon_lahiri = get_moon_longitude_lahiri(ROLLOVER_DOB, ROLLOVER_TOB, *NEW_YORK)

# TRUE computation: UTC is 1990-01-16 04:30 (correct rolled-over date).
true_rollover_jd = swe.julday(1990, 1, 16, 4 + 30 / 60.0)
true_rollover_moon_long = swe.calc_ut(true_rollover_jd, swe.MOON)[0][0]
true_rollover_ayanamsa = swe.get_ayanamsa_ut(true_rollover_jd)
true_rollover_moon_deg = (true_rollover_moon_long - true_rollover_ayanamsa) % 360

# WRONG (subtle-bug) computation: correct UTC hour (04:30) but the
# ORIGINAL local calendar date (1990-01-15) -- i.e. failing to roll
# the date over. This must NOT match the actual engine's output.
wrong_jd = swe.julday(1990, 1, 15, 4 + 30 / 60.0)
wrong_moon_long = swe.calc_ut(wrong_jd, swe.MOON)[0][0]
wrong_ayanamsa = swe.get_ayanamsa_ut(wrong_jd)
wrong_moon_deg = (wrong_moon_long - wrong_ayanamsa) % 360

check("UTC rollover: engine's moon_longitude_lahiri matches the TRUE rolled-over UTC date (1990-01-16)",
      close(rollover_moon_lahiri, true_rollover_moon_deg, tol=0.01))
check("UTC rollover: engine's moon_longitude_lahiri does NOT match the subtly-wrong same-local-date computation",
      not close(rollover_moon_lahiri, wrong_moon_deg, tol=0.01))
check("UTC rollover: calculate_planet_positions' Moon sign matches the TRUE rolled-over-date sign",
      rollover_moon["sign"] == SIGNS[int(true_rollover_moon_deg // 30)])

# ---------------------------------------------------------------------
# 6. DST ambiguous/nonexistent local time -- must propagate
#    BirthTimezoneError uncaught, through all three engine entry
#    points, with ZERO silent chart produced.
# ---------------------------------------------------------------------
AMBIGUOUS_DOB, AMBIGUOUS_TOB = "2023-11-05", "01:30"
NONEXISTENT_DOB, NONEXISTENT_TOB = "2023-03-12", "02:30"

for label, dob, tob in [
    ("ambiguous (America/New_York fall-back)", AMBIGUOUS_DOB, AMBIGUOUS_TOB),
    ("nonexistent (America/New_York spring-forward)", NONEXISTENT_DOB, NONEXISTENT_TOB),
]:
    try:
        calculate_planet_positions(dob, tob, *NEW_YORK)
        check(f"calculate_planet_positions raises BirthTimezoneError for {label} local time", False)
    except BirthTimezoneError:
        check(f"calculate_planet_positions raises BirthTimezoneError for {label} local time", True)

    try:
        get_moon_longitude_lahiri(dob, tob, *NEW_YORK)
        check(f"get_moon_longitude_lahiri raises BirthTimezoneError for {label} local time", False)
    except BirthTimezoneError:
        check(f"get_moon_longitude_lahiri raises BirthTimezoneError for {label} local time", True)

    try:
        calculate_full_kundali("DST Test", dob, tob, *NEW_YORK, user_id=None, language="en")
        check(f"calculate_full_kundali raises BirthTimezoneError for {label} local time (no silent chart)", False)
    except BirthTimezoneError:
        check(f"calculate_full_kundali raises BirthTimezoneError for {label} local time (no silent chart)", True)

# ---------------------------------------------------------------------
# 7. calculate_full_kundali end-to-end -- India / NY / London / Kathmandu.
# ---------------------------------------------------------------------
E2E_FIXTURES = {
    "India (Lucknow)": ("1990-06-15", "14:30", 26.8467, 80.9462),
    "New York": ("1990-07-15", "14:30", 40.7128, -74.0060),
    "London": ("1990-07-15", "14:30", 51.5074, -0.1278),
    "Kathmandu": ("1990-06-15", "14:30", 27.7172, 85.3240),
}
for label, (dob, tob, lat, lon) in E2E_FIXTURES.items():
    result = calculate_full_kundali(f"E2E {label}", dob, tob, lat, lon, user_id=None, language="en")
    check(f"calculate_full_kundali ({label}) completes and returns lagna_sign", bool(result.get("lagna_sign")))
    check(f"calculate_full_kundali ({label}) returns rashi (moon sign)", bool(result.get("rashi")))
    check(f"calculate_full_kundali ({label}) returns non-empty planets list", len(result.get("planets") or []) > 0)
    check(f"calculate_full_kundali ({label}) returns non-empty Mahadasha sequence", len(result.get("Mahadasha") or []) > 0)
    check(f"calculate_full_kundali ({label}) returns current_mahadasha", bool(result.get("current_mahadasha")))
    check(f"calculate_full_kundali ({label}) latitude/longitude in output match input (customer coords preserved)",
          float(result["latitude"]) == float(lat) and float(result["longitude"]) == float(lon))

# NY end-to-end must reflect the SAME corrected Moon sign proven above.
ny_e2e = calculate_full_kundali("E2E NY check", "1990-07-15", "14:30", *NEW_YORK, user_id=None, language="en")
check("calculate_full_kundali (New York) rashi == Aries (matches corrected lower-level Moon sign)",
      ny_e2e["rashi"] == "Aries")

# ---------------------------------------------------------------------
# 8. Ascendant coordinates preserved -- customer lat/lon, not a
#    timezone/location-derived substitute, still drives swe.houses().
#    Same UTC instant (India fixture), different real coordinates ->
#    different Lagna, proving lat/lon is not being overridden/ignored.
# ---------------------------------------------------------------------
delhi_planets = calculate_planet_positions(DOB, TOB, 28.7041, 77.1025)
mumbai_planets = calculate_planet_positions(DOB, TOB, 19.0760, 72.8777)
delhi_lagna = next(p for p in delhi_planets if "Ascendant" in p["name"])
mumbai_lagna = next(p for p in mumbai_planets if "Ascendant" in p["name"])
check("Ascendant coordinates preserved: Delhi and Mumbai (different lat/lon, same UTC instant) produce different Lagna degrees",
      not close(delhi_lagna["degree"], mumbai_lagna["degree"], tol=0.01) or delhi_lagna["sign"] != mumbai_lagna["sign"])

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
    print("ALL T3 NATAL INTEGRATION TESTS PASSED")
