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

CRITICAL scope rule, updated for Q3 Batch 2: at Batch 0 every one of
the 25 entries had q3_enabled=False. Batch 1 flipped 4 -- gemstone_
consultation, saturn_transit_report, mood_mental_health_report,
divorce_possibility_report. Batch 2 flips 4 more -- marriage_report,
delay_in_marriage_report, problem_in_marriage_report, second_marriage_
report -- for a total of 8 q3_enabled=True out of 25. Each flip happens
only together with that product's own prompt rewrite for the
structured-output contract, never before. The remaining 17 products
stay q3_enabled=False and byte-for-byte unaffected; flipping any of
them on is a later batch's job. tasks.py/modules/love/love_premium_
task.py both check this flag before ever calling report_structured_
output.py's parser/validator -- a product with q3_enabled=False is
completely unaffected by anything in this file beyond being looked up.

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
    )


# Q3A audit's own per-product houses/planets/gemstone-policy/disclaimer
# rulings, condensed. See the Q3A/Q3B conversation for the full
# per-product reasoning behind each choice below -- not re-derived here.
REGISTRY: dict = {
    "sadhesati_report": _standard(
        "sadhesati_report",
        context_keys=("sadhesati_summary",),
        hero_value_source="deterministic:sadhesati_summary",
        required_hero_fields=("label", "interpretation"),
        gemstone="substone_only",
        disclaimer="none",
    ),
    "financial_report": _standard(
        "financial_report",
        houses=(2, 5, 8, 11), planets=("Jupiter", "Venus", "Mercury"),
        context_keys=("house_lord_summary", "dasha_window_summary", "gemstone_summary"),
        gemstone="optional", disclaimer="financial_business",
    ),
    "love_relationship_report": _standard(
        "love_relationship_report",
        houses=(5, 7), planets=("Venus", "Moon"),
        context_keys=("house_lord_summary", "aspect_summary", "targeted_aspect_summary"),
        hero_value_source="ai", required_hero_fields=("label", "interpretation", "evidence"),
        gemstone="optional", disclaimer="relationship_privacy",
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
    "startup_suggestion_report": _standard(
        "startup_suggestion_report",
        houses=(2, 7, 10), planets=("Mercury", "Jupiter", "Saturn"),
        context_keys=("house_lord_summary", "dasha_window_summary", "gemstone_summary"),
        gemstone="optional", disclaimer="financial_business",
    ),
    "love_marriage_report": _standard(
        "love_marriage_report",
        houses=(5, 7), planets=("Venus", "Moon"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="relationship_privacy",
    ),
    "government_job_report": _standard(
        "government_job_report",
        houses=(6, 9, 10, 11), planets=("Sun", "Saturn", "Mars", "Jupiter"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="general",
    ),
    "foreign_travel_report": _standard(
        "foreign_travel_report",
        houses=(9, 12), planets=("Rahu", "Moon", "Jupiter"),
        context_keys=("foreign_travel_summary",),
        hero_value_source="ai", required_hero_fields=("label", "interpretation", "evidence"),
        gemstone="disabled", disclaimer="general",
    ),
    "business_report": _standard(
        "business_report",
        houses=(2, 7, 10), planets=("Mercury", "Jupiter", "Saturn"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="financial_business",
    ),
    "career_report": _standard(
        "career_report",
        houses=(2, 6, 10, 11), planets=("Sun", "Saturn", "Mercury"),
        context_keys=("house_lord_summary", "dasha_window_summary", "targeted_aspect_summary"),
        gemstone="optional", disclaimer="general",
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
    "children_parenting_report": _standard(
        "children_parenting_report",
        houses=(5,), planets=("Jupiter", "Moon"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="sensitive_topic",
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
    "financial_stability_report": _standard(
        "financial_stability_report",
        houses=(2, 8, 12), planets=("Saturn",),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="financial_business",
    ),
    "jupiter_transit_report": _standard(
        "jupiter_transit_report",
        houses=(), planets=("Jupiter",),
        context_keys=("transit_facts_summary", "house_lord_summary"),
        hero_value_source="deterministic:transit_facts_summary",
        required_hero_fields=("label", "interpretation"),
        gemstone="optional", disclaimer="general",
    ),
    "lifestyle_analysis_report": _standard(
        "lifestyle_analysis_report",
        houses=(6,), planets=("Moon", "Saturn"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="general",
    ),
    "love_disappointment_report": _standard(
        "love_disappointment_report",
        houses=(5, 7), planets=("Venus", "Moon"),
        context_keys=("house_lord_summary", "aspect_summary", "targeted_aspect_summary"),
        gemstone="optional", disclaimer="relationship_privacy",
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
    "property_report": _standard(
        "property_report",
        houses=(4,), planets=("Mars", "Saturn"),
        context_keys=("house_lord_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="legal_financial",
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
    "legal_disputes_report": _standard(
        "legal_disputes_report",
        houses=(6, 7, 8, 12), planets=("Saturn", "Rahu", "Ketu", "Mars"),
        context_keys=("house_lord_summary", "targeted_aspect_summary", "dasha_window_summary"),
        gemstone="optional", disclaimer="legal_mandatory",
    ),
    "relationship_future_report": ProductIntelligence(
        report_slug="relationship_future_report",
        generator="love_premium_v1",
        q3_enabled=False,
        hero_value_source="deterministic:love_data_collector.verdict",
        required_hero_fields=("label", "interpretation"),
        relevant_houses=(), relevant_planets=(),
        required_context_keys=(),  # separate pipeline -- love_data_collector.py, not summary_blocks.py
        components_enabled={"answer_hero": True, "table": True, "gemstone": False},
        gemstone_policy="disabled",
        disclaimer_type="relationship_privacy",
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
