"""
test_marriage_path_seventh_lord.py
-------------------------------------------------
Marriage Path correctness gate (free tool, services/marriage_path.py).

No DB/Flask dependency -- calls build_marriage_path() directly with minimal
kundali dicts (lagna_sign + planets with house/sign), the same shape the
life-tools endpoint passes in.

Covers:
  A. The "Rahu with the 7th lord" finding names the 7th lord the rule actually
     evaluated (the rule itself is unchanged: Rahu in the same house as the
     7th lord).
       A1. Libra lagna -> 7th = Aries -> lord Mars: still says Mars.
       A2. Aries lagna -> 7th = Libra -> lord Venus: says Venus, never Mars.
       A3. Capricorn lagna -> 7th = Cancer -> lord Moon, Hindi run: says Moon.
       A4. Rahu NOT with the 7th lord: no conjunction finding at all.
  B. The result CTA no longer carries a hard-coded price (EN + HI).
"""
import re
import sys

from services.marriage_path import build_marriage_path

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


SIGN_ORDER = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
              "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]


def chart(lagna_sign, placements):
    """placements: {planet: house}; each planet's sign is derived from the house (whole-sign)."""
    lagna_index = SIGN_ORDER.index(lagna_sign)
    planets = [{"name": name, "house": house, "sign": SIGN_ORDER[(lagna_index + house - 1) % 12]}
               for name, house in placements.items()]
    return {"lagna_sign": lagna_sign, "lagna_house": 1, "planets": planets}


def conjunction_lines(result):
    return [p for p in result["negative_points"] if p.startswith("Rahu is conjoined with")]


print("=== A. Rahu + 7th lord finding names the actual 7th lord ===")

# A1: Libra lagna -> 7th house Aries -> 7th lord Mars. Rahu and Mars together in the 3rd house.
r1 = build_marriage_path(chart("Libra", {"Mars": 3, "Rahu": 3, "Ketu": 9, "Venus": 1, "Jupiter": 4}))
check("A1 Mars really is the 7th lord -> 'Rahu is conjoined with Mars (7th house lord).'",
      conjunction_lines(r1) == ["Rahu is conjoined with Mars (7th house lord)."])

# A2: Aries lagna -> 7th house Libra -> 7th lord Venus. Rahu and Venus together in the 5th house;
# Mars is elsewhere and is NOT the 7th lord.
r2 = build_marriage_path(chart("Aries", {"Venus": 5, "Rahu": 5, "Ketu": 11, "Mars": 2, "Jupiter": 9}))
check("A2 non-Mars 7th lord (Venus) -> 'Rahu is conjoined with Venus (7th house lord).'",
      conjunction_lines(r2) == ["Rahu is conjoined with Venus (7th house lord)."])
check("A2 output never claims Mars is the 7th lord", not any("Mars" in p for p in conjunction_lines(r2)))

# A3: Capricorn lagna -> 7th house Cancer -> 7th lord Moon; Hindi run.
r3 = build_marriage_path(chart("Capricorn", {"Moon": 10, "Rahu": 10, "Ketu": 4, "Mars": 6}), language="hi")
check("A3 Hindi run, 7th lord Moon -> finding names Moon, not Mars",
      conjunction_lines(r3) == ["Rahu is conjoined with Moon (7th house lord)."])

# A4: Aries lagna -> 7th lord Venus in the 5th, Rahu in the 8th: rule not met -> no finding.
r4 = build_marriage_path(chart("Aries", {"Venus": 5, "Rahu": 8, "Ketu": 2, "Mars": 1}))
check("A4 Rahu not with the 7th lord -> no conjunction finding", conjunction_lines(r4) == [])

print("\n=== B. Result CTA carries no hard-coded price ===")
check("B1 EN CTA has no rupee amount", "₹" not in r1["cta"] and "98" not in r1["cta"])
check("B2 HI CTA has no rupee amount", "₹" not in r3["cta"] and "98" not in r3["cta"])
check("B3 CTA keeps its snapshot framing (EN + HI)",
      "general marriage snapshot" in r1["cta"] and "सामान्य वैवाहिक झलक" in r3["cta"])
check("B4 CTA points to the Marriage Report as a separate reading (EN + HI)",
      "The Marriage Report is a separate, detailed reading" in r1["cta"] and "विवाह रिपोर्ट" in r3["cta"])
check("B5 CTA claims no Transit / Navamsa (D9) / exact date for the report",
      not re.search(r"\b(Transit|Navamsa|D9|date|age)\b", r1["cta"]) and
      not any(w in r3["cta"] for w in ("गोचर", "नवांश", "तारीख", "आयु")))

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
