"""
Q4.4A -- relationship_future_report: the dedicated Hindi prompt (modules/love/love_prompt_builder.py) follows the
approved modern conversational Hindi/Hinglish policy, while EVERYTHING ELSE about the product is unchanged.

Q4.2B rolled the policy out to the 24 standard_v1 prompts but never reached this Python-built prompt, which still
said "खरीदा गया प्रश्न" / "गतिशीलता". Only the LANGUAGE STYLE of the Hindi instructions may change:
  * the whole English prompt is pinned byte-for-byte (hash),
  * the machine-readable wire contract (===META===/===REPORT=== + hero JSON), the disclaimer and the
    deterministic-evidence JSON are pinned byte-for-byte (hash),
  * the authority / privacy / safety rules are asserted token by token,
  * the 10-section structure is asserted in order.
Q4.4B update: headings no longer carry their AI instruction ("Title -- instruction" was the customer-facing defect), the
internal mode name is no longer sent to the model, and the model is given both names -- see test_love_prompt_customer_contract_q44b.py.
No AI call.
"""
import hashlib
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("DATABASE_URL", "postgresql://sample:unused@localhost:5432/jyotishasha_local")
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from full_kundali_api import calculate_full_kundali  # noqa: E402
from modules.love.love_data_collector import collect_love_report_data  # noqa: E402
from modules.love.love_prompt_builder import build_love_premium_prompt, LovePromptBuilderError  # noqa: E402
from modules.payments.report_q3_batch1 import get_mandatory_disclaimer  # noqa: E402
from modules.payments.report_structured_output import parse_structured_response, validate_required_hero_fields  # noqa: E402
from modules.payments.report_product_intelligence import get_product_intelligence  # noqa: E402

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def fixed_payload(lang):
    return dict(
        language=lang, compiled_report={}, astro_facts={},
        compatibility={"case": "A_FULL_DUAL", "ashtakoot": {"total_score": 32.5, "max_score": 36.0, "kootas": {"varna": {"score": 1, "max": 1}}}},
        user_house_lord_facts=[{"house": 5, "sign": "Aquarius"}], user_dasha_context={"window_summary": "x"},
    )


WIRE_MARK = "\nReturn exactly this machine-readable format."
# pins taken from the committed (pre-Q4.4A) builder output for fixed_payload()
PIN_WIRE = "8712f6314bb26977"
PIN_DISCLAIMER_HI = "84ac354d64727478"

en = build_love_premium_prompt(fixed_payload("en"))
hi = build_love_premium_prompt(fixed_payload("hi"))
hi_instr = hi[:hi.index(WIRE_MARK)]

print("\n=== 1: the wire contract and the disclaimer are byte-identical ===")
check("1: the machine-readable wire block (markers + hero JSON) is unchanged",
      h(hi[hi.index(WIRE_MARK):hi.index("\nDisclaimer:\n")]) == PIN_WIRE)
check("1: the mandatory Hindi disclaimer block is unchanged", h(hi[hi.index("\nDisclaimer:\n"):hi.index("\nDeterministic evidence:\n")]) == PIN_DISCLAIMER_HI)
check("1: the disclaimer is still the exact production disclaimer", get_mandatory_disclaimer("relationship_future_non_certainty_mandatory", "hi") in hi)
check("1: the Hindi and English wire blocks are identical", hi[hi.index(WIRE_MARK):hi.index("\nDisclaimer:\n")] == en[en.index(WIRE_MARK):en.index("\nDisclaimer:\n")])

print("\n=== 2: structured-output / hero contract is unchanged ===")
check("2: ===META=== appears exactly once", hi.count("===META===") == 1)
check("2: ===REPORT=== appears exactly once, after ===META===", hi.count("===REPORT===") == 1 and hi.index("===META===") < hi.index("===REPORT==="))
check("2: the hero JSON shape is exactly the production one",
      '{"hero":{"label":"Relationship Outlook","value":"<qualitative synthesis>","interpretation":"<evidence-grounded sentence>","evidence":["<actual supplied fact>"],"action_items":["<practical guidance>"]}}' in hi)
check("2: 'Only the listed hero fields are allowed' + no percentage rule preserved", "Only the listed hero fields are allowed" in hi and "Do not emit compatibility percentages" in hi)
check("2: the hero label stays the English 'Relationship Outlook' (never translated)", "Relationship Outlook" in hi_instr)
sample = '===META===\n{"hero":{"label":"Relationship Outlook","value":"Warm and steady","interpretation":"x","evidence":["e"],"action_items":["a"]}}\n===REPORT===\n1. A\nBody'
meta, body = parse_structured_response(sample)
check("2: the real parser + validator still accept the contract", validate_required_hero_fields({"answer_hero": meta["hero"]}, get_product_intelligence("relationship_future_report").required_hero_fields)["label"] == "Relationship Outlook")

print("\n=== 3: deterministic-evidence injection ('placeholders') is unchanged ===")
evidence = json.loads(hi.split("Deterministic evidence:\n")[1])
check("3: evidence keys are exactly partner_birth_data / ashtakoot / user_house_lord_facts / user_dasha_context (no internal mode name)",
      set(evidence) == {"partner_birth_data", "ashtakoot", "user_house_lord_facts", "user_dasha_context"})
check("3: Ashtakoot evidence reaches the model verbatim", evidence["ashtakoot"]["total_score"] == 32.5 and evidence["partner_birth_data"]["completeness"] == "full")
for key in ("compiled_report", "compatibility", "astro_facts"):
    try:
        build_love_premium_prompt({k: v for k, v in fixed_payload("hi").items() if k != key})
        ok = False
    except LovePromptBuilderError:
        ok = True
    check(f"3: a payload missing {key} still raises LovePromptBuilderError", ok)
for forbidden in ("love_vs_arranged", "stability_score", "99%"):
    check(f"3: forbidden legacy field {forbidden!r} still excluded", forbidden not in hi)

print("\n=== 4: the 10-section structure is preserved, in order ===")
numbered = re.findall(r"^(\d+)\.\s+(.+)$", hi, re.M)
check("4: exactly 10 numbered sections, numbered 1..10 in order", [n for n, _ in numbered] == [str(i) for i in range(1, 11)])
HEADINGS = {
    1: "आपके Relationship का Outlook",
    2: "Compatibility का Snapshot",
    3: "Koota-wise Compatibility Evidence",
    4: "Emotional और Relationship Dynamics",
    5: "5th और 7th House का Context",
    6: "Connection की Strengths",
    7: "किन बातों पर ध्यान दें",
    8: "Current Dasha का Context",
    9: "Relationship के लिए Practical Guidance",
    10: "Summary",
}
for n, text in HEADINGS.items():
    check(f"4: section {n} heading is exactly the clean modern title '{text}'", dict(numbered)[str(n)] == text)

print("\n=== 5: deterministic authority rules are preserved ===")
AUTHORITY = [
    "partner_birth_data", "/36", "Ashtakoot", "Dasha", "exactly as given", "Aspects",
    "hero value नहीं", "percentage में न बदलें", "कोई Koota या fact अपनी तरफ़ से न बनाएँ", "partner का Lagna",
    "primary person के Houses हैं, partner के नहीं", "खाली 5th या 7th House",
]
for tok in AUTHORITY:
    check(f"5: authority rule preserved: {tok!r}", tok in hi_instr)
check("5: the deterministic evidence order (Ashtakoot -> user 5th/7th -> Dasha) is preserved",
      hi_instr.index("Ashtakoot का result") < hi_instr.index("5th/7th House के facts") < hi_instr.index("Dasha का context"))
check("5: hero value must still be qualitative -- no percentage, number or fixed prediction", "percentage, अंक (number) या पक्की भविष्यवाणी नहीं" in hi_instr)

print("\n=== 6: privacy / safety / no-guarantee rules are preserved ===")
SAFETY = ["निजी विचार", "भावनाएँ", "इरादे", "निष्ठा", "बेवफाई", "विश्वासघात", "संबंध-विच्छेद", "अवसाद", "चिंता", "आघात",
          "diagnosis न करें", "निश्चित तारीख", "साल या उम्र", "गारंटी न दें", "gemstone", "रत्न", "sales message न जोड़ें",
          "Relationship खत्म करने की सलाह न दें", "partner के छोड़ने"]
for tok in SAFETY:
    check(f"6: safety/privacy rule preserved: {tok!r}", tok in hi_instr)
check("6: 'no exact timing' rule still forbids marriage/reunion/separation dates", "Marriage" in hi_instr and "दोबारा मिलने" in hi_instr and "अलग होने" in hi_instr)

print("\n=== 7: the modern conversational Hindi policy is present (same markers as the 24 standard prompts) ===")
POLICY = ["Modern Conversational Hindi", "क्लिष्ट, संस्कृतनिष्ठ, academic", "बिल्कुल वैसे ही (exactly as given) लिखें",
          "Sun (Surya), Moon (Chandra), Mars (Mangal), Mercury (Budh), Jupiter (Guru), Venus (Shukra), Saturn (Shani), Rahu, Ketu",
          "छोटे और सीधे वाक्य", "जाने-पहचाने modern शब्द English में ही रखें"]
for tok in POLICY:
    check(f"7: policy marker present: {tok!r}", tok in hi_instr)
for term in ("Relationship", "Compatibility", "Marriage", "Lagna", "Rashi", "Moon", "Nakshatra", "Ashtakoot", "Manglik", "House Lord", "Dasha", "Mahadasha", "Antardasha", "Transit", "Yog"):
    check(f"7: preferred term is used/allowed: {term}", term in hi_instr)

print("\n=== 8: the formal / Sanskritized wording targeted by this task is gone ===")
OBSOLETE = ["खरीदा गया प्रश्न", "गतिशीलता", "कूटवार", "अनुकूलता का सार", "पाँचवें", "सातवें", "पाँचवाँ", "सातवाँ", "व्यावहारिक", "अस्वीकरण", "रेंडरर",
            "गायब कूट", "पुनर्मिलन", "उपयोगकर्ता", "स्वाभाविक हिंदी", "द्वितीयक", "व्याख्यात्मक"]
for w in OBSOLETE:
    check(f"8: obsolete formal wording removed: {w!r}", w not in hi_instr)
check("8: natural conversational opener is used ('आपका सवाल')", "आपका सवाल" in hi_instr)

print("\n=== 9: the real live-shape payload produces a coherent Hindi prompt end to end ===")
order = dict(name="Aarav Sharma", dob="1990-06-15", tob="14:30", pob="Lucknow, Uttar Pradesh, India", latitude="26.8467", longitude="80.9462", language="hi",
             partner=dict(name="Ananya Verma", dob="1992-03-22", tob="10:45", pob="New Delhi, India", latitude=28.6139, longitude=77.2090))
kundali = calculate_full_kundali(name=order["name"], dob=order["dob"], tob=order["tob"], lat=26.8467, lon=80.9462, language="hi")
live = collect_love_report_data(order=order, user_kundali=kundali, language="hi", boy_is_user=True)
live_prompt = build_love_premium_prompt(live)
live_evidence = json.loads(live_prompt.split("Deterministic evidence:\n")[1])
check("9: live payload -> full partner birth data in the Hindi prompt evidence", live_evidence["partner_birth_data"]["completeness"] == "full")
check("9: live payload -> 32.5/36 in the Hindi prompt evidence", live_evidence["ashtakoot"]["total_score"] == 32.5)
check("9: live prompt still has exactly 10 numbered sections", len(re.findall(r"^\d+\.", live_prompt, re.M)) == 10)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)
if failed:
    sys.exit(1)
