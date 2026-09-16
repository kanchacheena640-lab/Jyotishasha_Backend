"""
test_summary_blocks_q1_context.py
-------------------------------------------------
Paid Report Quality -- Q1 (Shared Astrology Data Quality Upgrade)
verification.

summary_blocks.py has zero Flask/DB dependency (pure function of its
kundali/transit dict inputs) -- this file needs no local Postgres, no
app context, no OPENAI_API_KEY. Fixtures below mirror the exact
real shapes read from full_kundali_api.py::calculate_full_kundali()
and transit_engine.py::get_current_positions(), inspected directly
before writing this file (not guessed).

Covers:
  A. Ordinal formatting (_ordinal) for houses 1-12, plus edge cases.
  B. birth_chart_summary uses correct ordinals end-to-end.
  C. mahadasha_summary / current_transit_summary UNCHANGED (Q1
     compatibility requirement) -- exact prior text reproduced.
  D. aspect_summary / manglik_summary still present and stable.
  E. dasha_window_summary -- current window, upcoming windows, the
     Mahadasha-boundary-crossing case, and the "not available" fallback.
  F. transit_facts_summary -- all planets, Lagna-relative house, and
     the "not available" fallback.
  G. gemstone_summary -- normal case, incomplete-data fallback case.
  H. Context contract: every key existing/future prompts may rely on
     is present, and Q3-facing new keys don't collide with the three
     existing ones.
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
# Fixtures -- shapes verified directly against full_kundali_api.py /
# transit_engine.py before writing this file.
# ---------------------------------------------------------------

def _antardashas(maha_lord, sequence, start_year):
    """Build a 9-entry antardasha list for one Mahadasha, matching
    full_kundali_api.py::calculate_antardashas()'s own output shape."""
    out = []
    for i, lord in enumerate(sequence):
        out.append({
            "planet": lord,
            "start": f"{start_year + i}-01-01",
            "end": f"{start_year + i + 1}-01-01",
        })
    return out


DASHA_SEQUENCE = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]


def _mahadashas():
    """A minimal-but-realistic 2-Mahadasha fixture (only 2 of the real
    9 are needed to exercise the boundary-crossing case) shaped exactly
    like calculate_vimshottari_dasha()'s real return value."""
    return [
        {
            "mahadasha": "Rahu",
            "start": "2015-01-01",
            "end": "2033-01-01",
            "antardashas": _antardashas("Rahu", DASHA_SEQUENCE, 2015),
        },
        {
            "mahadasha": "Jupiter",
            "start": "2033-01-01",
            "end": "2049-01-01",
            "antardashas": _antardashas("Jupiter", DASHA_SEQUENCE, 2033),
        },
    ]


def _kundali(**overrides):
    mahadashas = _mahadashas()
    base = {
        "lagna_sign": "Leo",
        "planets": [
            # "Sun" is listed before "Ascendant (Lagna)" deliberately: the
            # UNCHANGED (Q1 does not touch it) current_transit_summary
            # lagna_lord search takes the FIRST house==1 entry it finds.
            # Real production data (calculate_planet_positions()'s own
            # sort key (house, name)) would alphabetically sort "Ascendant
            # (Lagna)" before any real planet sharing house 1 -- a
            # pre-existing quirk of that unchanged logic, out of Q1's
            # scope to fix (see report), and deliberately not exercised
            # by this compatibility check.
            {"name": "Sun", "house": 1, "sign": "Leo"},
            {"name": "Ascendant (Lagna)", "house": 1, "sign": "Leo"},
            {"name": "Moon", "house": 2, "sign": "Virgo", "aspecting": ["Mars"]},
            {"name": "Mars", "house": 3, "sign": "Libra"},
            {"name": "Mercury", "house": 11, "sign": "Gemini"},
            {"name": "Jupiter", "house": 12, "sign": "Cancer"},
            {"name": "Venus", "house": 9, "sign": "Taurus"},
        ],
        "manglik_dosh": {"is_manglik": False},
        "Mahadasha": mahadashas,
        "current_mahadasha": mahadashas[0],
        "current_antardasha": mahadashas[0]["antardashas"][0],
        "gemstone_suggestion": {
            "planet": "Jupiter",
            "paragraph": "We have deeply analyzed your Kundali...",
            "gemstone": "Yellow Sapphire (पुखराज)",
            "substone": "Citrine (सुनैला)",
            "cta": {},
        },
    }
    base.update(overrides)
    return base


def _transit():
    return {
        "timestamp_ist": "2026-09-16 12:00:00 IST",
        "positions": {
            "Sun": {"rashi": "Virgo", "degree": 10.5, "motion": "Direct"},
            "Moon": {"rashi": "Aries", "degree": 5.0, "motion": "Direct"},
            "Mars": {"rashi": "Gemini", "degree": 12.0, "motion": "Direct"},
            "Mercury": {"rashi": "Virgo", "degree": 3.2, "motion": "Retrograde"},
            "Jupiter": {"rashi": "Cancer", "degree": 20.0, "motion": "Direct"},
            "Venus": {"rashi": "Libra", "degree": 1.1, "motion": "Direct"},
            "Saturn": {"rashi": "Aquarius", "degree": 8.8, "motion": "Retrograde"},
            "Rahu": {"rashi": "Pisces", "degree": 15.0, "motion": "Retrograde"},
            "Ketu": {"rashi": "Virgo", "degree": 15.0, "motion": "Retrograde"},
        },
    }


# =================================================================
print("=== A: _ordinal() -- houses 1-12 and edge cases ===")
# =================================================================
EXPECTED_ORDINALS = {
    1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th",
    7: "7th", 8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th",
}
for house, expected in EXPECTED_ORDINALS.items():
    check(f"A: house {house} -> {expected!r}", sb._ordinal(house) == expected)

check("A: 21 -> '21st' (not 21th)", sb._ordinal(21) == "21st")
check("A: 111 -> '111th' (11-13 exception applies at any hundred)", sb._ordinal(111) == "111th")
check("A: 22 -> '22nd'", sb._ordinal(22) == "22nd")

# =================================================================
print("\n=== B: birth_chart_summary uses correct ordinals end-to-end ===")
# =================================================================
blocks = sb.build_summary_blocks_with_transit(_kundali(), _transit())
check("B: no 'in 1th'/'in 2th'/'in 3th' anywhere in birth_chart_summary (word-boundary-safe check)",
      not any(bad in blocks["birth_chart_summary"] for bad in ("in 1th house", "in 2th house", "in 3th house")))
check("B: '1st house' present for Sun", "1st house" in blocks["birth_chart_summary"])
check("B: '11th house' present for Mercury", "11th house" in blocks["birth_chart_summary"])
check("B: '12th house' present for Jupiter", "12th house" in blocks["birth_chart_summary"])
check("B: Ascendant line itself is not duplicated as a placement", "Ascendant (Lagna) is placed" not in blocks["birth_chart_summary"])

# =================================================================
print("\n=== C: mahadasha_summary / current_transit_summary UNCHANGED ===")
# =================================================================
k = _kundali()
t = _transit()
maha = k["current_mahadasha"]
antar = k["current_antardasha"]
expected_mahadasha_summary = (
    f"You are currently in the Mahadasha of {maha.get('mahadasha')} and Antardasha of {antar.get('planet')}. "
    f"This phase will end on {antar.get('end')}."
)
check("C: mahadasha_summary text byte-for-byte matches the pre-Q1 formula",
      blocks["mahadasha_summary"] == expected_mahadasha_summary)

check("C: current_transit_summary still Lagna-lord/Saturn/Jupiter only (old shape preserved)",
      "Your Lagna lord Sun is transiting in Virgo" in blocks["current_transit_summary"]
      and "Saturn is currently in Aquarius" in blocks["current_transit_summary"]
      and "Jupiter is currently in Cancer" in blocks["current_transit_summary"])
check("C: current_transit_summary does NOT include Mars/Venus/Mercury (old shape, not the new richer one)",
      "Mars is currently" not in blocks["current_transit_summary"]
      and "Venus is currently" not in blocks["current_transit_summary"])

# =================================================================
print("\n=== D: aspect_summary / manglik_summary still present and stable ===")
# =================================================================
check("D: aspect_summary key present", "aspect_summary" in blocks)
check("D: aspect_summary reflects Moon's aspecting data", "Moon is aspecting Mars" in blocks["aspect_summary"])
check("D: manglik_summary key present and correct for is_manglik=False", blocks["manglik_summary"] == "You are not Mangalik.")

blocks_manglik = sb.build_summary_blocks_with_transit(_kundali(manglik_dosh={"is_manglik": True}), _transit())
check("D: manglik_summary correct for is_manglik=True", blocks_manglik["manglik_summary"] == "You are Mangalik.")

# =================================================================
print("\n=== E: dasha_window_summary -- new, deterministic, no invented dates ===")
# =================================================================
check("E: dasha_window_summary key present", "dasha_window_summary" in blocks)
check("E: current window states real Mahadasha/Antardasha lords and dates",
      "Current window: Rahu Mahadasha - Ketu Antardasha, from 2015-01-01 to 2016-01-01" in blocks["dasha_window_summary"])
check("E: current window also states the overall Mahadasha end date",
      "The overall Rahu Mahadasha runs until 2033-01-01" in blocks["dasha_window_summary"])
check("E: two real upcoming windows are listed (Venus, then Sun antardasha)",
      "Upcoming window: Rahu Mahadasha - Venus Antardasha, from 2016-01-01 to 2017-01-01" in blocks["dasha_window_summary"]
      and "Upcoming window: Rahu Mahadasha - Sun Antardasha, from 2017-01-01 to 2018-01-01" in blocks["dasha_window_summary"])

# Boundary case: current antardasha is the LAST one in its Mahadasha --
# upcoming windows must correctly cross into the NEXT Mahadasha's own
# already-computed antardashas, never invent a date to bridge the gap.
mahadashas = _mahadashas()
last_antar_kundali = _kundali(
    current_mahadasha=mahadashas[0],
    current_antardasha=mahadashas[0]["antardashas"][-1],  # Mercury, the 9th/last antardasha of Rahu MD
)
boundary_blocks = sb.build_summary_blocks_with_transit(last_antar_kundali, _transit())
check("E: Mahadasha-boundary upcoming window crosses into the next real Mahadasha (Jupiter MD, Ketu AD)",
      "Upcoming window: Jupiter Mahadasha - Ketu Antardasha" in boundary_blocks["dasha_window_summary"])

# Fallback: current window cannot be located / malformed input -> safe
# string, never a raised exception.
fallback_blocks = sb.build_summary_blocks_with_transit(
    _kundali(current_mahadasha={}, current_antardasha={}), _transit(),
)
check("E: missing current dasha data -> safe fallback string, no crash",
      fallback_blocks["dasha_window_summary"] == "Dasha window data not available.")

# =================================================================
print("\n=== F: transit_facts_summary -- all planets + Lagna-relative house ===")
# =================================================================
check("F: transit_facts_summary key present", "transit_facts_summary" in blocks)
for planet in ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"):
    check(f"F: {planet} present in transit_facts_summary", planet in blocks["transit_facts_summary"])
check("F: retrograde motion is stated as a fact (Saturn)",
      "Saturn is transiting Aquarius" in blocks["transit_facts_summary"] and "Retrograde" in blocks["transit_facts_summary"])
# Lagna = Leo (index 4). Sun transiting Virgo (index 5) -> (5-4)%12+1 = 2nd house.
check("F: Lagna-relative house computed correctly (Sun in Virgo, Leo Lagna -> 2nd house)",
      "Sun is transiting Virgo (10.5°, Direct), your 2nd house from Lagna." in blocks["transit_facts_summary"])
check("F: context builder states facts only, never a favorable/unfavorable judgment word",
      not any(w in blocks["transit_facts_summary"].lower() for w in ("favorable", "unfavorable", "good time", "bad time")))

empty_transit_blocks = sb.build_summary_blocks_with_transit(_kundali(), {"positions": {}})
check("F: no transit positions -> safe fallback string, no crash",
      empty_transit_blocks["transit_facts_summary"] == "Transit data not available.")

# =================================================================
print("\n=== G: gemstone_summary -- real backend data now reaches the context ===")
# =================================================================
check("G: gemstone_summary key present", "gemstone_summary" in blocks)
check("G: gemstone_summary states the real calculated planet/gemstone",
      "Your supportive planet is Jupiter, associated with the gemstone Yellow Sapphire (पुखराज)." in blocks["gemstone_summary"])
check("G: gemstone_summary includes the sub-stone alternative when present",
      "A supportive sub-stone alternative is Citrine (सुनैला)." in blocks["gemstone_summary"])

incomplete_gem_blocks = sb.build_summary_blocks_with_transit(
    _kundali(gemstone_suggestion={"planet": None, "paragraph": "Data incomplete for recommendation."}),
    _transit(),
)
check("G: incomplete gemstone_suggestion (no 'gemstone'/'substone' keys) -> safe fallback, no KeyError",
      incomplete_gem_blocks["gemstone_summary"] == "Gemstone recommendation data not available.")

missing_gem_blocks = sb.build_summary_blocks_with_transit(_kundali(gemstone_suggestion=None), _transit())
check("G: gemstone_suggestion entirely absent/None -> safe fallback, no crash",
      missing_gem_blocks["gemstone_summary"] == "Gemstone recommendation data not available.")

# =================================================================
print("\n=== H: context contract -- stable keys for current + future prompts ===")
# =================================================================
REQUIRED_EXISTING_KEYS = {
    "birth_chart_summary", "mahadasha_summary", "current_transit_summary",
}
REQUIRED_NEW_KEYS = {
    "aspect_summary", "manglik_summary",
    "dasha_window_summary", "transit_facts_summary", "gemstone_summary",
}
check("H: every existing prompt-facing key is present",
      REQUIRED_EXISTING_KEYS.issubset(blocks.keys()))
check("H: every Q1 new/stabilized key is present",
      REQUIRED_NEW_KEYS.issubset(blocks.keys()))
# Q1.5 -- Paid Report Product Intelligence Data Foundation legitimately
# added further keys (house_lord_summary/targeted_aspect_summary/
# sadhesati_summary/foreign_travel_summary) after this Q1 test file was
# written. This was an exact-equality check when Q1 was the only phase
# that had touched this dict; it is now a subset check instead, so it
# keeps proving "no Q1 key was ever renamed/dropped" (its real intent)
# without falsely flagging Q1.5's own approved, additive evolution of
# the same dict as a regression. Q1.5's own test file owns the current
# full key-count assertion.
check("H: no Q1 key was renamed or dropped by any later phase",
      (REQUIRED_EXISTING_KEYS | REQUIRED_NEW_KEYS).issubset(blocks.keys()))
check("H: every value is a plain string (str.format()-safe, no nested dict/list leaking into a prompt)",
      all(isinstance(v, str) for v in blocks.values()))

# =================================================================
print("\n=== I: existing report generation compatibility -- prompt .format() still works ===")
# =================================================================
sample_template = (
    "{birth_chart_summary}\n{mahadasha_summary}\n{current_transit_summary}"
)
try:
    sample_template.format(**blocks)
    check("I: a real 3-placeholder standard prompt still formats successfully with the new context dict", True)
except Exception as exc:
    check(f"I: a real 3-placeholder standard prompt still formats successfully ({exc})", False)

try:
    "{dasha_window_summary} {transit_facts_summary} {gemstone_summary}".format(**blocks)
    check("I: a hypothetical Q3 prompt using all 3 new keys formats successfully", True)
except Exception as exc:
    check(f"I: a hypothetical Q3 prompt using all 3 new keys formats successfully ({exc})", False)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
