# modules/intents/intent_contract.py

"""
intent_contract.py -- Intent-Based Micro Reports, foundation phase.

The schema (plain frozen dataclasses + controlled vocabularies) for the
CODE-BASED Intent Contract registry and the bilingual customer-question
catalog. Deliberately a plain Python module, mirroring the precedent of
modules/payments/report_product_intelligence.py: product DESIGN intent is
versioned with the code that consumes it, not stored in a database table.

FOUNDATION ONLY. Nothing here is wired to payment, orders, the dispatcher,
Luna, evidence collection or PDF generation. It imports nothing from Flask,
SQLAlchemy, OpenAI or any other module of this codebase, so it can never
change the behavior of the 25 frozen paid reports.

TWO LAYERS, ONE SELECTION
  * IntentContract -- the CORE backend intent (12 of them). Defines WHAT
    astrology evidence a family of questions needs and WHAT the report must
    output. Shared by many customer questions.
  * IntentQuestion -- a customer-facing question (bilingual) that maps to
    exactly one core intent. Wording differs; the analysis is shared.
  * IntentSelection -- what a future runtime carries: the resolved intent
    AND the exact question the customer bought (question_key survives the
    mapping), so the Prompt Composer can answer that exact framing.

ASTROLOGY RULES ARE NOT INVENTED HERE
  Every astrology block (houses, planets, yogas, Dasha, transit, dual) is
  explicit about its approval state via RuleStatus. Until an expert approves
  a mapping it stays PENDING; the only numbers present are SEED REFERENCES
  copied from the closest existing (already shipped) report and verified
  against that report's own registry entry by the tests -- never a new
  claim. Seeds are NOT approved intent mappings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Product invariants
# ---------------------------------------------------------------------------
# Every focused micro report costs Rs 51 (locked product decision). Reusing
# the existing "reports51" Google Play strategy later needs NO new Play
# product: config/google_play_report_products.py already maps any Rs 51
# registry product to it. Deliberately NOT added to config/pricing.py
# (PRODUCT_PRICES is the frozen 25-report catalog and several frozen tests
# pin its exact size).
INTENT_REPORT_PRICE_RUPEES = 51
INTENT_REPORT_CURRENCY = "INR"

PERSON_SINGLE = "single"
PERSON_DUAL = "dual"
PERSON_MODES = (PERSON_SINGLE, PERSON_DUAL)

# Reserved generator keys (NOT registered anywhere yet -- the dispatcher's
# KNOWN_GENERATORS is untouched in this phase).
GENERATOR_KEY_BY_PERSON_MODE = {
    PERSON_SINGLE: "intent_single_v1",
    PERSON_DUAL: "intent_dual_v1",
}

# ---------------------------------------------------------------------------
# Categories (shared by intents and customer questions)
# ---------------------------------------------------------------------------
CATEGORY_CAREER = "career"
CATEGORY_MONEY_BUSINESS = "money_business"
CATEGORY_MARRIAGE = "marriage"
CATEGORY_RELATIONSHIP = "relationship"
CATEGORY_FOREIGN = "foreign"
CATEGORY_EDUCATION = "education"
CATEGORY_PROPERTY = "property"
CATEGORY_LIFE = "life"


@dataclass(frozen=True)
class LocalizedText:
    en: str
    hi: str

    def __post_init__(self):
        for language, value in (("en", self.en), ("hi", self.hi)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"LocalizedText.{language} must be a non-empty string")

    def get(self, language: str) -> str:
        """'hi' for Hindi (incl. 'hi-IN'), otherwise English."""
        return self.hi if str(language or "").strip().lower().startswith("hi") else self.en


@dataclass(frozen=True)
class CategoryInfo:
    category_id: str
    label: LocalizedText


CATEGORIES: Tuple[CategoryInfo, ...] = (
    CategoryInfo(CATEGORY_CAREER, LocalizedText("Career & Job", "करियर और नौकरी")),
    CategoryInfo(CATEGORY_MONEY_BUSINESS, LocalizedText("Money & Business", "पैसा और बिज़नेस")),
    CategoryInfo(CATEGORY_MARRIAGE, LocalizedText("Marriage", "शादी")),
    CategoryInfo(CATEGORY_RELATIONSHIP, LocalizedText("Relationship (Two People)", "रिश्ता (दो लोगों का)")),
    CategoryInfo(CATEGORY_FOREIGN, LocalizedText("Foreign & Relocation", "विदेश और शिफ्टिंग")),
    CategoryInfo(CATEGORY_EDUCATION, LocalizedText("Education", "शिक्षा")),
    CategoryInfo(CATEGORY_PROPERTY, LocalizedText("Property & Home", "प्रॉपर्टी और घर")),
    CategoryInfo(CATEGORY_LIFE, LocalizedText("Life Direction", "जीवन की दिशा")),
)
CATEGORY_IDS = tuple(info.category_id for info in CATEGORIES)

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------
class RuleStatus:
    """Approval state of an astrology rule block."""
    PENDING = "pending_expert_approval"          # nothing approved yet -- do not build on it
    NOT_APPLICABLE = "not_applicable"            # the block genuinely does not apply to this intent


class Readiness:
    """How far an intent is from being sellable."""
    CONTRACT_DRAFT = "contract_draft"                        # identity/output contract drafted; evidence rules pending
    CONDITIONAL_NOT_READY = "conditional_not_ready"          # additionally weak evidence / differentiation -- decide later


class Activation:
    """Nothing is purchasable in the foundation phase."""
    INACTIVE = "inactive"


class EvidencePackStatus:
    NOT_IMPLEMENTED = "packs_not_implemented"


class QuestionStatus:
    WORDING_READY = "wording_ready"                # bilingual wording drafted and reviewable
    HELD_CONDITIONAL = "held_conditional"          # belongs to a conditional intent -- do not surface yet


class DisclaimerStatus:
    EXISTING = "existing_reuse"                    # DISCLAIMER_TEXT already has this type
    PENDING_TEXT = "pending_new_text"              # a new type whose EN/HI text still needs approval


# The four approved future evidence packs (NOT implemented in this phase).
PACK_NATAL = "NatalFactsPack"
PACK_DASHA = "DashaWindowPack"
PACK_TRANSIT = "TransitWindowPack"
PACK_DUAL = "DualCompatibilityPack"
EVIDENCE_PACKS = (PACK_NATAL, PACK_DASHA, PACK_TRANSIT, PACK_DUAL)


class AnswerMode:
    """HOW the Prompt Composer should frame the answer to the exact purchased
    question. Framing only -- it carries no astrology rule."""
    BEST_WINDOWS = "best_windows"          # rank the supportive upcoming periods
    WHEN_BEGINS = "when_begins"            # when things begin to look favourable
    DELAY_REASON = "delay_reason"          # explain what may be holding it back, then when it may ease
    CURRENT_PERIOD = "current_period"      # assess the present period
    EASING_PERIOD = "easing_period"        # when pressure / slowness may reduce
    CARE_PERIODS = "care_periods"          # periods that need extra care
    OVERVIEW = "overview"                  # a non-timing overview
    GUIDANCE = "guidance"                  # practical guidance


ANSWER_MODES = (
    AnswerMode.BEST_WINDOWS, AnswerMode.WHEN_BEGINS, AnswerMode.DELAY_REASON, AnswerMode.CURRENT_PERIOD,
    AnswerMode.EASING_PERIOD, AnswerMode.CARE_PERIODS, AnswerMode.OVERVIEW, AnswerMode.GUIDANCE,
)


class ForbiddenClaim:
    """Codes for claims a report of the intent must never make (the later
    output validator and the Prompt Composer read these)."""
    EXACT_EVENT_DATE = "exact_event_date_or_age"
    GUARANTEED_OUTCOME = "guaranteed_outcome"
    JOB_LOSS = "job_loss_or_termination_prediction"
    INVESTMENT_RETURN = "investment_return_or_financial_advice"
    LEGAL_OUTCOME = "legal_outcome"
    MEDICAL_FERTILITY = "medical_pregnancy_or_fertility_claim"
    EXAM_RESULT = "exam_or_selection_result"
    VISA_IMMIGRATION = "visa_or_immigration_outcome"
    THIRD_PARTY_MIND = "third_party_thoughts_feelings_or_fidelity"
    BREAKUP_PREDICTION = "breakup_or_partner_leaving_prediction"
    SPOUSE_DETAILS = "spouse_appearance_or_identity"
    INTERNAL_TERMS = "internal_engine_terms_or_field_names"


BASE_FORBIDDEN_CLAIMS = (
    ForbiddenClaim.EXACT_EVENT_DATE,
    ForbiddenClaim.GUARANTEED_OUTCOME,
    ForbiddenClaim.MEDICAL_FERTILITY,
    ForbiddenClaim.LEGAL_OUTCOME,
    ForbiddenClaim.INTERNAL_TERMS,
)

_SLUG = re.compile(r"[a-z][a-z0-9_]*")


def _require_slug(value: str, what: str) -> None:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise ValueError(f"{what} must be a lower_snake_case slug, got {value!r}")


# ---------------------------------------------------------------------------
# Astrology contract blocks
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SeedReference:
    """SEED, NOT AN APPROVED MAPPING. The houses/planets the closest EXISTING
    report already uses, copied verbatim so a later expert review has a
    starting point. The tests verify these equal that report's own
    report_product_intelligence entry, so a seed can never be a new claim."""
    report_slug: str
    houses: Tuple[int, ...] = ()
    planets: Tuple[str, ...] = ()


@dataclass(frozen=True)
class HouseSpec:
    """Primary / supporting / pressure houses. Empty + PENDING until an
    expert approves the split for this intent."""
    primary: Tuple[int, ...] = ()
    supporting: Tuple[int, ...] = ()
    pressure: Tuple[int, ...] = ()
    status: str = RuleStatus.PENDING
    seed: Optional[SeedReference] = None

    def __post_init__(self):
        if self.status == RuleStatus.PENDING and (self.primary or self.supporting or self.pressure):
            raise ValueError("a PENDING HouseSpec must not carry approved houses")
        for house in self.primary + self.supporting + self.pressure:
            if not isinstance(house, int) or not 1 <= house <= 12:
                raise ValueError(f"invalid house number {house!r}")


@dataclass(frozen=True)
class RulePlaceholder:
    """An astrology rule block (planets / yogas & specials / Dasha / transit /
    dual) that is NOT designed yet. `items` stays empty until approved."""
    status: str = RuleStatus.PENDING
    items: Tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self):
        if self.status == RuleStatus.PENDING and self.items:
            raise ValueError("a PENDING rule placeholder must not carry approved items")


@dataclass(frozen=True)
class DualRule:
    """Dual-person requirements. requires_full_birth_data mirrors the existing
    paid relationship order contract (partner name/dob/tob/pob/lat/lng, valid
    non-(0,0) coordinates). The evidence rules themselves stay pending."""
    requires_full_birth_data: bool = True
    status: str = RuleStatus.PENDING
    note: str = ""


@dataclass(frozen=True)
class SectionSpec:
    """One ordered section of the focused PDF. `instruction` is PRIVATE (for the
    Prompt Composer, never printed to the customer)."""
    key: str
    title: LocalizedText
    instruction: str

    def __post_init__(self):
        _require_slug(self.key, "section key")
        if not isinstance(self.instruction, str) or not self.instruction.strip():
            raise ValueError(f"section {self.key!r} needs a private instruction")


# ---------------------------------------------------------------------------
# The core intent contract
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IntentContract:
    # identity
    intent_slug: str
    category: str
    person_mode: str
    # bilingual identity
    canonical_question: LocalizedText
    # astrology contract (nothing approved yet -- see RuleStatus)
    houses: HouseSpec
    planets: RulePlaceholder
    yogas_and_specials: RulePlaceholder
    dasha_rule: RulePlaceholder
    transit_rule: RulePlaceholder
    dual_rule: Optional[DualRule]
    required_evidence_packs: Tuple[str, ...]
    evidence_status: str
    # output contract
    sections: Tuple[SectionSpec, ...]
    disclaimer_type: str
    disclaimer_status: str
    forbidden_claims: Tuple[str, ...]
    upsell_slug: Optional[str]
    # status
    readiness: str
    activation: str = Activation.INACTIVE
    price_rupees: int = INTENT_REPORT_PRICE_RUPEES
    notes: str = ""

    def __post_init__(self):
        _require_slug(self.intent_slug, "intent_slug")
        if self.category not in CATEGORY_IDS:
            raise ValueError(f"unknown category {self.category!r}")
        if self.person_mode not in PERSON_MODES:
            raise ValueError(f"unknown person_mode {self.person_mode!r}")
        if self.price_rupees != INTENT_REPORT_PRICE_RUPEES:
            raise ValueError("every focused intent report costs Rs 51")
        if (self.person_mode == PERSON_DUAL) != (self.dual_rule is not None):
            raise ValueError("a dual_rule is required for (and only for) DUAL intents")
        if (self.person_mode == PERSON_DUAL) != (PACK_DUAL in self.required_evidence_packs):
            raise ValueError("DualCompatibilityPack is required for (and only for) DUAL intents")
        for pack in self.required_evidence_packs:
            if pack not in EVIDENCE_PACKS:
                raise ValueError(f"unknown evidence pack {pack!r}")
        keys = [section.key for section in self.sections]
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("sections must be non-empty with unique keys")
        if self.readiness not in (Readiness.CONTRACT_DRAFT, Readiness.CONDITIONAL_NOT_READY):
            raise ValueError(f"unknown readiness {self.readiness!r}")
        if self.activation != Activation.INACTIVE:
            raise ValueError("no intent may be active in the foundation phase")
        if not set(BASE_FORBIDDEN_CLAIMS) <= set(self.forbidden_claims):
            raise ValueError("every intent must carry the base forbidden claims")

    @property
    def requires_partner(self) -> bool:
        return self.person_mode == PERSON_DUAL

    @property
    def generator_key(self) -> str:
        """The generator key reserved for this person mode (not registered yet)."""
        return GENERATOR_KEY_BY_PERSON_MODE[self.person_mode]


# ---------------------------------------------------------------------------
# Customer questions and the runtime selection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IntentQuestion:
    question_key: str
    intent_slug: str
    category: str
    person_mode: str
    question: LocalizedText
    answer_mode: str
    lens: str = ""
    status: str = QuestionStatus.WORDING_READY

    def __post_init__(self):
        _require_slug(self.question_key, "question_key")
        _require_slug(self.intent_slug, "intent_slug")
        if self.category not in CATEGORY_IDS:
            raise ValueError(f"unknown category {self.category!r}")
        if self.person_mode not in PERSON_MODES:
            raise ValueError(f"unknown person_mode {self.person_mode!r}")
        if self.answer_mode not in ANSWER_MODES:
            raise ValueError(f"unknown answer_mode {self.answer_mode!r}")
        if self.lens:
            _require_slug(self.lens, "lens")
        if self.status not in (QuestionStatus.WORDING_READY, QuestionStatus.HELD_CONDITIONAL):
            raise ValueError(f"unknown question status {self.status!r}")

    @property
    def question_en(self) -> str:
        return self.question.en

    @property
    def question_hi(self) -> str:
        return self.question.hi

    @property
    def requires_partner(self) -> bool:
        return self.person_mode == PERSON_DUAL


@dataclass(frozen=True)
class IntentSelection:
    """What a future runtime carries after the customer picks a question. The
    question_key is NEVER dropped when it is mapped to its core intent: the
    evidence layer keys off `intent_slug`; the Prompt Composer answers
    `display_question` using `answer_mode` / `lens`."""
    intent_slug: str
    question_key: str
    category: str
    person_mode: str
    display_question: LocalizedText
    answer_mode: str
    lens: str
    price_rupees: int = INTENT_REPORT_PRICE_RUPEES

    @property
    def requires_partner(self) -> bool:
        return self.person_mode == PERSON_DUAL

    def display(self, language: str) -> str:
        return self.display_question.get(language)
