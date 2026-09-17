"""
test_report_structured_output.py
-------------------------------------------------
Q3 Batch 0 -- META/REPORT parser, validator, and deterministic-authority
assembly helpers verification. No DB/Flask/network dependency -- this
module is a pure function of its string/dict inputs.

Covers:
  A. Valid META+REPORT parsing (exact wire format).
  B. Malformed META behavior -- missing markers, bad JSON, non-object
     JSON -- all degrade to (None, ...) WITHOUT raising (parsing is
     never itself a source of a hard failure; that's validation's job).
  C. Q3-enabled required-hero validation: missing metadata, missing
     answer_hero, missing/empty required fields, malformed evidence --
     ALL raise ReportMetadataError (Q3 Batch 0 correction #1, locked --
     never a silent narrative-only degrade for a required field).
  D. A fully valid hero passes validation.
  E. Deterministic value/timing overrides an AI-supplied value/timing
     (Q3B Part 4/5 -- AI is never the authority for a deterministic
     fact); AI's own value is used only when no override is given.
  F. Gemstone assembly is built entirely from trusted Kundali data;
     `planet`/`gemstone`/`substone` are never taken from the `ai_reason`
     argument; missing/incomplete gemstone data -> None (component
     omitted), never invented.
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from modules.payments.report_structured_output import (
    parse_structured_response,
    validate_required_hero_fields,
    assemble_answer_hero,
    assemble_gemstone_component,
    ReportMetadataError,
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


# =================================================================
print("=== A: valid META+REPORT parsing ===")
# =================================================================
raw = (
    '===META===\n'
    '{"answer_hero": {"label": "Startup Outlook", "value": "FAVORABLE", '
    '"interpretation": "Good window.", "evidence": ["fact one", "fact two"]}}\n'
    '===REPORT===\n'
    '**Business Orientation**\nNarrative content here.\n'
)
metadata, narrative = parse_structured_response(raw)
check("A: metadata parsed as a real dict", isinstance(metadata, dict))
check("A: metadata contains the answer_hero object", metadata.get("answer_hero", {}).get("label") == "Startup Outlook")
check("A: narrative is the text after ===REPORT===, unaffected by the JSON", narrative.startswith("**Business Orientation**"))
check("A: narrative does not contain the META marker or JSON", "===META===" not in narrative and "FAVORABLE" not in narrative)

# =================================================================
print("\n=== B: malformed META behavior -- never raises, degrades to None ===")
# =================================================================
no_markers = "Just a plain narrative response, no structured metadata at all."
metadata, narrative = parse_structured_response(no_markers)
check("B: no markers at all -> metadata is None", metadata is None)
check("B: no markers at all -> entire response treated as narrative", narrative == no_markers)

bad_json = "===META===\n{not valid json,,,}\n===REPORT===\nNarrative anyway."
metadata, narrative = parse_structured_response(bad_json)
check("B: malformed JSON -> metadata is None, never raises", metadata is None)
check("B: malformed JSON -> narrative half still recovered correctly", narrative == "Narrative anyway.")

non_object_json = "===META===\n[1, 2, 3]\n===REPORT===\nNarrative."
metadata, narrative = parse_structured_response(non_object_json)
check("B: valid JSON but not an object (a list) -> metadata is None", metadata is None)

markers_reversed = "===REPORT===\nNarrative first.\n===META===\n{}"
metadata, narrative = parse_structured_response(markers_reversed)
check("B: markers in the wrong order -> metadata is None, whole text treated as narrative", metadata is None and narrative == markers_reversed)

check("B: empty string input -> (None, '') without raising", parse_structured_response("") == (None, ""))
check("B: None-shaped falsy input -> (None, '') without raising", parse_structured_response(None) == (None, ""))

# =================================================================
print("\n=== C: Q3-enabled required-hero validation -- hard failures ===")
# =================================================================
REQUIRED = ("label", "value", "interpretation", "evidence")

try:
    validate_required_hero_fields(None, REQUIRED)
    check("C: metadata=None raises ReportMetadataError", False)
except ReportMetadataError:
    check("C: metadata=None raises ReportMetadataError", True)

try:
    validate_required_hero_fields({"not_answer_hero": {}}, REQUIRED)
    check("C: metadata without an answer_hero object raises", False)
except ReportMetadataError:
    check("C: metadata without an answer_hero object raises", True)

try:
    validate_required_hero_fields({"answer_hero": {"label": "X"}}, REQUIRED)
    check("C: answer_hero missing required fields (value/interpretation/evidence) raises", False)
except ReportMetadataError as exc:
    check("C: answer_hero missing required fields (value/interpretation/evidence) raises", True)
    check("C: the error message names the actual missing fields", "value" in str(exc) and "evidence" in str(exc))

try:
    validate_required_hero_fields(
        {"answer_hero": {"label": "X", "value": "", "interpretation": "Y", "evidence": ["a"]}}, REQUIRED,
    )
    check("C: an empty-string required field (value='') raises, not just a missing key", False)
except ReportMetadataError:
    check("C: an empty-string required field (value='') raises, not just a missing key", True)

try:
    validate_required_hero_fields(
        {"answer_hero": {"label": "X", "value": "V", "interpretation": "Y", "evidence": []}}, REQUIRED,
    )
    check("C: an empty evidence list raises (evidence must be non-empty)", False)
except ReportMetadataError:
    check("C: an empty evidence list raises (evidence must be non-empty)", True)

try:
    validate_required_hero_fields(
        {"answer_hero": {"label": "X", "value": "V", "interpretation": "Y", "evidence": ["", "  "]}}, REQUIRED,
    )
    check("C: an evidence list of only blank strings raises", False)
except ReportMetadataError:
    check("C: an evidence list of only blank strings raises", True)

try:
    validate_required_hero_fields(
        {"answer_hero": {"label": "X", "value": "V", "interpretation": "Y", "evidence": "not a list"}}, REQUIRED,
    )
    check("C: evidence as a string instead of a list raises (structurally invalid)", False)
except ReportMetadataError:
    check("C: evidence as a string instead of a list raises (structurally invalid)", True)

# =================================================================
print("\n=== D: a fully valid hero passes validation ===")
# =================================================================
valid_hero_meta = {
    "answer_hero": {
        "label": "Startup Outlook", "value": "FAVORABLE",
        "interpretation": "Good window.", "evidence": ["fact one", "fact two"],
        "caution": "Stay disciplined.",
    }
}
validated = validate_required_hero_fields(valid_hero_meta, REQUIRED)
check("D: a fully valid hero returns the answer_hero dict unchanged", validated["value"] == "FAVORABLE" and validated["evidence"] == ["fact one", "fact two"])
check("D: optional fields (caution) not in required_fields still pass through", validated.get("caution") == "Stay disciplined.")

# Fewer required fields (e.g. a deterministic-value product only requires label+interpretation)
minimal_required = ("label", "interpretation")
minimal_hero_meta = {"answer_hero": {"label": "Sade Sati Status", "interpretation": "You are in the 2nd phase."}}
validated_minimal = validate_required_hero_fields(minimal_hero_meta, minimal_required)
check("D: a product declaring fewer required fields validates successfully with just those", validated_minimal["label"] == "Sade Sati Status")

# =================================================================
print("\n=== E: deterministic override -- AI value/timing is discarded ===")
# =================================================================
ai_hero = {"label": "L", "value": "AI-GUESSED-VALUE", "interpretation": "I", "evidence": ["e"], "timing": "AI-GUESSED-TIMING"}

overridden = assemble_answer_hero(ai_hero, deterministic_value="2nd Phase (Active)", deterministic_timing="2025-03-29 to 2027-06-02")
check("E: deterministic_value REPLACES the AI's own value entirely", overridden["value"] == "2nd Phase (Active)")
check("E: deterministic_timing REPLACES the AI's own timing entirely", overridden["timing"] == "2025-03-29 to 2027-06-02")
check("E: AI's own value/timing are gone from the result -- not merged, not appended", "AI-GUESSED-VALUE" not in overridden.values() and "AI-GUESSED-TIMING" not in overridden.values())
check("E: other AI-authored fields (label/interpretation/evidence) pass through unchanged", overridden["label"] == "L" and overridden["interpretation"] == "I" and overridden["evidence"] == ["e"])

not_overridden = assemble_answer_hero(ai_hero)
check("E: with no deterministic override supplied, AI's own value is used (product declared hero_value_source='ai')", not_overridden["value"] == "AI-GUESSED-VALUE")
check("E: with no deterministic override supplied, AI's own timing is used", not_overridden["timing"] == "AI-GUESSED-TIMING")

check("E: assemble_answer_hero never mutates the caller's original dict", ai_hero["value"] == "AI-GUESSED-VALUE")

# =================================================================
print("\n=== F: gemstone assembly -- deterministic authority ===")
# =================================================================
real_gemstone = {"planet": "Jupiter", "gemstone": "Yellow Sapphire", "substone": "Citrine", "cta": {}}
component = assemble_gemstone_component(real_gemstone, ai_reason="Jupiter is the strongest benefic in this chart.")
check("F: planet comes from trusted Kundali data, not AI", component["planet"] == "Jupiter")
check("F: gemstone comes from trusted Kundali data, not AI", component["gemstone"] == "Yellow Sapphire")
check("F: substone comes from trusted Kundali data, not AI", component["substone"] == "Citrine")
check("F: only 'reason' is AI-authored", component["reason"] == "Jupiter is the strongest benefic in this chart.")

check("F: an ai_reason claiming a DIFFERENT gemstone does not change planet/gemstone/substone",
      assemble_gemstone_component(real_gemstone, ai_reason="Actually Blue Sapphire is better")["gemstone"] == "Yellow Sapphire")

check("F: missing gemstone_suggestion entirely -> None (component omitted)", assemble_gemstone_component(None) is None)
check("F: empty dict gemstone_suggestion -> None", assemble_gemstone_component({}) is None)
check("F: incomplete gemstone_suggestion (neither planet nor gemstone present) -> None, never invented",
      assemble_gemstone_component({"paragraph": "Data incomplete for recommendation.", "planet": None}) is None)
check("F: gemstone present without ai_reason still assembles (reason is optional)",
      assemble_gemstone_component(real_gemstone)["reason"] is None)

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
