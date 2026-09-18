# modules/payments/report_product_intelligence.py

"""
report_product_intelligence.py -- Paid Report Platform, Q3 Batch 0.

Static, code-level registry of per-product design intent (Q3A's own
audit, condensed into a machine-readable shape) -- NOT a database
table. This is deliberately a plain Python module, mirroring the
existing precedent of config/pricing.py::PRODUCT_PRICES and config/
google_play_report_products.py: product DESIGN intent (which houses
matter, which components apply, whether gemstone is relevant) is
versioned with the code that consumes it, not admin-editable runtime
business data (price/active-status, which already live in
ReportProduct, untouched by this file).

CRITICAL scope rule, updated for Q3 Batch 5 (FINAL): at Batch 0 every
one of the 25 entries had q3_enabled=False. Batch 1 flipped 4 --
gemstone_consultation, saturn_transit_report, mood_mental_health_report,
divorce_possibility_report. Batch 2 flipped 4 more -- marriage_report,
delay_in_marriage_report, problem_in_marriage_report, second_marriage_
report. Batch 3 flipped 6 more -- financial_report, financial_stability_
report, career_report, government_job_report, business_report,
startup_suggestion_report. Batch 4 flipped 4 more -- love_relationship_
report, love_marriage_report, love_disappointment_report,
relationship_future_report -- for a total of 18 q3_enabled=True out of
25. Batch 5 flips the LAST 7 -- sadhesati_report, foreign_travel_report,
children_parenting_report, jupiter_transit_report, lifestyle_analysis_
report, property_report, legal_disputes_report -- for a final total of
25 q3_enabled=True out of 25 (0 remaining disabled). Each flip happens
only together with that product's own prompt rewrite for the
structured-output contract, never before. tasks.py/modules/love/
love_premium_task.py both check this flag before ever calling
report_structured_output.py's parser/validator -- a product with
q3_enabled=False is completely unaffected by anything in this file
beyond being looked up.

Fields per entry:
  generator            "standard_v1" | "love_premium_v1"
  q3_enabled           bool -- see above; False for all 25 at Batch 0
  hero_value_source     "ai" | "deterministic:<summary_blocks key or
                        other named source>" -- which of the two
                        assemble_answer_hero() branches applies once
                        this product IS enabled (informational at
                        Batch 0; not consumed until a product flips on)
  required_hero_fields  the fields validate_required_hero_fields() will
                        enforce once q3_enabled=True (informational at
                        Batch 0)
  relevant_houses       int list, Q3A's own named house set
  relevant_planets      str list, Q3A's own named planet set
  required_context_keys summary_blocks.py keys this product's rewritten
                        prompt is expected to consume
  components_enabled    which Q2.1 PDF components this product may use
                        (dict of component-name -> True/False/"optional"
                        /"substone_only" etc.)
  gemstone_policy       "disabled" | "optional" | "required" |
                        "substone_only" -- Q3A's own per-product ruling
  disclaimer_type       a short label naming which disclaimer class
                        applies (actual text is a future batch's job)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProductIntelligence:
    report_slug: str
    generator: str
    q3_enabled: bool
    hero_value_source: str
    required_hero_fields: tuple
    relevant_houses: tuple
    relevant_planets: tuple
    required_context_keys: tuple
    components_enabled: dict
    gemstone_policy: str
    disclaimer_type: str
    hero_label: str = ""


def _standard(
    slug,
    *,
    houses=(),
    planets=(),
    context_keys=("birth_chart_summary", "mahadasha_summary", "current_transit_summary"),
    hero_value_source="ai",
    required_hero_fields=("label", "value", "interpretation", "evidence"),
    components=None,
    gemstone="optional",
    disclaimer="general",
    q3_enabled=False,
    hero_label="",
):
    return ProductIntelligence(
        report_slug=slug,
        generator="standard_v1",
        q3_enabled=q3_enabled,
        hero_value_source=hero_value_source,
        required_hero_fields=tuple(required_hero_fields),
        relevant_houses=tuple(houses),
        relevant_planets=tuple(planets),
        required_context_keys=tuple(context_keys),
        components_enabled=components or {"answer_hero": True, "timeline": True, "gemstone": gemstone != "disabled"},
        gemstone_policy=gemstone,
        disclaimer_type=disclaimer,
        hero_label=hero_label,
    )


# Q3A audit's own per-product houses/planets/gemstone-policy/disclaimer
# rulings, condensed. See the Q3A/Q3B conversation for the full
# per-product reasoning behind each choice below -- not re-derived here.
REGISTRY: dict = {
    # Q3 Batch 5 (FINAL) -- ENABLED. `value` is ALWAYS overwritten with
    # the deterministic Sade Sati status/phase from kundali["sadhesati"]
    # (report_q3_batch5.py::compute_sadhesati_hero(), reusing
    # summary_blocks.py's own phase-date-key mapping -- no new
    # astrology calculation, and NOT the underlying engine's own
    # (buggy) internal date lookup). Real Sade Sati phase dates only,
    # never a guessed negative life event -- see the mandatory
    # disclaimer. gemstone_policy stays "substone_only" (unchanged
    # label from Batch 0); the shared assembler has no distinct
    # substone-only rendering mode (confirmed in the Q3 Final-7 audit),
    # so this resolves through the SAME deterministic gemstone path
    # every other non-disabled product uses -- planet/gemstone/
    # substone are still 100% backend-sourced, Luna still never
    # chooses one, only the visual "substone-only" framing is
    # currently unenforced. Known, documented limitation -- not a
    # safety gap.
    "sadhesati_report": _standard(
        "sadhesati_report",
        hero_label="Sade Sati Status",
        houses=(), planets=("Saturn", "Moon"),
        context_keys=("sadhesati_summary", "dasha_window_summary"),
        hero_value_source="deterministic:sadhesati_summary",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="substone_only",
        disclaimer="sadhesati_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 3 -- ENABLED. `value` stays AI-authored (a qualitative
    # wealth-growth descriptor, e.g. "Building Momentum" -- no numeric
    # financial-score engine exists in this codebase, so this can never
    # be a deterministic value). `wealth_yoga_summary` surfaces already-
    # computed Dhan/Kuber/Lakshmi/Chandra-Mangal Yog results (see
    # summary_blocks.py) -- real deterministic evidence, never invented
    # by Luna. `timeline` reuses report_q3_batch2.py's own Dasha-window
    # helper unchanged (see report_q3_batch3.py). This product answers
    # GENERATING/BUILDING wealth -- distinct from financial_stability_
    # report's own RETENTION/VOLATILITY question.
    "financial_report": _standard(
        "financial_report",
        houses=(2, 5, 8, 11), planets=("Jupiter", "Venus", "Mercury", "Saturn"),
        context_keys=("house_lord_summary", "dasha_window_summary", "wealth_yoga_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="financial_advice_non_certainty_mandatory",
        q3_enabled=True,
    ),
    "love_relationship_report": _standard(
        "love_relationship_report",
        hero_label="Relationship Pattern",
        houses=(5, 7), planets=("Venus", "Moon", "Mars"),
        context_keys=("house_lord_summary", "dasha_window_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="relationship_pattern_general",
        q3_enabled=True,
    ),
    # Q3 Batch 2 -- ENABLED. `value` stays AI-authored (a qualitative
    # outlook descriptor, e.g. "Supportive, With Steady Effort" -- never
    # an exact age/date; the previous prompt's "before 24 / after 29"
    # instruction is removed, not softened -- no deterministic engine
    # in this codebase computes a marriage age). `timeline` is real
    # Dasha-window dates via report_q3_batch2.py::compute_dasha_window_
    # timeline() (reuses summary_blocks.py's own dasha-sequence
    # flattening -- no new astrology calculation).
    "marriage_report": _standard(
        "marriage_report",
        houses=(7,), planets=("Venus", "Jupiter", "Mars", "Saturn", "Rahu"),
        context_keys=("house_lord_summary", "manglik_summary", "dasha_window_summary", "targeted_aspect_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": True, "timeline": True, "action_list": True},
        gemstone="optional", disclaimer="general",
        q3_enabled=True,
    ),
    # Q3 Batch 3 -- ENABLED. `value` stays AI-authored, PREPARATION/
    # LAUNCH-READINESS framed (e.g. "Preparation Phase", "Comparatively
    # Ready to Launch") -- deliberately distinct from business_report's
    # own ONGOING-CAPACITY framing (see that entry's own comment). Same
    # relevant_houses as business_report intentionally narrowed to the
    # tighter 2/7/10 launch-evidence set (business_report additionally
    # covers the 11th for sustaining/growth) -- one concrete registry-
    # level differentiation signal on top of the much larger hero/
    # section differences the prompt itself carries.
    "startup_suggestion_report": _standard(
        "startup_suggestion_report",
        houses=(2, 7, 10), planets=("Mercury", "Jupiter", "Saturn", "Mars"),
        context_keys=("house_lord_summary", "dasha_window_summary", "career_yoga_summary", "wealth_yoga_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="business_outcome_non_certainty_mandatory",
        q3_enabled=True,
    ),
    "love_marriage_report": _standard(
        "love_marriage_report",
        hero_label="Love-Marriage Tendency",
        houses=(5, 7), planets=("Venus", "Mars", "Jupiter"),
        context_keys=("house_lord_summary", "targeted_aspect_summary", "dasha_window_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="relationship_pattern_general",
        q3_enabled=True,
    ),
    # Q3 Batch 3 -- ENABLED. `value` stays AI-authored, PROMPT-
    # constrained (not backend-enum-validated, same precedent as
    # delay_in_marriage_report/second_marriage_report in Q3 Batch 2) to
    # exactly one of Low/Moderate/Elevated -- an astrological TENDENCY
    # signal only, never a prediction of exam success, selection, or
    # appointment (see the mandatory disclaimer). `career_yoga_summary`
    # surfaces already-computed Rajya-Sambandh/Parashari/Panch-
    # Mahapurush/Gajakesari/etc. yoga results -- real evidence, never
    # invented.
    "government_job_report": _standard(
        "government_job_report",
        houses=(6, 9, 10, 11), planets=("Sun", "Saturn", "Mars", "Jupiter"),
        context_keys=("house_lord_summary", "dasha_window_summary", "career_yoga_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="government_job_selection_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 5 (FINAL) -- ENABLED. `value` stays AI-authored,
    # PROMPT-constrained (not backend-enum-validated, same precedent as
    # delay_in_marriage_report/government_job_report) to exactly one of
    # Low/Moderate/Elevated -- a general foreign-travel TENDENCY signal
    # only. No sub-category (tourism/education/work/settlement) is ever
    # claimed: services/foreign_travel.py's own deterministic evaluator
    # has no concept of these categories (confirmed in the Q3 Final-7
    # audit), only a general positive/negative signal from 9th/12th
    # house+lord+planet+aspect facts.
    "foreign_travel_report": _standard(
        "foreign_travel_report",
        hero_label="Foreign Travel Potential",
        houses=(9, 12), planets=("Rahu", "Moon", "Jupiter"),
        context_keys=("foreign_travel_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": False, "action_list": True},
        gemstone="disabled", disclaimer="general",
        q3_enabled=True,
    ),
    # Q3 Batch 3 -- ENABLED. `value` stays AI-authored, ONGOING-CAPACITY
    # framed (e.g. "Naturally Suited, With Steady Discipline") --
    # deliberately distinct from startup_suggestion_report's own
    # PREPARATION/LAUNCH-READINESS framing (see that entry's own
    # comment). Answers "can I run/sustain/grow a business", not
    # "should I start one now."
    "business_report": _standard(
        "business_report",
        houses=(2, 7, 10, 11), planets=("Mercury", "Jupiter", "Saturn", "Mars"),
        context_keys=("house_lord_summary", "dasha_window_summary", "career_yoga_summary", "wealth_yoga_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="business_outcome_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 3 -- ENABLED. `value` stays AI-authored, an ORIENTATION
    # descriptor (e.g. "Structured, Service-Oriented Tendency") --
    # deliberately NOT forced into a Job-vs-Business binary (no
    # deterministic classifier for that exists in this codebase); the
    # prompt may lean toward one without declaring it categorically.
    "career_report": _standard(
        "career_report",
        houses=(2, 6, 10, 11), planets=("Sun", "Saturn", "Mercury", "Jupiter", "Mars"),
        context_keys=("house_lord_summary", "dasha_window_summary", "career_yoga_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True},
        gemstone="optional", disclaimer="general",
        q3_enabled=True,
    ),
    # Q3 Batch 1 -- ENABLED. The gemstone recommendation itself is the
    # purchased product; `value` is ALWAYS overwritten with the
    # deterministic kundali["gemstone_suggestion"]["gemstone"] name
    # (report_q3_batch1.py::compute_gemstone_hero_value()), never
    # trusted from Luna. gemstone_policy="required" means tasks.py
    # raises (hard FAIL, F2-recoverable) rather than deliver a report
    # missing its own purchased gemstone box. No timeline -- this
    # product has no deterministic timing source.
    "gemstone_consultation": _standard(
        "gemstone_consultation",
        houses=(1, 2, 4, 5, 7, 9, 10, 11), planets=(),
        context_keys=("gemstone_summary", "house_lord_summary", "dasha_window_summary"),
        hero_value_source="deterministic:gemstone_recommendation",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": True, "timeline": False, "action_list": True},
        gemstone="required", disclaimer="none",
        q3_enabled=True,
    ),
    # Q3 Batch 5 (FINAL) -- ENABLED. `value` stays AI-authored, a
    # qualitative PARENTING descriptor only (never a tier, never a
    # fertility/pregnancy score -- no such classifier exists anywhere
    # in this codebase). Reframed to answer PARENTING TENDENCIES/
    # PARENT-CHILD DYNAMICS specifically -- never fertility, pregnancy,
    # conception timing, a child's health, or a child's sex (see the
    # mandatory disclaimer and the rewritten prompt's own explicit
    # prohibitions).
    "children_parenting_report": _standard(
        "children_parenting_report",
        hero_label="Parenting Pattern",
        houses=(5,), planets=("Jupiter", "Moon"),
        context_keys=("house_lord_summary", "dasha_window_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="children_parenting_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 2 -- ENABLED. `value` stays AI-authored but is
    # PROMPT-CONSTRAINED (not backend-enum-validated -- same established
    # precedent as divorce_possibility_report's own Low/Moderate/Elevated
    # field, Q3 Batch 1) to exactly one of Low/Moderate/Elevated -- never
    # a percentage or score, since no deterministic delay-scoring engine
    # exists. `timeline` is real Dasha-window dates, same helper as
    # marriage_report.
    "delay_in_marriage_report": _standard(
        "delay_in_marriage_report",
        houses=(7,), planets=("Venus", "Jupiter", "Saturn", "Mars", "Rahu", "Ketu"),
        context_keys=("house_lord_summary", "targeted_aspect_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": True, "timeline": True, "action_list": True},
        gemstone="optional", disclaimer="general",
        q3_enabled=True,
    ),
    # Q3 Batch 3 -- ENABLED. `value` stays AI-authored, PROMPT-
    # constrained (not backend-enum-validated, same precedent as
    # delay_in_marriage_report/second_marriage_report in Q3 Batch 2) to
    # exactly one of Low/Moderate/Elevated. IMPORTANT SEMANTIC (locked
    # by the Batch 3 spec, stated explicitly in the prompt and tested):
    # this tier represents financial VOLATILITY/INSTABILITY tendency,
    # NOT "how stable" -- Low = lower instability tendency, Elevated =
    # higher instability tendency. Answers RETENTION/STABILITY/
    # VOLATILITY -- distinct from financial_report's own GENERATING/
    # BUILDING-wealth question.
    "financial_stability_report": _standard(
        "financial_stability_report",
        houses=(2, 8, 12), planets=("Saturn", "Jupiter"),
        context_keys=("house_lord_summary", "dasha_window_summary", "wealth_yoga_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="financial_advice_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 5 (FINAL) -- ENABLED. `value` is ALWAYS overwritten with
    # Jupiter's real, deterministic Lagna-relative transit house
    # (report_q3_batch5.py::compute_jupiter_transit_hero(), reusing
    # summary_blocks.py's own sign-offset math and the SAME planet-
    # generic smart_transit_engine.get_current_sign_residency() call
    # saturn_transit_report already uses -- no new engine). `timing`
    # is best-effort real dates from that same call, never a guessed
    # life event. gemstone_policy is "disabled" (changed from Batch
    # 0's "optional") -- mirrors saturn_transit_report's own Batch-1
    # visual-QA correction: a deterministic gemstone existing is not
    # itself a reason to show one on a transit-timing product.
    "jupiter_transit_report": _standard(
        "jupiter_transit_report",
        hero_label="Jupiter Transit Focus",
        houses=(), planets=("Jupiter",),
        context_keys=("transit_facts_summary", "house_lord_summary"),
        hero_value_source="deterministic:transit_facts_summary",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": False, "action_list": True},
        gemstone="disabled", disclaimer="general",
        q3_enabled=True,
    ),
    # Q3 Batch 5 (FINAL) -- ENABLED. `value` stays AI-authored, a
    # qualitative descriptor of daily-habit/routine/discipline balance
    # only -- distinct from mood_mental_health_report's own EMOTIONAL/
    # MOOD framing (4th/12th house + Moon) by house set (6th house)
    # and by question (habits/routine, never emotional tendency). No
    # medical/diagnostic authority exists anywhere in this codebase --
    # the mandatory disclaimer and rewritten prompt both explicitly
    # forbid diagnosis, treatment, or guaranteed health outcomes.
    "lifestyle_analysis_report": _standard(
        "lifestyle_analysis_report",
        hero_label="Lifestyle Balance Pattern",
        houses=(6,), planets=("Moon", "Saturn"),
        context_keys=("house_lord_summary", "dasha_window_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="lifestyle_health_non_certainty_mandatory",
        q3_enabled=True,
    ),
    "love_disappointment_report": _standard(
        "love_disappointment_report",
        hero_label="Emotional Relationship Pattern",
        houses=(5, 7, 8, 12), planets=("Venus", "Moon", "Saturn", "Rahu", "Ketu"),
        context_keys=("house_lord_summary", "targeted_aspect_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": False, "action_list": True, "disclaimer": True},
        gemstone="disabled", disclaimer="love_disappointment_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 2 -- ENABLED. `value` stays AI-authored, a calm
    # qualitative descriptor (e.g. "Manageable With Communication") --
    # never a diagnostic/certainty label, never Low/Moderate/Elevated
    # (deliberately NOT forced into that tier family -- this is a
    # friction-pattern product, not a risk-signal product). Safety-
    # sensitive (no claims about a partner's private thoughts/
    # intentions, no divorce prediction) -- the mandatory disclaimer is
    # backend-controlled via DISCLAIMER_TEXT["marriage_problem_non_
    # certainty_mandatory"] in report_q3_batch1.py, injected
    # unconditionally regardless of Luna's own output. No gemstone --
    # a gemstone box on a marital-friction product would read as "wear
    # this to fix your marriage," matching the precedent already set
    # for mood_mental_health_report/divorce_possibility_report.
    "problem_in_marriage_report": _standard(
        "problem_in_marriage_report",
        houses=(7,), planets=("Venus", "Jupiter"),
        context_keys=("house_lord_summary", "targeted_aspect_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": False, "timeline": False, "action_list": True, "disclaimer": True},
        gemstone="disabled", disclaimer="marriage_problem_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 1 -- ENABLED. `value` stays AI-authored (a gentle
    # tendency descriptor, never a diagnostic label) -- hero_value_
    # source is deliberately "ai", not deterministic; only the
    # MANDATORY disclaimer is backend-controlled (report_q3_batch1.py::
    # DISCLAIMER_TEXT["mental_health_mandatory"], injected
    # unconditionally in tasks.py regardless of Luna's own output).
    #
    # Human visual QA correction (post-Batch-1): gemstone_policy
    # changed "optional" -> "disabled". This is a well-being insight
    # product, not a gemstone product -- no gemstone component of any
    # kind renders here, regardless of whether deterministic gemstone
    # data exists.
    "mood_mental_health_report": _standard(
        "mood_mental_health_report",
        houses=(4, 12), planets=("Moon",),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": False, "timeline": False, "action_list": True, "disclaimer": True},
        gemstone="disabled", disclaimer="mental_health_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 5 (FINAL) -- ENABLED. `value` stays AI-authored,
    # PROMPT-constrained (not backend-enum-validated, same precedent as
    # delay_in_marriage_report) to exactly one of Low/Moderate/Elevated
    # -- a property-acquisition TENDENCY signal only. No price/
    # valuation/legal-title-verification engine exists anywhere in
    # this codebase; the mandatory disclaimer and rewritten prompt
    # both explicitly forbid guaranteed purchase, price appreciation,
    # investment return, or legal-title-outcome claims.
    "property_report": _standard(
        "property_report",
        hero_label="Property Acquisition Tendency",
        houses=(4,), planets=("Mars", "Saturn"),
        context_keys=("house_lord_summary", "dasha_window_summary", "gemstone_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="property_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 1 -- ENABLED. `value` is ALWAYS overwritten with Saturn's
    # real, deterministic Lagna-relative transit house (report_q3_
    # batch1.py::compute_saturn_transit_hero(), reusing summary_blocks.
    # py's own sign-offset math -- no new astrology calculation).
    # `timing` is best-effort real dates from smart_transit_engine.
    # get_current_sign_residency("Saturn") when available, otherwise
    # omitted -- never guessed. Distinct from sadhesati_report
    # (Moon-relative Saturn phase system) -- sadhesati_summary is
    # available as supporting context only, never merged with this
    # product's own Lagna-relative reading.
    #
    # Human visual QA correction (post-Batch-1): gemstone_policy
    # changed "substone_only" -> "disabled". A deterministic gemstone
    # recommendation existing in kundali["gemstone_suggestion"] is not,
    # on its own, a reason to show a gemstone box on a Saturn TRANSIT
    # product whose purchased answer is the transit house/timing, not a
    # gemstone -- showing one anyway turns every paid report into a
    # gemstone upsell. No product-specific justification for including
    # one was identified for this report.
    "saturn_transit_report": _standard(
        "saturn_transit_report",
        houses=(), planets=("Saturn",),
        context_keys=("transit_facts_summary", "house_lord_summary", "sadhesati_summary"),
        hero_value_source="deterministic:saturn_transit_house",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": False, "timeline": True, "action_list": True},
        gemstone="disabled", disclaimer="none",
        q3_enabled=True,
    ),
    # Q3 Batch 2 -- ENABLED. `value` stays AI-authored, PROMPT-
    # CONSTRAINED (not backend-enum-validated, same precedent as
    # delay_in_marriage_report above) to exactly one of Low/Moderate/
    # Elevated. Evidence spans BOTH the 7th and 9th houses (classical
    # second-marriage significators) -- an empty house is never treated
    # as "no evidence" (see the prompt's own explicit instruction).
    # Safety-sensitive: the mandatory disclaimer (DISCLAIMER_TEXT
    # ["second_marriage_non_certainty_mandatory"]) is backend-
    # controlled, never left to Luna. No gemstone, same reasoning as
    # problem_in_marriage_report.
    "second_marriage_report": _standard(
        "second_marriage_report",
        houses=(7, 9), planets=("Venus", "Jupiter"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": False, "timeline": False, "action_list": True, "disclaimer": True},
        gemstone="disabled", disclaimer="second_marriage_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 1 -- ENABLED. `value` stays AI-authored (a calibrated
    # Low/Moderate/Elevated tendency, always framed as astrological
    # signal, never certainty) -- hero_value_source is "ai", not
    # deterministic. The MANDATORY non-certainty/non-legal disclaimer is
    # backend-controlled (report_q3_batch1.py::DISCLAIMER_TEXT
    # ["divorce_non_certainty_mandatory"]), injected unconditionally
    # regardless of Luna's own output.
    #
    # Human visual QA correction (post-Batch-1): gemstone_policy
    # changed "optional" -> "disabled". A relationship-stress-signal
    # product must never look like a gemstone-remedy upsell -- no
    # gemstone component renders here.
    "divorce_possibility_report": _standard(
        "divorce_possibility_report",
        houses=(6, 7, 8), planets=(),
        context_keys=("house_lord_summary", "targeted_aspect_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "gemstone": False, "timeline": False, "action_list": True, "disclaimer": True},
        gemstone="disabled", disclaimer="divorce_non_certainty_mandatory",
        q3_enabled=True,
    ),
    # Q3 Batch 5 (FINAL) -- ENABLED, HIGHEST safety scrutiny of the
    # final 7. `value` stays AI-authored, PROMPT-constrained to exactly
    # one of Low/Moderate/Elevated -- an astrological DISPUTE-PRESSURE
    # tendency signal only, never a legal-outcome score. No court-
    # result/arrest/conviction/acquittal-prediction capability exists
    # anywhere in this codebase, and this product must never provide
    # legal advice (see the mandatory disclaimer and the fully
    # rewritten -- not merely re-translated -- EN+HI prompts, which
    # remove the prior Hindi prompt's "victory" (विजय) framing
    # entirely). targeted_aspect_summary is deliberately DROPPED from
    # this product's context keys -- that summary is hardcoded to the
    # 7th house + Saturn/Venus/Moon only (a marriage-relationship-
    # oriented fact), a poor evidentiary fit for a 6th/7th/8th/12th-
    # house legal-dispute product (confirmed in the Q3 Final-7 audit).
    "legal_disputes_report": _standard(
        "legal_disputes_report",
        hero_label="Legal Dispute Pressure",
        houses=(6, 7, 8, 12), planets=("Saturn", "Rahu", "Ketu", "Mars"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        components={"answer_hero": True, "timeline": True, "gemstone": True, "action_list": True, "disclaimer": True},
        gemstone="optional", disclaimer="legal_dispute_non_certainty_mandatory",
        q3_enabled=True,
    ),
    "relationship_future_report": ProductIntelligence(
        report_slug="relationship_future_report",
        hero_label="Relationship Outlook",
        generator="love_premium_v1",
        q3_enabled=True,
        hero_value_source="ai",
        required_hero_fields=("label", "value", "interpretation", "evidence"),
        relevant_houses=(), relevant_planets=(),
        required_context_keys=(),  # separate pipeline -- love_data_collector.py, not summary_blocks.py
        components_enabled={"answer_hero": True, "timeline": False, "gemstone": False, "action_list": True, "disclaimer": True},
        gemstone_policy="disabled",
        disclaimer_type="relationship_future_non_certainty_mandatory",
    ),
}


_DEFAULT_LEGACY = ProductIntelligence(
    report_slug="__unknown__",
    generator="standard_v1",
    q3_enabled=False,
    hero_value_source="ai",
    required_hero_fields=(),
    relevant_houses=(), relevant_planets=(), required_context_keys=(),
    components_enabled={},
    gemstone_policy="disabled",
    disclaimer_type="general",
)


def get_product_intelligence(report_slug: Optional[str]) -> ProductIntelligence:
    """Never raises, never returns None -- an unrecognized/legacy slug
    (or one genuinely absent from REGISTRY) safely resolves to a
    q3_enabled=False default, so a lookup miss can never itself become
    a new report-generation failure mode. This is the ONLY function
    tasks.py/love_premium_task.py should call; never index REGISTRY
    directly."""
    if not report_slug:
        return _DEFAULT_LEGACY
    return REGISTRY.get(report_slug, _DEFAULT_LEGACY)
