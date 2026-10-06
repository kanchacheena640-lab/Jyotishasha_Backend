"""
SNR-2C -- Spouse Nature Report (rep_026) narrative contract.

Turns the deterministic `spouse_evidence_v1` payload (SNR-2B,
modules/payments/spouse_evidence.py -- the SOURCE OF TRUTH) into a Luna
prompt, and validates/assembles Luna's answer. Luna explains and
synthesises; it never calculates astrology.

Reuses the existing standard_v1 / Q3 architecture, never a parallel one:
  * prompt templates live in prompts/spouse_nature_report_{en,hi}.txt and
    are filled with str.format() exactly like tasks.py fills every other
    product's template (literal braces doubled in the template);
  * the model is called ONLY through report_ai_client.generate_report_completion()
    (the model id lives only in app_config.PAID_REPORT_AI_MODEL; never re-declared here);
  * the response uses the existing ===META=== / ===REPORT=== wire format and is
    parsed with report_structured_output.parse_structured_response(), hero
    fields checked with validate_required_hero_fields(), and the hero `value`
    overridden with a DETERMINISTIC backend value via assemble_answer_hero();
  * failures raise report_structured_output.ReportMetadataError -- the same
    hard-failure class tasks.py already maps to report_stage="Failed";
  * disclaimers and the limitations section are FIXED backend text (like
    report_q3_batch1.DISCLAIMER_TEXT) -- never authored by Luna.

Prompt-injection safety: the prompt contains NO user-entered text (no name,
place or other metadata -- the same convention every existing standard_v1
prompt follows). The evidence block is rendered only from closed
vocabularies (sign/planet names, class labels) and every value is checked
against those vocabularies before interpolation.

Wired into tasks.py for spouse_nature_report (SNR-2D); see that file's
spouse branch for the evidence -> prompt -> Luna -> validation order.

SNR-2C.4 attribution boundary -- the BACKEND owns "why", Luna owns "what it
means". Luna receives a factor-free digest (no planets, signs, houses,
placements, Darakaraka identity or Basis lists) and writes sections 1, 2, 3,
6, 7 and 8. Every chart-factor -> trait statement is rendered here from the
frozen evidence votes: sections 4 and 5, the opening chart-basis line of
sections 6 and 7, and the hero evidence bullets.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional

from modules.payments.report_structured_output import (
    ReportMetadataError,
    assemble_answer_hero,
    parse_structured_response,
    validate_required_hero_fields,
)
from modules.payments.spouse_sign_table import DIMENSION_POLES, SIGN_ORDER, TRAIT_DIMENSIONS
from data.name_mappings import planet_labels_hi, sign_labels_hi

PRODUCT_SLUG = "spouse_nature_report"
EVIDENCE_SCHEMA = "spouse_evidence_v1"
LANGUAGES = ("en", "hi")
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "prompts")

GRAHAS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
TRAIT_CLASSES = ("DOMINANT", "SUPPORTED", "MIXED", "NOT_INDICATED")
RECONCILIATIONS = ("CONFIRMED", "D1_ONLY", "REFINEMENT", "OUTER_INNER_CONTRAST")
HEALTH_CLASSES = ("SUPPORTIVE", "MIXED", "NEEDS_ATTENTION")
WEALTH_CLASSES = ("STEADY", "GROWTH_ORIENTED", "EFFORT_BUILT", "MIXED")
ITEM_RESULTS = ("SUPPORT", "STRESS", "MIXED", "NONE")
DIM_STATES = ("SUPPORTED", "STRAINED", "MIXED", "NEUTRAL")
# Hero evidence bullets are backend-rendered (SNR-2C.4); Luna supplies only the interpretation.
REQUIRED_HERO_FIELDS = ("label", "value", "interpretation")

# Narrative sections Luna writes (1-8). Section 9 (limitations) is fixed backend text.
SECTION_KEYS = ("snapshot", "nature", "communication", "chart_basis", "navamsa", "health", "wealth", "integrated")
SECTION_TITLES = {
    "en": {
        "snapshot": "Future Spouse Snapshot",
        "nature": "Nature & Personality",
        "communication": "Communication & Emotional Style",
        "chart_basis": "Why Your Chart Suggests This",
        "navamsa": "Navamsa & Supporting Evidence",
        "health": "Spouse Health Tendencies",
        "wealth": "Financial Background & Wealth Tendencies",
        "integrated": "Integrated Spouse Profile",
        "limitations": "Important Limitations",
    },
    "hi": {
        "snapshot": "भावी जीवनसाथी की झलक",
        "nature": "स्वभाव और व्यक्तित्व",
        "communication": "संवाद और भावनात्मक शैली",
        "chart_basis": "आपकी कुंडली ऐसा क्यों संकेत देती है",
        "navamsa": "नवांश और सहायक प्रमाण",
        "health": "जीवनसाथी के स्वास्थ्य की प्रवृत्तियाँ",
        "wealth": "आर्थिक पृष्ठभूमि और धन की प्रवृत्तियाँ",
        "integrated": "जीवनसाथी की समग्र प्रोफ़ाइल",
        "limitations": "महत्वपूर्ण सीमाएँ",
    },
}
# SNR-2C.4: Luna writes these sections; 4 (chart_basis) and 5 (navamsa) are backend-rendered.
LUNA_SECTION_KEYS = ("snapshot", "nature", "communication", "health", "wealth", "integrated")
BACKEND_SECTION_KEYS = ("chart_basis", "navamsa")
LUNA_SECTION_NUMBERS = tuple(SECTION_KEYS.index(k) + 1 for k in LUNA_SECTION_KEYS)  # (1, 2, 3, 6, 7, 8)
CANONICAL_DIMENSIONS = tuple(d for d, _ in TRAIT_DIMENSIONS)

NATURE_SECTION_DIMS = ("temperament", "sociability", "independence", "approach_to_life", "responsibility", "convention")
COMMUNICATION_SECTION_DIMS = ("communication", "emotional_style")

HERO_LABEL = {"en": "Future Spouse Snapshot", "hi": "भावी जीवनसाथी की झलक"}

POLE_LABELS = {
    "en": {
        "steady": "Steady", "dynamic": "Dynamic", "reserved": "Reserved", "expressive": "Expressive",
        "guarded": "Emotionally Private", "open": "Emotionally Open", "home_centred": "Home-Centred",
        "outgoing": "Outgoing", "practical": "Practical", "idealistic": "Idealistic", "dutiful": "Responsible",
        "flexible": "Easygoing", "partnership_oriented": "Partnership-Oriented", "independent": "Independent",
        "traditional": "Traditional", "unconventional": "Unconventional",
    },
    "hi": {
        "steady": "स्थिर स्वभाव", "dynamic": "ऊर्जावान", "reserved": "संयमित", "expressive": "अभिव्यक्तिशील",
        "guarded": "भावनाओं में निजी", "open": "भावनात्मक रूप से खुला", "home_centred": "घर-परिवार केंद्रित",
        "outgoing": "मिलनसार", "practical": "व्यावहारिक", "idealistic": "आदर्शवादी", "dutiful": "ज़िम्मेदार",
        "flexible": "सहज और लचीला", "partnership_oriented": "साझेदारी-प्रधान", "independent": "स्वतंत्र विचारों वाला",
        "traditional": "पारंपरिक", "unconventional": "अपरंपरागत",
    },
}
MIXED_HERO_VALUE = {"en": "A Blend of Different Tendencies", "hi": "विभिन्न प्रवृत्तियों का मिश्रण"}

# Fixed, customer-facing backend text (never AI-authored).
LIMITATIONS_TEXT = {
    "en": (
        "Astrology describes tendencies, not certainties. Your future spouse is a real person with free "
        "will, and life circumstances, upbringing and personal choices shape who they are.\n"
        "This reading is built from your 7th house, its lord, the planets connected to it, your Navamsa "
        "chart and your Darakaraka. It deliberately does not use a few specialised techniques -- Upapada "
        "Lagna, retrograde motion, planetary combustion and Shadbala strength scores -- so it does not "
        "comment on anything that would depend on them.\n"
        "The health section describes broad astrological tendencies only; it is not a medical assessment. "
        "The financial section describes broad tendencies only; it is not financial advice or a prediction "
        "of exact income or wealth."
    ),
    "hi": (
        "ज्योतिष प्रवृत्तियाँ बताता है, निश्चितताएँ नहीं। आपका भावी जीवनसाथी एक वास्तविक व्यक्ति होगा जिसकी अपनी "
        "स्वतंत्र इच्छा है, और जीवन की परिस्थितियाँ, परवरिश तथा व्यक्तिगत निर्णय भी उसके स्वभाव को आकार देते हैं।\n"
        "यह विश्लेषण आपके सप्तम भाव, सप्तमेश, उससे जुड़े ग्रहों, आपकी नवांश कुंडली और दाराकारक पर आधारित है। इसमें "
        "कुछ विशेष तकनीकों -- उपपद लग्न, वक्री गति, ग्रहों का अस्त होना और षड्बल -- का उपयोग जानबूझकर नहीं किया गया है, "
        "इसलिए उन पर निर्भर बातों पर यह रिपोर्ट कुछ नहीं कहती।\n"
        "स्वास्थ्य वाला भाग केवल व्यापक ज्योतिषीय प्रवृत्तियाँ बताता है; यह कोई चिकित्सीय आकलन नहीं है। आर्थिक भाग भी "
        "केवल व्यापक प्रवृत्तियाँ बताता है; यह वित्तीय सलाह या आय और संपत्ति की सटीक भविष्यवाणी नहीं है।"
    ),
}
DISCLAIMERS = {
    "general": {
        "en": "This report describes astrological tendencies, not certainties. It does not identify a specific person.",
        "hi": "यह रिपोर्ट ज्योतिषीय प्रवृत्तियाँ बताती है, निश्चितताएँ नहीं। यह किसी विशेष व्यक्ति की पहचान नहीं करती।",
    },
    "health": {
        "en": ("The health section describes broad astrological tendencies and is not a medical diagnosis or a "
               "substitute for professional medical advice. For any health concern, consult a qualified doctor."),
        "hi": ("स्वास्थ्य वाला भाग व्यापक ज्योतिषीय प्रवृत्तियाँ बताता है; यह कोई चिकित्सीय निदान नहीं है और न ही "
               "डॉक्टर की सलाह का विकल्प है। स्वास्थ्य संबंधी किसी भी चिंता के लिए योग्य डॉक्टर से परामर्श करें।"),
    },
    "financial": {
        "en": ("The financial section describes broad astrological tendencies only. It is not financial advice "
               "and does not predict exact income, savings or wealth."),
        "hi": ("आर्थिक भाग केवल व्यापक ज्योतिषीय प्रवृत्तियाँ बताता है। यह वित्तीय सलाह नहीं है और आय, बचत या "
               "संपत्ति की सटीक भविष्यवाणी नहीं करता।"),
    },
}


# ---------------------------------------------------------------------------
# Evidence block (deterministic, closed vocabulary) + reference ids
# ---------------------------------------------------------------------------
def _require(value, allowed, what):
    if value not in allowed:
        raise ReportMetadataError(f"spouse evidence: unexpected {what} value {value!r}")
    return value


def _planets(values) -> list:
    return [_require(v, GRAHAS, "planet") for v in (values or [])]


FACTOR_PHRASE = {
    "occupant_7th": "{planet} placed in the 7th house",
    "seventh_sign": "7th-house sign {sign}",
    "seventh_lord": "{planet} as the 7th lord",
    "aspect_on_7th": "{planet} aspecting the 7th house",
    "influence_on_7th_lord": "{planet} conjunct with or aspecting the 7th lord",
    "d9_seventh_sign": "Navamsa 7th sign {sign}",
    "d9_seventh_lord": "{planet} as the Navamsa 7th lord",
    "d9_occupant_7th": "{planet} in the Navamsa 7th house",
    "darakaraka": "{planet} as Darakaraka",
}


FACTOR_PHRASE_HI = {
    "occupant_7th": "सप्तम भाव में स्थित {planet}",
    "seventh_sign": "सप्तम भाव की राशि {sign}",
    "seventh_lord": "सप्तमेश {planet}",
    "aspect_on_7th": "सप्तम भाव पर {planet} की दृष्टि",
    "influence_on_7th_lord": "सप्तमेश से {planet} की युति या दृष्टि",
    "d9_seventh_sign": "नवांश की सप्तम राशि {sign}",
    "d9_seventh_lord": "नवांश सप्तमेश {planet}",
    "d9_occupant_7th": "नवांश के सप्तम भाव में {planet}",
    "darakaraka": "दाराकारक {planet}",
}
FACTOR_PHRASES = {"en": FACTOR_PHRASE, "hi": FACTOR_PHRASE_HI}

DIMENSION_LABELS = {
    "en": {"temperament": "Temperament", "communication": "Communication", "emotional_style": "Emotional style",
           "sociability": "Sociability", "approach_to_life": "Approach to life", "responsibility": "Responsibility",
           "independence": "Independence", "convention": "Relationship to convention"},
    "hi": {"temperament": "स्वभाव", "communication": "संवाद", "emotional_style": "भावनात्मक शैली",
           "sociability": "मिलनसारिता", "approach_to_life": "जीवन के प्रति दृष्टिकोण", "responsibility": "ज़िम्मेदारी",
           "independence": "स्वतंत्रता", "convention": "परंपरा"},
}
CLASS_WORDS = {
    "en": {"DOMINANT": "a prominent tendency", "SUPPORTED": "a supported tendency", "MIXED": "both sides appear"},
    "hi": {"DOMINANT": "एक प्रमुख प्रवृत्ति", "SUPPORTED": "समर्थित प्रवृत्ति", "MIXED": "दोनों पक्ष दिखाई देते हैं"},
}
# Health items (frozen SNR-2A ids/names) and their result words -- verbalised, never re-interpreted.
HEALTH_ITEM_PHRASES = {
    "en": {"seventh_lord_dignity": "the 7th lord's dignity",
           "seventh_lord_placement_from_spouse": "the 7th lord's placement counted from the spouse's side",
           "influences_on_native_7th": "planetary influences on your 7th house",
           "influences_on_7th_lord": "planetary influences on the 7th lord",
           "lord_of_native_12_joins_spouse_1st": "the lord of your 12th house placed in your 7th house or with the 7th lord",
           "lord_of_native_6_joins_spouse_1st": "the lord of your 6th house placed in your 7th house or with the 7th lord"},
    "hi": {"seventh_lord_dignity": "सप्तमेश का बल",
           "seventh_lord_placement_from_spouse": "जीवनसाथी की ओर से गिनी गई सप्तमेश की स्थिति",
           "influences_on_native_7th": "आपके सप्तम भाव पर ग्रहों का प्रभाव",
           "influences_on_7th_lord": "सप्तमेश पर ग्रहों का प्रभाव",
           "lord_of_native_12_joins_spouse_1st": "आपके बारहवें भाव के स्वामी का सप्तम भाव में या सप्तमेश के साथ होना",
           "lord_of_native_6_joins_spouse_1st": "आपके छठे भाव के स्वामी का सप्तम भाव में या सप्तमेश के साथ होना"},
}
HEALTH_RESULT_WORDS = {
    "en": {"SUPPORT": "supportive", "STRESS": "calls for more care", "MIXED": "mixed"},
    "hi": {"SUPPORT": "सहायक", "STRESS": "अधिक देखभाल की ओर संकेत", "MIXED": "मिला-जुला"},
}
WEALTH_DIMENSION_LABELS = {
    "en": {"resources": "Resources", "income_growth": "Income growth", "professional_standing": "Professional standing"},
    "hi": {"resources": "संसाधन", "income_growth": "आय में वृद्धि", "professional_standing": "पेशेवर प्रतिष्ठा"},
}
DIM_STATE_WORDS = {
    "en": {"SUPPORTED": "supported", "STRAINED": "calls for more effort", "MIXED": "mixed", "NEUTRAL": "no strong emphasis"},
    "hi": {"SUPPORTED": "समर्थित", "STRAINED": "अधिक प्रयास की ओर संकेत", "MIXED": "मिला-जुला", "NEUTRAL": "कोई विशेष ज़ोर नहीं"},
}
# Factor-free D1/D9 relationship semantics for Luna (no "Navamsa", no placements).
RELATION_FOR_LUNA = {
    "CONFIRMED": "confirmed again at a deeper level",
    "REFINEMENT": "a secondary, deeper nuance toward {direction}",
    "D1_ONLY": "an outward-level tendency with no separate deeper-level note",
}
EXPRESSION_FOR_LUNA = {"well_supported": "expressed with clear support", "uneven": "may show unevenly",
                       "neutral": "no special note on expression"}
HEALTH_MEANING_FOR_LUNA = {
    "SUPPORTIVE": "overall supportive indicators around general wellbeing",
    "MIXED": "wellbeing may depend more on lifestyle, routine and circumstances",
    "NEEDS_ATTENTION": "more care around wellbeing, rest and routine may help",
}
WEALTH_MEANING_FOR_LUNA = {
    "STEADY": "a relatively steady resource-building tendency",
    "GROWTH_ORIENTED": "potential for gradual growth in resources or earnings",
    "EFFORT_BUILT": "resources may be built more through sustained effort and persistence",
    "MIXED": "financial indicators are mixed rather than pointing to one simple pattern",
}
UI = {
    "en": {
        "birth_chart": "Birth chart", "navamsa": "Navamsa", "toward": "Toward",
        "seventh_occupied": "Your 7th house is {sign}; its lord, {lord}, sits in house {house} ({lord_sign}). Planets in your 7th house: {planets}.",
        "seventh_empty": "Your 7th house is {sign}; its lord, {lord}, sits in house {house} ({lord_sign}). No planet occupies your 7th house, so it is read through its sign, its lord and the planets connected with them.",
        "basis_intro": "These are the chart factors behind each trait described in this reading:",
        "navamsa_only": "shown through the Navamsa (see the next section)",
        "dk_only": "supported by the Darakaraka (see the next section)",
        "d9_intro": "Navamsa 7th sign: {sign}. Navamsa 7th lord: {lord}.",
        "d9_occupants": "Planets in the Navamsa 7th house: {planets}.",
        "confirmed": "{dim} -- {pole}: the Navamsa repeats this direction ({factors}).",
        "refinement": "{dim} -- {pole}: the Navamsa adds this as a secondary nuance ({factors}).",
        "contrast": "{dim}: outwardly {outer} in the birth chart; in private life the Navamsa leans {inner} ({factors}).",
        "contrast_both": "{dim}: the birth chart shows both sides outwardly; in private life the Navamsa leans {inner} ({factors}).",
        "d1_only_with_d9": "{dim}: Navamsa factors -- {parts}; the reading of this trait rests on the birth chart.",
        "no_d9": "The Navamsa does not add a separate emphasis to the traits above.",
        "dk": "Darakaraka (a supporting indicator only): {planet} -- {leanings}.",
        "dk_tie": "Darakaraka (an exact tie; supporting indicators only): {planets}. {parts}",
        "dk_planet_leanings": "{planet} leans toward {leanings}.",
        "dk_planet_none": "{planet} adds no separate emphasis to the traits described here.",
        "dk_none": "it adds no separate emphasis to the traits described here",
        "leaning": "{pole} ({dim})",
        "navamsa_rule": "The Navamsa confirms or refines the birth-chart picture; the birth chart remains the primary reading.",
        "health_basis": "Chart basis: {items}.",
        "health_none": "Chart basis: no single factor stands out strongly here.",
        "wealth_item": "{label} -- the spouse's house {spouse_house} (your house {native_house}, {sign}): {state}",
        "wealth_basis": "Chart basis: {items}.",
        "hero_line": "{dim} -- {pole}: {factors}",
        "hero_fallback": "Your 7th house is {sign} and its lord is {lord}.",
        "join": "; ", "and": " and ",
    },
    "hi": {
        "birth_chart": "जन्मकुंडली", "navamsa": "नवांश", "toward": "की ओर",
        "seventh_occupied": "आपका सप्तम भाव {sign} राशि में है; सप्तमेश {lord} भाव {house} ({lord_sign}) में है। सप्तम भाव में स्थित ग्रह: {planets}।",
        "seventh_empty": "आपका सप्तम भाव {sign} राशि में है; सप्तमेश {lord} भाव {house} ({lord_sign}) में है। सप्तम भाव में कोई ग्रह नहीं है, इसलिए इसे इसकी राशि, सप्तमेश और उनसे जुड़े ग्रहों से पढ़ा जाता है।",
        "basis_intro": "इस विश्लेषण में बताए गए हर गुण के पीछे कुंडली के ये कारक हैं:",
        "navamsa_only": "नवांश से दिखाई देता है (अगला भाग देखें)",
        "dk_only": "दाराकारक से सहायक संकेत (अगला भाग देखें)",
        "d9_intro": "नवांश की सप्तम राशि: {sign}। नवांश सप्तमेश: {lord}।",
        "d9_occupants": "नवांश के सप्तम भाव में ग्रह: {planets}।",
        "confirmed": "{dim} -- {pole}: नवांश इसी दिशा को दोहराता है ({factors})।",
        "refinement": "{dim} -- {pole}: नवांश इसे एक अतिरिक्त, सूक्ष्म पहलू के रूप में जोड़ता है ({factors})।",
        "contrast": "{dim}: जन्मकुंडली में बाहरी रूप से {outer}; निजी जीवन में नवांश {inner} की ओर झुकता है ({factors})।",
        "contrast_both": "{dim}: जन्मकुंडली में बाहरी रूप से दोनों पक्ष दिखते हैं; निजी जीवन में नवांश {inner} की ओर झुकता है ({factors})।",
        "d1_only_with_d9": "{dim}: नवांश के कारक -- {parts}; इस गुण का विश्लेषण जन्मकुंडली पर आधारित है।",
        "no_d9": "नवांश ऊपर बताए गए गुणों पर अलग से कोई ज़ोर नहीं जोड़ता।",
        "dk": "दाराकारक (केवल सहायक संकेत): {planet} -- {leanings}।",
        "dk_tie": "दाराकारक (बराबरी की स्थिति; केवल सहायक संकेत): {planets}। {parts}",
        "dk_planet_leanings": "{planet} {leanings} की ओर संकेत करता है।",
        "dk_planet_none": "{planet} यहाँ बताए गए गुणों पर अलग से कोई ज़ोर नहीं जोड़ता।",
        "dk_none": "यह यहाँ बताए गए गुणों पर अलग से कोई ज़ोर नहीं जोड़ता",
        "leaning": "{pole} ({dim})",
        "navamsa_rule": "नवांश जन्मकुंडली की पुष्टि करता है या उसमें सूक्ष्म पहलू जोड़ता है; मुख्य आधार जन्मकुंडली ही रहती है।",
        "health_basis": "कुंडली का आधार: {items}।",
        "health_none": "कुंडली का आधार: यहाँ कोई एक कारक विशेष रूप से उभरकर नहीं आता।",
        "wealth_item": "{label} -- जीवनसाथी का भाव {spouse_house} (आपका भाव {native_house}, {sign}): {state}",
        "wealth_basis": "कुंडली का आधार: {items}।",
        "hero_line": "{dim} -- {pole}: {factors}",
        "hero_fallback": "आपका सप्तम भाव {sign} राशि में है और सप्तमेश {lord} है।",
        "join": "; ", "and": " और ",
    },
}


def _planet_name(planet, language):
    _require(planet, GRAHAS, "planet")
    return planet if language == "en" else planet_labels_hi[planet]


def _sign_name(sign, language):
    _require(sign, SIGN_ORDER, "sign")
    return sign if language == "en" else sign_labels_hi[sign]


def _factor_text(v: dict, language: str = "en") -> str:
    """One evidence factor, verbalised from the frozen factor vocabulary only."""
    phrase = FACTOR_PHRASES[language].get(v.get("factor"))
    if phrase is None:
        raise ReportMetadataError(f"spouse evidence: unknown factor {v.get('factor')!r}")
    planet = _planet_name(v["planet"], language) if v.get("planet") else None
    sign = _sign_name(v["sign"], language) if v.get("sign") else None
    return phrase.format(planet=planet, sign=sign)


def _reportable_traits(evidence: dict) -> list:
    out = []
    for t in evidence["nature"]["traits"]:
        _require(t["dimension"], DIMENSION_POLES, "dimension")
        klass = _require(t["class"], TRAIT_CLASSES, "trait class")
        _require(t["d1_d9"], RECONCILIATIONS, "reconciliation")
        if t.get("reportable") and klass != "NOT_INDICATED":
            for v in t["evidence"]:
                _require(v.get("pole"), DIMENSION_POLES[t["dimension"]], "pole")
                _require(v.get("chart"), ("D1", "D9"), "chart")
            out.append(t)
    return out


def _is_dk(v):
    return v.get("factor") == "darakaraka"


def _d1_votes(t, pole):
    return [v for v in t["evidence"] if v["chart"] == "D1" and not _is_dk(v) and v["pole"] == pole]


def _d9_votes(t, pole=None):
    return [v for v in t["evidence"] if v["chart"] == "D9" and (pole is None or v["pole"] == pole)]


def contrast_poles(t: dict) -> tuple:
    """(outer, inner) for an OUTER_INNER_CONTRAST trait: inner = the single pole all
    Navamsa votes share (the frozen rule's d9 direction); outer = the other pole.
    Fails closed if the Navamsa votes are not unanimous."""
    d9_poles = {v["pole"] for v in _d9_votes(t)}
    if len(d9_poles) != 1:
        raise ReportMetadataError(f"spouse evidence: contrast for {t['dimension']!r} has no single Navamsa direction")
    inner = d9_poles.pop()
    a, b = DIMENSION_POLES[t["dimension"]]
    return (b if inner == a else a), inner


def outer_poles(t: dict) -> tuple:
    """Directions the BIRTH chart shows for a trait (primary/secondary votes -- the
    tiers the frozen contrast rule reads), in canonical order."""
    present = {v["pole"] for v in t["evidence"] if v["chart"] == "D1" and v.get("tier") in ("P", "S")}
    return tuple(p for p in DIMENSION_POLES[t["dimension"]] if p in present)


def _luna_relation(t: dict) -> str:
    recon = t["d1_d9"]
    if recon == "OUTER_INNER_CONTRAST":
        _, inner = contrast_poles(t)
        shown = outer_poles(t)
        outward = "both sides appear outwardly" if len(shown) == 2 else f"outwardly {shown[0]}"
        return f"{outward}; in private life leaning {inner}"
    return RELATION_FOR_LUNA[recon].format(direction=t.get("direction"))


def build_evidence_block(evidence: dict) -> tuple:
    """Factor-FREE digest for Luna (SNR-2C.4): trait conclusions, health and wealth
    meaning only -- no planets, signs, houses, placements, Darakaraka identity or
    Basis lists. Returns (text, allowed_refs). NOT_INDICATED traits are omitted."""
    if not isinstance(evidence, dict) or evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ReportMetadataError("spouse narrative requires a spouse_evidence_v1 payload")
    lines, refs = [], []

    def ref(rid, text):
        refs.append(rid)
        lines.append(f"[{rid}] {text}")

    lines.append("== Spouse traits to interpret (only these; anything not listed must not be described) ==")
    for t in _reportable_traits(evidence):
        dim, klass = t["dimension"], t["class"]
        a, b = DIMENSION_POLES[dim]
        if klass == "MIXED":
            body = f"class MIXED (both directions appear: {a} and {b})"
        else:
            direction = _require(t["direction"], (a, b), "direction")
            quality = EXPRESSION_FOR_LUNA[_require(t["expression_quality"], tuple(EXPRESSION_FOR_LUNA), "expression quality")]
            body = f"class {klass} toward {direction} ({quality})"
        ref(f"nature.{dim}", f"dimension {dim}: {body}; depth: {_luna_relation(t)}.")
    snap = [f"{_require(s['dimension'], DIMENSION_POLES, 'dimension')}={s['direction']}" for s in evidence["nature"]["snapshot_traits"]]
    lines.append(f"Snapshot traits (strongest): {', '.join(snap) if snap else 'none -- the picture is mostly mixed'}")

    lines.append("== Spouse wellbeing (use ONLY this class) ==")
    h = _require(evidence["health"]["class"], HEALTH_CLASSES, "health class")
    ref("health.class", f"Health class: {h} -- {HEALTH_MEANING_FOR_LUNA[h]}")

    lines.append("== Spouse financial background (use ONLY this class) ==")
    w = evidence["wealth"]
    wc = _require(w["class"], WEALTH_CLASSES, "wealth class")
    ref("wealth.class", f"Wealth class: {wc} -- {WEALTH_MEANING_FOR_LUNA[wc]}")
    for key in ("resources", "income_growth", "professional_standing"):
        state = _require(w["dimensions"][key]["state"], DIM_STATES, "state")
        ref(f"wealth.{key}", f"{key.replace('_', ' ')}: {DIM_STATE_WORDS['en'][state]}")
    if w["unconventional_pattern"]:
        ref("wealth.unconventional_pattern", "unconventional pattern: present -- non-traditional, changing or unusual channels")
    else:
        lines.append("unconventional pattern: absent -- do not describe one")
    return "\n".join(lines), refs


# ---------------------------------------------------------------------------
# Backend attribution renderer (SNR-2C.4) -- the ONLY place chart factors are
# connected to traits. Verbalises frozen evidence votes; adds no astrology.
# ---------------------------------------------------------------------------
def _join(items, language):
    return UI[language]["join"].join(items)


def _pole(pole, language):
    return POLE_LABELS[language][pole]


def _dim(dim, language):
    return DIMENSION_LABELS[language][dim]


def render_chart_basis(evidence: dict, language: str) -> str:
    """Section 4 body: 7th-house facts + birth-chart factors per reportable trait."""
    u = UI[language]
    d1 = evidence["chart_facts"]["d1"]
    facts = dict(sign=_sign_name(d1["seventh_sign"], language), lord=_planet_name(d1["seventh_lord"], language),
                 house=int(d1["seventh_lord_house"]), lord_sign=_sign_name(d1["seventh_lord_sign"], language))
    if d1["occupants_7th"]:
        intro = u["seventh_occupied"].format(planets=", ".join(_planet_name(p, language) for p in d1["occupants_7th"]), **facts)
    else:
        intro = u["seventh_empty"].format(**facts)
    out = [intro, "", u["basis_intro"]]
    for t in _reportable_traits(evidence):
        dim = t["dimension"]
        if t["class"] == "MIXED":
            head = f"- **{_dim(dim, language)}** ({CLASS_WORDS[language]['MIXED']})"
            parts = []
            for pole in DIMENSION_POLES[dim]:
                f = _d1_votes(t, pole)
                if f:
                    parts.append(f"{_pole(pole, language)} -- {_join([_factor_text(v, language) for v in f], language)}")
                elif _d9_votes(t, pole):
                    parts.append(f"{_pole(pole, language)} -- {u['navamsa_only']}")
                elif any(_is_dk(v) and v["pole"] == pole for v in t["evidence"]):
                    parts.append(f"{_pole(pole, language)} -- {u['dk_only']}")
            body = " | ".join(parts) if parts else u["navamsa_only"]
        else:
            head = f"- **{_dim(dim, language)} -- {_pole(t['direction'], language)}** ({CLASS_WORDS[language][t['class']]})"
            f = _d1_votes(t, t["direction"])
            body = _join([_factor_text(v, language) for v in f], language) if f else u["navamsa_only"]
        out.append(f"{head}: {body}")
    return "\n".join(out)


def _dk_leanings(evidence, planet, language):
    leanings = [UI[language]["leaning"].format(pole=_pole(v["pole"], language), dim=_dim(t["dimension"], language))
                for t in _reportable_traits(evidence) for v in t["evidence"] if _is_dk(v) and v.get("planet") == planet]
    if not leanings:
        return UI[language]["dk_none"]
    return leanings[0] if len(leanings) == 1 else ", ".join(leanings[:-1]) + UI[language]["and"] + leanings[-1]


def render_navamsa(evidence: dict, language: str) -> str:
    """Section 5 body: Navamsa facts, per-trait D1/D9 relationship, Darakaraka."""
    u = UI[language]
    d9 = evidence["chart_facts"]["d9"]
    out = [u["d9_intro"].format(sign=_sign_name(d9["seventh_sign"], language), lord=_planet_name(d9["seventh_lord"], language))]
    if d9["occupants_d9_7th"]:
        out.append(u["d9_occupants"].format(planets=", ".join(_planet_name(p, language) for p in d9["occupants_d9_7th"])))
    trait_lines = []
    for t in _reportable_traits(evidence):
        dim, recon = t["dimension"], t["d1_d9"]
        factors = lambda vs: _join([_factor_text(v, language) for v in vs], language)  # noqa: E731
        if recon in ("CONFIRMED", "REFINEMENT"):
            _require(t.get("direction"), DIMENSION_POLES[dim], "direction")
            if not _d9_votes(t, t["direction"]):
                raise ReportMetadataError(f"spouse evidence: {recon} for {dim!r} without a Navamsa factor")
        if recon == "CONFIRMED":
            trait_lines.append(u["confirmed"].format(dim=_dim(dim, language), pole=_pole(t["direction"], language),
                                                     factors=factors(_d9_votes(t, t["direction"]))))
        elif recon == "REFINEMENT":
            trait_lines.append(u["refinement"].format(dim=_dim(dim, language), pole=_pole(t["direction"], language),
                                                      factors=factors(_d9_votes(t, t["direction"]))))
        elif recon == "OUTER_INNER_CONTRAST":
            _, inner = contrast_poles(t)
            shown = outer_poles(t)
            template = u["contrast_both"] if len(shown) == 2 else u["contrast"]
            trait_lines.append(template.format(dim=_dim(dim, language), outer=_pole(shown[0], language),
                                               inner=_pole(inner, language), factors=factors(_d9_votes(t, inner))))
        elif _d9_votes(t):  # D1_ONLY but Navamsa factors exist: state them, never as support/override.
            parts = [f"{_pole(p, language)}: {factors(_d9_votes(t, p))}" for p in DIMENSION_POLES[dim] if _d9_votes(t, p)]
            trait_lines.append(u["d1_only_with_d9"].format(dim=_dim(dim, language), parts=_join(parts, language)))
    out += [f"- {line}" for line in trait_lines] or [u["no_d9"]]
    out.append(u["navamsa_rule"])
    dk = evidence["chart_facts"]["darakaraka"]
    planets = [_require(p, GRAHAS, "planet") for p in dk["planets"]]
    if not planets:
        raise ReportMetadataError("spouse evidence: Darakaraka missing")
    if len(planets) == 1 and not dk.get("tie"):
        out.append(u["dk"].format(planet=_planet_name(planets[0], language), leanings=_dk_leanings(evidence, planets[0], language)))
    else:
        parts = " ".join(
            u["dk_planet_leanings"].format(planet=_planet_name(p, language), leanings=_dk_leanings(evidence, p, language))
            if _dk_leanings(evidence, p, language) != u["dk_none"] else u["dk_planet_none"].format(planet=_planet_name(p, language))
            for p in planets)
        out.append(u["dk_tie"].format(planets=", ".join(_planet_name(p, language) for p in planets), parts=parts))
    return "\n".join(out)


def render_health_basis(evidence: dict, language: str) -> str:
    items = []
    for item in evidence["health"]["primary_items"] + evidence["health"]["secondary_items"]:
        result = _require(item["result"], ITEM_RESULTS, "item result")
        phrase = HEALTH_ITEM_PHRASES[language].get(item["item"])
        if phrase is None:
            raise ReportMetadataError(f"spouse evidence: unknown health item {item['item']!r}")
        if result != "NONE":
            items.append(f"{phrase} -- {HEALTH_RESULT_WORDS[language][result]}")
    u = UI[language]
    return u["health_basis"].format(items=_join(items, language)) if items else u["health_none"]


def render_wealth_basis(evidence: dict, language: str) -> str:
    items = []
    for key in ("resources", "income_growth", "professional_standing"):
        d = evidence["wealth"]["dimensions"][key]
        items.append(UI[language]["wealth_item"].format(
            label=WEALTH_DIMENSION_LABELS[language][key], spouse_house=int(d["spouse_house"]),
            native_house=int(d["native_house"]), sign=_sign_name(d["sign"], language),
            state=DIM_STATE_WORDS[language][_require(d["state"], DIM_STATES, "state")]))
    return UI[language]["wealth_basis"].format(items=_join(items, language))


def render_hero_evidence(evidence: dict, language: str) -> list:
    """Backend hero bullets: the snapshot traits with their own birth-chart factors
    (Navamsa factors only when the direction came from the Navamsa)."""
    traits = {t["dimension"]: t for t in _reportable_traits(evidence)}
    lines = []
    for s in evidence["nature"]["snapshot_traits"][:3]:
        t = traits.get(s["dimension"])
        if t is None or t["class"] == "MIXED":
            continue
        votes = _d1_votes(t, t["direction"]) or _d9_votes(t, t["direction"])
        if votes:
            lines.append(UI[language]["hero_line"].format(dim=_dim(t["dimension"], language), pole=_pole(t["direction"], language),
                                                          factors=_join([_factor_text(v, language) for v in votes], language)))
    if not lines:
        d1 = evidence["chart_facts"]["d1"]
        lines.append(UI[language]["hero_fallback"].format(sign=_sign_name(d1["seventh_sign"], language),
                                                          lord=_planet_name(d1["seventh_lord"], language)))
    return lines


def build_attribution(evidence: dict, language: str) -> dict:
    """Every backend-owned, customer-facing chart attribution for one report."""
    if language not in LANGUAGES:
        raise ReportMetadataError(f"Unsupported language {language!r}")
    return {
        "chart_basis": render_chart_basis(evidence, language),
        "navamsa": render_navamsa(evidence, language),
        "health_basis": render_health_basis(evidence, language),
        "wealth_basis": render_wealth_basis(evidence, language),
        "hero_evidence": render_hero_evidence(evidence, language),
    }


def deterministic_hero_value(evidence: dict, language: str) -> str:
    """Hero `value`: the strongest reportable snapshot traits (backend), never AI."""
    snap = evidence["nature"]["snapshot_traits"]
    if not snap:
        return MIXED_HERO_VALUE[language]
    return ", ".join(POLE_LABELS[language][s["direction"]] for s in snap)


def build_spouse_prompt(evidence: dict, language: str) -> str:
    """Fills prompts/spouse_nature_report_{language}.txt with the evidence block.
    No user metadata is ever placed in the prompt."""
    if language not in LANGUAGES:
        raise ReportMetadataError(f"Unsupported language {language!r}")
    with open(os.path.join(PROMPTS_DIR, f"{PRODUCT_SLUG}_{language}.txt"), encoding="utf-8") as f:
        template = f.read()
    block, refs = build_evidence_block(evidence)
    return template.format(
        spouse_evidence_block=block,
        allowed_refs=", ".join(refs),
        hero_value=deterministic_hero_value(evidence, language),
        allowed_dimensions=", ".join(t["dimension"] for t in _reportable_traits(evidence)),
        health_class=evidence["health"]["class"],
        wealth_class=evidence["wealth"]["class"],
    )


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
_EN_FLAGS = re.IGNORECASE
PROHIBITED = {
    "probability": [
        re.compile(r"\d+(\.\d+)?\s*%"), re.compile(r"\b(percent|percentage|probability|probabilities)\b", _EN_FLAGS),
        re.compile(r"\b\d+\s*(in|out of)\s*\d+\b", _EN_FLAGS), re.compile(r"(प्रतिशत|संभाव्यता)"),
    ],
    "medical": [
        re.compile(r"\b(diseases?|diagnos\w*|illness(es)?|cancer|diabet\w*|tumou?rs?|surgery|surgical|hospital\w*|"
                   r"lifespan|life span|longevity|death|dies?|dying|fatal|fertil\w*|infertil\w*|pregnan\w*|miscarriage|"
                   r"childbirth|depression|depressive|bipolar|schizophren\w*|psychiatric|mental illness|medication|"
                   r"medicines?|treatments?|heart attack|blood pressure|kidneys?|liver)\b", _EN_FLAGS),
        re.compile(r"(बीमारी|निदान|कैंसर|मधुमेह|सर्जरी|ऑपरेशन|अस्पताल|जीवनकाल|मृत्यु|मौत|प्रजनन|गर्भ|बांझ|अवसाद|"
                   r"मानसिक रोग|दवा|इलाज|उपचार|दीर्घायु)"),
    ],
    "financial": [
        re.compile(r"[₹$]"),
        re.compile(r"\b(salary|salaries|net worth|crores?|lakhs?|rupees?|dollars?|rich|richer|wealthy|poor|poverty|"
                   r"millionaire|billionaire|invest\w*|stock market|mutual funds?)\b", _EN_FLAGS),
        re.compile(r"(वेतन|सैलरी|नेट वर्थ|करोड़|लाख|रुपये|अमीर|गरीब|धनवान|निवेश|शेयर बाज़ार)"),
    ],
    "certainty": [
        re.compile(r"\b(definitely|certainly|guarantee\w*|undoubtedly|for sure|will always|without (any )?doubt)\b", _EN_FLAGS),
        re.compile(r"(निश्चित रूप से|अवश्य ही|गारंटी|बिना किसी संदेह)"),
    ],
    "unsupported_factor": [
        re.compile(r"\b(upapada|retrograde|combust\w*|shadbala|moolatrikona|mulatrikona|yogakaraka|maraka|nakshatras?|"
                   r"ashtakavarga|gemstones?|mantras?|puja|remed(y|ies)|mahadasha|antardasha|dasha)\b", _EN_FLAGS),
        re.compile(r"(उपपद|वक्री|षड्बल|मूलत्रिकोण|योगकारक|मारक|नक्षत्र|रत्न|मंत्र|पूजा|उपाय|महादशा|अंतर्दशा|दशा)"),
    ],
    "d9_override": [
        re.compile(r"\b(overrid\w*|overrul\w*|correct(s|ed)? the birth chart)\b", _EN_FLAGS),
        re.compile(r"(खारिज|पलट दे)"),
    ],
    "timing": [re.compile(r"\b(19|20)\d{2}\b"), re.compile(r"\bat (the )?age\s+\d+", _EN_FLAGS)],
}
WEALTH_INSTABILITY = [
    re.compile(r"\b(unstable|instability|loss|losses|debts?|bankrupt\w*|financial (problems?|trouble|crisis|difficult\w*))\b", _EN_FLAGS),
    re.compile(r"(अस्थिर|नुकसान|घाटा|आर्थिक संकट|कर्ज)"),
]

# Machine vocabulary that must never reach customer prose (SNR-2C.3). META keeps
# its structured class/direction fields; only the customer-visible text is scanned.
# The capitalised states are matched case-sensitively as whole tokens, so ordinary
# prose ("mixed", "Steady") is unaffected.
DIGNITIES = ("EXALTED", "OWN", "DEBILITATED", "NEUTRAL")
DARAKARAKA_STATUSES = ("DK_TIE",)
RAW_INTERNAL_LABELS = frozenset(TRAIT_CLASSES + RECONCILIATIONS + HEALTH_CLASSES + WEALTH_CLASSES
                                + ITEM_RESULTS + DIM_STATES + DIGNITIES + DARAKARAKA_STATUSES)
_RAW_LABEL = re.compile(r"(?<![A-Za-z0-9_])("
                        + "|".join(sorted(map(re.escape, RAW_INTERNAL_LABELS), key=len, reverse=True))
                        + r")(?![A-Za-z0-9_])")
# snake_case identifiers (approach_to_life, unconventional_pattern) and evidence ref ids.
_MACHINE_IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b|\b(?:nature|health|wealth|chart_facts)\.[A-Za-z0-9_.-]+")


def internal_label_leaks(text: str) -> list:
    """Raw internal labels / identifiers found in customer-visible text."""
    return sorted({m.group(0) for rx in (_RAW_LABEL, _MACHINE_IDENTIFIER) for m in rx.finditer(text or "")})


def _scan(text: str, groups) -> list:
    hits = []
    for name in groups:
        for rx in PROHIBITED[name]:
            m = rx.search(text or "")
            if m:
                hits.append(f"{name}:{m.group(0)}")
    return hits


_HEADING = re.compile(r"^\s*\*\*\s*(\d+)\.\s*(.+?)\s*\*\*\s*$", re.MULTILINE)


def split_sections(narrative: str) -> dict:
    """{section_number: (title, body)} from the existing **N. Title** heading convention."""
    marks = list(_HEADING.finditer(narrative or ""))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(narrative)
        out[int(m.group(1))] = (m.group(2).strip(), narrative[m.end():end].strip())
    return out


def validate_spouse_response(raw_text: str, evidence: dict, language: str) -> dict:
    """Parses and validates one Luna response against the backend evidence.
    Raises ReportMetadataError (hard failure) listing every problem found;
    returns {"metadata", "narrative", "sections"} when valid."""
    if language not in LANGUAGES:
        raise ReportMetadataError(f"Unsupported language {language!r}")
    _, allowed = build_evidence_block(evidence)
    allowed = set(allowed)
    metadata, narrative = parse_structured_response(raw_text)
    hero = validate_required_hero_fields(metadata, REQUIRED_HERO_FIELDS)  # raises on missing/malformed
    problems = []

    # Backend classes must be echoed exactly (Luna may not override them).
    classes = metadata.get("classes") or {}
    if classes.get("health") != evidence["health"]["class"]:
        problems.append(f"health class {classes.get('health')!r} != backend {evidence['health']['class']!r}")
    if classes.get("wealth") != evidence["wealth"]["class"]:
        problems.append(f"wealth class {classes.get('wealth')!r} != backend {evidence['wealth']['class']!r}")

    # Traits Luna describes must be backend-reportable, with the same class/direction.
    backend = {t["dimension"]: t for t in evidence["nature"]["traits"]}
    discussed = metadata.get("traits_discussed")
    if not isinstance(discussed, list):
        problems.append("traits_discussed missing")
        discussed = []
    for t in discussed:
        dim = t.get("dimension") if isinstance(t, dict) else None
        if dim not in CANONICAL_DIMENSIONS:
            problems.append(f"trait dimension {dim!r} is not a canonical dimension name {CANONICAL_DIMENSIONS}")
            continue
        b = backend.get(dim)
        if b is None or not b.get("reportable") or b["class"] == "NOT_INDICATED":
            problems.append(f"trait {dim!r} is not reportable (invented or NOT_INDICATED)")
            continue
        if t.get("class") != b["class"]:
            problems.append(f"trait {dim} class {t.get('class')!r} != backend {b['class']!r}")
        expected_dir = None if b["class"] == "MIXED" else b["direction"]
        if t.get("direction") != expected_dir:
            problems.append(f"trait {dim} direction {t.get('direction')!r} != backend {expected_dir!r}")

    # Evidence references: every ref must exist; each section must cite its anchor.
    hero_refs = hero.get("evidence_refs")
    if not isinstance(hero_refs, list) or not hero_refs:
        problems.append("answer_hero.evidence_refs missing")
        hero_refs = []
    sections_meta = metadata.get("sections")
    if not isinstance(sections_meta, list):
        problems.append("sections missing")
        sections_meta = []
    by_key = {s.get("key"): s for s in sections_meta if isinstance(s, dict)}
    for key in LUNA_SECTION_KEYS:
        if key not in by_key:
            problems.append(f"section {key!r} missing from META")
    for key in by_key:
        if key not in LUNA_SECTION_KEYS:
            problems.append(f"section {key!r} is not written by Luna")
    all_refs = list(hero_refs)
    for s in by_key.values():
        r = s.get("evidence_refs")
        if not isinstance(r, list):
            problems.append(f"section {s.get('key')!r} evidence_refs not a list")
            continue
        all_refs.extend(r)
    for r in all_refs:
        if r not in allowed:
            problems.append(f"evidence ref {r!r} does not exist in backend evidence")
    reportable_refs = {f"nature.{t['dimension']}" for t in evidence["nature"]["traits"] if t.get("reportable")}

    def cites(key, predicate):
        return any(predicate(r) for r in (by_key.get(key, {}).get("evidence_refs") or []))
    if "health" in by_key and not cites("health", lambda r: r == "health.class"):
        problems.append("health section must cite health.class")
    if "wealth" in by_key and not cites("wealth", lambda r: r == "wealth.class"):
        problems.append("wealth section must cite wealth.class")
    if reportable_refs and "snapshot" in by_key and not cites("snapshot", lambda r: r in reportable_refs):
        problems.append("snapshot section must cite at least one reportable trait")

    # Narrative: exactly Luna's sections (1, 2, 3, 6, 7, 8), with the fixed titles.
    # Sections 4 and 5 are backend-rendered and must not be written by Luna.
    sections = split_sections(narrative)
    titles = SECTION_TITLES[language]
    if sorted(sections) != list(LUNA_SECTION_NUMBERS):
        problems.append(f"narrative must contain exactly sections {list(LUNA_SECTION_NUMBERS)} (found {sorted(sections)})")
    for key in LUNA_SECTION_KEYS:
        i = SECTION_KEYS.index(key) + 1
        if i in sections and sections[i][0] != titles[key]:
            problems.append(f"section {i} title {sections[i][0]!r} != {titles[key]!r}")
        if i in sections and not sections[i][1]:
            problems.append(f"section {i} is empty")

    # Content guardrails over EVERYTHING Luna authored.
    action_items = metadata.get("action_items") or []
    if not isinstance(action_items, list) or not all(isinstance(a, str) for a in action_items):
        problems.append("action_items must be a list of strings")
        action_items = []
    # Customer-visible Luna text (hero evidence bullets are backend-rendered; any
    # Luna-supplied `evidence` is discarded and never shown).
    ai_text = "\n".join([hero.get("interpretation", ""), *action_items, narrative or ""])
    for hit in _scan(ai_text, PROHIBITED):
        problems.append(f"prohibited content {hit!r}")
    for token in internal_label_leaks(ai_text):
        problems.append(f"internal label in customer text {token!r}")
    wealth_body = sections.get(SECTION_KEYS.index("wealth") + 1, ("", ""))[1]
    for rx in WEALTH_INSTABILITY:
        m = rx.search(wealth_body)
        if m:
            problems.append(f"wealth section implies instability/loss {m.group(0)!r} without backend evidence")

    if problems:
        raise ReportMetadataError("Spouse narrative rejected: " + "; ".join(problems))
    return {"metadata": metadata, "narrative": narrative, "sections": sections}


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def assemble_spouse_report(raw_text: str, evidence: dict, language: str) -> dict:
    """Validated Luna output + fixed backend parts, in the shape the existing
    PDF pipeline consumes (answer_hero / narrative / action items / disclaimer).
    Gemstone and Dasha timeline are OFF for this product."""
    v = validate_spouse_response(raw_text, evidence, language)
    attribution = build_attribution(evidence, language)
    hero = assemble_answer_hero(
        {"interpretation": v["metadata"]["answer_hero"]["interpretation"], "evidence": attribution["hero_evidence"]},
        deterministic_value=deterministic_hero_value(evidence, language),
    )
    hero["label"] = HERO_LABEL[language]
    titles = SECTION_TITLES[language]
    blocks = []
    for i, key in enumerate(SECTION_KEYS, start=1):
        if key in BACKEND_SECTION_KEYS:
            body = attribution[key]
        elif key in ("health", "wealth"):
            body = attribution[f"{key}_basis"] + "\n\n" + v["sections"][i][1]
        else:
            body = v["sections"][i][1]
        blocks.append(f"**{i}. {titles[key]}**\n{body}")
    blocks.append(f"**9. {titles['limitations']}**\n{LIMITATIONS_TEXT[language]}")
    return {
        "answer_hero": hero,
        "narrative": "\n\n".join(blocks),
        "action_items": [a.strip() for a in (v["metadata"].get("action_items") or []) if a.strip()][:5],
        "disclaimers": {k: DISCLAIMERS[k][language] for k in DISCLAIMERS},
        "section_refs": {s["key"]: list(s["evidence_refs"]) for s in v["metadata"]["sections"]},
        "gemstone": None,
        "timeline": None,
    }


def combined_disclaimer(language: str) -> str:
    """The three fixed DISCLAIMERS (general, health, financial) as the single
    string the existing PDF disclaimer slot renders."""
    return " ".join(DISCLAIMERS[k][language] for k in ("general", "health", "financial"))


def generate_spouse_narrative(evidence: dict, language: str, completion_fn: Optional[Callable] = None) -> dict:
    """Prompt -> Luna (existing client/model) -> validated assembly. `completion_fn`
    is injectable so tests never call the live API."""
    if completion_fn is None:
        from modules.payments.report_ai_client import generate_report_completion as completion_fn  # lazy: no client at import
    completion = completion_fn(build_spouse_prompt(evidence, language))
    content = getattr(completion, "content", completion)
    return assemble_spouse_report(content, evidence, language)
