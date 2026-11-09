"""
test_love_life.py

Love Life correctness gate (free tool, services/love_life.py). No DB/Flask dependency -- calls build_love_life()
directly with minimal whole-sign charts shaped like the kundali the /api/life-tool endpoint passes in.
Run: python test_love_life.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from services.love_life import build_love_life  # noqa: E402

passed = 0
failed = 0


def check(label, ok):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]


def chart(lagna, placements):
    i = SIGNS.index(lagna)
    return {"lagna_sign": lagna, "planets": [{"name": n, "house": h, "sign": SIGNS[(i + h - 1) % 12]} for n, h in placements.items()]}


def en(points):
    return [p["en"] for p in points]


print("=== A. No invented points ===")
none = build_love_life(chart("Aries", {"Venus": 2, "Moon": 4, "Saturn": 10, "Ketu": 3, "Sun": 1, "Mars": 6}))
check("A1 no-rule chart: both lists empty (no fallback text)", none["positive_points"] == [] and none["negative_points"] == [])
check("A2 no universal remedy verdict", none["verdict"] == "")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "services", "love_life.py"), encoding="utf-8").read()
check("A3 fallback / remedy sentences are gone from the code",
      not re.search(r"need some remedy|Instead of everything good|Remedies and maturity|थोड़े उपायों|उपाय और समझदारी", src))

print("\n=== B. Rules, wording and dignity ===")
r = build_love_life(chart("Aries", {"Venus": 5, "Moon": 7, "Saturn": 5, "Mars": 7}))
check("B1 ordinals: '5th house' / '7th house', never '5 house'",
      all(re.search(r"the (5th|7th) house", t) for t in en(r["positive_points"] + r["negative_points"])) and
      not any(re.search(r"\b[57] house\b", t) for t in en(r["positive_points"] + r["negative_points"])))
check("B2 Venus 5th and Moon 7th supportive; Saturn 5th and Mars 7th to watch",
      len(r["positive_points"]) == 2 and len(r["negative_points"]) == 2)
deb_v = build_love_life(chart("Taurus", {"Venus": 5}))  # Taurus + 4 = Virgo: Venus debilitated
check("B3 debilitated Venus in the 5th is not supportive; listed as needing care",
      deb_v["positive_points"] == [] and len(deb_v["negative_points"]) == 1 and "debilitated" in deb_v["negative_points"][0]["en"])
deb_m = build_love_life(chart("Taurus", {"Moon": 7}))  # Taurus + 6 = Scorpio: Moon debilitated
check("B4 debilitated Moon in the 7th is not supportive; listed as needing care",
      deb_m["positive_points"] == [] and "debilitated" in deb_m["negative_points"][0]["en"] and "नीच" in deb_m["negative_points"][0]["hi"])
ex_v = build_love_life(chart("Scorpio", {"Venus": 5}))  # Scorpio + 4 = Pisces
check("B5 non-debilitated Venus in the 5th stays supportive", len(ex_v["positive_points"]) == 1)
check("B6 cautious wording: no 'creates emotional blocks' / 'may cause' / 'supports love and emotional bonding.' certainty",
      not re.search(r"creates emotional blocks|may cause ego|उत्पन्न करता है", src))
nr = build_love_life(chart("Aries", {"Rahu": 7, "Jupiter": 5}))
check("B7 no new rules: Rahu/Jupiter in the 5th/7th add no points", nr["positive_points"] == [] and nr["negative_points"] == [])

print("\n=== C. Language, shape and facts ===")
hi = build_love_life(chart("Aries", {"Venus": 5, "Saturn": 7}), "hi")
DEV = re.compile(r"[ऀ-ॿ]")
check("C1 every point is a {en, hi} object with Hindi text", all(set(p) == {"en", "hi"} and DEV.search(p["hi"]) for p in hi["positive_points"] + hi["negative_points"]))
check("C2 heading and cta follow the language; no 'compatibility' claim",
      DEV.search(hi["heading"]) and DEV.search(hi["cta"]) and "compatib" not in build_love_life(chart("Aries", {}))["heading"].lower())
legacy = {"heading": str, "positive_points": list, "negative_points": list, "cta": str, "verdict": str}
check("C3 every existing field kept with its type", all(isinstance(hi[k], t) for k, t in legacy.items()))
f = build_love_life(chart("Leo", {"Venus": 5, "Moon": 5, "Saturn": 7, "Rahu": 1}))
check("C4 facts: 5th Sagittarius, 7th Aquarius, occupants listed (Leo lagna)",
      f["fifth_sign"] == "Sagittarius" and f["seventh_sign"] == "Aquarius" and f["fifth_house_planets"] == ["Venus", "Moon"] and f["seventh_house_planets"] == ["Saturn"])
check("C5 empty houses give empty occupant lists, signs still present",
      none["fifth_sign"] == "Leo" and none["seventh_sign"] == "Libra" and none["fifth_house_planets"] == [] and none["seventh_house_planets"] == [])

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)
if failed:
    sys.exit(1)
