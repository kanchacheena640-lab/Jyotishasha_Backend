# modules/intents/intent_registry.py

"""
intent_registry.py -- Intent-Based Micro Reports, foundation phase.

The CODE-BASED registry of the 12 approved CORE intent contracts (no DB
table). 10 are SINGLE person, 2 are DUAL person. Every one is INACTIVE and
nothing here is purchasable; wiring to the order/payment/dispatcher flow,
evidence packs, Luna and PDF generation are later phases.

WHAT IS AND IS NOT DECIDED HERE
  Decided (product/output design): identity, bilingual canonical question,
  ordered bilingual sections with private composer instructions, the
  disclaimer type, forbidden claims, the upsell target, the future evidence
  packs each intent will need, and the Rs 51 price.

  NOT decided (kept explicitly PENDING -- see RuleStatus): the astrology
  mapping. Primary/supporting/pressure houses, planets, yoga/special
  allowlists and the Dasha / transit / dual rules are all pending expert
  approval. The only astrology numbers present are `HouseSpec.seed`
  references copied from the closest EXISTING report; they are not approved
  intent mappings and the tests verify they equal that report's registry
  entry.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Dict, Optional, Tuple

from modules.intents.intent_contract import (
    BASE_FORBIDDEN_CLAIMS,
    CATEGORY_CAREER,
    CATEGORY_EDUCATION,
    CATEGORY_FOREIGN,
    CATEGORY_LIFE,
    CATEGORY_MARRIAGE,
    CATEGORY_MONEY_BUSINESS,
    CATEGORY_PROPERTY,
    CATEGORY_RELATIONSHIP,
    PACK_DASHA,
    PACK_DUAL,
    PACK_NATAL,
    PACK_TRANSIT,
    PERSON_DUAL,
    PERSON_SINGLE,
    Activation,
    DisclaimerStatus,
    DualRule,
    EvidencePackStatus,
    ForbiddenClaim as FC,
    HouseSpec,
    IntentContract,
    LocalizedText,
    Readiness,
    RulePlaceholder,
    RuleStatus,
    SectionSpec,
    SeedReference,
)


class UnknownIntentError(KeyError):
    """Raised for an intent_slug that is not in the registry."""


# ---------------------------------------------------------------------------
# Section library -- reusable bilingual sections (private instruction is for
# the Prompt Composer only and is never printed to the customer).
# ---------------------------------------------------------------------------
def _section(key: str, en: str, hi: str, instruction: str) -> SectionSpec:
    return SectionSpec(key=key, title=LocalizedText(en, hi), instruction=instruction)


_LIBRARY: Dict[str, SectionSpec] = {s.key: s for s in (
    _section(
        "your_question", "Your Question and Short Answer", "आपका सवाल और सीधा जवाब",
        "Restate the exact purchased question (the selection's display question), then give a direct, hedged "
        "answer in two or three sentences. Never guarantee an outcome and never give an exact date or age."),
    _section(
        "supportive_periods", "Your Supportive Periods", "आपके अनुकूल समय",
        "Present only the periods supplied in the deterministic timeline evidence, strongest first. Never add, "
        "shift or invent a date. Describe strength in plain words, never as a score or percentage."),
    _section(
        "why_chart_shows", "Why Your Chart Shows This", "आपका चार्ट ऐसा क्यों दिखाता है",
        "Explain each supplied evidence item in plain astrology language. Never state a fact that was not "
        "supplied and never repeat internal field names."),
    _section(
        "holding_back_factors", "What May Be Holding Things Back", "क्या चीज़ें रोक रही हो सकती हैं",
        "Describe only the supplied delay or pressure factors, calmly and without fear, and say when the "
        "supplied timeline shows them easing. No doom language."),
    _section(
        "patience_periods", "Periods That Need Patience", "धैर्य रखने वाले समय",
        "Name only the supplied slower or cautious periods, framed as periods for preparation, never as "
        "predicted failure."),
    _section(
        "practical_guidance", "What You Can Do", "आप क्या कर सकते हैं",
        "Give practical, non-astrological actions the customer controls, tied to the supplied periods. "
        "No guarantees, no financial, legal or medical advice."),
    _section(
        "current_period_view", "Where You Stand Right Now", "अभी आप कहाँ हैं",
        "Assess the current period using only the supplied current-period evidence, then contrast it with "
        "the next supplied period."),
    _section(
        "pressure_relief_periods", "When Pressure May Ease", "दबाव कब कम हो सकता है",
        "Describe only the supplied periods in which financial pressure may reduce. This is not financial, "
        "investment or debt advice and must not promise any amount or result."),
    _section(
        "start_and_growth_periods", "Periods for Starting and Growing", "शुरुआत और बढ़त के समय",
        "Separate the supplied periods that suit starting from those that suit growing or expanding. No "
        "profit, revenue or success claims."),
    _section(
        "purpose_lens", "Your Purpose: Work, Study or Settling", "आपका उद्देश्य: काम, पढ़ाई या बसना",
        "Cover the purpose implied by the selected question (its lens) using only supplied evidence. Never "
        "predict a visa, approval or immigration outcome."),
    _section(
        "key_turning_points", "Your Turning Points", "आपके जीवन के turning points",
        "List the supplied turning-point periods chronologically, each with a one-line plain meaning. "
        "Dates only as supplied."),
    _section(
        "areas_to_watch", "Areas That Need Attention", "जिन क्षेत्रों पर ध्यान चाहिए",
        "Name only the life areas the supplied evidence marks as activated in those periods, framed as "
        "awareness, not warning of harm."),
    _section(
        "natural_strengths", "Your Natural Strengths", "आपकी प्राकृतिक ताकतें",
        "Describe only strengths supported by the supplied natal evidence."),
    _section(
        "life_direction", "Your Life Direction", "आपकी जीवन की दिशा",
        "Describe directions the supplied natal evidence supports, as tendencies and never as instructions "
        "or predictions."),
    _section(
        "both_charts_overview", "Your Two Charts at a Glance", "आप दोनों के चार्ट एक नज़र में",
        "Summarise each person's supplied facts with first names, never swapping the two people, and never "
        "revealing how complete the partner's birth data is."),
    _section(
        "compatibility_evidence", "What Your Compatibility Shows", "आपकी compatibility क्या दिखाती है",
        "Explain the supplied compatibility evidence in plain language. No percentages, no engine terms, no "
        "status labels."),
    _section(
        "marriage_readiness", "Readiness for Marriage", "शादी के लिए तैयारी",
        "Describe readiness indicators only from supplied evidence. Never predict a marriage date, age or "
        "outcome and never speak for either person's intentions."),
    _section(
        "shared_strengths", "Where You Fit Well", "जहाँ आपका तालमेल अच्छा है",
        "Describe only strengths supported by the supplied compatibility and chart evidence."),
    _section(
        "friction_points", "Where You May Clash", "जहाँ टकराव हो सकता है",
        "Describe supplied friction areas constructively. Never infer thoughts, feelings, fidelity or "
        "intentions, and never predict a breakup."),
    _section(
        "care_periods", "Periods That Need Extra Care", "जब ज़्यादा ध्यान चाहिए",
        "Name only supplied periods that need extra care in the relationship, framed as attention, not "
        "as predicted trouble."),
    _section(
        "practical_guidance_together", "What You Can Do Together", "आप दोनों साथ मिलकर क्या कर सकते हैं",
        "Give practical shared actions. No guarantees and no claims about either person's private feelings."),
)}


def _sections(*keys: str) -> Tuple[SectionSpec, ...]:
    return tuple(_LIBRARY[key] for key in keys)


# ---------------------------------------------------------------------------
# Shared blocks
# ---------------------------------------------------------------------------
_PENDING = RulePlaceholder(status=RuleStatus.PENDING)
_NOT_APPLICABLE = RulePlaceholder(status=RuleStatus.NOT_APPLICABLE)
_TIMING_PACKS = (PACK_NATAL, PACK_DASHA, PACK_TRANSIT)
_DUAL_PACKS = (PACK_NATAL, PACK_DUAL)

# Disclaimer types. EXISTING = already in modules/payments/report_q3_batch1.py's
# DISCLAIMER_TEXT (reused unchanged); PENDING_TEXT = a NEW type whose EN/HI
# text still has to be written and approved (nothing is added to that frozen
# module in this phase).
_TIMING_DISCLAIMER = "intent_timing_non_certainty"
_EDUCATION_DISCLAIMER = "intent_education_non_certainty"
_FOREIGN_DISCLAIMER = "intent_foreign_non_certainty"
_LIFE_DISCLAIMER = "intent_life_guidance_non_certainty"

_DUAL_RULE = DualRule(
    requires_full_birth_data=True,
    note="Dual evidence rules are not designed yet. Orders must carry both people's full birth details "
         "(the existing relationship order contract, including the non-(0,0) coordinate guard).",
)


def _houses(seed_slug: Optional[str] = None, houses: Tuple[int, ...] = (), planets: Tuple[str, ...] = ()) -> HouseSpec:
    """Houses are PENDING for every intent; a seed is only a reference to what the closest EXISTING
    report already uses (verified against that report's registry entry by the tests)."""
    seed = SeedReference(report_slug=seed_slug, houses=houses, planets=planets) if seed_slug else None
    return HouseSpec(status=RuleStatus.PENDING, seed=seed)


def _contract(
    slug: str, category: str, person_mode: str, question_en: str, question_hi: str, *,
    houses: HouseSpec, packs: Tuple[str, ...], sections: Tuple[SectionSpec, ...],
    disclaimer_type: str, disclaimer_status: str, extra_forbidden: Tuple[str, ...] = (),
    upsell_slug: Optional[str], readiness: str = Readiness.CONTRACT_DRAFT, notes: str = "",
) -> IntentContract:
    dual = person_mode == PERSON_DUAL
    return IntentContract(
        intent_slug=slug, category=category, person_mode=person_mode,
        canonical_question=LocalizedText(question_en, question_hi),
        houses=houses,
        planets=_PENDING,
        yogas_and_specials=_PENDING,
        dasha_rule=_PENDING if PACK_DASHA in packs or dual else _NOT_APPLICABLE,
        transit_rule=_PENDING if PACK_TRANSIT in packs or dual else _NOT_APPLICABLE,
        dual_rule=_DUAL_RULE if dual else None,
        required_evidence_packs=packs,
        evidence_status=EvidencePackStatus.NOT_IMPLEMENTED,
        sections=sections,
        disclaimer_type=disclaimer_type, disclaimer_status=disclaimer_status,
        forbidden_claims=BASE_FORBIDDEN_CLAIMS + tuple(c for c in extra_forbidden if c not in BASE_FORBIDDEN_CLAIMS),
        upsell_slug=upsell_slug,
        readiness=readiness, activation=Activation.INACTIVE,
        notes=notes,
    )


_CONTRACTS: Tuple[IntentContract, ...] = (
    # ----------------------------- CAREER -----------------------------
    _contract(
        "career_growth_timing", CATEGORY_CAREER, PERSON_SINGLE,
        "When is my career likely to move forward, and what may be holding it back?",
        "मेरा करियर कब आगे बढ़ सकता है, और क्या चीज़ें इसे रोक रही हो सकती हैं?",
        houses=_houses("career_report", (2, 6, 10, 11), ("Sun", "Saturn", "Mercury", "Jupiter", "Mars")),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "supportive_periods", "why_chart_shows", "holding_back_factors",
                           "patience_periods", "practical_guidance"),
        disclaimer_type=_TIMING_DISCLAIMER, disclaimer_status=DisclaimerStatus.PENDING_TEXT,
        extra_forbidden=(FC.JOB_LOSS,),
        upsell_slug="career_report",
        notes="Absorbs promotion, career improvement, delay, salary growth and recognition questions.",
    ),
    _contract(
        "job_change_timing", CATEGORY_CAREER, PERSON_SINGLE,
        "Is a job change favourable for me, and in which periods?",
        "क्या मेरे लिए नौकरी बदलना अनुकूल है, और कौन-से समय में?",
        houses=_houses("career_report", (2, 6, 10, 11), ("Sun", "Saturn", "Mercury", "Jupiter", "Mars")),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "current_period_view", "supportive_periods", "why_chart_shows",
                           "patience_periods", "practical_guidance"),
        disclaimer_type=_TIMING_DISCLAIMER, disclaimer_status=DisclaimerStatus.PENDING_TEXT,
        extra_forbidden=(FC.JOB_LOSS,),
        upsell_slug="career_report",
        notes="Absorbs new-job, job-search and job-gap questions. Must never tell a customer to quit.",
    ),
    # ------------------------- MONEY / BUSINESS -------------------------
    _contract(
        "money_improvement_timing", CATEGORY_MONEY_BUSINESS, PERSON_SINGLE,
        "When may my income and financial situation improve?",
        "मेरी आमदनी और आर्थिक स्थिति कब बेहतर हो सकती है?",
        houses=_houses("financial_report", (2, 5, 8, 11), ("Jupiter", "Venus", "Mercury", "Saturn")),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "supportive_periods", "why_chart_shows", "pressure_relief_periods",
                           "patience_periods", "practical_guidance"),
        disclaimer_type="financial_advice_non_certainty_mandatory", disclaimer_status=DisclaimerStatus.EXISTING,
        extra_forbidden=(FC.INVESTMENT_RETURN,),
        upsell_slug="financial_report",
        notes="Absorbs income-increase, pressure-easing and debt-pressure questions. Not financial advice.",
    ),
    _contract(
        "business_timing", CATEGORY_MONEY_BUSINESS, PERSON_SINGLE,
        "Which periods are most supportive for starting or growing a business?",
        "बिज़नेस शुरू करने या बढ़ाने के लिए कौन-से समय सबसे अनुकूल हैं?",
        houses=_houses("business_report", (2, 7, 10, 11), ("Mercury", "Jupiter", "Saturn", "Mars")),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "start_and_growth_periods", "why_chart_shows", "patience_periods",
                           "practical_guidance"),
        disclaimer_type="business_outcome_non_certainty_mandatory", disclaimer_status=DisclaimerStatus.EXISTING,
        extra_forbidden=(FC.INVESTMENT_RETURN,),
        upsell_slug="business_report",
    ),
    # ----------------------------- MARRIAGE -----------------------------
    _contract(
        "marriage_timing", CATEGORY_MARRIAGE, PERSON_SINGLE,
        "When are my strongest periods for marriage?",
        "मेरी शादी के लिए सबसे मजबूत समय कब है?",
        houses=_houses("marriage_report", (7,), ("Venus", "Jupiter", "Mars", "Saturn", "Rahu")),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "supportive_periods", "why_chart_shows", "holding_back_factors",
                           "patience_periods", "practical_guidance"),
        disclaimer_type=_TIMING_DISCLAIMER, disclaimer_status=DisclaimerStatus.PENDING_TEXT,
        extra_forbidden=(FC.SPOUSE_DETAILS,),
        upsell_slug="marriage_report",
        notes="Windows only -- no marriage age or date (existing marriage_report policy). Whether the "
              "customer's gender is needed for significators is an open expert decision; no gender field exists.",
    ),
    # ------------------------ RELATIONSHIP (DUAL) ------------------------
    _contract(
        "relationship_marriage_potential", CATEGORY_RELATIONSHIP, PERSON_DUAL,
        "Do our two charts support this relationship growing into a lasting marriage?",
        "क्या हम दोनों के चार्ट इस रिश्ते के लंबी शादी में बदलने का साथ देते हैं?",
        houses=_houses("love_marriage_report", (5, 7), ("Venus", "Mars", "Jupiter")),
        packs=_DUAL_PACKS,
        sections=_sections("your_question", "both_charts_overview", "compatibility_evidence", "marriage_readiness",
                           "friction_points", "practical_guidance_together"),
        disclaimer_type="relationship_future_non_certainty_mandatory", disclaimer_status=DisclaimerStatus.EXISTING,
        extra_forbidden=(FC.THIRD_PARTY_MIND, FC.BREAKUP_PREDICTION, FC.SPOUSE_DETAILS),
        upsell_slug="relationship_future_report",
        notes="Absorbs long-term and kundali-match compatibility. The Rs 199 relationship_future_report is the "
              "comprehensive upsell; no percentages (the free love tools show them; premium policy forbids them).",
    ),
    _contract(
        "relationship_strengths_and_challenges", CATEGORY_RELATIONSHIP, PERSON_DUAL,
        "Where do we fit well, and where are we likely to clash?",
        "हम दोनों का तालमेल कहाँ अच्छा है, और टकराव कहाँ हो सकता है?",
        houses=_houses("love_relationship_report", (5, 7), ("Venus", "Moon", "Mars")),
        packs=_DUAL_PACKS,
        sections=_sections("your_question", "both_charts_overview", "shared_strengths", "friction_points",
                           "care_periods", "practical_guidance_together"),
        disclaimer_type="relationship_future_non_certainty_mandatory", disclaimer_status=DisclaimerStatus.EXISTING,
        extra_forbidden=(FC.THIRD_PARTY_MIND, FC.BREAKUP_PREDICTION),
        upsell_slug="relationship_future_report",
        notes="Heavy evidence overlap with relationship_marriage_potential; launch after it.",
    ),
    # ----------------------------- FOREIGN -----------------------------
    _contract(
        "foreign_move_timing", CATEGORY_FOREIGN, PERSON_SINGLE,
        "Which periods are supportive for going or settling abroad?",
        "विदेश जाने या वहाँ बसने के लिए कौन-से समय अनुकूल हैं?",
        houses=_houses("foreign_travel_report", (9, 12), ("Rahu", "Moon", "Jupiter")),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "supportive_periods", "purpose_lens", "why_chart_shows",
                           "holding_back_factors", "patience_periods", "practical_guidance"),
        disclaimer_type=_FOREIGN_DISCLAIMER, disclaimer_status=DisclaimerStatus.PENDING_TEXT,
        extra_forbidden=(FC.VISA_IMMIGRATION,),
        upsell_slug="foreign_travel_report",
        notes="Absorbs work, study, settlement and relocation lenses (the question's lens selects the framing).",
    ),
    # ---------------------------- EDUCATION ----------------------------
    _contract(
        "study_exam_timing", CATEGORY_EDUCATION, PERSON_SINGLE,
        "Which periods are strongest for my studies, higher education and exam preparation?",
        "मेरी पढ़ाई, उच्च शिक्षा और परीक्षा की तैयारी के लिए कौन-से समय सबसे मजबूत हैं?",
        houses=_houses(),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "supportive_periods", "why_chart_shows", "patience_periods",
                           "practical_guidance"),
        disclaimer_type=_EDUCATION_DISCLAIMER, disclaimer_status=DisclaimerStatus.PENDING_TEXT,
        extra_forbidden=(FC.EXAM_RESULT,),
        upsell_slug=None,
        notes="No existing report or houses to seed from. Adult customers only until a minors/consent policy "
              "exists. Preparation-favourable periods only, never a result.",
    ),
    # ----------------------------- PROPERTY -----------------------------
    _contract(
        "property_timing", CATEGORY_PROPERTY, PERSON_SINGLE,
        "When is a good time to buy property or a home?",
        "प्रॉपर्टी या घर खरीदने का अच्छा समय कब है?",
        houses=_houses("property_report", (4,), ("Mars", "Saturn")),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "supportive_periods", "why_chart_shows", "holding_back_factors",
                           "patience_periods", "practical_guidance"),
        disclaimer_type="property_non_certainty_mandatory", disclaimer_status=DisclaimerStatus.EXISTING,
        extra_forbidden=(FC.INVESTMENT_RETURN,),
        upsell_slug="property_report",
    ),
    # -------------------------------- LIFE --------------------------------
    _contract(
        "life_turning_points", CATEGORY_LIFE, PERSON_SINGLE,
        "What are the major turning-point periods in my coming years?",
        "आने वाले सालों में मेरे जीवन के बड़े turning-point वाले समय कौन-से हैं?",
        houses=_houses(),
        packs=_TIMING_PACKS,
        sections=_sections("your_question", "key_turning_points", "why_chart_shows", "areas_to_watch",
                           "practical_guidance"),
        disclaimer_type=_LIFE_DISCLAIMER, disclaimer_status=DisclaimerStatus.PENDING_TEXT,
        upsell_slug="sadhesati_report",
        notes="Mostly a reshaping of dates the engine already computes (Dasha changes, Sade Sati, ingresses); "
              "the least judgement-heavy intent -- the recommended pilot.",
    ),
    _contract(
        "life_direction_and_strengths", CATEGORY_LIFE, PERSON_SINGLE,
        "What are my natural strengths and the life direction that suits me best?",
        "मेरी प्राकृतिक ताकतें क्या हैं और मेरे लिए जीवन की कौन-सी दिशा सबसे सही है?",
        houses=_houses(),
        packs=(PACK_NATAL,),
        sections=_sections("your_question", "natural_strengths", "life_direction", "why_chart_shows",
                           "practical_guidance"),
        disclaimer_type=_LIFE_DISCLAIMER, disclaimer_status=DisclaimerStatus.PENDING_TEXT,
        upsell_slug=None,
        notes="Natal-only (no structured dignity/karaka data, no Navamsa); modules/focused_reports/life_evidence.py "
              "synthesizes tendencies from existing house/lord and placement facts only, deliberately never a "
              "numeric strength ranking. Implemented and part of the 61-question catalog like every other intent.",
    ),
)

INTENT_REGISTRY = MappingProxyType({contract.intent_slug: contract for contract in _CONTRACTS})
INTENT_SLUGS: Tuple[str, ...] = tuple(contract.intent_slug for contract in _CONTRACTS)


def get_intent_contract(intent_slug: str) -> IntentContract:
    """The contract for a core intent. Raises UnknownIntentError for anything else."""
    try:
        return INTENT_REGISTRY[intent_slug]
    except (KeyError, TypeError):
        raise UnknownIntentError(intent_slug) from None


def list_intents(category: Optional[str] = None) -> Tuple[IntentContract, ...]:
    return tuple(c for c in _CONTRACTS if category is None or c.category == category)


def is_purchasable(intent_slug: str) -> bool:
    """False for every intent in the foundation phase (nothing is wired to payment or orders)."""
    return get_intent_contract(intent_slug).activation != Activation.INACTIVE
