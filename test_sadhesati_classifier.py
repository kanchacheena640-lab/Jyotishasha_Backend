# test_sadhesati_classifier.py

"""
U4B.1 -- permanent regression tests for:
    services/sadhesati_classifier.py::classify_sade_sati()
    services/current_saturn_resolver.py::resolve_current_saturn_sign()
    services/sadhesati_report_generator.py::generate_sadhesati_report()
      (product-compatibility check -- refactored to delegate to the
      shared classifier; externally-visible status/phase must be
      byte-identical to before for identical inputs)

Pure Python -- no Flask app context, no database (this module has no
DB dependency at all; the classifier and resolver are pure/thin
functions). Mirrors the U4B.0 audit's own executed proof (144
Moon x Saturn combinations), now made permanent.

LOCAL ONLY (though no DB access happens here).
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.sadhesati_classifier import (  # noqa: E402
    classify_sade_sati,
    SADE_SATI_SIGN_ORDER,
    PHASE_FIRST,
    PHASE_SECOND,
    PHASE_THIRD,
    STATE_ACTIVE,
    STATE_INACTIVE,
    STATE_NOT_CALCULATED,
    STATE_SATURN_UNAVAILABLE,
)
from services.current_saturn_resolver import (  # noqa: E402
    resolve_current_saturn_sign,
    CURRENT_SATURN_SOURCE,
)
import services.sadhesati_report_generator as sg  # noqa: E402

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


# Standard zodiac order -- used ONLY to independently derive the
# expected truth table, NOT the classifier's own SADE_SATI_SIGN_ORDER
# (proving the classifier's rotated-order list still yields correct
# RELATIVE results regardless of its own starting point).
STANDARD_ZODIAC = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]


def expected_triplet(moon_sign):
    i = STANDARD_ZODIAC.index(moon_sign)
    return (
        STANDARD_ZODIAC[(i - 1) % 12],  # 12th sign
        STANDARD_ZODIAC[i],             # natal sign
        STANDARD_ZODIAC[(i + 1) % 12],  # 2nd sign
    )


def main():
    # ==========================================================
    print("=== 1: 144-combination correctness (12 Moon x 12 Saturn) ===")
    # ==========================================================
    total_combinations = 0
    for moon_sign in STANDARD_ZODIAC:
        twelfth, natal, second = expected_triplet(moon_sign)

        for saturn_sign in STANDARD_ZODIAC:
            total_combinations += 1
            result = classify_sade_sati(moon_sign, saturn_sign)

            if saturn_sign == twelfth:
                check(f"[{moon_sign}] Saturn={saturn_sign} (12th) -> active/1st Phase",
                      result == {"state": STATE_ACTIVE, "active": True, "phase": PHASE_FIRST})
            elif saturn_sign == natal:
                check(f"[{moon_sign}] Saturn={saturn_sign} (natal) -> active/2nd Phase",
                      result == {"state": STATE_ACTIVE, "active": True, "phase": PHASE_SECOND})
            elif saturn_sign == second:
                check(f"[{moon_sign}] Saturn={saturn_sign} (2nd) -> active/3rd Phase",
                      result == {"state": STATE_ACTIVE, "active": True, "phase": PHASE_THIRD})
            else:
                check(f"[{moon_sign}] Saturn={saturn_sign} (other) -> inactive/None",
                      result == {"state": STATE_INACTIVE, "active": False, "phase": None})

    check("exactly 144 combinations exercised", total_combinations == 144)

    # ==========================================================
    print("\n=== 2: zodiac wrap edge cases ===")
    # ==========================================================
    check("Pisces natal, Saturn=Aries (wrap, 2nd sign) -> active/3rd Phase",
          classify_sade_sati("Pisces", "Aries") == {"state": STATE_ACTIVE, "active": True, "phase": PHASE_THIRD})
    check("Aries natal, Saturn=Pisces (wrap, 12th sign) -> active/1st Phase",
          classify_sade_sati("Aries", "Pisces") == {"state": STATE_ACTIVE, "active": True, "phase": PHASE_FIRST})

    # ==========================================================
    print("\n=== 3: null / invalid / missing input semantics ===")
    # ==========================================================
    check("missing Moon sign (None) -> NOT_CALCULATED, never inactive",
          classify_sade_sati(None, "Aries") == {"state": STATE_NOT_CALCULATED, "active": None, "phase": None})
    check("invalid Moon sign (garbage string) -> NOT_CALCULATED, never inactive",
          classify_sade_sati("Frobnicate", "Aries") == {"state": STATE_NOT_CALCULATED, "active": None, "phase": None})
    check("empty-string Moon sign -> NOT_CALCULATED",
          classify_sade_sati("", "Aries")["state"] == STATE_NOT_CALCULATED)
    check("missing Saturn sign (None) -> SATURN_UNAVAILABLE, never inactive, distinct from NOT_CALCULATED",
          classify_sade_sati("Aries", None) == {"state": STATE_SATURN_UNAVAILABLE, "active": None, "phase": None})
    check("invalid Saturn sign (garbage string) -> SATURN_UNAVAILABLE",
          classify_sade_sati("Aries", "NotARealSign") == {"state": STATE_SATURN_UNAVAILABLE, "active": None, "phase": None})
    check("both missing -> NOT_CALCULATED wins (Moon-sign problem checked first, both are genuinely unclassifiable)",
          classify_sade_sati(None, None)["state"] == STATE_NOT_CALCULATED)
    check("NOT_CALCULATED is a distinct state from INACTIVE (never conflated)", STATE_NOT_CALCULATED != STATE_INACTIVE)
    check("SATURN_UNAVAILABLE is a distinct state from INACTIVE (never conflated)", STATE_SATURN_UNAVAILABLE != STATE_INACTIVE)
    check("SATURN_UNAVAILABLE is a distinct state from NOT_CALCULATED", STATE_SATURN_UNAVAILABLE != STATE_NOT_CALCULATED)

    # ==========================================================
    print("\n=== 4: active/phase invariants ===")
    # ==========================================================
    active_result = classify_sade_sati("Leo", "Cancer")
    check("active state always has phase in the 3 canonical strings", active_result["phase"] in (PHASE_FIRST, PHASE_SECOND, PHASE_THIRD))
    inactive_result = classify_sade_sati("Leo", "Libra")
    check("inactive state always has phase=None", inactive_result["phase"] is None)

    # ==========================================================
    print("\n=== 5: no Lagna / no house dependency (structural proof) ===")
    # ==========================================================
    import inspect
    classifier_source = inspect.getsource(classify_sade_sati)
    check("classify_sade_sati() source never references 'lagna'", "lagna" not in classifier_source.lower())
    check("classify_sade_sati() source never references 'house'", "house" not in classifier_source.lower())
    check("classify_sade_sati() source never references 'planet'", "planet" not in classifier_source.lower())
    check("classify_sade_sati() takes exactly 2 parameters (no full-Kundali/DOB/TOB dependency)",
          list(inspect.signature(classify_sade_sati).parameters.keys()) == ["natal_moon_sign", "saturn_sign"])

    # ==========================================================
    print("\n=== 6: zero ephemeris calls in the pure classifier (structural proof) ===")
    # ==========================================================
    # Checked against the actual import LINES only (not the whole module
    # source/docstring, which necessarily NAMES these other modules in
    # prose to explain why they are deliberately not imported here).
    classifier_module_source = inspect.getsource(sys.modules["services.sadhesati_classifier"])
    # Real top-level import statements are never indented; only checking
    # column-0 lines excludes indented docstring prose that happens to
    # start with the English word "from" (e.g. "distinct from X").
    import_lines = "\n".join(
        line for line in classifier_module_source.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    )
    check("sadhesati_classifier.py's import lines never mention swisseph", "swisseph" not in import_lines)
    check("sadhesati_classifier.py's import lines never mention smart_transit_engine", "smart_transit_engine" not in import_lines)
    check("sadhesati_classifier.py's import lines never mention transit_engine", "transit_engine" not in import_lines)
    check("sadhesati_classifier.py's import lines never mention full_kundali_api", "full_kundali_api" not in import_lines)
    check("sadhesati_classifier.py's import lines never mention openai", "openai" not in import_lines.lower())
    check("sadhesati_classifier.py's only real imports are stdlib (typing/__future__)",
          import_lines.strip().splitlines() == ["from __future__ import annotations", "from typing import Optional, TypedDict"])

    # ==========================================================
    print("\n=== 7: retrograde safety -- state follows the SUPPLIED Saturn sign, no monotonic/prior-state assumption ===")
    # ==========================================================
    # Simulate a retrograde loop: Cancer -> Gemini -> Cancer -> Leo,
    # calling the SAME pure classifier fresh each time (no persisted
    # state passed between calls) and confirming each result reflects
    # ONLY that call's own Saturn sign, never a "previous phase".
    moon = "Leo"  # 12th=Cancer, natal=Leo, 2nd=Virgo
    sequence = ["Cancer", "Gemini", "Cancer", "Leo", "Virgo", "Libra"]
    expected_phases = [PHASE_FIRST, None, PHASE_FIRST, PHASE_SECOND, PHASE_THIRD, None]
    all_correct = True
    for saturn_sign, expected_phase in zip(sequence, expected_phases):
        r = classify_sade_sati(moon, saturn_sign)
        if r["phase"] != expected_phase:
            all_correct = False
            print(f"    MISMATCH: saturn={saturn_sign} expected_phase={expected_phase} got={r['phase']}")
    check("retrograde re-entry sequence (Cancer->Gemini->Cancer->Leo->Virgo->Libra) classifies correctly at every step, independent of history", all_correct)
    check("re-entering the SAME sign (Cancer, step 1 and step 3) produces the IDENTICAL result both times (no hidden state)",
          classify_sade_sati(moon, "Cancer") == classify_sade_sati(moon, "Cancer"))

    # ==========================================================
    print("\n=== 8: current Saturn resolver ===")
    # ==========================================================
    resolution = resolve_current_saturn_sign()
    check("resolver returns a saturn_sign that is one of the 12 canonical signs", resolution.saturn_sign in SADE_SATI_SIGN_ORDER)
    check("resolver reports its source as smart_transit_engine (preserves existing verified behavior, per U4B.1 decision)",
          resolution.source == CURRENT_SATURN_SOURCE == "smart_transit_engine")
    check("resolver's saturn_sign feeds classify_sade_sati() without error", classify_sade_sati("Leo", resolution.saturn_sign)["state"] in (STATE_ACTIVE, STATE_INACTIVE))

    # Saturn resolver failure -- simulate the underlying ephemeris call
    # raising, and confirm the resolver does NOT swallow it into a
    # fabricated sign (Section 9: never silently classify as inactive).
    import smart_transit_engine

    def _raise(*a, **kw):
        raise RuntimeError("simulated ephemeris failure")

    original_fn = smart_transit_engine.get_planet_position_on
    smart_transit_engine.get_planet_position_on = _raise
    resolver_raised = False
    try:
        resolve_current_saturn_sign()
    except RuntimeError:
        resolver_raised = True
    finally:
        smart_transit_engine.get_planet_position_on = original_fn
    check("resolver propagates a genuine ephemeris failure (never fabricates a sign, never silently returns 'inactive')", resolver_raised)

    # ==========================================================
    print("\n=== 9: N+1-shaped proof -- ONE resolution serves many users ===")
    # ==========================================================
    resolution_once = resolve_current_saturn_sign()
    simulated_users_moon_signs = STANDARD_ZODIAC  # stand-in for 12 different persisted AppUser.moon_sign values
    results = [classify_sade_sati(m, resolution_once.saturn_sign) for m in simulated_users_moon_signs]
    check(
        f"one resolve_current_saturn_sign() call classified all {len(simulated_users_moon_signs)} simulated users "
        "(zero additional ephemeris calls per user)",
        len(results) == len(simulated_users_moon_signs) and all(r["state"] in (STATE_ACTIVE, STATE_INACTIVE) for r in results),
    )

    # ==========================================================
    print("\n=== 10: generate_sadhesati_report() product-compatibility -- refactor preserves external behavior ===")
    # ==========================================================
    def run_report(moon_sign, saturn_rashi):
        original_pos, original_prev, original_next = sg.get_planet_position_on, sg.get_prev_transits, sg.get_next_transits
        sg.get_planet_position_on = lambda date_str, planet: {
            "planet": planet, "date": date_str, "rashi": saturn_rashi, "degree": 15.0, "motion": "Direct",
        }
        sg.get_prev_transits = lambda planet, count=12: []
        sg.get_next_transits = lambda planet, count=12: []
        try:
            return sg.generate_sadhesati_report({"moon_sign": moon_sign, "language": "en"})
        finally:
            sg.get_planet_position_on, sg.get_prev_transits, sg.get_next_transits = original_pos, original_prev, original_next

    # BEFORE/EXPECTED behavior (U4B.0's own audit, and the original
    # pre-refactor code): Active/1st,2nd,3rd Phase for 12th/natal/2nd
    # sign; Inactive/None otherwise; "Error"/"Invalid Rashi" for a bad
    # sign. Re-verified here against the REFACTORED function.
    for moon_sign in STANDARD_ZODIAC:
        twelfth, natal, second = expected_triplet(moon_sign)
        r = run_report(moon_sign, twelfth)
        check(f"[report:{moon_sign}] 12th sign -> status=Active, phase=1st Phase (unchanged)", r["status"] == "Active" and r["phase"] == "1st Phase")
        r = run_report(moon_sign, natal)
        check(f"[report:{moon_sign}] natal sign -> status=Active, phase=2nd Phase (unchanged)", r["status"] == "Active" and r["phase"] == "2nd Phase")
        r = run_report(moon_sign, second)
        check(f"[report:{moon_sign}] 2nd sign -> status=Active, phase=3rd Phase (unchanged)", r["status"] == "Active" and r["phase"] == "3rd Phase")
        other = next(s for s in STANDARD_ZODIAC if s not in (twelfth, natal, second))
        r = run_report(moon_sign, other)
        check(f"[report:{moon_sign}] other sign -> status=Inactive, phase=None (unchanged)", r["status"] == "Inactive" and r["phase"] is None)

    r_invalid = run_report("NotARealSign", "Aries")
    check("[report] invalid Moon sign -> status=Error, heading=Invalid Rashi (unchanged)",
          r_invalid == {"status": "Error", "heading": "Invalid Rashi", "explanation": "Moon sign or Saturn sign could not be matched."})

    r_invalid2 = run_report("Leo", "NotARealSign")
    check("[report] invalid Saturn sign -> status=Error, heading=Invalid Rashi (unchanged)",
          r_invalid2 == {"status": "Error", "heading": "Invalid Rashi", "explanation": "Moon sign or Saturn sign could not be matched."})

    # Report shape unchanged -- exact same keys as before the refactor.
    r_shape = run_report("Leo", "Cancer")
    check("[report] output keys unchanged by the refactor",
          set(r_shape.keys()) == {"status", "moon_rashi", "saturn_rashi", "phase", "phase_dates",
                                   "short_description", "report_paragraphs", "summary_block", "explanation"})

    print(f"\n{'='*70}\nRESULTS: {passed} passed, {failed} failed\n{'='*70}")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
