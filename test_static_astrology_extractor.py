# test_static_astrology_extractor.py

"""
USERS U3B.1 -- modules/services/static_astrology_extractor.py unit
tests, exercised entirely with hand-crafted dicts standing in for an
ALREADY-CALCULATED calculate_full_kundali() result. Pure Python --
no Flask app context, no database, no real astrology calculation.

LOCAL ONLY (though this file needs no DB access at all).
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.services.static_astrology_extractor import (  # noqa: E402
    extract_moon_static_facts,
    extract_static_yog,
    extract_static_dosh,
    build_static_astrology_snapshot,
    build_not_calculated_snapshot,
    apply_snapshot_to_app_user,
    STATIC_ASTROLOGY_VERSION,
)

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


def _inactive_yog(canonical_id):
    return {"id": canonical_id, "is_active": False, "strength": "None",
            "reasons": ["not active"], "positives": [], "challenge": "no challenge",
            "description": "inactive", "upsell": {}, "emoji": "x"}


# All 13 simple Yog + the Panch Mahapurush umbrella, all inactive by
# default -- individual tests override one at a time.
def _base_kundali(**overrides):
    k = {
        "lagna_sign": "Leo",
        "rashi": "Taurus",
        "planets": [
            {"name": "Sun", "sign": "Aries", "house": 1, "nakshatra": "Ashwini", "pada": 1},
            {"name": "Moon", "sign": "Taurus", "house": 2, "nakshatra": "Rohini", "pada": 3},
        ],
        "budh_aditya_yog": _inactive_yog("budh_aditya_yog"),
        "chandra_mangal_yog": _inactive_yog("chandra_mangal_yog"),
        "adhi_rajyog": _inactive_yog("adhi_rajyog"),
        "dhan_yog": _inactive_yog("dhan_yog"),
        "dharma_karmadhipati_rajyog": _inactive_yog("dharma_karmadhipati_rajyog"),
        "gajakesari_yog": _inactive_yog("gajakesari_yog"),
        "kuber_rajyog": _inactive_yog("kuber_rajyog"),
        "lakshmi_yog": _inactive_yog("lakshmi_yog"),
        "neechbhang_rajyog": _inactive_yog("neechbhang_rajyog"),
        "panch_mahapurush_yog": {"id": "panch_mahapurush_rajyog", "is_active": False, "sub_yogs": []},
        "parashari_rajyog": _inactive_yog("parashari_rajyog"),
        "rajya_sambandh_rajyog": _inactive_yog("rajya_sambandh_rajyog"),
        "shubh_kartari_yog": _inactive_yog("shubh_kartari_yog"),
        "vipreet_rajyog": _inactive_yog("vipreet_rajyog"),
        "manglik_dosh": {"status": {"strength": "None"}, "heading": "Not Mangalic"},
        "kaalsarp_dosh": {"is_present": False, "heading": "Kaalsarp Dosh Not Found"},
    }
    k.update(overrides)
    return k


def main():
    # ==========================================================
    print("=== A: Moon Pada extraction 1-4 ===")
    # ==========================================================
    for pada_value in (1, 2, 3, 4):
        k = _base_kundali()
        k["planets"][1]["pada"] = pada_value
        facts = extract_moon_static_facts(k)
        check(f"A: Moon pada={pada_value} extracted correctly", facts["nakshatra_pada"] == pada_value)
    facts = extract_moon_static_facts(_base_kundali())
    check("A: lagna/moon_sign/nakshatra also extracted alongside pada",
          facts["lagna"] == "Leo" and facts["moon_sign"] == "Taurus" and facts["nakshatra"] == "Rohini")

    # ==========================================================
    print("\n=== B/C/D/E: active Yog stored, inactive omitted, strength retained, prose omitted ===")
    # ==========================================================
    k = _base_kundali(gajakesari_yog={
        "id": "gajakesari_yog", "is_active": True, "strength": "High",
        "reasons": ["Moon and Jupiter conjunct"], "positives": ["good luck"],
        "challenge": "none", "description": "present", "upsell": {"x": 1}, "emoji": "🔥",
    })
    result = extract_static_yog(k)
    check("B: active Yog (gajakesari) IS stored", "gajakesari_yog" in result)
    check("C: every other (inactive) Yog is OMITTED entirely", set(result.keys()) == {"gajakesari_yog"})
    check("D: strength is retained for the active Yog", result["gajakesari_yog"]["strength"] == "High")
    check("E: prose fields (reasons/positives/challenge/description/upsell/emoji) are NOT stored",
          set(result["gajakesari_yog"].keys()) == {"strength"})

    # ==========================================================
    print("\n=== F/G: Panch Mahapurush umbrella + sub-yog mapping ===")
    # ==========================================================
    k = _base_kundali(panch_mahapurush_yog={
        "id": "panch_mahapurush_rajyog", "is_active": True, "strength": "High",
        "sub_yogs": ["Ruchaka Yog", "Hamsa Yog"],
        "reasons": ["Mars in own sign", "Jupiter in own sign"],
    })
    result = extract_static_yog(k)
    check("F: Panch Mahapurush umbrella stored under its own evaluator id",
          "panch_mahapurush_rajyog" in result and result["panch_mahapurush_rajyog"] == {"strength": "High"})
    check("G: each detected sub-yog mapped to its architecture-frozen machine key",
          "panch_mahapurush_ruchaka" in result and "panch_mahapurush_hamsa" in result)
    check("G: undetected sub-yogs (Bhadra/Malavya/Shasha) are NOT present",
          "panch_mahapurush_bhadra" not in result
          and "panch_mahapurush_malavya" not in result
          and "panch_mahapurush_shasha" not in result)
    check("G: sub-yog entries carry presence only (no fabricated strength)",
          result["panch_mahapurush_ruchaka"] == {} and result["panch_mahapurush_hamsa"] == {})

    # Panch Mahapurush inactive -> nothing stored at all, including no sub-yogs.
    k_inactive_panch = _base_kundali()
    result_inactive_panch = extract_static_yog(k_inactive_panch)
    check("F/G: inactive Panch Mahapurush umbrella -> no umbrella key, no sub-yog keys",
          not any(key.startswith("panch_mahapurush") for key in result_inactive_panch))

    # ==========================================================
    print("\n=== H/I: Manglik Dosh present / absent(-cancelled) ===")
    # ==========================================================
    k_strong = _base_kundali(manglik_dosh={"status": {"strength": "Strong"}, "heading": "Yes, Mangalic"})
    check("H: Manglik 'Strong' -> present, severity retained",
          extract_static_dosh(k_strong) == {"manglik": {"severity": "Strong"}})

    k_partial = _base_kundali(manglik_dosh={"status": {"strength": "Partial"}, "heading": "Yes, partial"})
    check("H: Manglik 'Partial' -> also present",
          extract_static_dosh(k_partial) == {"manglik": {"severity": "Partial"}})

    k_cancelled = _base_kundali(manglik_dosh={"status": {"strength": "Cancelled"}, "heading": "Cancelled"})
    check("I: Manglik 'Cancelled' -> NOT present (matches the evaluator's own human-readable label)",
          "manglik" not in extract_static_dosh(k_cancelled))

    k_none = _base_kundali(manglik_dosh={"status": {"strength": "None"}, "heading": "Not Mangalic"})
    check("I: Manglik 'None' -> NOT present", "manglik" not in extract_static_dosh(k_none))

    # ==========================================================
    print("\n=== J/K: Kaal Sarp is_present True/False -- STRICT machine signal only ===")
    # ==========================================================
    k_present = _base_kundali(kaalsarp_dosh={"is_present": True, "heading": "Kaalsarp Dosh Detected"})
    check("J: Kaal Sarp is_present=True -> stored as present, empty detail object",
          extract_static_dosh(k_present) == {"kaal_sarp": {}})

    k_absent = _base_kundali(kaalsarp_dosh={"is_present": False, "heading": "Kaalsarp Dosh Not Found"})
    check("K: Kaal Sarp is_present=False -> key entirely absent",
          "kaal_sarp" not in extract_static_dosh(k_absent))

    # STRICT: heading deliberately says "Detected" while is_present is
    # False (a deliberately contradictory/mocked fixture) -- proves
    # presence is read ONLY from is_present, never from heading text.
    k_contradictory = _base_kundali(kaalsarp_dosh={"is_present": False, "heading": "Kaalsarp Dosh Detected"})
    check("Strict: contradictory heading text ('Detected') does NOT flip the result when is_present=False",
          "kaal_sarp" not in extract_static_dosh(k_contradictory))

    # ==========================================================
    print("\n=== L/M: zero active Yog / zero present Dosh -> {} (never None, never omitted) ===")
    # ==========================================================
    baseline = _base_kundali()
    check("L: zero active Yog -> {}", extract_static_yog(baseline) == {})
    check("M: zero present Dosh -> {}", extract_static_dosh(baseline) == {})

    # ==========================================================
    print("\n=== N: malformed/missing optional result never fabricates a trait ===")
    # ==========================================================
    check("N: completely empty kundali -> moon facts all None, never fabricated",
          extract_moon_static_facts({}) == {"lagna": None, "moon_sign": None, "nakshatra": None, "nakshatra_pada": None})
    check("N: completely empty kundali -> zero active Yog", extract_static_yog({}) == {})
    check("N: completely empty kundali -> zero present Dosh", extract_static_dosh({}) == {})
    check("N: malformed (non-dict) Yog/Dosh results are skipped, not crashed on",
          extract_static_yog({"gajakesari_yog": "not a dict"}) == {}
          and extract_static_dosh({"manglik_dosh": None, "kaalsarp_dosh": ["also wrong"]}) == {})
    check("N: planets list with no Moon entry -> nakshatra/pada stay None",
          extract_moon_static_facts({"planets": [{"name": "Sun", "nakshatra": "Ashwini", "pada": 1}]})["nakshatra_pada"] is None)

    # ==========================================================
    print("\n=== Snapshot builders ===")
    # ==========================================================
    full_snapshot = build_static_astrology_snapshot(_base_kundali(gajakesari_yog={
        "id": "gajakesari_yog", "is_active": True, "strength": "Moderate",
    }))
    check("snapshot: has exactly the 8 documented keys",
          set(full_snapshot.keys()) == {"lagna", "moon_sign", "nakshatra", "nakshatra_pada",
                                         "static_yog", "static_dosh",
                                         "static_astrology_calculated_at", "static_astrology_version"})
    check("snapshot: static_astrology_version is the central constant", full_snapshot["static_astrology_version"] == STATIC_ASTROLOGY_VERSION)
    check("snapshot: static_astrology_calculated_at is set (not None)", full_snapshot["static_astrology_calculated_at"] is not None)
    check("snapshot: static_yog reflects the active Yog passed in", full_snapshot["static_yog"] == {"gajakesari_yog": {"strength": "Moderate"}})

    not_calc = build_not_calculated_snapshot()
    check("not-calculated snapshot: every one of the 8 keys is None",
          set(not_calc.keys()) == set(full_snapshot.keys()) and all(v is None for v in not_calc.values()))

    class _FakeAppUser:
        pass

    fake_user = _FakeAppUser()
    apply_snapshot_to_app_user(fake_user, full_snapshot)
    check("apply_snapshot_to_app_user: every snapshot key becomes an attribute",
          all(getattr(fake_user, k) == v for k, v in full_snapshot.items()))

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    if not ok:
        sys.exit(1)
