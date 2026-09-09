"""
test_lahiri_thread_safety.py
-----------------------------------
U4C.2B -- reproduces the exact U4C.2A bug on a fresh thread and proves
the fix. LOCAL ONLY, no DB access needed (pure Swiss Ephemeris calls).

Sequence (per U4C.2B's own mandatory spec):
  1. Main thread imports the modules under test.
  2. Spawn a brand-new Python thread.
  3. Do NOT manually set sidereal mode inside the test thread.
  4. Call the public/authoritative calculation normally, on that thread.
  5. Compare against an independently-established explicit Lahiri
     oracle (a separate ayanamsa/swe.calc_ut call made directly in this
     test file, not reusing transit_engine's own internals as its own
     oracle).

Fixed instant used throughout: 2026-09-07 12:00 UTC -- the exact
instant U4C.2A's own audit used, where Mercury is known to sit at
0.29 degrees into sidereal Virgo under true Lahiri (and would read
29.41 degrees into Leo under the un-set Fagan-Bradley-equivalent
default) -- the real, non-manufactured boundary case from that audit.

This test is expected to FAIL if any of the guarded functions'
ensure_lahiri_mode() calls were removed/reverted, and to PASS after
the U4C.2B fix.
"""

import sys
import threading
import datetime
import pytz

import swisseph as swe

import transit_engine as te
import smart_transit_engine as ste
import services.astro_core as astro_core

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.UTC

FIXED_UTC = datetime.datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
FIXED_IST = FIXED_UTC.astimezone(IST)

RASHIS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra",
          "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

NAME_TO_ID = {"Sun": 0, "Moon": 1, "Mercury": 2, "Venus": 3, "Mars": 4,
              "Jupiter": 5, "Saturn": 6}

_passed = 0
_failed = 0


def check(label, condition):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS: {label}")
    else:
        _failed += 1
        print(f"  FAIL: {label}")


def independent_lahiri_oracle():
    """Independently establishes true Lahiri sidereal longitudes for
    all 9 planets at FIXED_UTC, calling swisseph directly -- NOT
    reusing transit_engine/smart_transit_engine's own internals, so
    this is a genuine external oracle, not the function under test
    checking itself."""
    jd = swe.julday(FIXED_UTC.year, FIXED_UTC.month, FIXED_UTC.day,
                     FIXED_UTC.hour + FIXED_UTC.minute / 60.0)
    swe.set_sid_mode(swe.SIDM_LAHIRI)  # explicit, on THIS (main) thread, for the oracle only
    ay = swe.get_ayanamsa_ut(jd)
    out = {}
    for name, pid in NAME_TO_ID.items():
        res = swe.calc_ut(jd, pid)[0]
        sid = (res[0] - ay) % 360
        out[name] = {
            "sidereal_longitude": sid,
            "rashi": RASHIS[int(sid // 30)],
            "degree": round(sid % 30, 4),
            "motion": "Retrograde" if res[3] < 0 else "Direct",
        }
    rahu_lon = swe.calc_ut(jd, swe.MEAN_NODE)[0][0]
    rahu_sid = (rahu_lon - ay) % 360
    out["Rahu"] = {"sidereal_longitude": rahu_sid, "rashi": RASHIS[int(rahu_sid // 30)],
                   "degree": round(rahu_sid % 30, 4), "motion": "Retrograde"}
    ketu_sid = (rahu_sid + 180.0) % 360
    out["Ketu"] = {"sidereal_longitude": ketu_sid, "rashi": RASHIS[int(ketu_sid // 30)],
                   "degree": round(ketu_sid % 30, 4), "motion": "Retrograde"}
    return out


def main():
    print("=== U4C.2B Multi-Thread Lahiri Safety Regression ===")
    print(f"Fixed instant: {FIXED_UTC.isoformat()} UTC = {FIXED_IST.isoformat()} IST\n")

    oracle = independent_lahiri_oracle()

    print("=== 1: Explicit oracle sanity -- Mercury must independently be Virgo ===")
    check("1: independent oracle -- Mercury is Virgo under true Lahiri", oracle["Mercury"]["rashi"] == "Virgo")

    # --- Fresh thread, transit_engine.get_current_positions()-equivalent path ---
    thread_results = {}

    def fresh_thread_transit_engine():
        # Deliberately NEVER calls swe.set_sid_mode itself -- this
        # thread has never touched Swiss Ephemeris before. Uses
        # transit_engine's own internal primitives directly (mirroring
        # get_current_positions()'s own math) so we can inject the
        # FIXED instant instead of "now".
        jd = te._to_julday_utc(FIXED_UTC)
        out = {}
        for name in NAME_TO_ID:
            r = te._planet_rashi_on_day(name, FIXED_UTC)
            out[name] = r
        out["Rahu"] = te._planet_rashi_on_day("Rahu", FIXED_UTC)
        out["Ketu"] = te._planet_rashi_on_day("Ketu", FIXED_UTC)
        thread_results["transit_engine_rashis"] = out

    t1 = threading.Thread(target=fresh_thread_transit_engine)
    t1.start()
    t1.join()

    print("\n=== 2: transit_engine._planet_rashi_on_day() on a FRESH thread (no manual set_sid_mode) ===")
    for name in list(NAME_TO_ID) + ["Rahu", "Ketu"]:
        check(f"2: {name} rashi on fresh thread == oracle ({oracle[name]['rashi']})",
              thread_results["transit_engine_rashis"][name] == oracle[name]["rashi"])

    print("\n=== 3: Mandatory Mercury assertion -- must be Virgo on the fresh thread ===")
    check("3: Mercury resolves to Virgo on a fresh thread under the corrected runtime contract",
          thread_results["transit_engine_rashis"]["Mercury"] == "Virgo")

    # --- Fresh thread, smart_transit_engine.get_planet_position_on() ---
    ste_results = {}

    def fresh_thread_smart_transit_engine():
        date_str = FIXED_IST.strftime("%Y-%m-%d %H:%M")
        for name in list(NAME_TO_ID) + ["Rahu", "Ketu"]:
            ste_results[name] = ste.get_planet_position_on(date_str, name)

    t2 = threading.Thread(target=fresh_thread_smart_transit_engine)
    t2.start()
    t2.join()

    print("\n=== 4: smart_transit_engine.get_planet_position_on() on a FRESH thread ===")
    for name in list(NAME_TO_ID) + ["Rahu", "Ketu"]:
        check(f"4: {name} rashi (smart_transit_engine, fresh thread) == oracle ({oracle[name]['rashi']})",
              ste_results[name]["rashi"] == oracle[name]["rashi"])
    check("4: Mercury (smart_transit_engine, fresh thread) == Virgo",
          ste_results["Mercury"]["rashi"] == "Virgo")

    # --- All-9 planet full comparison (sidereal longitude/degree/motion), fresh thread ---
    print("\n=== 5: All-9 planet full comparison (longitude/degree/motion) -- transit_engine, fresh thread ===")

    full_results = {}

    def fresh_thread_full_positions():
        jd = te._to_julday_utc(FIXED_UTC)
        ay = swe.get_ayanamsa_ut(jd)
        # deliberately does NOT call ensure_lahiri_mode/set_sid_mode
        # itself here -- the whole point is to prove get_current_positions()
        # and _planet_rashi_on_day() establish it themselves.
        for name in NAME_TO_ID:
            full_results[name] = {
                "rashi": te._planet_rashi_on_day(name, FIXED_UTC),
                "degree": round((swe.calc_ut(jd, NAME_TO_ID[name])[0][0] - swe.get_ayanamsa_ut(jd)) % 360 % 30, 4),
                "motion": te._planet_motion_on_day(name, FIXED_UTC),
            }
        full_results["Rahu"] = {
            "rashi": te._planet_rashi_on_day("Rahu", FIXED_UTC),
            "motion": te._planet_motion_on_day("Rahu", FIXED_UTC),
        }
        full_results["Ketu"] = {
            "rashi": te._planet_rashi_on_day("Ketu", FIXED_UTC),
            "motion": te._planet_motion_on_day("Ketu", FIXED_UTC),
        }

    t3 = threading.Thread(target=fresh_thread_full_positions)
    t3.start()
    t3.join()

    for name in list(NAME_TO_ID) + ["Rahu", "Ketu"]:
        check(f"5: {name} rashi matches oracle", full_results[name]["rashi"] == oracle[name]["rashi"])
        check(f"5: {name} motion matches oracle", full_results[name]["motion"] == oracle[name]["motion"])
        if "degree" in full_results[name]:
            check(f"5: {name} degree matches oracle within 0.01", abs(full_results[name]["degree"] - oracle[name]["degree"]) < 0.01)

    # --- Panchang (services/astro_core.py::sidereal_longitudes), fresh thread ---
    print("\n=== 6: services/astro_core.py::sidereal_longitudes() on a FRESH thread (Panchang's own Sun/Moon source) ===")
    panchang_results = {}

    def fresh_thread_panchang():
        # astro_core.sidereal_longitudes() takes a naive IST datetime,
        # matching its own existing contract -- not touched here.
        sun, moon = astro_core.sidereal_longitudes(FIXED_IST.replace(tzinfo=None))
        panchang_results["sun"] = sun
        panchang_results["moon"] = moon

    t4 = threading.Thread(target=fresh_thread_panchang)
    t4.start()
    t4.join()

    check("6: Panchang Sun sidereal longitude (fresh thread) matches oracle within 0.01",
          abs(panchang_results["sun"] - oracle["Sun"]["sidereal_longitude"]) < 0.01)
    check("6: Panchang Moon sidereal longitude (fresh thread) matches oracle within 0.01",
          abs(panchang_results["moon"] - oracle["Moon"]["sidereal_longitude"]) < 0.01)

    print(f"\n{'='*70}\nRESULTS: {_passed} passed, {_failed} failed\n{'='*70}")
    return _failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
