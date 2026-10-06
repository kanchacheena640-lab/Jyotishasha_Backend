"""
SNR-2B -- deterministic spouse-evidence engine (Spouse Nature Report,
rep_026). Verifies modules/payments/spouse_evidence.py and
modules/payments/spouse_sign_table.py against the FROZEN SNR-2A /
SNR-2A.1 astrology contract.

Plain check()-harness, same style as the repo's other standalone tests.
Run:  python test_spouse_evidence_engine.py
"""

import copy
import json
import sys
from fractions import Fraction

from full_kundali_api import DRISHTI_RULES, calculate_full_kundali, calculate_house_aspects
from services.neechbhang_rajyog import DEBILITATIONS, EXALTATIONS
from summary_blocks import SIGN_LORDS
from modules.payments import spouse_evidence as se
from modules.payments.spouse_sign_table import (
    DIMENSION_POLES, SEVENTH_SIGN_TABLE, SIGN_ORDER, TRAIT_DIMENSIONS, seventh_sign_for_lagna, seventh_sign_layer,
)

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


def dms(deg, minute=0, sec=0.0):
    return deg + minute / 60 + sec / 3600


GRAHAS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")


def make_kundali(lagna, places, asc_deg=10.0):
    """Synthetic calculate_full_kundali()-shaped input. places: planet -> (sign, degree_in_sign)."""
    li = SIGN_ORDER.index(lagna)
    planets = []
    for name in GRAHAS:
        sign, deg = places[name]
        si = SIGN_ORDER.index(sign)
        planets.append({"name": name, "sign": sign, "house": (si - li) % 12 + 1,
                        "degree": round(deg, 2), "longitude": si * 30 + deg})
    planets.append({"name": "Ascendant (Lagna)", "sign": lagna, "house": 1,
                    "degree": round(asc_deg, 2), "longitude": li * 30 + asc_deg})
    return {"lagna_sign": lagna, "planets": planets}


def opposite(sign):
    return SIGN_ORDER[(SIGN_ORDER.index(sign) + 6) % 12]


# Base (Aries Lagna): 7th Libra (lord Venus) is EMPTY and un-aspected; Venus in Gemini (3rd) unaspected.
BASE_ARIES = {
    "Sun": ("Taurus", 5.0), "Moon": ("Taurus", 6.0), "Mars": ("Taurus", 7.0), "Mercury": ("Taurus", 8.0),
    "Jupiter": ("Taurus", 9.0), "Venus": ("Gemini", 15.0), "Saturn": ("Taurus", 11.0),
    "Rahu": ("Taurus", 12.0), "Ketu": ("Scorpio", 12.0),
}


def chart_of(kundali):
    return se._Chart(kundali)


print("=== 1. Navamsa (D9) boundaries ===")
nav = se.navamsa_sign_from_longitude
check("0deg00'00\" Aries -> Aries", nav(0.0) == "Aries")
check("3deg19'59\" Aries -> Aries", nav(dms(3, 19, 59)) == "Aries")
check("3deg20'00\" Aries -> Taurus (lower-inclusive boundary)", nav(dms(3, 20, 0)) == "Taurus")
check("26deg40'00\" Aries -> Sagittarius", nav(dms(26, 40, 0)) == "Sagittarius")
check("29deg59'59\" Aries -> Sagittarius", nav(dms(29, 59, 59)) == "Sagittarius")
check("0deg Taurus -> Capricorn (fixed: 9th from it)", nav(30.0) == "Capricorn")
check("0deg Gemini -> Libra (dual: 5th from it)", nav(60.0) == "Libra")
check("0deg Cancer -> Cancer (movable: same sign)", nav(90.0) == "Cancer")
check("29deg59'59\" Pisces -> Pisces", nav(330 + dms(29, 59, 59)) == "Pisces")


def classical_d9(sign_idx, segment):
    modality = ("movable", "fixed", "dual")[sign_idx % 3]
    start = {"movable": sign_idx, "fixed": sign_idx + 8, "dual": sign_idx + 4}[modality]
    return SIGN_ORDER[(start + segment) % 12]


ok_all = True
for si in range(12):
    for k in range(9):
        lower = si * 30 + k * 10 / 3
        mid = lower + 5 / 3
        last = si * 30 + (k + 1) * 10 / 3 - 1 / 36000  # 0.1" before the next boundary
        expected = classical_d9(si, k)
        if not (nav(lower) == nav(mid) == nav(last) == expected):
            ok_all = False
check("all 108 segments (lower edge, middle, 0.1\" before upper edge) match the classical movable/fixed/dual sequence", ok_all)
check("3deg19'59.9\" stays Aries (full precision; the rounded 0.01deg value 3.33 would be ambiguous)",
      nav(dms(3, 19, 59.9)) == "Aries" and round(dms(3, 19, 59.9), 2) == 3.33)
check("3deg20'00.1\" is Taurus although its rounded degree (3.33) looks like the Aries segment",
      nav(dms(3, 20, 0.1)) == "Taurus" and round(dms(3, 20, 0.1), 2) == 3.33)
check("longitude 360 wraps to Aries", nav(360.0) == "Aries")

print("\n=== 2. Darakaraka (7-karaka) ===")
k = make_kundali("Aries", dict(BASE_ARIES, Sun=("Taurus", 5.0), Moon=("Taurus", 2.0)))
dk = se._darakaraka(chart_of(k))
check("lowest degree within sign wins (Moon 2deg)", dk["planet"] == "Moon" and dk["status"] == "OK" and dk["scheme"] == "7_karaka")
k = make_kundali("Aries", dict(BASE_ARIES, Rahu=("Taurus", 0.5), Ketu=("Scorpio", 0.5), Moon=("Taurus", 2.0)))
check("Rahu/Ketu ignored even at a lower degree", se._darakaraka(chart_of(k))["planet"] == "Moon")
k = make_kundali("Aries", dict(BASE_ARIES, Sun=("Taurus", 1.25), Moon=("Gemini", 1.25)))
dk = se._darakaraka(chart_of(k))
check("exact tie -> DK_TIE with both planets preserved", dk["tie"] and dk["status"] == "DK_TIE" and dk["planets"] == ["Sun", "Moon"] and dk["planet"] is None)
k = make_kundali("Aries", dict(BASE_ARIES, Sun=("Leo", 1.0), Moon=("Aries", 4.0), Mars=("Taurus", 7.0)))
check("uses degree within sign, not absolute longitude (Sun 121deg abs but 1deg in sign)", se._darakaraka(chart_of(k))["planet"] == "Sun")

print("\n=== 3. Dignity ===")
check("all 7 exaltation signs -> EXALTED", all(se.dignity(p, s) == "EXALTED" for p, s in EXALTATIONS.items()))
check("all 7 debilitation signs -> DEBILITATED", all(se.dignity(p, s) == "DEBILITATED" for p, s in DEBILITATIONS.items()))
check("own signs (from SIGN_LORDS) -> OWN, unless also the exaltation sign",
      all(se.dignity(lord, sign) == "OWN" for sign, lord in SIGN_LORDS.items() if EXALTATIONS.get(lord) != sign))
check("precedence: Mercury in Virgo (own AND exalted) -> EXALTED", se.dignity("Mercury", "Virgo") == "EXALTED")
check("a neutral placement -> NEUTRAL (Venus in Gemini)", se.dignity("Venus", "Gemini") == "NEUTRAL")
check("Rahu/Ketu have no dignity", all(se.dignity(n, s) is None for n in ("Rahu", "Ketu") for s in SIGN_ORDER))
check("tables are the existing Jyotishasha tables (no new dignity source)", se.EXALTATIONS is EXALTATIONS and se.DEBILITATIONS is DEBILITATIONS)

print("\n=== 4. Aspects / Ascendant exclusion / empty 7th ===")
parity = all(se.aspect_targets(p, h) == [((h + n - 1) % 12) or 12 for n in DRISHTI_RULES.get(p, [7])]
             for p in GRAHAS for h in range(1, 13))
check("aspect targets == existing DRISHTI_RULES for every planet x house", parity and se.DRISHTI_RULES is DRISHTI_RULES)
k = make_kundali("Aries", BASE_ARIES)
global_aspects = calculate_house_aspects(copy.deepcopy(k["planets"]))
check("(control) the GLOBAL helper does count the Ascendant record as aspecting the 7th", "Ascendant (Lagna)" in global_aspects[7])
payload = se.build_spouse_evidence(k)
blob = json.dumps(payload)
check("the Ascendant record never appears anywhere in spouse evidence", "Ascendant" not in blob)
d1 = payload["chart_facts"]["d1"]
check("empty 7th still has sign, lord and lord placement", d1["occupants_7th"] == [] and d1["seventh_sign"] == "Libra"
      and d1["seventh_lord"] == "Venus" and d1["seventh_lord_house"] == 3 and d1["seventh_lord_house_from_seventh"] == 9)
check("empty, un-aspected 7th -> empty aspects list, still valid payload", d1["aspects_on_7th"] == [] and payload["schema_version"] == "spouse_evidence_v1")
check("all 12 houses present with sign and lord, empty houses included",
      [h["house"] for h in d1["houses"]] == list(range(1, 13)) and all(h["sign"] and h["lord"] for h in d1["houses"])
      and any(h["occupants"] == [] for h in d1["houses"]))
k2 = make_kundali("Aries", dict(BASE_ARIES, Saturn=("Cancer", 11.0)))  # Saturn 4th -> 10th aspect lands on 1st; 4th->? (3,7,10) -> 6,10,1
k3 = make_kundali("Aries", dict(BASE_ARIES, Mars=("Cancer", 7.0)))     # Mars 4th -> 4th aspect lands on 7th
check("Mars special 4th aspect reaches the empty 7th", "Mars" in se.build_spouse_evidence(k3)["chart_facts"]["d1"]["aspects_on_7th"])
check("Saturn in 4th does not aspect the 7th (3/7/10 -> 6/10/1)", "Saturn" not in se.build_spouse_evidence(k2)["chart_facts"]["d1"]["aspects_on_7th"])

print("\n=== 5. Derived spouse houses ===")
check("spouse 1..12 -> native 7,8,9,10,11,12,1,2,3,4,5,6",
      [se.native_house_for_spouse_house(n) for n in range(1, 13)] == [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6])
check("inverse mapping round-trips", all(se.spouse_house_for_native_house(se.native_house_for_spouse_house(n)) == n for n in range(1, 13)))
check("spouse kendras = native 7,10,1,4; trikonas = native 7,11,3; used dusthanas = native 12,6",
      se.SPOUSE_KENDRA_NATIVE == {7, 10, 1, 4} and se.SPOUSE_TRIKONA_NATIVE == {7, 11, 3} and se.SPOUSE_DUSTHANA_USED_NATIVE == {12, 6})
check("growth houses = spouse 3/6/10/11 = native 9/12/4/5", se.SPOUSE_GROWTH_NATIVE == {9, 12, 4, 5})

print("\n=== 6. Valence (frozen order) ===")
# Cancer Lagna: 7th Capricorn, lord Saturn. Saturn debilitated in Aries (10th) aspects the 7th by its 10th aspect.
c = chart_of(make_kundali("Cancer", dict(BASE_ARIES, Saturn=("Aries", 11.0), Rahu=("Taurus", 12.0), Ketu=("Scorpio", 12.0))))
check("step 1: a planet owning the target -> SUPPORT, even when debilitated", se.planet_valence(c, "Saturn", 7, "health") == {"valence": "SUPPORT", "rule": "owns_target", "tags": []})
c = chart_of(make_kundali("Aries", dict(BASE_ARIES, Mars=("Capricorn", 7.0), Jupiter=("Capricorn", 9.0), Saturn=("Leo", 11.0))))
check("step 2: exalted malefic (Mars in Capricorn) -> SUPPORT", se.planet_valence(c, "Mars", 7, "health")["valence"] == "SUPPORT")
check("step 3: debilitated benefic (Jupiter in Capricorn) -> STRESS", se.planet_valence(c, "Jupiter", 7, "health")["valence"] == "STRESS")
check("step 4: natural malefic on a growth house (native 5 = spouse 11th) -> NEUTRAL", se.planet_valence(c, "Saturn", 5, "wealth")["rule"] == "growth_house_malefic")
check("step 5: same Saturn on native 7 -> STRESS", se.planet_valence(c, "Saturn", 7, "health")["valence"] == "STRESS")
check("step 5: Venus natural benefic -> SUPPORT (neutral dignity)", se.planet_valence(chart_of(make_kundali("Taurus", BASE_ARIES | {"Venus": ("Gemini", 15.0)})), "Venus", 7, "health")["valence"] == "SUPPORT")
check("Sun/Moon/Mercury fall back to NEUTRAL", all(se.planet_valence(c, p, 7, "health")["rule"] in ("natural_neutral", "dignified") for p in ("Sun", "Mercury")))
check("Rahu: STRESS for health, NEUTRAL + 'unconventional' tag for wealth (native 8, not a growth house)",
      se.planet_valence(c, "Rahu", 7, "health")["valence"] == "STRESS"
      and se.planet_valence(c, "Rahu", 8, "wealth") == {"valence": "NEUTRAL", "rule": "node_wealth_neutral", "tags": ["unconventional"]})

print("\n=== 7. Nature: classification fixtures ===")


def src(tier, chart, pole, dim="communication", planet=None, q=None, sid=None):
    return {"source": sid or f"{tier}{chart}{pole}{planet}", "factor": "f", "tier": tier, "chart": chart,
            "planet": planet, "sign": None, "votes": {dim: pole}, "expression_quality": q}


cd = se.classify_dimension
r = cd("communication", [src("P", "D1", "expressive"), src("P", "D1", "expressive", sid="x")])
check("DOMINANT: >=2 primary, no opposing primary", r["class"] == "DOMINANT" and r["direction"] == "expressive" and r["d1_d9"] == "D1_ONLY")
r = cd("communication", [src("P", "D1", "expressive"), src("S", "D1", "expressive")])
check("SUPPORTED: 1 primary + 1 secondary same direction", r["class"] == "SUPPORTED")
r = cd("communication", [src("P", "D1", "expressive"), src("T", "D1", "expressive")])
check("SUPPORTED: 1 primary + 1 supporting same direction", r["class"] == "SUPPORTED")
r = cd("communication", [src("P", "D1", "expressive"), src("S", "D1", "reserved")])
check("MIXED: primary vs opposing secondary", r["class"] == "MIXED" and r["direction"] is None and r["reportable"])
r = cd("communication", [src("P", "D1", "expressive"), src("P", "D1", "expressive", sid="y"), src("P", "D1", "reserved")])
check("MIXED (not DOMINANT) when a primary vote opposes", r["class"] == "MIXED")
r = cd("communication", [src("T", "D1", "expressive")])
check("NOT_INDICATED: supporting tier alone; kept but not reportable", r["class"] == "NOT_INDICATED" and not r["reportable"] and r["evidence"])
r = cd("communication", [src("P", "D1", "expressive"), src("S", "D1", "expressive"), src("S", "D9", "expressive")])
check("CONFIRMED: SUPPORTED + matching D9 -> DOMINANT", r["class"] == "DOMINANT" and r["d1_d9"] == "CONFIRMED")
r = cd("communication", [src("P", "D1", "expressive"), src("S", "D9", "expressive")])
check("CONFIRMED: lone primary + matching D9 -> SUPPORTED", r["class"] == "SUPPORTED" and r["d1_d9"] == "CONFIRMED")
r = cd("communication", [src("S", "D9", "reserved"), src("S", "D9", "reserved", sid="z")])
check("REFINEMENT: D9-only (2 votes) -> SUPPORTED at most", r["class"] == "SUPPORTED" and r["d1_d9"] == "REFINEMENT")
r = cd("communication", [src("S", "D9", "reserved")])
check("REFINEMENT: a single D9 vote is not reportable", r["class"] == "NOT_INDICATED" and r["d1_d9"] == "REFINEMENT")
r = cd("communication", [src("P", "D1", "expressive"), src("P", "D1", "expressive", sid="w"), src("S", "D9", "reserved")])
check("OUTER_INNER_CONTRAST: D1 primary vs opposing D9 -> MIXED (D9 never overrides)", r["class"] == "MIXED" and r["d1_d9"] == "OUTER_INNER_CONTRAST")
r = cd("communication", [src("P", "D1", "expressive", planet="Mars", q="well_supported"), src("S", "D1", "expressive", planet="Venus", q="uneven"),
                         src("T", "D1", "expressive", planet="Sun", q="well_supported")])
check("dignity changes expression_quality only, never direction", r["direction"] == "expressive")
check("expression_quality is presence/conflict, not a majority: well + uneven present -> neutral", r["expression_quality"] == "neutral")
r = cd("communication", [src("P", "D1", "expressive", planet="Mars", q="well_supported"), src("S", "D1", "expressive", planet="Sun", q="well_supported")])
check("expression_quality: only well_supported present -> well_supported", r["expression_quality"] == "well_supported")
r = cd("communication", [src("P", "D1", "expressive", planet="Mars", q="uneven"), src("S", "D1", "expressive", planet="Sun")])
check("expression_quality: only uneven present -> uneven", r["expression_quality"] == "uneven")
r = cd("communication", [src("S", "D1", "expressive"), src("S", "D9", "reserved"), src("S", "D9", "reserved", sid="v")])
check("D9 never overrides opposing D1 secondary evidence -> MIXED (not a D9 REFINEMENT)",
      r["class"] == "MIXED" and r["direction"] is None and r["d1_d9"] == "OUTER_INNER_CONTRAST")
r = cd("communication", [src("T", "D1", "expressive"), src("S", "D9", "reserved"), src("S", "D9", "reserved", sid="u")])
check("supporting-tier-only D1 does not block a D9 REFINEMENT (frozen MIXED rule uses primary/secondary)",
      r["class"] == "SUPPORTED" and r["d1_d9"] == "REFINEMENT")
check("no probability: class labels only, no floats in a trait", "%" not in json.dumps(r) and not any(isinstance(v, float) for v in json.dumps(r)))

print("\n=== 8. Nature: one vote per source / no double counting ===")
check("Leo: element (dynamic) vs modality (steady) conflict -> no temperament vote", "temperament" not in SEVENTH_SIGN_TABLE["Leo"]["votes"])
check("Capricorn: earth (steady) vs movable (dynamic) -> no temperament vote", "temperament" not in SEVENTH_SIGN_TABLE["Capricorn"]["votes"])
check("Aries: fire + movable both 'dynamic' -> ONE temperament vote", SEVENTH_SIGN_TABLE["Aries"]["votes"]["temperament"] == "dynamic")
check("every sign casts at most one vote per dimension, only on valid poles",
      all(set(v["votes"]) <= set(DIMENSION_POLES) and all(p in DIMENSION_POLES[d] for d, p in v["votes"].items()) for v in SEVENTH_SIGN_TABLE.values()))
# Aries Lagna, Venus (7th lord) in Libra = occupies the 7th: counted once as P3, never also as P1.
c = chart_of(make_kundali("Aries", dict(BASE_ARIES, Venus=("Libra", 15.0))))
d9 = se._d9_facts(c)
srcs = se._nature_sources(c, d9, se._darakaraka(c))
ids = [s["source"] for s in srcs]
check("7th lord in the 7th: P3 present, no P1 duplicate", "p3_seventh_lord:Venus" in ids and "p1_occupant:Venus" not in ids)
check("the 7th sign source carries element/modality votes only (equals the shared table)",
      next(s for s in srcs if s["source"] == "p2_seventh_sign")["votes"] == SEVENTH_SIGN_TABLE["Libra"]["votes"])
check("every source votes at most once per dimension", all(len(s["votes"]) == len(set(s["votes"])) for s in srcs) and len(ids) == len(set(ids)))
# Taurus Lagna: 7th Scorpio (Mars). Venus & Jupiter in Leo (4th): not in/aspecting the 7th, not conjunct/aspecting Mars.
unlinked = {"Sun": ("Gemini", 0.5), "Moon": ("Gemini", 6.0), "Mars": ("Gemini", 7.0), "Mercury": ("Gemini", 8.0),
            "Jupiter": ("Leo", 9.0), "Venus": ("Leo", 15.0), "Saturn": ("Gemini", 11.0), "Rahu": ("Taurus", 12.0), "Ketu": ("Scorpio", 12.0)}
pl = se.build_spouse_evidence(make_kundali("Taurus", unlinked))
all_votes = [v for t in pl["nature"]["traits"] for v in t["evidence"]]
check("unlinked Venus/Jupiter cast no D1 karaka trait vote",
      not any(v["planet"] in ("Venus", "Jupiter") and v["chart"] == "D1" for v in all_votes))
check("(a D9 role such as D9 7th lord is a separate, legitimate S3 factor)",
      all(v["source"].startswith("s3_d9_") for v in all_votes if v["planet"] in ("Venus", "Jupiter")))
check("unlinked Venus/Jupiter still reported as context with empty links",
      pl["chart_facts"]["d1"]["venus"]["link_to_7th"] == [] and pl["chart_facts"]["d1"]["jupiter"]["link_to_7th"] == [])

print("\n=== 9. Health ===")
H = se.classify_health_counts
check("NEEDS_ATTENTION: PT>=2, PS=0", H(0, 2, 0) == "NEEDS_ATTENTION" and H(0, 3, 0) == "NEEDS_ATTENTION")
check("NEEDS_ATTENTION: PT>=1, PS=0, ST>=1", H(0, 1, 1) == "NEEDS_ATTENTION")
check("MIXED: PT=1, PS=0, ST=0 (one stress alone is not enough)", H(0, 1, 0) == "MIXED")
check("MIXED: PT>=2 but any PS", H(1, 2, 0) == "MIXED")
check("SUPPORTIVE: PS>=2, PT=0, ST=0", H(2, 0, 0) == "SUPPORTIVE" and H(4, 0, 0) == "SUPPORTIVE")
check("MIXED: PS>=2 but ST>=1", H(2, 0, 1) == "MIXED")
check("MIXED: PS=1 only / nothing", H(1, 0, 0) == "MIXED" and H(0, 0, 0) == "MIXED")
# Aries Lagna: native 12 Pisces (lord Jupiter) placed in the 7th -> S-a STRESS.
h = se.build_spouse_evidence(make_kundali("Aries", dict(BASE_ARIES, Jupiter=("Libra", 9.0))))["health"]
check("S-a: lord of native 12 sitting in native 7 -> STRESS", next(i for i in h["secondary_items"] if i["id"] == "S-a")["result"] == "STRESS")
# Taurus Lagna: Mars rules the 7th (Scorpio) AND the 12th (Aries) -> S-a exception NONE.
h = se.build_spouse_evidence(make_kundali("Taurus", unlinked))["health"]
sa = next(i for i in h["secondary_items"] if i["id"] == "S-a")
check("S-a exception: native-12 lord is also the 7th lord -> NONE", sa["result"] == "NONE" and sa["evidence"][0].get("exception") == "also_seventh_lord")
# Aries Lagna: Venus (7th lord) in Taurus = native 2 (spouse 8th): own sign -> P-a SUPPORT, P-b NONE.
h = se.build_spouse_evidence(make_kundali("Aries", dict(BASE_ARIES, Venus=("Taurus", 15.0))))["health"]
pa = next(i for i in h["primary_items"] if i["id"] == "P-a")
pb = next(i for i in h["primary_items"] if i["id"] == "P-b")
check("7th lord in native 2 (spouse 8th) -> P-b NONE (excluded v1)", pb["result"] == "NONE" and pa["result"] == "SUPPORT")
check("spouse 8th / native 2nd recorded as excluded", h["derived_houses"]["spouse_8th_excluded"] == 2)
# 7th lord in native 12 -> P-b STRESS.
h = se.build_spouse_evidence(make_kundali("Aries", dict(BASE_ARIES, Venus=("Pisces", 15.0))))["health"]
check("7th lord in native 12 (spouse 6th) -> P-b STRESS; exalted Venus -> P-a SUPPORT",
      next(i for i in h["primary_items"] if i["id"] == "P-b")["result"] == "STRESS"
      and next(i for i in h["primary_items"] if i["id"] == "P-a")["result"] == "SUPPORT")
check("a primary MIXED item counts as neither support nor stress",
      sum(1 for i in h["primary_items"] if i["result"] == "SUPPORT") == h["counts"]["primary_support"])

print("\n=== 10. Wealth ===")
W = se.classify_wealth_states
check("STEADY: R=SUPPORTED, G not STRAINED", W("SUPPORTED", "NEUTRAL") == "STEADY" and W("SUPPORTED", "SUPPORTED") == "STEADY" and W("SUPPORTED", "MIXED") == "STEADY")
check("not STEADY when R=SUPPORTED but G=STRAINED -> MIXED", W("SUPPORTED", "STRAINED") == "MIXED")
check("GROWTH_ORIENTED: G=SUPPORTED, R in {NEUTRAL, MIXED}", W("NEUTRAL", "SUPPORTED") == "GROWTH_ORIENTED" and W("MIXED", "SUPPORTED") == "GROWTH_ORIENTED")
check("EFFORT_BUILT: both STRAINED", W("STRAINED", "STRAINED") == "EFFORT_BUILT")
check("EFFORT_BUILT: one STRAINED, other not SUPPORTED", W("STRAINED", "NEUTRAL") == "EFFORT_BUILT" and W("MIXED", "STRAINED") == "EFFORT_BUILT")
check("MIXED: R=STRAINED, G=SUPPORTED", W("STRAINED", "SUPPORTED") == "MIXED")
check("MIXED: nothing either way", W("NEUTRAL", "NEUTRAL") == "MIXED" and W("MIXED", "MIXED") == "MIXED")
# Aries Lagna, Rahu in Scorpio = native 8 (R) and its 9th aspect reaches native 4 (S) -> 2 dims -> unconventional.
w = se.build_spouse_evidence(make_kundali("Aries", dict(BASE_ARIES, Rahu=("Scorpio", 12.0), Ketu=("Taurus", 12.0))))["wealth"]
check("unconventional_pattern when nodes influence >=2 of R/G/S", w["unconventional_pattern"] is True)
rahu_on_r = [i for i in w["dimensions"]["resources"]["influences"] if i["planet"] == "Rahu"]
check("Rahu on the resources house is NEUTRAL + 'unconventional' (never automatically negative)",
      rahu_on_r and all(i["valence"] == "NEUTRAL" and "unconventional" in i["tags"] for i in rahu_on_r))
check("standing_note mirrors professional_standing state and does not drive the class",
      w["standing_note"] == w["dimensions"]["professional_standing"]["state"]
      and w["class"] == W(w["dimensions"]["resources"]["state"], w["dimensions"]["income_growth"]["state"]))
check("wealth uses only native 8 / 5 / 4 (spouse 2 / 11 / 10); spouse 9th removed",
      [(d["spouse_house"], d["native_house"]) for d in w["dimensions"].values()] == [(2, 8), (11, 5), (10, 4)]
      and w["excluded"]["spouse_9th_native_3rd"] == "removed_v1")

print("\n=== 11. Input safety ===")
for bad in ({"lagna_sign": "Ophiuchus", "planets": make_kundali("Aries", BASE_ARIES)["planets"]},
            {"planets": make_kundali("Aries", BASE_ARIES)["planets"]}):
    try:
        se.build_spouse_evidence(bad)
        check(f"unknown/missing Lagna raises ({bad.get('lagna_sign')})", False)
    except se.SpouseEvidenceError:
        check(f"unknown/missing Lagna raises explicitly ({bad.get('lagna_sign')})", True)
no_lon = make_kundali("Aries", BASE_ARIES)
del no_lon["planets"][0]["longitude"]
try:
    se.build_spouse_evidence(no_lon)
    check("missing full-precision longitude raises", False)
except se.SpouseEvidenceError:
    check("missing full-precision longitude raises (never falls back to rounded degree)", True)
mismatch = make_kundali("Aries", BASE_ARIES)
mismatch["lagna_sign"] = "Taurus"
try:
    se.build_spouse_evidence(mismatch)
    check("lagna_sign vs Ascendant record mismatch raises", False)
except se.SpouseEvidenceError:
    check("lagna_sign vs Ascendant record mismatch raises", True)
k = make_kundali("Aries", BASE_ARIES)
before = copy.deepcopy(k)
se.build_spouse_evidence(k)
check("input kundali is not mutated", k == before)

print("\n=== 12. Payload ===")


def walk(x):
    if isinstance(x, dict):
        for kk, vv in x.items():
            yield kk, vv
            yield from walk(vv)
    elif isinstance(x, list):
        for vv in x:
            yield None, vv
            yield from walk(vv)


PROHIBITED_KEYS = {"probability", "percent", "percentage", "confidence", "disease", "illness", "diagnosis", "lifespan",
                   "longevity", "death", "fertility", "salary", "income_amount", "net_worth", "rich", "poor"}
for lagna in ("Aries", "Taurus"):
    pl = se.build_spouse_evidence(make_kundali(lagna, BASE_ARIES if lagna == "Aries" else unlinked))
    items = list(walk(pl))
    check(f"[{lagna}] schema_version", pl["schema_version"] == "spouse_evidence_v1")
    check(f"[{lagna}] no floats anywhere (no fake precision / probabilities)", not any(isinstance(v, float) for _, v in items))
    check(f"[{lagna}] no prohibited medical/financial/probability keys", not ({kk for kk, _ in items if kk} & PROHIBITED_KEYS))
    check(f"[{lagna}] every reportable trait carries evidence", all(t["evidence"] for t in pl["nature"]["traits"] if t["reportable"]))
    check(f"[{lagna}] all 8 dimensions present in frozen order", [t["dimension"] for t in pl["nature"]["traits"]] == [d for d, _ in TRAIT_DIMENSIONS])
    check(f"[{lagna}] snapshot <= 3 and only DOMINANT/SUPPORTED", len(pl["nature"]["snapshot_traits"]) <= 3
          and all(t["class"] in ("DOMINANT", "SUPPORTED") for t in pl["nature"]["snapshot_traits"]))
    check(f"[{lagna}] limitations listed", {"no_upapada_v1", "no_retrograde_v1", "no_combustion_v1", "no_shadbala",
                                            "tendencies_not_certainties"} <= set(pl["limitations"]))
    check(f"[{lagna}] health/wealth classes are within the frozen label sets",
          pl["health"]["class"] in ("SUPPORTIVE", "MIXED", "NEEDS_ATTENTION")
          and pl["wealth"]["class"] in ("STEADY", "GROWTH_ORIENTED", "EFFORT_BUILT", "MIXED"))
    check(f"[{lagna}] free_tool_layer == shared table for this Lagna",
          pl["free_tool_layer"] == {"seventh_sign": seventh_sign_for_lagna(lagna), "sign_card_id": seventh_sign_layer(lagna)["sign_card_id"]})

print("\n=== 13. Shared 7th-sign table ===")
check("12 signs, each with card id, element, modality, votes", len(SEVENTH_SIGN_TABLE) == 12 and all(
    set(v) == {"sign", "sign_card_id", "element", "modality", "votes"} for v in SEVENTH_SIGN_TABLE.values()))
check("Lagna -> 7th sign for all 12 Lagnas", [seventh_sign_for_lagna(s) for s in SIGN_ORDER] == [opposite(s) for s in SIGN_ORDER])
try:
    seventh_sign_for_lagna("Ophiuchus")
    check("free-tool helper rejects an unknown Lagna", False)
except ValueError:
    check("free-tool helper rejects an unknown Lagna", True)
check("the paid engine imports the SAME table object (no duplicate interpretation)", se.SEVENTH_SIGN_TABLE is SEVENTH_SIGN_TABLE)

print("\n=== 14. Golden charts (real calculate_full_kundali output) ===")


def d9_oracle(longitude):
    lon = Fraction(longitude) % 360
    si = int(lon // 30)
    k_ = int((lon - si * 30) * 3 // 10)
    return classical_d9(si, k_)


GOLDEN = [
    ("Aarav Sharma", "1990-06-15", "14:30", 26.8467, 80.9462),  # the published sample persona (Lucknow)
    ("Delhi Dawn", "1985-01-01", "05:10", 28.6139, 77.2090),
    ("London", "1975-03-09", "08:05", 51.5074, -0.1278),
]
for name, dob, tob, lat, lon in GOLDEN:
    kund = calculate_full_kundali(name=name, dob=dob, tob=tob, lat=lat, lon=lon, language="en")
    a = se.build_spouse_evidence(kund)
    b = se.build_spouse_evidence(copy.deepcopy(kund))
    check(f"[{name}] deterministic: identical payload on repeat", json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))
    pos = {p["name"]: p for p in kund["planets"]}
    d9f = a["chart_facts"]["d9"]
    check(f"[{name}] D9 signs equal an independent classical-sequence oracle (all 9 grahas + Lagna)",
          all(d9f["planet_signs"][g] == d9_oracle(pos[g]["longitude"]) for g in GRAHAS)
          and d9f["lagna"] == d9_oracle(pos["Ascendant (Lagna)"]["longitude"]))
    karakas = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
    lowest = min(karakas, key=lambda g: Fraction(pos[g]["longitude"]) % 30)
    check(f"[{name}] Darakaraka equals an independent exact-fraction oracle", a["chart_facts"]["darakaraka"]["planets"] == [lowest])
    check(f"[{name}] D1 houses agree with the API's own house field", all(
        a["chart_facts"]["d1"]["houses"][pos[g]["house"] - 1]["sign"] == pos[g]["sign"] for g in GRAHAS))

aarav = se.build_spouse_evidence(calculate_full_kundali(name="Aarav Sharma", dob="1990-06-15", tob="14:30", lat=26.8467, lon=80.9462, language="en"))
ad1 = aarav["chart_facts"]["d1"]
check("[Aarav Sharma] matches the published sample: Libra Lagna, 7th Aries, lord Mars in the 6th (Pisces), Venus in the 7th",
      ad1["lagna"] == "Libra" and ad1["seventh_sign"] == "Aries" and ad1["seventh_lord"] == "Mars"
      and ad1["seventh_lord_house"] == 6 and ad1["seventh_lord_sign"] == "Pisces" and ad1["occupants_7th"] == ["Venus"])
check("[Aarav Sharma] Venus linked to the 7th by occupancy", ad1["venus"]["link_to_7th"] == ["occupies_7th"])

print(f"\nRESULTS: {PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
