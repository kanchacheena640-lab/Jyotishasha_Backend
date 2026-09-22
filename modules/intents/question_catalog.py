# modules/intents/question_catalog.py

"""
question_catalog.py -- Intent-Based Micro Reports, foundation phase.

The ONE authoritative bilingual catalog of customer-facing questions. Many
questions map to the SAME core intent (wording differs, the astrology
analysis is shared -- a new backend intent is never created merely because
the wording differs). Catalog questions map to 12 core intents.

THE SELECTED QUESTION SURVIVES THE MAPPING
  resolve_selection(question_key) returns an IntentSelection carrying BOTH the
  core `intent_slug` (what the evidence layer keys off) AND the exact
  `question_key` / `display_question` / `answer_mode` / `lens` the customer
  chose (what the Prompt Composer answers). Example:

      intent_slug      = "career_growth_timing"
      question_key     = "promotion_timing"
      display_question = "Is this a good time for my promotion?" / "क्या यह समय मेरे प्रमोशन के लिए अच्छा है?"

  The mapping is a pure lookup -- it never rewrites, merges or drops the
  question.

WORDING RULES (product safety)
  Questions are hedged ("योग", "likely", "supportive periods") and never ask
  the astrology to guarantee an outcome. Nothing here asks for mind reading,
  cheating detection, medical/fertility/pregnancy claims, investment returns,
  legal or exam/job/business outcome guarantees. Hindi is natural consumer
  Hindi (common English loanwords kept in Roman script, as in the paid
  reports) and deliberately gender-neutral in its verb forms.

FOUNDATION ONLY: not wired to orders, payment, the dispatcher, Luna, evidence
packs or PDFs. Pure Python; imports no Flask/SQLAlchemy/OpenAI.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Tuple

from modules.intents.intent_contract import (
    CATEGORIES,
    CATEGORY_CAREER,
    CATEGORY_EDUCATION,
    CATEGORY_FOREIGN,
    CATEGORY_LIFE,
    CATEGORY_MARRIAGE,
    CATEGORY_MONEY_BUSINESS,
    CATEGORY_PROPERTY,
    CATEGORY_RELATIONSHIP,
    INTENT_REPORT_CURRENCY,
    INTENT_REPORT_PRICE_RUPEES,
    PERSON_DUAL,
    PERSON_SINGLE,
    AnswerMode as AM,
    IntentQuestion,
    IntentSelection,
    LocalizedText,
    QuestionStatus,
)
from modules.intents.intent_registry import INTENT_REGISTRY, INTENT_SLUGS


class UnknownQuestionError(KeyError):
    """Raised for a question_key that is not in the catalog."""


def _group(intent_slug: str, category: str, person_mode: str, rows, *, status: str = QuestionStatus.WORDING_READY):
    """rows: (question_key, question_en, question_hi, answer_mode[, lens]). The group parameters are written out
    by hand on purpose -- the tests verify them against the intent registry, so a mismatch cannot pass."""
    questions = []
    for row in rows:
        key, en, hi, mode = row[:4]
        lens = row[4] if len(row) > 4 else ""
        questions.append(IntentQuestion(
            question_key=key, intent_slug=intent_slug, category=category, person_mode=person_mode,
            question=LocalizedText(en, hi), answer_mode=mode, lens=lens, status=status,
        ))
    return questions


_QUESTION_LIST: List[IntentQuestion] = []

# ------------------------------- CAREER -------------------------------
_QUESTION_LIST += _group("career_growth_timing", CATEGORY_CAREER, PERSON_SINGLE, [
    ("promotion_timing", "Is this a good time for my promotion?",
     "क्या यह समय मेरे प्रमोशन के लिए अच्छा है?", AM.CURRENT_PERIOD, "promotion"),
    ("career_improvement_timing", "When is my career likely to start improving?",
     "मेरा करियर कब सुधरना शुरू हो सकता है?", AM.WHEN_BEGINS),
    ("career_growth_delay_reason", "Why is my career growth delayed?",
     "मेरे करियर की ग्रोथ में देरी क्यों हो रही है?", AM.DELAY_REASON),
    ("next_strong_career_period", "When is my next strong career period?",
     "मेरे करियर का अगला मजबूत समय कब है?", AM.BEST_WINDOWS),
    ("salary_growth_timing", "When can I expect a good salary increase?",
     "मेरी सैलरी में अच्छी बढ़ोतरी कब हो सकती है?", AM.WHEN_BEGINS, "salary"),
    ("work_recognition_timing", "When am I likely to get recognition at work?",
     "मुझे ऑफिस में पहचान और सम्मान कब मिल सकता है?", AM.WHEN_BEGINS, "recognition"),
    ("best_career_years", "Which coming years look best for my career growth?",
     "आने वाले कौन-से साल मेरे करियर ग्रोथ के लिए सबसे अच्छे दिखते हैं?", AM.BEST_WINDOWS),
])
_QUESTION_LIST += _group("job_change_timing", CATEGORY_CAREER, PERSON_SINGLE, [
    ("job_change_now", "Is this a good time to change my job?",
     "क्या अभी नौकरी बदलने का सही समय है?", AM.CURRENT_PERIOD),
    ("new_job_timing", "When am I likely to get a new job?",
     "मुझे नई नौकरी मिलने के योग कब बन रहे हैं?", AM.WHEN_BEGINS, "new_job"),
    ("best_period_to_switch", "Which upcoming period is best for switching jobs?",
     "नौकरी बदलने के लिए आने वाला सबसे अच्छा समय कौन-सा है?", AM.BEST_WINDOWS),
    ("job_search_start_timing", "When is the best time to start an active job search?",
     "नौकरी की तलाश तेज़ करने का सही समय कब है?", AM.BEST_WINDOWS, "job_search"),
    ("job_gap_easing", "When may my phase without a suitable job ease?",
     "सही नौकरी न मिलने का यह दौर कब बदल सकता है?", AM.EASING_PERIOD, "job_gap"),
])

# --------------------------- MONEY / BUSINESS ---------------------------
_QUESTION_LIST += _group("money_improvement_timing", CATEGORY_MONEY_BUSINESS, PERSON_SINGLE, [
    ("financial_improvement_timing", "When will my financial situation improve?",
     "मेरी आर्थिक स्थिति कब सुधरने के योग हैं?", AM.WHEN_BEGINS),
    ("income_increase_timing", "When may my income increase?",
     "मेरी आमदनी कब बढ़ सकती है?", AM.WHEN_BEGINS, "income"),
    ("money_growth_periods", "Which coming periods are best for money growth?",
     "पैसों की बढ़ोतरी के लिए आने वाले कौन-से समय सबसे अच्छे हैं?", AM.BEST_WINDOWS),
    ("financial_pressure_easing", "When may my financial pressure ease?",
     "मेरा आर्थिक दबाव कब कम हो सकता है?", AM.EASING_PERIOD, "pressure"),
    ("debt_pressure_easing", "When may the pressure of debt start to reduce?",
     "कर्ज़ का दबाव कब हल्का होना शुरू हो सकता है?", AM.EASING_PERIOD, "debt"),
])
_QUESTION_LIST += _group("business_timing", CATEGORY_MONEY_BUSINESS, PERSON_SINGLE, [
    ("business_start_timing", "When is a good time to start a business?",
     "बिज़नेस शुरू करने का अच्छा समय कब है?", AM.BEST_WINDOWS, "start"),
    ("business_growth_timing", "When may my business grow?",
     "मेरा बिज़नेस कब बढ़ सकता है?", AM.WHEN_BEGINS, "growth"),
    ("best_business_periods", "Which coming periods are best for my business?",
     "मेरे बिज़नेस के लिए आने वाले कौन-से समय सबसे अच्छे हैं?", AM.BEST_WINDOWS),
    ("business_expansion_timing", "When is a good time to expand my business?",
     "अपना बिज़नेस बढ़ाने (expand करने) का सही समय कब है?", AM.BEST_WINDOWS, "expansion"),
    ("business_slowdown_easing", "When may the slow phase in my business ease?",
     "मेरे बिज़नेस की सुस्ती का दौर कब कम हो सकता है?", AM.EASING_PERIOD, "slowdown"),
    ("new_venture_partnership_timing", "When is a good time to begin a new venture or partnership?",
     "नया काम या पार्टनरशिप शुरू करने का सही समय कब है?", AM.BEST_WINDOWS, "partnership"),
])

# ------------------------------- MARRIAGE -------------------------------
_QUESTION_LIST += _group("marriage_timing", CATEGORY_MARRIAGE, PERSON_SINGLE, [
    ("strongest_marriage_periods", "When are my strongest periods for marriage?",
     "मेरी शादी के लिए सबसे मजबूत समय कब है?", AM.BEST_WINDOWS),
    ("marriage_chances_timing", "When do the chances of my marriage begin to look favourable?",
     "मेरी शादी के योग कब बनते दिख रहे हैं?", AM.WHEN_BEGINS),
    ("marriage_delay_reason", "Why is my marriage getting delayed?",
     "मेरी शादी में देरी क्यों हो रही है?", AM.DELAY_REASON),
    ("marriage_delay_easing", "When may the delay in my marriage ease?",
     "मेरी शादी में हो रही देरी कब खत्म हो सकती है?", AM.EASING_PERIOD),
    ("marriage_talks_current_period", "Is the current period supportive for marriage talks?",
     "क्या अभी का समय शादी की बातचीत के लिए अनुकूल है?", AM.CURRENT_PERIOD),
    ("relationship_to_marriage_window", "When could my current relationship move towards marriage?",
     "मेरा मौजूदा रिश्ता शादी की ओर कब बढ़ सकता है?", AM.WHEN_BEGINS, "own_relationship"),
])

# ------------------------- RELATIONSHIP (DUAL) -------------------------
_QUESTION_LIST += _group("relationship_marriage_potential", CATEGORY_RELATIONSHIP, PERSON_DUAL, [
    ("relationship_lead_to_marriage", "Do our charts support our relationship leading to marriage?",
     "क्या हमारे चार्ट बताते हैं कि हमारा रिश्ता शादी तक पहुँच सकता है?", AM.OVERVIEW),
    ("long_term_compatibility", "How compatible are we in the long term?",
     "लंबे समय के लिए हम दोनों की compatibility कैसी है?", AM.OVERVIEW, "long_term"),
    ("kundali_match_for_marriage", "Is our kundali match supportive for marriage?",
     "क्या शादी के लिए हम दोनों की कुंडली का मिलान अनुकूल है?", AM.OVERVIEW, "kundali_match"),
    ("right_time_to_consider_marriage", "Is this a supportive period for us to think about marriage?",
     "क्या यह समय हमारे शादी के बारे में सोचने के लिए अनुकूल है?", AM.CURRENT_PERIOD),
])
_QUESTION_LIST += _group("relationship_strengths_and_challenges", CATEGORY_RELATIONSHIP, PERSON_DUAL, [
    ("relationship_strengths_risks", "What are the strengths and challenges in our relationship?",
     "हमारे रिश्ते की ताकत और चुनौतियाँ क्या हैं?", AM.OVERVIEW),
    ("conflict_areas", "Where are we most likely to face conflicts?",
     "हम दोनों के बीच टकराव की संभावना कहाँ ज़्यादा है?", AM.OVERVIEW, "conflict"),
    ("emotional_communication_fit", "How well do our emotional needs and communication match?",
     "हम दोनों की भावनात्मक ज़रूरतों और बातचीत का तालमेल कैसा है?", AM.OVERVIEW, "emotional_fit"),
    ("strengthen_relationship", "What can we do to make our relationship stronger?",
     "अपने रिश्ते को और मजबूत बनाने के लिए हम क्या कर सकते हैं?", AM.GUIDANCE),
    ("relationship_care_periods", "Which periods need extra care in our relationship?",
     "हमारे रिश्ते में कौन-से समय में ज़्यादा ध्यान रखने की ज़रूरत है?", AM.CARE_PERIODS),
])

# -------------------------------- FOREIGN --------------------------------
_QUESTION_LIST += _group("foreign_move_timing", CATEGORY_FOREIGN, PERSON_SINGLE, [
    ("going_abroad_timing", "When are my chances of going abroad strongest?",
     "मेरे विदेश जाने के योग कब सबसे मजबूत हैं?", AM.BEST_WINDOWS),
    ("foreign_work_timing", "When is a good time to go abroad for work?",
     "विदेश में काम के लिए जाने का सही समय कब है?", AM.BEST_WINDOWS, "work"),
    ("study_abroad", "Would studying abroad be good for me?",
     "क्या विदेश में पढ़ाई करना मेरे लिए अच्छा रहेगा?", AM.GUIDANCE, "study"),
    ("foreign_settlement_timing", "When may I be able to settle abroad?",
     "मेरे विदेश में बसने के योग कब बन सकते हैं?", AM.WHEN_BEGINS, "settlement"),
    ("relocation_timing", "When is a good time to relocate to another city or country?",
     "दूसरे शहर या देश में शिफ्ट होने का सही समय कब है?", AM.BEST_WINDOWS, "relocation"),
    ("foreign_plans_delay_reason", "Why are my plans to go abroad getting delayed?",
     "मेरे विदेश जाने के प्लान में देरी क्यों हो रही है?", AM.DELAY_REASON),
])

# ------------------------------- EDUCATION -------------------------------
_QUESTION_LIST += _group("study_exam_timing", CATEGORY_EDUCATION, PERSON_SINGLE, [
    ("study_strong_period", "Which periods are strongest for my studies?",
     "मेरी पढ़ाई के लिए कौन-से समय सबसे मजबूत हैं?", AM.BEST_WINDOWS),
    ("exam_preparation_period", "Which coming periods support my exam preparation?",
     "मेरी परीक्षा की तैयारी के लिए आने वाले कौन-से समय अनुकूल हैं?", AM.BEST_WINDOWS, "exam_preparation"),
    ("higher_education_timing", "When is a good time to begin higher education?",
     "उच्च शिक्षा (higher education) शुरू करने का सही समय कब है?", AM.BEST_WINDOWS, "higher_education"),
    ("study_progress_improvement", "When may my progress in studies improve?",
     "मेरी पढ़ाई में प्रगति कब बेहतर हो सकती है?", AM.WHEN_BEGINS),
])

# ------------------------------- PROPERTY -------------------------------
_QUESTION_LIST += _group("property_timing", CATEGORY_PROPERTY, PERSON_SINGLE, [
    ("property_purchase_timing", "When is a good time to buy property?",
     "प्रॉपर्टी खरीदने का अच्छा समय कब है?", AM.BEST_WINDOWS),
    ("property_current_period", "Is the current period supportive for buying property?",
     "क्या अभी का समय प्रॉपर्टी खरीदने के लिए अनुकूल है?", AM.CURRENT_PERIOD),
    ("property_strongest_period", "Which coming period is strongest for acquiring property?",
     "प्रॉपर्टी लेने के लिए आने वाला सबसे मजबूत समय कौन-सा है?", AM.BEST_WINDOWS),
    ("property_delay_reason", "Why is my property purchase getting delayed?",
     "मेरी प्रॉपर्टी खरीदने में देरी क्यों हो रही है?", AM.DELAY_REASON),
    ("own_home_timing", "When may I be able to buy a home of my own?",
     "मेरा अपना घर लेने के योग कब बन सकते हैं?", AM.WHEN_BEGINS, "own_home"),
])

# --------------------------------- LIFE ---------------------------------
_QUESTION_LIST += _group("life_turning_points", CATEGORY_LIFE, PERSON_SINGLE, [
    ("major_turning_points", "What are the major turning points in my coming years?",
     "आने वाले सालों में मेरे जीवन के बड़े turning points कौन-से हैं?", AM.OVERVIEW),
    ("next_life_change_period", "When is my next major phase change?",
     "मेरे जीवन का अगला बड़ा बदलाव कब आ सकता है?", AM.WHEN_BEGINS),
    ("important_years_ahead", "Which coming years are the most important for me?",
     "आने वाले कौन-से साल मेरे लिए सबसे अहम हैं?", AM.BEST_WINDOWS),
    ("current_phase_meaning", "What does my current life phase mean, and when does it change?",
     "मेरा मौजूदा समय किस तरह का है और यह कब बदलेगा?", AM.CURRENT_PERIOD),
    ("areas_needing_attention", "Which areas of life need attention in the coming years?",
     "आने वाले सालों में जीवन के किन क्षेत्रों पर ध्यान देना ज़रूरी है?", AM.CARE_PERIODS),
])
_QUESTION_LIST += _group("life_direction_and_strengths", CATEGORY_LIFE, PERSON_SINGLE, [
    ("natural_strengths", "What are my natural strengths?",
     "मेरी प्राकृतिक ताकतें क्या हैं?", AM.OVERVIEW),
    ("life_direction", "Which life direction suits me best?",
     "मेरे लिए जीवन की कौन-सी दिशा सबसे सही रहेगी?", AM.OVERVIEW),
    ("focus_to_use_strengths", "What should I focus on to make the most of my strengths?",
     "अपनी ताकतों का पूरा फायदा उठाने के लिए मुझे किस पर ध्यान देना चाहिए?", AM.GUIDANCE),
])

QUESTIONS: Tuple[IntentQuestion, ...] = tuple(_QUESTION_LIST)
del _QUESTION_LIST

_BY_KEY: Dict[str, IntentQuestion] = {q.question_key: q for q in QUESTIONS}


def normalize_question_text(text: str) -> str:
    """Comparison form used to detect duplicate wording: Unicode NFC, lower-cased, punctuation removed,
    whitespace collapsed."""
    text = unicodedata.normalize("NFC", text or "").lower()
    # Drop punctuation/symbols only. Devanagari vowel signs are combining marks (not "word" characters),
    # so a \w-based filter would corrupt Hindi words.
    text = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def get_question(question_key: str) -> IntentQuestion:
    try:
        return _BY_KEY[question_key]
    except (KeyError, TypeError):
        raise UnknownQuestionError(question_key) from None


def questions_for_intent(intent_slug: str) -> Tuple[IntentQuestion, ...]:
    return tuple(q for q in QUESTIONS if q.intent_slug == intent_slug)


def questions_for_category(category: str) -> Tuple[IntentQuestion, ...]:
    return tuple(q for q in QUESTIONS if q.category == category)


def resolve_selection(question_key: str) -> IntentSelection:
    """Map a customer question to its core intent WITHOUT losing the question: the returned selection
    carries the core intent_slug AND the exact question_key / display question / answer_mode / lens."""
    question = get_question(question_key)
    contract = INTENT_REGISTRY[question.intent_slug]
    return IntentSelection(
        intent_slug=contract.intent_slug,
        question_key=question.question_key,
        category=contract.category,
        person_mode=contract.person_mode,
        display_question=question.question,
        answer_mode=question.answer_mode,
        lens=question.lens,
        price_rupees=contract.price_rupees,
    )


def validate_catalog() -> List[str]:
    """Cross-check the catalog against the registry. Returns a list of problems (empty == consistent)."""
    problems: List[str] = []
    seen_keys, seen_en, seen_hi = set(), {}, {}
    for question in QUESTIONS:
        if question.question_key in seen_keys:
            problems.append(f"duplicate question_key {question.question_key}")
        seen_keys.add(question.question_key)
        contract = INTENT_REGISTRY.get(question.intent_slug)
        if contract is None:
            problems.append(f"{question.question_key}: unknown intent {question.intent_slug}")
            continue
        if question.category != contract.category:
            problems.append(f"{question.question_key}: category {question.category} != intent {contract.category}")
        if question.person_mode != contract.person_mode:
            problems.append(f"{question.question_key}: person_mode {question.person_mode} != intent {contract.person_mode}")
        for language, store, text in (("en", seen_en, question.question_en), ("hi", seen_hi, question.question_hi)):
            normalized = normalize_question_text(text)
            if normalized in store:
                problems.append(f"{question.question_key}: duplicate normalized {language} wording of {store[normalized]}")
            store[normalized] = question.question_key
    for slug in INTENT_SLUGS:
        if not questions_for_intent(slug):
            problems.append(f"orphan intent {slug}")
    return problems


def export_catalog() -> dict:
    """The authoritative catalog as plain JSON-able data. The frontend mirror
    (jyotishasha-frontend/app/data/intentCatalog.json) is exactly this export; a test fails on any drift."""
    return {
        "schema_version": 1,
        "price_rupees": INTENT_REPORT_PRICE_RUPEES,
        "currency": INTENT_REPORT_CURRENCY,
        "categories": [
            {"category_id": info.category_id, "label_en": info.label.en, "label_hi": info.label.hi}
            for info in CATEGORIES
        ],
        "intents": [
            {
                "intent_slug": c.intent_slug,
                "category": c.category,
                "person_mode": c.person_mode,
                "canonical_question_en": c.canonical_question.en,
                "canonical_question_hi": c.canonical_question.hi,
                "readiness": c.readiness,
                "activation": c.activation,
                "upsell_slug": c.upsell_slug,
            }
            for c in INTENT_REGISTRY.values()
        ],
        "questions": [
            {
                "question_key": q.question_key,
                "intent_slug": q.intent_slug,
                "category": q.category,
                "person_mode": q.person_mode,
                "question_en": q.question_en,
                "question_hi": q.question_hi,
                "answer_mode": q.answer_mode,
                "lens": q.lens,
                "status": q.status,
            }
            for q in QUESTIONS
        ],
    }
