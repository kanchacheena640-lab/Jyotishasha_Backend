"""
test_report_product_intelligence.py
-------------------------------------------------
Q3 Batch 0 -- product-intelligence registry foundation verification.

No DB/Flask dependency -- this is a static Python module.

Covers:
  A. All 25 report_slug entries exist, keyed by the exact trusted slugs
     (cross-checked against the same 25-product list Q1's own R2
     migration seeded -- not re-typed independently here without
     verification).
  B. CRITICAL Batch-0 invariant: every one of the 25 entries has
     q3_enabled=False -- staged migration must be safe; no product may
     be accidentally left requiring structured metadata its own prompt
     was never rewritten to produce.
  C. get_product_intelligence() never raises and never returns None,
     even for an unrecognized/legacy slug -- a lookup miss is not a
     new failure mode.
  D. Each entry's own declared shape is internally consistent (e.g. a
     "deterministic:..." hero_value_source names a real, recognizable
     source; gemstone_policy is one of the declared vocabulary values).
  E. relationship_future_report is correctly registered under
     generator="love_premium_v1", distinct from every other entry's
     "standard_v1".
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from modules.payments.report_product_intelligence import (
    REGISTRY, get_product_intelligence, ProductIntelligence,
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


# The exact 25 report_slug values, cross-checked against migrations/
# versions/65bed70e2520_r2_seed_report_products_from_product_.py's own
# 24 standard-product list + relationship_future_report (the one
# love_premium_v1 product) -- the same source of truth Q1's own R2
# phase used, not re-derived independently here.
EXPECTED_SLUGS = {
    "sadhesati_report", "financial_report", "love_relationship_report",
    "marriage_report", "startup_suggestion_report", "love_marriage_report",
    "government_job_report", "foreign_travel_report", "business_report",
    "career_report", "gemstone_consultation", "children_parenting_report",
    "delay_in_marriage_report", "financial_stability_report",
    "jupiter_transit_report", "lifestyle_analysis_report",
    "love_disappointment_report", "problem_in_marriage_report",
    "mood_mental_health_report", "property_report", "saturn_transit_report",
    "second_marriage_report", "divorce_possibility_report",
    "legal_disputes_report", "relationship_future_report",
}

# =================================================================
print("=== A: all 25 report_slug entries exist ===")
# =================================================================
check("A: exactly 25 entries in REGISTRY", len(REGISTRY) == 25)
check("A: REGISTRY keys are exactly the 25 trusted report_slugs (no typo, none missing, none extra)",
      set(REGISTRY.keys()) == EXPECTED_SLUGS)

# =================================================================
print("\n=== B: CRITICAL -- exactly ALL 25 products are enabled (Q3 Batches 1-5, FINAL) ===")
# =================================================================
EXPECTED_Q3_ENABLED = {
    # Q3 Batch 1
    "gemstone_consultation", "saturn_transit_report",
    "mood_mental_health_report", "divorce_possibility_report",
    # Q3 Batch 2
    "marriage_report", "delay_in_marriage_report",
    "problem_in_marriage_report", "second_marriage_report",
    # Q3 Batch 3
    "financial_report", "financial_stability_report", "career_report",
    "government_job_report", "business_report", "startup_suggestion_report",
    # Q3 Batch 4
    "love_relationship_report", "love_marriage_report",
    "love_disappointment_report", "relationship_future_report",
    # Q3 Batch 5 (FINAL)
    "sadhesati_report", "foreign_travel_report", "children_parenting_report",
    "jupiter_transit_report", "lifestyle_analysis_report", "property_report",
    "legal_disputes_report",
}
actually_enabled = {slug for slug, p in REGISTRY.items() if p.q3_enabled}
check("B: exactly these 25 products have q3_enabled=True (Q3 Batches 1-5, FINAL migration)",
      actually_enabled == EXPECTED_Q3_ENABLED)
check("B: EXPECTED_Q3_ENABLED covers the entire 25-product registry -- 0 remain disabled",
      EXPECTED_Q3_ENABLED == set(REGISTRY.keys()))
check("B: 0 products have q3_enabled=False (staged migration COMPLETE)",
      all(p.q3_enabled for p in REGISTRY.values()))

# =================================================================
print("\n=== C: get_product_intelligence() never raises, never returns None ===")
# =================================================================
for bad_input in (None, "", "not_a_real_product_slug", "STARTUP_SUGGESTION_REPORT", 12345):
    try:
        result = get_product_intelligence(bad_input)
        check(f"C: get_product_intelligence({bad_input!r}) returns a ProductIntelligence, never raises",
              isinstance(result, ProductIntelligence))
        check(f"C: get_product_intelligence({bad_input!r}) safely defaults to q3_enabled=False",
              result.q3_enabled is False)
    except Exception as exc:
        check(f"C: get_product_intelligence({bad_input!r}) returns a ProductIntelligence, never raises ({exc})", False)

check("C: a real, known slug returns its actual registry entry, not the default",
      get_product_intelligence("sadhesati_report").hero_value_source == "deterministic:sadhesati_summary")

# =================================================================
print("\n=== D: internal consistency of declared shapes ===")
# =================================================================
VALID_GEMSTONE_POLICIES = {"disabled", "optional", "required", "substone_only"}
for slug, p in REGISTRY.items():
    check(f"D: {slug}: gemstone_policy is a recognized vocabulary value ({p.gemstone_policy!r})",
          p.gemstone_policy in VALID_GEMSTONE_POLICIES)
    check(f"D: {slug}: generator is standard_v1 or love_premium_v1",
          p.generator in ("standard_v1", "love_premium_v1"))
    check(f"D: {slug}: hero_value_source is 'ai' or a 'deterministic:...' string",
          p.hero_value_source == "ai" or p.hero_value_source.startswith("deterministic:"))
    check(f"D: {slug}: required_hero_fields is a non-empty tuple (every product needs SOME required fields once enabled)",
          isinstance(p.required_hero_fields, tuple) and len(p.required_hero_fields) > 0)

check("D: gemstone_consultation is the one product with gemstone_policy='required'",
      REGISTRY["gemstone_consultation"].gemstone_policy == "required")
check("D: relationship_future_report and foreign_travel_report both have gemstone_policy='disabled' (Q3A's own locked rulings)",
      REGISTRY["relationship_future_report"].gemstone_policy == "disabled"
      and REGISTRY["foreign_travel_report"].gemstone_policy == "disabled")
check("D: sadhesati_report is 'substone_only' (never a primary gemstone push, unchanged/out of Batch 1 scope)",
      REGISTRY["sadhesati_report"].gemstone_policy == "substone_only")
check("D: (human visual QA correction) saturn_transit_report's gemstone_policy is 'disabled' -- "
      "a deterministic gemstone existing is not itself a reason to show one on a transit-timing product",
      REGISTRY["saturn_transit_report"].gemstone_policy == "disabled")
check("D: (human visual QA correction) mood_mental_health_report's gemstone_policy is 'disabled' -- no gemstone upsell on a well-being product",
      REGISTRY["mood_mental_health_report"].gemstone_policy == "disabled")
check("D: (human visual QA correction) divorce_possibility_report's gemstone_policy is 'disabled' -- no gemstone upsell on a relationship-risk product",
      REGISTRY["divorce_possibility_report"].gemstone_policy == "disabled")
check("D: gemstone_consultation's gemstone_policy is UNCHANGED at 'required' by the visual QA correction",
      REGISTRY["gemstone_consultation"].gemstone_policy == "required")

# =================================================================
print("\n=== E: relationship_future_report is correctly distinguished ===")
# =================================================================
rel = REGISTRY["relationship_future_report"]
check("E: relationship_future_report's generator is love_premium_v1", rel.generator == "love_premium_v1")
check("E: every OTHER product's generator is standard_v1",
      all(p.generator == "standard_v1" for slug, p in REGISTRY.items() if slug != "relationship_future_report"))
check("E: relationship_future_report's required_context_keys is empty (its own separate love_data_collector.py pipeline, not summary_blocks.py)",
      rel.required_context_keys == ())

print("\n" + "=" * 50)
print(f"TOTAL: {passed} passed, {failed} failed")
print("=" * 50)

if failed:
    sys.exit(1)
