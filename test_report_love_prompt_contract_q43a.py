"""
Q4.3A -- the six standard love prompts must follow the standard_v1 output contract.

Blocker (found in Q4.3): love_disappointment_report / love_marriage_report /
love_relationship_report (EN + HI) told gpt-5.6-luna "OUTPUT FORMAT: valid JSON".
Luna answered with ONE standalone JSON object, the parser (correctly) found no
===META===/===REPORT=== markers, and the paid order failed with ReportMetadataError.
The parser is not the defect; the prompts must conform to the contract that every
working standard prompt already uses ("STRICT, MACHINE-PARSED", two literal markers).

This file proves, without any AI call, that for all six prompts:
  * the strict two-marker contract wording is present and the "valid JSON" wording is gone,
  * each marker appears exactly once (the first ===META=== is the real block),
  * the META block is byte-identical to before (keys, label, value rules),
  * the rules/privacy/safety prefix, placeholders, section list and closing rule are
    byte-identical to before (pinned hashes) -- only the output-contract wording changed,
  * the real parser + hero validator accept a contract-following reply and (as a control)
    reject a JSON-only reply, i.e. the failure Q4.3 saw is exactly what the prompt used to invite.
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

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from modules.payments.report_product_intelligence import REGISTRY  # noqa: E402
from modules.payments.report_structured_output import (  # noqa: E402
    parse_structured_response, validate_required_hero_fields, ReportMetadataError,
)

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


LOVE = ("love_disappointment_report", "love_marriage_report", "love_relationship_report")
BAR = "=" * 50
HEADER = {"en": BAR + "\nOUTPUT FORMAT -- STRICT, MACHINE-PARSED\n" + BAR,
          "hi": BAR + "\nआउटपुट फॉर्मेट -- सख्त, मशीन-पठनीय\n" + BAR}
TWO_MARKERS = {"en": "with these two literal markers on their own lines",
               "hi": "इन दो मार्करों के साथ अपनी-अपनी अलग पंक्ति में"}
NO_STANDALONE_JSON = {"en": "Do NOT return a single standalone JSON object",
                      "hi": "एक अकेले JSON object की तरह न दें"}
META_RULES = {"en": "Rules for the META block:", "hi": "META block के नियम:"}
SECTION_HEADER = {"en": "NARRATIVE REPORT -- STRICT SECTION STRUCTURE", "hi": "Report -- सख्त Section Structure"}

# ---- pinned, pre-fix facts (taken from the committed prompts before Q4.3A) -----------------
PLACEHOLDERS = {
    "love_disappointment_report": {"birth_chart_summary", "house_lord_summary", "dasha_window_summary", "targeted_aspect_summary"},
    "love_marriage_report": {"birth_chart_summary", "house_lord_summary", "dasha_window_summary", "targeted_aspect_summary", "gemstone_summary"},
    "love_relationship_report": {"birth_chart_summary", "house_lord_summary", "dasha_window_summary", "gemstone_summary"},
}
LABEL = {"love_disappointment_report": "Emotional Relationship Pattern", "love_marriage_report": "Love-Marriage Tendency",
         "love_relationship_report": "Relationship Pattern"}
META_KEYS = {"love_disappointment_report": {"answer_hero", "action_items"},
             "love_marriage_report": {"answer_hero", "action_items", "gemstone_reason"},
             "love_relationship_report": {"answer_hero", "action_items", "gemstone_reason"}}
N_SECTIONS = {"love_disappointment_report": 9, "love_marriage_report": 8, "love_relationship_report": 9}
PINS = {
    "love_disappointment_report_en": dict(prefix="98c044b5b3393a69", meta="10a29fb095ca80e9", sections="4b0dd5045768115e"),
    "love_disappointment_report_hi": dict(prefix="a089813be0d0e12a", meta="10a29fb095ca80e9", sections="7515cc610c7eaf2d"),
    "love_marriage_report_en": dict(prefix="3de2d386fadbeabb", meta="e12c62496e57cc4a", sections="0313f58fc2bf01c2"),
    "love_marriage_report_hi": dict(prefix="bfd0941491ae26a9", meta="e12c62496e57cc4a", sections="c0965d3acae55fd8"),
    "love_relationship_report_en": dict(prefix="469e67eef41d2fc8", meta="582c5e2f55fb8cd9", sections="ba2e8ac7525fa1e1"),
    "love_relationship_report_hi": dict(prefix="95be3933a1535536", meta="582c5e2f55fb8cd9", sections="5a3bf1d37ee0e541"),
}
SAFETY = {
    "en": ["private thoughts", "feelings", "intentions", "fidelity", "cheating", "betrayal", "breakup", "depression", "anxiety",
           "trauma", "ending a relationship", "Never say you will meet someone", "No exact marriage date/year/age",
           "copy each supplied date exactly as given", "Explicitly acknowledge missing evidence", "Do not add sales copy", "Do not invent facts"],
    "hi": ["निजी विचार", "भावनाएँ", "इरादे", "निष्ठा", "बेवफाई", "विश्वासघात", "संबंध-विच्छेद", "अवसाद", "चिंता", "आघात", "संबंध खत्म",
           "बिल्कुल वैसे ही (exactly as given)", "प्रमाण उपलब्ध न हो", "sales message न जोड़ें", "कोई तथ्य न गढ़ें"],
}
HI_POLICY = ("Modern Conversational Hindi", "क्लिष्ट, संस्कृतनिष्ठ, academic", "बिल्कुल वैसे ही (exactly as given) लिखें",
             "Sun (Surya), Moon (Chandra), Mars (Mangal), Mercury (Budh), Jupiter (Guru), Venus (Shukra), Saturn (Shani), Rahu, Ketu")
FILLER = {p: "X" for s in PLACEHOLDERS.values() for p in s}

for slug in LOVE:
    for lang in ("en", "hi"):
        tag = f"{slug}_{lang}"
        print(f"\n=== {tag} ===")
        src = open(os.path.join(ROOT, "prompts", f"{tag}.txt"), encoding="utf-8").read()

        # --- contract wording ---------------------------------------------------------------
        check(f"{tag}: strict machine-parsed OUTPUT FORMAT header present", HEADER[lang] in src)
        check(f"{tag}: tells the model to use the two literal markers on their own lines", TWO_MARKERS[lang] in src)
        check(f"{tag}: explicitly forbids a single standalone JSON object", NO_STANDALONE_JSON[lang] in src)
        check(f"{tag}: the old 'OUTPUT FORMAT: valid JSON' instruction is gone", "OUTPUT FORMAT: valid JSON" not in src and "valid JSON, no comments or Markdown fences" not in src)
        check(f"{tag}: has an explicit META-block rules list", META_RULES[lang] in src)
        check(f"{tag}: has an explicit narrative section-structure header", SECTION_HEADER[lang] in src)
        check(f"{tag}: ===META=== appears exactly once, before ===REPORT=== (also exactly once)",
              src.count("===META===") == 1 and src.count("===REPORT===") == 1 and src.index("===META===") < src.index("===REPORT==="))
        pos = lambda needle: src.find(needle)
        check(f"{tag}: the contract header precedes the first marker (marker not mentioned earlier)", 0 <= pos(HEADER[lang]) < pos("===META==="))
        check(f"{tag}: the plain-text report instruction follows ===REPORT===",
              0 <= pos("===REPORT===") < pos(META_RULES[lang]) < pos(SECTION_HEADER[lang]) < pos("**1.") and pos(META_RULES[lang]) >= 0)

        # --- byte-identical parts (only the contract wording may change) --------------------
        pin = PINS[tag]
        i = src.find(HEADER[lang]) if HEADER[lang] in src else src.find("OUTPUT FORMAT: valid JSON")
        m, r, s = src.index("===META==="), src.index("===REPORT==="), src.index("**1.")
        check(f"{tag}: rules/privacy/safety prefix (incl. purchased question + Data block) is byte-identical", h(src[:i]) == pin["prefix"])
        check(f"{tag}: META JSON block is byte-identical (keys, label, value rules)", h(src[m:r]) == pin["meta"])
        check(f"{tag}: numbered section list + closing rule are byte-identical", h(src[s:]) == pin["sections"])

        # --- placeholders / format ----------------------------------------------------------
        found = set(re.findall(r"(?<!{){([a-z_]+)}(?!})", src))
        check(f"{tag}: placeholders preserved exactly {sorted(PLACEHOLDERS[slug])}", found == PLACEHOLDERS[slug])
        try:
            formatted = src.format(**FILLER)
            fmt_ok = True
        except Exception as exc:  # KeyError / ValueError from a stray brace
            formatted, fmt_ok = "", False
            print("   format error:", exc)
        check(f"{tag}: str.format(**blocks) still works (no stray braces introduced)", fmt_ok)

        # --- META contract (as the model sees it) -------------------------------------------
        mm = re.search(r"===META===\s*(\{.*?\})\s*===REPORT===", formatted, re.S)
        try:
            meta = json.loads(mm.group(1))
        except Exception:
            meta = None
        check(f"{tag}: formatted META example is valid JSON", isinstance(meta, dict))
        if isinstance(meta, dict):
            check(f"{tag}: META top-level keys preserved {sorted(META_KEYS[slug])}", set(meta) == META_KEYS[slug])
            check(f"{tag}: answer_hero label preserved ({LABEL[slug]})", meta["answer_hero"]["label"] == LABEL[slug])
            check(f"{tag}: answer_hero carries label/value/interpretation/evidence",
                  set(meta["answer_hero"]) == {"label", "value", "interpretation", "evidence"})
        body_headings = re.findall(r"^\*\*(\d+)\.", formatted, re.M)
        check(f"{tag}: exactly {N_SECTIONS[slug]} numbered sections in order", body_headings == [str(n) for n in range(1, N_SECTIONS[slug] + 1)])

        # --- real parser + validator on the formatted prompt tail ---------------------------
        tail = formatted[formatted.index("===META==="):]
        pmeta, pbody = parse_structured_response(tail)
        try:
            hero = validate_required_hero_fields(pmeta, REGISTRY[slug].required_hero_fields)
            hero_ok = hero["label"] == LABEL[slug]
        except ReportMetadataError:
            hero_ok = False
        check(f"{tag}: real parse_structured_response + validate_required_hero_fields accept the contract example", hero_ok)

        # --- product-specific rules preserved -----------------------------------------------
        for tok in SAFETY[lang]:
            check(f"{tag}: safety/privacy rule text preserved: {tok!r}", tok in src)
        if slug == "love_disappointment_report":
            check(f"{tag}: gemstone stays out of love_disappointment", "gemstone" not in src.lower() and "रत्न" not in src)
        if slug == "love_marriage_report":
            for tok in ("Low", "Moderate", "Elevated", "love_vs_arranged", "stability_score", "marriage_report", "love_relationship_report"):
                check(f"{tag}: love_marriage rule token preserved: {tok}", tok in src)
        if slug == "love_relationship_report":
            check(f"{tag}: love_relationship still distinguishes marriage_report / love_marriage_report", "marriage_report" in src and "love_marriage_report" in src)
        if lang == "hi":
            check(f"{tag}: modern conversational Hindi policy block preserved", all(x in src for x in HI_POLICY))

# ---- control: what the model used to return vs what the parser needs -------------------------
print("\n=== control: parser behaviour ===")
good = '===META===\n{"answer_hero": {"label": "Relationship Pattern", "value": "Warm", "interpretation": "x", "evidence": ["e"]}, "action_items": ["a"]}\n===REPORT===\n**1. A**\nBody'
gm, gb = parse_structured_response(good)
check("control: a contract-following reply parses into metadata + narrative", isinstance(gm, dict) and gb.startswith("**1. A**"))
json_only = json.dumps({"answer_hero": {"label": "Relationship Pattern", "value": "Warm", "interpretation": "x", "evidence": ["e"]}, "action_items": ["a"], "report": "**1. A**\nBody"})
jm, _ = parse_structured_response(json_only)
check("control: a standalone JSON object (the Q4.3 failure shape) yields NO metadata -> the order would fail", jm is None)
try:
    validate_required_hero_fields(jm, REGISTRY["love_relationship_report"].required_hero_fields)
    raised = False
except ReportMetadataError:
    raised = True
check("control: validate_required_hero_fields raises ReportMetadataError for that shape (parser intentionally unchanged)", raised)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)
if failed:
    sys.exit(1)
