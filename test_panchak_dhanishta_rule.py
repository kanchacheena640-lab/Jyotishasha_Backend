"""
test_panchak_dhanishta_rule.py
------------------------------
Panchak = the Moon in Kumbha or Meena (sidereal 300-360 deg): from Dhanishta pada 3 to the end
of Revati. Dhanishta padas 1-2 lie in Makara and are NOT Panchak. calculate_panchang used to
mark every Dhanishta pada as Panchak, contradicting the website copy ("Dhanishta (last two
padas)", "begins when the Moon enters the third pada of Dhanishta").

Uses REAL Swiss Ephemeris positions (nothing astronomical is mocked): the exact moments the Moon
crosses 300 deg (Dhanishta pada 2 -> 3) and 360 deg (Revati -> Ashwini) are found by bisection,
and calculate_panchang is evaluated just before/after each via ref_dt_ist. Sunrise-based dates
the website and app actually show are checked too. No database, Celery or network.

Run:  python test_panchak_dhanishta_rule.py
"""

import sys
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.astro_core import sidereal_longitudes
from services.panchang_engine import calculate_panchang

LUCKNOW = (26.8467, 80.9462)  # reference location the website sends
PANCHAK_TRUE_EN = "⚠️ Panchak Kaal in effect – avoid construction, travel, and cremation."
PANCHAK_FALSE_EN = "✅ No Panchak today."
PANCHAK_FALSE_HI = "✅ आज पंचक नहीं है।"

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def moon_lon(dt):
    return sidereal_longitudes(dt)[1] % 360.0


def crossing(target_deg, start):
    """First IST moment after `start` at which the Moon's sidereal longitude reaches target_deg."""
    def off(t):  # signed angular distance moon - target, in (-180, 180]
        return ((moon_lon(t) - target_deg + 180.0) % 360.0) - 180.0
    t, step = start, timedelta(hours=1)
    while not (off(t) < 0 <= off(t + step)):
        t += step
        if t - start > timedelta(days=30):
            raise RuntimeError(f"no crossing of {target_deg} within 30 days of {start}")
    lo, hi = t, t + step
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) / 2
        lo, hi = (mid, hi) if off(mid) < 0 else (lo, mid)
    return hi


def panchang_at(dt, language="en"):
    return calculate_panchang(dt.date(), *LUCKNOW, language=language, ref_dt_ist=dt)


def state(dt, language="en"):
    r = panchang_at(dt, language)
    return r["nakshatra"]["name"], r["nakshatra"]["pada"], r["panchak"]


def expect(label, dt, nak, pada, active):
    n, p, pk = state(dt)
    check(f"{label}: {n} pada {p} -> active={pk['active']}",
          n == nak and (pada is None or p == pada) and pk["active"] is active,
          f"(expected {nak} pada {pada} active={active})")
    if active:
        check(f"{label}: active message + nakshatra", pk["message"] == PANCHAK_TRUE_EN and pk["nakshatra"] == nak)
    else:
        check(f"{label}: inactive message, no nakshatra", pk["message"] == PANCHAK_FALSE_EN and pk["nakshatra"] is None)


print("=== A. Start boundary: Moon enters Kumbha (300 deg) = Dhanishta pada 3 ===")
t300 = crossing(300.0, datetime(2026, 12, 13, 0, 0))
print(f"  Moon reaches 300 deg at {t300:%Y-%m-%d %H:%M:%S} IST")
before, after = t300 - timedelta(minutes=10), t300 + timedelta(minutes=10)
expect("10 min before 300 deg", before, "Dhanishta", 2, False)
expect("10 min after 300 deg", after, "Dhanishta", 3, True)
hi_before = panchang_at(before, "hi")["panchak"]
check("Hindi: Dhanishta pada 2 shows the no-Panchak message",
      hi_before["active"] is False and hi_before["message"] == PANCHAK_FALSE_HI and hi_before["nakshatra"] is None)

print("\n=== B. Every pada/nakshatra between Shravana and Ashwini ===")
# Moon moves ~13 deg/day; sample the middle of each pada (3 deg 20') across 290-361 deg.
span, pada_span = 360.0 / 27.0, 360.0 / 108.0
cases = [  # (nakshatra index 0-based, pada, expected active)
    (21, 4, False),                                   # Shravana pada 4 (Makara)
    (22, 1, False), (22, 2, False),                   # Dhanishta padas 1-2 (Makara)
    (22, 3, True), (22, 4, True),                     # Dhanishta padas 3-4 (Kumbha)
    (23, 1, True), (23, 4, True),                     # Shatabhisha
    (24, 1, True), (24, 4, True),                     # Purva Bhadrapada (pada 4 is in Meena)
    (25, 1, True), (25, 4, True),                     # Uttara Bhadrapada
    (26, 1, True), (26, 4, True),                     # Revati
]
names = {21: "Shravana", 22: "Dhanishta", 23: "Shatabhisha", 24: "Purva Bhadrapada",
         25: "Uttara Bhadrapada", 26: "Revati"}
anchor = t300 - timedelta(days=2)
for idx, pada, active in cases:
    mid_deg = idx * span + (pada - 0.5) * pada_span
    t = crossing(mid_deg, anchor)
    expect(f"{names[idx]} pada {pada} ({mid_deg:.2f} deg)", t, names[idx], pada, active)

print("\n=== C. End boundary: Moon leaves Revati (360 deg) ===")
t360 = crossing(0.0, t300)
print(f"  Moon reaches 0/360 deg at {t360:%Y-%m-%d %H:%M:%S} IST")
expect("10 min before 360 deg", t360 - timedelta(minutes=10), "Revati", 4, True)
expect("10 min after 360 deg", t360 + timedelta(minutes=10), "Ashwini", 1, False)
check("Panchak window is ~4.5 days (Moon crosses 60 deg)",
      timedelta(days=4) < t360 - t300 < timedelta(days=5, hours=12), f"({t360 - t300})")

print("\n=== D. Sunrise-based dates the website/app show (Lucknow) ===")
def at_sunrise(d):
    r = calculate_panchang(d, *LUCKNOW, language="en")
    return r["nakshatra"]["name"], r["nakshatra"]["pada"], r["panchak"]["active"]

for d, nak, pada, active in [
    (date(2027, 2, 7), "Dhanishta", 2, False),   # used to show Panchak active
    (date(2027, 3, 6), "Dhanishta", 1, False),   # used to show Panchak active
    (date(2026, 12, 15), "Dhanishta", 4, True),
    (date(2026, 12, 19), "Revati", None, True),
    (date(2026, 12, 20), "Ashwini", None, False),
]:
    n, p, a = at_sunrise(d)
    check(f"{d}: {n} pada {p} at sunrise -> active={a}",
          n == nak and (pada is None or p == pada) and a is active, f"(expected {nak} {pada} {active})")

# One full year of sunrises: active exactly when the sunrise Moon is in Dhanishta pada 3+ .. Revati.
mismatch = []
d = date(2026, 11, 23)
for _ in range(366):
    n, p, a = at_sunrise(d)
    want = n in ("Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati") or (n == "Dhanishta" and p >= 3)
    if a is not want:
        mismatch.append(f"{d} {n} p{p} active={a}")
    d += timedelta(days=1)
check("366 sunrises: active iff Dhanishta pada 3-4 .. Revati", not mismatch, f"{mismatch[:5]}")

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
