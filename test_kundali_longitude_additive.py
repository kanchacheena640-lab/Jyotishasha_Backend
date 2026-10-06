"""
SNR-2B -- the full-precision `longitude` field added to every planet and
the Ascendant record by full_kundali_api.calculate_planet_positions() is
ADDITIVE: every pre-existing field keeps its exact value and meaning, and
`longitude` is consistent with them.

Plain check()-harness. Run:  python test_kundali_longitude_additive.py
"""

import sys

from full_kundali_api import SIGNS, calculate_full_kundali, calculate_planet_positions, get_nakshatra_pada

PASSED = 0
FAILED = 0


def check(label, condition):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


PRE_EXISTING_KEYS = {"name", "degree", "sign", "house", "nakshatra", "pada"}
NAMES = {"Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Rahu", "Ketu", "Ascendant (Lagna)"}
CHARTS = [
    ("Aarav Sharma", "1990-06-15", "14:30", 26.8467, 80.9462),
    ("Delhi Dawn", "1985-01-01", "05:10", 28.6139, 77.2090),
    ("Mumbai Night", "2001-11-23", "23:45", 19.0760, 72.8777),
    ("New York", "1990-07-15", "14:30", 40.7128, -74.0060),
]

for name, dob, tob, lat, lon in CHARTS:
    print(f"\n=== {name} ===")
    positions = calculate_planet_positions(dob, tob, lat, lon)
    by_name = {p["name"]: p for p in positions}
    check("same 10 records as before (9 grahas + Ascendant)", set(by_name) == NAMES and len(positions) == 10)
    check("record keys == pre-existing keys + 'longitude' (nothing removed/renamed)",
          all(set(p) == PRE_EXISTING_KEYS | {"longitude"} for p in positions))
    check("0 <= longitude < 360", all(0 <= p["longitude"] < 360 for p in positions))
    check("sign == SIGNS[floor(longitude / 30)]", all(p["sign"] == SIGNS[int(p["longitude"] // 30)] for p in positions))
    check("degree == round(longitude % 30, 2) (rounded semantics unchanged)", all(p["degree"] == round(p["longitude"] % 30, 2) for p in positions))
    check("nakshatra/pada == get_nakshatra_pada(longitude)", all((p["nakshatra"], p["pada"]) == get_nakshatra_pada(p["longitude"]) for p in positions))
    asc = by_name["Ascendant (Lagna)"]
    check("whole-sign house unchanged: (sign - lagna sign) mod 12 + 1",
          all(p["house"] == (SIGNS.index(p["sign"]) - SIGNS.index(asc["sign"])) % 12 + 1 for p in positions))
    check("Ketu longitude is exactly Rahu + 180", abs(((by_name["Rahu"]["longitude"] + 180) % 360) - by_name["Ketu"]["longitude"]) < 1e-9)
    check("full-precision longitude is not the rounded degree (it carries more than 2 decimals for at least one record)",
          any(abs(p["longitude"] % 30 - p["degree"]) > 0 for p in positions))
    kund = calculate_full_kundali(name=name, dob=dob, tob=tob, lat=lat, lon=lon, language="en")
    check("calculate_full_kundali() planets carry the same additive longitude",
          all("longitude" in p for p in kund["planets"]) and {p["name"]: p["longitude"] for p in kund["planets"]} == {p["name"]: p["longitude"] for p in positions})

print(f"\nRESULTS: {PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
