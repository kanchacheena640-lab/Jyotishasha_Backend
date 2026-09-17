"""
test_summary_blocks_q1_5_context.py
-------------------------------------------------
Paid Report Product Intelligence Data Foundation (Q1.5) verification.

Zero Flask/DB dependency for the summary_blocks.py-only tests (A-F) --
pure functions of dict inputs, fixtures mirror the real shapes read
directly from services/sadhesati_report_generator.py,
services/foreign_travel.py, and full_kundali_api.py before writing any
implementation code. Section G additionally exercises the real,
additive full_kundali_api.py wiring (calculate_house_aspects(),
build_foreign_travel() integration) against real Swiss-Ephemeris
output -- needs no DB either, just the same imports tasks.py already
uses.

Covers:
  A. Sade Sati context -- Active case (incl. the phase-key-mismatch
     bug workaround), Inactive case (with and without an upcoming
     window), and the safe fallback for missing/malformed data.
  B. Foreign travel context -- normal case, incomplete/empty case.
  C. House-lord mapping -- all 12 houses always present, empty houses
     still carry sign/lord/lord-placement, lord-placement correctness,
     and the safe fallback for an unrecognized Lagna sign.
  D. Targeted aspect facts -- 7th house/7th lord facts, Saturn/Venus/
     Moon's own aspect targets, and the safe fallback.
  E. Context contract -- every Q1 key still present, every Q1.5 key
     present, exact total key count, every value a plain string.
  F. Existing prompt .format() compatibility unaffected.
  G. Real end-to-end wiring -- calculate_full_kundali() actually
     returns "foreign_travel"/"house_aspects", and
     calculate_drishti_for_planets()'s own aspect_summary-facing
     output is unchanged by the DRISHTI_RULES hoist refactor.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import summary_blocks as sb

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


# ---------------------------------------------------------------
# Shared fixtures (same shapes as test_summary_blocks_q1_context.py,
# extended with Q1.5's own new kundali fields).
# ---------------------------------------------------------------

def _antardashas(sequence, start_year):
    out = []
    for i, lord in enumerate(sequence):
        out.append({"planet": lord, "start": f"{start_year + i}-01-01", "end": f"{start_year + i + 1}-01-01"})
    return out


DASHA_SEQUENCE = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]


def _mahadashas():
    return [{"mahadasha": "Rahu", "start": "2015-01-01", "end": "2033-01-01", "antardashas": _antardashas(DASHA_SEQUENCE, 2015)}]


def _kundali(**overrides):
    mahadashas = _mahadashas()
    base = {
        "lagna_sign": "Leo",
        "planets": [
            {"name": "Sun", "house": 1, "sign": "Leo"},
            {"name": "Ascendant (Lagna)", "house": 1, "sign": "Leo"},
            {"name": "Moon", "house": 4, "sign": "Scorpio"},
            {"name": "Mars", "house": 6, "sign": "Capricorn"},
            {"name": "Mercury", "house": 11, "sign": "Gemini"},
            {"name": "Jupiter", "house": 12, "sign": "Cancer"},
            {"name": "Venus", "house": 9, "sign": "Aries"},
            {"name": "Saturn", "house": 6, "sign": "Capricorn"},
            {"name": "Rahu", "house": 6, "sign": "Capricorn"},
            {"name": "Ketu", "house": 12, "sign": "Cancer"},
        ],
        "manglik_dosh": {"is_manglik": False},
        "Mahadasha": mahadashas,
        "current_mahadasha": mahadashas[0],
        "current_antardasha": mahadashas[0]["antardashas"][0],
        "gemstone_suggestion": {"planet": "Sun", "gemstone": "Ruby", "substone": "Garnet", "cta": {}},
        # Q1.5 fixtures below.
        "sadhesati": {
            "status": "Active",
            "moon_rashi": "Aquarius",
            "saturn_rashi": "Pisces",
            "phase": "3rd Phase",
            # Correctly keyed "first_phase"/"second_phase"/"third_phase"
            # -- exactly as services/sadhesati_report_generator.py's own
            # RAW return value shape (the internal short_description/
            # start_date/end_date computation has the key-mismatch bug;
            # this raw phase_dates dict itself does not).
            "phase_dates": {
                "first_phase": {"start": "2022-04-29", "end": "2023-01-17"},
                "second_phase": {"start": "2023-01-17", "end": "2025-03-29"},
                "third_phase": {"start": "2025-03-29", "end": "2027-06-02"},
            },
            "short_description": "You are currently in the 3rd Phase of Sade Sati.",
        },
        "foreign_travel": {
            "tool_id": "foreign-travel",
            "language": "en",
            "heading": "Foreign Travel Insight",
            "cta": "some cta",
            "dominant_influence": "Jupiter, Rahu, 9th & 12th Houses",
            "positive_points": [
                {"en": "12th house lord Moon is placed in 7th house.", "hi": "..."},
                {"en": "Venus is placed in 9th house — favorable for foreign travel.", "hi": "..."},
            ],
            "negative_points": [
                {"en": "9th house lord Mars is in 6th house — may bring obstacles.", "hi": "..."},
            ],
        },
        "house_aspects": None,  # filled in below once planets are known
    }
    base.update(overrides)
    if base.get("house_aspects") is None:
        base["house_aspects"] = _house_aspects_for(base["planets"])
    return base


def _house_aspects_for(planets):
    """Mirrors full_kundali_api.py::calculate_house_aspects() exactly --
    a local, deliberately independent reimplementation for fixture
    purposes only (never imported from production code), so this test
    file can build a correct fixture without a live import of
    full_kundali_api.py (which has its own heavy Flask/service import
    chain) for the pure summary_blocks.py-only sections (A-F)."""
    rules = {"Saturn": [3, 7, 10], "Mars": [4, 7, 8], "Jupiter": [5, 7, 9], "Rahu": [5, 7, 9], "Ketu": [5, 7, 9]}
    house_aspects = {h: [] for h in range(1, 13)}
    for p in planets:
        for drishti_count in rules.get(p["name"], [7]):
            target = (p["house"] + drishti_count - 1) % 12 or 12
            house_aspects[target].append(p["name"])
    return house_aspects


def _transit():
    return {"positions": {
        "Sun": {"rashi": "Leo", "degree": 29.7, "motion": "Direct"},
        "Saturn": {"rashi": "Pisces", "degree": 18.4, "motion": "Retrograde"},
        "Jupiter": {"rashi": "Cancer", "degree": 22.7, "motion": "Direct"},
    }}


# =================================================================
print("=== A: Sade Sati context ===")
# =================================================================
blocks = sb.build_summary_blocks_with_transit(_kundali(), _transit())
check("A: sadhesati_summary key present", "sadhesati_summary" in blocks)
check("A: Active case states the real phase, Moon sign, Saturn sign",
      "3rd Phase" in blocks["sadhesati_summary"] and "Aquarius" in blocks["sadhesati_summary"] and "Pisces" in blocks["sadhesati_summary"])
check("A: Active case resolves the CORRECT window dates via the raw phase_dates dict (bug-bypassed)",
      "from 2025-03-29 to 2027-06-02" in blocks["sadhesati_summary"])
check("A: Active case does NOT show blank/empty dates (the bug this function sidesteps)",
      "from  to " not in blocks["sadhesati_summary"] and "from None to None" not in blocks["sadhesati_summary"])

inactive_no_upcoming = sb.build_summary_blocks_with_transit(
    _kundali(sadhesati={"status": "Inactive", "moon_rashi": "Aquarius", "saturn_rashi": "Leo", "phase": None, "phase_dates": {}}),
    _transit(),
)
check("A: Inactive, no upcoming window -> plain 'not currently under' statement",
      inactive_no_upcoming["sadhesati_summary"] == "You are not currently under Saturn's Sade Sati.")

inactive_with_upcoming = sb.build_summary_blocks_with_transit(
    _kundali(sadhesati={
        "status": "Inactive", "moon_rashi": "Aquarius", "saturn_rashi": "Leo", "phase": None,
        "phase_dates": {"first_phase": {"start": "2030-01-01", "end": "2032-06-01"}},
    }),
    _transit(),
)
check("A: Inactive with a real upcoming window states real dates (never invented)",
      "2030-01-01" in inactive_with_upcoming["sadhesati_summary"] and "2032-06-01" in inactive_with_upcoming["sadhesati_summary"])

no_data_blocks = sb.build_summary_blocks_with_transit(_kundali(sadhesati=None), _transit())
check("A: missing sadhesati data -> safe fallback, no crash", no_data_blocks["sadhesati_summary"] == "Sade Sati data not available.")

error_case_blocks = sb.build_summary_blocks_with_transit(
    _kundali(sadhesati={"status": "Error", "heading": "Invalid Rashi", "explanation": "..."}), _transit(),
)
check("A: Error-status sadhesati result -> safe fallback, no crash", error_case_blocks["sadhesati_summary"] == "Sade Sati data not available.")

# =================================================================
print("\n=== B: Foreign travel context ===")
# =================================================================
check("B: foreign_travel_summary key present", "foreign_travel_summary" in blocks)
check("B: real supportive points present (English only)",
      "Venus is placed in 9th house" in blocks["foreign_travel_summary"])
check("B: real cautionary points present",
      "9th house lord Mars is in 6th house" in blocks["foreign_travel_summary"])
check("B: no raw Hindi text leaked into this English-only key",
      "..." not in blocks["foreign_travel_summary"])

empty_travel_blocks = sb.build_summary_blocks_with_transit(
    _kundali(foreign_travel={"positive_points": [], "negative_points": []}), _transit(),
)
check("B: empty positive/negative points -> safe fallback, no crash",
      empty_travel_blocks["foreign_travel_summary"] == "Foreign travel indication data not available.")

missing_travel_blocks = sb.build_summary_blocks_with_transit(_kundali(foreign_travel=None), _transit())
check("B: missing foreign_travel entirely -> safe fallback, no crash",
      missing_travel_blocks["foreign_travel_summary"] == "Foreign travel indication data not available.")

# =================================================================
print("\n=== C: House-lord mapping ===")
# =================================================================
facts = sb.build_house_lord_facts(_kundali())
check("C: exactly 12 houses returned", len(facts) == 12)
check("C: houses are 1-12 in order", [f["house"] for f in facts] == list(range(1, 13)))

by_house = {f["house"]: f for f in facts}
check("C: House 1 sign is Leo (the Lagna sign itself)", by_house[1]["sign"] == "Leo")
check("C: House 7 sign is Aquarius (7th from Leo)", by_house[7]["sign"] == "Aquarius")
check("C: House 7 lord is Saturn (Aquarius's lord)", by_house[7]["lord"] == "Saturn")
check("C: House 7 lord-placement resolved correctly (Saturn is in house 6, Capricorn)",
      by_house[7]["lord_house"] == 6 and by_house[7]["lord_sign"] == "Capricorn")

# EMPTY HOUSE -- house 2 (Virgo) has no planet in the fixture, but
# sign/lord/lord-placement must all still be present.
check("C: EMPTY house 2 still has its sign (Virgo)", by_house[2]["sign"] == "Virgo")
check("C: EMPTY house 2 still has its lord (Mercury)", by_house[2]["lord"] == "Mercury")
check("C: EMPTY house 2's lord placement is still resolved (Mercury is in house 11)", by_house[2]["lord_house"] == 11)
check("C: EMPTY house 2 correctly shows zero occupying planets", by_house[2]["occupying_planets"] == [])

check("C: OCCUPIED house 6 lists both real occupants (Mars, Saturn, Rahu)",
      set(by_house[6]["occupying_planets"]) == {"Mars", "Saturn", "Rahu"})

check("C: house_lord_summary key present in the main dict", "house_lord_summary" in blocks)
check("C: house_lord_summary explicitly states an empty house rather than omitting it",
      "House 2 (Virgo): no planet placed" in blocks["house_lord_summary"])
check("C: house_lord_summary states an occupied house's real occupants",
      "House 6 (Capricorn):" in blocks["house_lord_summary"] and "Mars" in blocks["house_lord_summary"])

unresolvable = sb.build_house_lord_facts(_kundali(lagna_sign="NotASign"))
check("C: unrecognized Lagna sign -> [] (never fabricates a house)", unresolvable == [])
unresolvable_blocks = sb.build_summary_blocks_with_transit(_kundali(lagna_sign="NotASign"), _transit())
check("C: house_lord_summary safe fallback when Lagna is unrecognized",
      unresolvable_blocks["house_lord_summary"] == "House-lord data not available.")

# =================================================================
print("\n=== D: Targeted aspect facts ===")
# =================================================================
check("D: targeted_aspect_summary key present", "targeted_aspect_summary" in blocks)
# Saturn (house 6, rules [3,7,10]) -> aspects houses 8, 12, 3. Rahu/Ketu
# (house 6/12, rules [5,7,9]) both reach house 12/6/10 and 4/6/8
# respectively per the exact same DRISHTI_RULES table -- computed
# independently in _house_aspects_for() above for this fixture.
check("D: 7th house aspecting planets stated as a fact",
      blocks["targeted_aspect_summary"].startswith("Planets aspecting the 7th house:"))
check("D: 7th house lord (Saturn) and its own house's aspects stated",
      "The 7th house lord (Saturn) is placed in house 6 (Capricorn)." in blocks["targeted_aspect_summary"])
check("D: Saturn's own aspect targets stated, correctly excluding the 7th house here",
      "Saturn aspects the 3rd, 8th, 12th house(s) from its own position (not including the 7th house)." in blocks["targeted_aspect_summary"])
check("D: Venus's own aspect target stated (default [7] rule: house 9 + 6 = house 3)",
      "Venus aspects the 3rd house(s) from its own position" in blocks["targeted_aspect_summary"])
check("D: Moon's own aspect target stated (default [7] rule: house 4 + 6 = house 10)",
      "Moon aspects the 10th house(s) from its own position" in blocks["targeted_aspect_summary"])
check("D: no 'afflicted'/'malefic'/'benefic' judgment language anywhere (facts only, no invented doctrine)",
      not any(w in blocks["targeted_aspect_summary"].lower() for w in ("afflict", "malefic", "benefic")))

no_house_aspects_blocks = sb.build_summary_blocks_with_transit(_kundali(house_aspects={}), _transit())
check("D: missing house_aspects -> safe fallback, no crash",
      no_house_aspects_blocks["targeted_aspect_summary"] == "Targeted aspect data not available.")

# House 6 (the 7th lord Saturn's own house) is itself aspected by
# Jupiter (house 12, rule [5,7,9] -> 4,6,8) and Ketu (house 12, rule
# [5,7,9] -> 4,6,8) per DRISHTI_RULES -- hand-verified independently of
# the implementation before asserting this, not copied from its output.
check("D: 7th-lord-house aspectors are correctly computed via DRISHTI_RULES (Jupiter, Ketu)",
      "Planets aspecting that house: Jupiter, Ketu" in blocks["targeted_aspect_summary"])

# =================================================================
print("\n=== E: Context contract ===")
# =================================================================
Q1_KEYS = {
    "birth_chart_summary", "aspect_summary", "manglik_summary", "mahadasha_summary",
    "current_transit_summary", "dasha_window_summary", "transit_facts_summary", "gemstone_summary",
}
Q1_5_KEYS = {"house_lord_summary", "targeted_aspect_summary", "sadhesati_summary", "foreign_travel_summary"}
# Q3 Batch 3 -- two new additive, deterministic yoga-evidence keys
# (see summary_blocks.py's own comment block above
# _build_yoga_evidence_summary()). Purely additive: every pre-existing
# Q1/Q1.5 key above is untouched, still present, still the same shape.
Q3_BATCH3_KEYS = {"wealth_yoga_summary", "career_yoga_summary"}

check("E: every Q1 key preserved", Q1_KEYS.issubset(blocks.keys()))
check("E: every Q1.5 key present", Q1_5_KEYS.issubset(blocks.keys()))
check("E: exactly 14 keys total (8 Q1 + 4 Q1.5 + 2 Q3 Batch 3, no accidental extra/renamed key)",
      set(blocks.keys()) == Q1_KEYS | Q1_5_KEYS | Q3_BATCH3_KEYS)
check("E: every value is a plain string (str.format()-safe)",
      all(isinstance(v, str) for v in blocks.values()))

# =================================================================
print("\n=== F: existing prompt .format() compatibility unaffected ===")
# =================================================================
try:
    "{birth_chart_summary}\n{mahadasha_summary}\n{current_transit_summary}".format(**blocks)
    check("F: a real 3-placeholder standard prompt still formats successfully", True)
except Exception as exc:
    check(f"F: a real 3-placeholder standard prompt still formats successfully ({exc})", False)

try:
    "{house_lord_summary} {targeted_aspect_summary} {sadhesati_summary} {foreign_travel_summary}".format(**blocks)
    check("F: a hypothetical Q3 prompt using all 4 Q1.5 keys formats successfully", True)
except Exception as exc:
    check(f"F: a hypothetical Q3 prompt using all 4 Q1.5 keys formats successfully ({exc})", False)

# =================================================================
print("\n=== G: real end-to-end wiring (full_kundali_api.py) ===")
# =================================================================
try:
    from full_kundali_api import calculate_full_kundali, calculate_drishti_for_planets, DRISHTI_RULES

    real_kundali = calculate_full_kundali(
        name="Test User", dob="1990-06-15", tob="10:30",
        lat=28.6139, lon=77.2090, language="en",
    )
    check("G: calculate_full_kundali() now returns a 'foreign_travel' key", "foreign_travel" in real_kundali)
    check("G: 'foreign_travel' has the real build_foreign_travel() shape",
          isinstance(real_kundali.get("foreign_travel"), dict)
          and "positive_points" in real_kundali["foreign_travel"])
    check("G: calculate_full_kundali() now returns a 'house_aspects' key", "house_aspects" in real_kundali)
    check("G: 'house_aspects' covers all 12 houses",
          isinstance(real_kundali.get("house_aspects"), dict) and set(real_kundali["house_aspects"].keys()) == set(range(1, 13)))

    # DRISHTI_RULES hoist refactor: calculate_drishti_for_planets()'s
    # own output must be byte-for-byte unaffected.
    drishti_result = calculate_drishti_for_planets(real_kundali["planets"])
    check("G: calculate_drishti_for_planets() still returns a per-planet aspecting/aspected_by shape",
          all("aspecting" in v and "aspected_by" in v for v in drishti_result.values()))
    check("G: DRISHTI_RULES module constant matches the values calculate_drishti_for_planets() actually used",
          DRISHTI_RULES == {"Saturn": [3, 7, 10], "Mars": [4, 7, 8], "Jupiter": [5, 7, 9], "Rahu": [5, 7, 9], "Ketu": [5, 7, 9]})

    # Full pipeline: summary_blocks.py against REAL calculated data, no
    # KeyError/crash anywhere.
    from transit_engine import get_current_positions
    real_transit = get_current_positions()
    real_blocks = sb.build_summary_blocks_with_transit(real_kundali, real_transit)
    check("G: full real pipeline produces all 14 expected keys (Q1+Q1.5+Q3 Batch 3) with no crash",
          set(real_blocks.keys()) == Q1_KEYS | Q1_5_KEYS | Q3_BATCH3_KEYS)
    check("G: full real pipeline's house_lord_summary mentions all 12 houses",
          all(f"House {n} (" in real_blocks["house_lord_summary"] for n in range(1, 13)))
except Exception as exc:
    check(f"G: real end-to-end wiring test raised an unexpected exception ({exc})", False)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
