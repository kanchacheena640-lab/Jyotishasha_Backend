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
REQUIRED_HERO_FIELDS = ("label", "value", "interpretation", "evidence")

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


def _factor_text(v: dict) -> str:
    phrase = FACTOR_PHRASE.get(v.get("factor"))
    if phrase is None:
        raise ReportMetadataError(f"spouse evidence: unknown factor {v.get('factor')!r}")
    planet = _require(v["planet"], GRAHAS, "planet") if v.get("planet") else None
    sign = _require(v["sign"], SIGN_ORDER, "sign") if v.get("sign") else None
    return phrase.format(planet=planet, sign=sign)


def build_evidence_block(evidence: dict) -> tuple:
    """Deterministic, human-readable evidence digest with [ref] ids.
    Returns (text, allowed_refs). Only REPORTABLE traits get a reference --
    a NOT_INDICATED trait is never offered to Luna."""
    if not isinstance(evidence, dict) or evidence.get("schema_version") != EVIDENCE_SCHEMA:
        raise ReportMetadataError("spouse narrative requires a spouse_evidence_v1 payload")
    lines, refs = [], []

    def ref(rid, text):
        refs.append(rid)
        lines.append(f"[{rid}] {text}")

    d1 = evidence["chart_facts"]["d1"]
    d9 = evidence["chart_facts"]["d9"]
    dk = evidence["chart_facts"]["darakaraka"]

    lines.append("== Nature traits (only these may be described; anything not listed is NOT indicated) ==")
    for t in evidence["nature"]["traits"]:
        dim = _require(t["dimension"], DIMENSION_POLES, "dimension")
        klass = _require(t["class"], TRAIT_CLASSES, "trait class")
        recon = _require(t["d1_d9"], RECONCILIATIONS, "reconciliation")
        if not t.get("reportable") or klass == "NOT_INDICATED":
            continue
        a, b = DIMENSION_POLES[dim]
        if klass == "MIXED":
            factors_a = "; ".join(_factor_text(v) for v in t["evidence"] if v["pole"] == a) or "none"
            factors_b = "; ".join(_factor_text(v) for v in t["evidence"] if v["pole"] == b) or "none"
            ref(f"nature.{dim}", f"{dim}: MIXED (navamsa: {recon}). Toward '{a}': {factors_a}. Toward '{b}': {factors_b}.")
        else:
            direction = _require(t["direction"], (a, b), "direction")
            quality = _require(t["expression_quality"], ("well_supported", "uneven", "neutral"), "expression quality")
            factors = "; ".join(_factor_text(v) for v in t["evidence"] if v["pole"] == direction)
            ref(f"nature.{dim}", f"{dim}: {klass} toward '{direction}' (navamsa: {recon}; expression: {quality}). Basis: {factors}.")
    snap = [f"{_require(s['dimension'], DIMENSION_POLES, 'dimension')}={s['direction']}" for s in evidence["nature"]["snapshot_traits"]]
    lines.append(f"Snapshot traits (strongest reportable): {', '.join(snap) if snap else 'none -- the evidence is mostly mixed'}")

    lines.append("== Birth chart (D1) facts ==")
    ref("chart_facts.d1.seventh_sign", f"Lagna {_require(d1['lagna'], SIGN_ORDER, 'sign')}; 7th-house sign {_require(d1['seventh_sign'], SIGN_ORDER, 'sign')}")
    ref("chart_facts.d1.seventh_lord",
        f"7th lord {_require(d1['seventh_lord'], GRAHAS, 'planet')} in {_require(d1['seventh_lord_sign'], SIGN_ORDER, 'sign')}, "
        f"house {int(d1['seventh_lord_house'])} (house {int(d1['seventh_lord_house_from_seventh'])} counted from the 7th); "
        f"dignity {d1['seventh_lord_dignity']}")
    if d1["occupants_7th"]:
        ref("chart_facts.d1.occupants_7th", f"Planets in the 7th house: {', '.join(_planets(d1['occupants_7th']))}")
    else:
        lines.append("The 7th house has no planet in it -- it is still read through its sign, its lord and the planets aspecting it.")
    if d1["aspects_on_7th"]:
        ref("chart_facts.d1.aspects_on_7th", f"Planets aspecting the 7th house: {', '.join(_planets(d1['aspects_on_7th']))}")
    if d1["conjunct_with_7th_lord"]:
        ref("chart_facts.d1.conjunct_with_7th_lord", f"Planets conjunct with the 7th lord: {', '.join(_planets(d1['conjunct_with_7th_lord']))}")
    if d1["aspects_on_7th_lord"]:
        ref("chart_facts.d1.aspects_on_7th_lord", f"Planets aspecting the 7th lord: {', '.join(_planets(d1['aspects_on_7th_lord']))}")
    for karaka in ("venus", "jupiter"):
        k = d1[karaka]
        if k["link_to_7th"]:
            ref(f"chart_facts.d1.{karaka}", f"{karaka.title()} in {_require(k['sign'], SIGN_ORDER, 'sign')} (house {int(k['house'])}), linked to the 7th by: {', '.join(k['link_to_7th'])}")

    lines.append("== Navamsa (D9) facts -- confirm or refine only, never override D1 ==")
    ref("chart_facts.d9.seventh_sign", f"Navamsa Lagna {_require(d9['lagna'], SIGN_ORDER, 'sign')}; Navamsa 7th sign {_require(d9['seventh_sign'], SIGN_ORDER, 'sign')}")
    ref("chart_facts.d9.seventh_lord",
        f"Navamsa 7th lord {_require(d9['seventh_lord'], GRAHAS, 'planet')} in {_require(d9['seventh_lord_d9_sign'], SIGN_ORDER, 'sign')} "
        f"(Navamsa house {int(d9['seventh_lord_d9_house'])}); dignity {d9['seventh_lord_d9_dignity']}")
    if d9["occupants_d9_7th"]:
        ref("chart_facts.d9.occupants_d9_7th", f"Planets in the Navamsa 7th house: {', '.join(_planets(d9['occupants_d9_7th']))}")
    ref("chart_facts.darakaraka", f"Darakaraka (supporting only): {', '.join(_planets(dk['planets']))}{' (exact tie)' if dk['tie'] else ''}")

    lines.append("== Spouse health tendency (use ONLY this class) ==")
    h = evidence["health"]
    ref("health.class", f"Health class: {_require(h['class'], HEALTH_CLASSES, 'health class')}")
    for item in h["primary_items"] + h["secondary_items"]:
        ref(f"health.{item['id']}", f"{item['item']}: {_require(item['result'], ITEM_RESULTS, 'item result')}")

    lines.append("== Spouse financial-background tendency (use ONLY this class) ==")
    w = evidence["wealth"]
    ref("wealth.class", f"Wealth class: {_require(w['class'], WEALTH_CLASSES, 'wealth class')}")
    for key in ("resources", "income_growth", "professional_standing"):
        d = w["dimensions"][key]
        ref(f"wealth.{key}", f"{key} ({d['role']}; spouse's house {int(d['spouse_house'])} = your house {int(d['native_house'])}, "
                             f"sign {_require(d['sign'], SIGN_ORDER, 'sign')}): {_require(d['state'], DIM_STATES, 'state')}")
    if w["unconventional_pattern"]:
        ref("wealth.unconventional_pattern", "unconventional_pattern: TRUE -- non-traditional, changing or unusual channels")
    return "\n".join(lines), refs


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
    for key in SECTION_KEYS:
        if key not in by_key:
            problems.append(f"section {key!r} missing from META")
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
    if "navamsa" in by_key and not cites("navamsa", lambda r: r.startswith("chart_facts.d9.") or r == "chart_facts.darakaraka"):
        problems.append("navamsa section must cite Navamsa or Darakaraka evidence")
    if "chart_basis" in by_key and not cites("chart_basis", lambda r: r.startswith("chart_facts.d1.")):
        problems.append("chart_basis section must cite birth-chart evidence")
    if reportable_refs and "snapshot" in by_key and not cites("snapshot", lambda r: r in reportable_refs):
        problems.append("snapshot section must cite at least one reportable trait")

    # Narrative: sections 1-8 present, in order, with the fixed titles.
    sections = split_sections(narrative)
    titles = SECTION_TITLES[language]
    if sorted(sections) != list(range(1, len(SECTION_KEYS) + 1)):
        problems.append(f"narrative must contain exactly sections 1-{len(SECTION_KEYS)} (found {sorted(sections)})")
    for i, key in enumerate(SECTION_KEYS, start=1):
        if i in sections and sections[i][0] != titles[key]:
            problems.append(f"section {i} title {sections[i][0]!r} != {titles[key]!r}")
        if i in sections and not sections[i][1]:
            problems.append(f"section {i} is empty")

    # Content guardrails over EVERYTHING Luna authored.
    action_items = metadata.get("action_items") or []
    if not isinstance(action_items, list) or not all(isinstance(a, str) for a in action_items):
        problems.append("action_items must be a list of strings")
        action_items = []
    ai_text = "\n".join([hero.get("interpretation", ""), *hero.get("evidence", []), *action_items, narrative or ""])
    for hit in _scan(ai_text, PROHIBITED):
        problems.append(f"prohibited content {hit!r}")
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
    hero = assemble_answer_hero(
        {k: v["metadata"]["answer_hero"][k] for k in ("interpretation", "evidence")},
        deterministic_value=deterministic_hero_value(evidence, language),
    )
    hero["label"] = HERO_LABEL[language]
    limitations = f"**9. {SECTION_TITLES[language]['limitations']}**\n{LIMITATIONS_TEXT[language]}"
    return {
        "answer_hero": hero,
        "narrative": v["narrative"].rstrip() + "\n\n" + limitations,
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
