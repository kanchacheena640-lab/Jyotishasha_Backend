"""Live bilingual Q3 prompt for the dedicated two-person report."""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List
from modules.payments.report_q3_batch1 import get_mandatory_disclaimer


class LovePromptBuilderError(Exception):
    pass


# The ONLY text that may appear as a section heading in the customer report (single source of truth for
# the prompt, the heading normalizer and the tests). The AI's instructions for each section are kept separate below.
RELATIONSHIP_SECTION_TITLES = {
    "en": (
        "Relationship Outlook",
        "Compatibility Snapshot",
        "Koota-Wise Compatibility Evidence",
        "Emotional & Relationship Dynamics",
        "5th & 7th House Context",
        "Strengths in the Connection",
        "Areas Requiring Attention",
        "Current Dasha Context",
        "Practical Relationship Guidance",
        "Summary",
    ),
    "hi": (
        "आपके Relationship का Outlook",
        "Compatibility का Snapshot",
        "Koota-wise Compatibility Evidence",
        "Emotional और Relationship Dynamics",
        "5th और 7th House का Context",
        "Connection की Strengths",
        "किन बातों पर ध्यान दें",
        "Current Dasha का Context",
        "Relationship के लिए Practical Guidance",
        "Summary",
    ),
}

_SECTION_INSTRUCTIONS = {
    "en": (
        "Synthesize the overall outlook and answer the purchased question, grounded in the Ashtakoot evidence.",
        "State the actual Ashtakoot total out of 36 exactly as given, and describe how complete the partner's birth data is in plain words, following the partner-birth-data rules above.",
        "Go through every available koota with its real result: the koota name, the obtained score out of its maximum and a concise interpretation. Never invent a missing koota and never print raw engine fields.",
        "Interpret the evidence for emotional and relationship dynamics without mind-reading either person.",
        "Use the primary person's own 5th and 7th house sign, lord and lord placement. These are the primary person's house facts, not the partner's.",
        "Describe the strengths that the evidence supports.",
        "Describe the areas requiring attention that the evidence supports.",
        "Use the real supplied Dasha windows as interpretive context only.",
        "Give practical, non-directive guidance. Never advise ending the relationship.",
        "Give a concise, balanced summary.",
    ),
    "hi": (
        "पूरा Outlook समझाएँ और customer के सवाल का सीधा जवाब दें, Ashtakoot evidence के आधार पर।",
        "असली Ashtakoot total /36 में जैसा दिया है वैसा ही लिखें, और ऊपर के partner-birth-data नियमों के हिसाब से आसान शब्दों में बताएँ कि partner का birth data कितना पूरा है।",
        "हर उपलब्ध Koota को उसके असली result के साथ समझाएँ: Koota का नाम, maximum में से मिला हुआ score और छोटा सा मतलब। कोई Koota खुद न बनाएँ और engine के raw fields कभी न लिखें।",
        "Evidence से Emotional और Relationship Dynamics समझाएँ, किसी के मन को पढ़ने का दावा किए बिना।",
        "Primary person के अपने 5th और 7th House की Rashi, House Lord और Lord की position इस्तेमाल करें। ये primary person के House facts हैं, partner के नहीं।",
        "Evidence जो Strengths support करता है, उन्हें बताएँ।",
        "Evidence जिन बातों पर ध्यान देने को कहता है, उन्हें बताएँ।",
        "असली दिए गए Dasha windows को सिर्फ समझाने के context की तरह इस्तेमाल करें।",
        "Practical, non-directive guidance दें। Relationship खत्म करने की सलाह कभी न दें।",
        "छोटा और संतुलित Summary दें।",
    ),
}

# Raw calculation fields that must never reach customer prose; the model still gets score / maximum and the
# koota-specific attributes (varna, gana, yoni, nadi, lords, bhakoot dosha) it needs for an accurate interpretation.
_RAW_KOOTA_FIELDS = frozenset({"status", "bride_to_groom_remainder", "groom_to_bride_remainder", "positions"})

_PARTNER_BIRTH_DATA = {
    "A_FULL_DUAL": ("full", "Complete birth details (date, time and place) were available and used for both people."),
    "B_DOB_ONLY_HYBRID": (
        "partial",
        "Only the partner's date of birth was available, so the partner's Moon position is approximated from it "
        "(a Moon-based comparison); the partner's ascendant, houses, birth time and place are not available.",
    ),
}

# Internal vocabulary that must never be customer-facing (exact identifiers -> deterministic detection).
INTERNAL_IDENTIFIERS = (
    "A_FULL_DUAL", "B_DOB_ONLY_HYBRID", "partner_data_mode", "partner_birth_data", "astro_facts", "compiled_report",
    "verdict_level", "user_house_lord_facts", "user_dasha_context", "invalid_kootas",
)
_PROMPT_ARTIFACTS = re.compile(r"private instruction|customer heading", re.I)
_ENGINE_STATUS_LABEL = re.compile(r"\bstatus\s*[:=]?\s*(?:pass|partial|fail|dosha|mixed)\b", re.I)
_FALLBACK_TALK = re.compile(r"DOB[- ]only|Moon[- ]only|hybrid|full[- ]dual", re.I)


def find_internal_leaks(text: str, *, full_data: bool) -> List[str]:
    """Internal terms found in customer-facing text. The DOB-only/fallback vocabulary is only a leak when the
    partner data was full (a genuine partial-data report must be free to state its limitation)."""
    if not text:
        return []
    found = [token for token in INTERNAL_IDENTIFIERS if token in text]
    if _PROMPT_ARTIFACTS.search(text):
        found.append("prompt instruction text")
    if _ENGINE_STATUS_LABEL.search(text):
        found.append("engine status label")
    if full_data and _FALLBACK_TALK.search(text):
        found.append("fallback-mode wording")
    return found


_NUMBERED_LINE = re.compile(r"^(?P<lead>\s*(?:\*\*)?)(?P<n>\d{1,2})[.)]\s+(?P<text>.+?)(?P<tail>\*{0,2})\s*$")
_SUFFIX_SEPARATOR = re.compile(r"^\s*(?:—|–|--|-|:|\()")


def normalize_relationship_headings(text: str, language: str) -> str:
    """Deterministic safety net: a numbered heading that starts with the approved title but carries an appended
    instruction fragment ("Title — instruction") is cut back to the approved title. Nothing else is touched."""
    titles = RELATIONSHIP_SECTION_TITLES["hi" if language == "hi" else "en"]
    lines = []
    for line in (text or "").split("\n"):
        m = _NUMBERED_LINE.match(line)
        if m and 1 <= int(m.group("n")) <= len(titles):
            title = titles[int(m.group("n")) - 1]
            body = m.group("text").strip()
            if body.lower().startswith(title.lower()) and _SUFFIX_SEPARATOR.match(body[len(title):]):
                line = f"{m.group('lead')}{m.group('n')}. {title}{m.group('tail')}"
        lines.append(line)
    return "\n".join(lines)


def _customer_ashtakoot(ashtakoot: Any) -> Dict[str, Any]:
    if not isinstance(ashtakoot, dict):
        return {}
    cleaned = dict(ashtakoot)
    kootas = ashtakoot.get("kootas")
    if isinstance(kootas, dict):
        cleaned["kootas"] = {
            name: ({k: v for k, v in koota.items() if k not in _RAW_KOOTA_FIELDS} if isinstance(koota, dict) else koota)
            for name, koota in kootas.items()
        }
    return cleaned


def _person_name(love_payload: Dict[str, Any], who: str) -> str:
    identity = love_payload.get("identity")
    person = identity.get(who) if isinstance(identity, dict) else None
    name = person.get("name") if isinstance(person, dict) else None
    return str(name).strip() if name else ""


def _names_line(language: str, primary: str, partner: str) -> str:
    p1 = primary.split()[0] if primary else ""
    p2 = partner.split()[0] if partner else ""
    if language == "hi":
        owner = primary or "primary person (report का owner)"
        other = partner or "partner"
        return (
            f"Report के owner {owner} हैं और partner {other} हैं। Evidence में groom/boy की values "
            f"{p1 or 'primary person'} की हैं और bride/girl की values {p2 or 'partner'} की।"
        )
    owner = primary or "the primary person (the report owner)"
    other = partner or "the partner"
    return (
        f"The report owner is {owner} and the partner is {other}. In the evidence, the groom/boy values belong to "
        f"{p1 or 'the primary person'} and the bride/girl values belong to {p2 or 'the partner'}."
    )


def _sections_block(language: str) -> str:
    lang = "hi" if language == "hi" else "en"
    label = "Private instruction, report में कभी न लिखें" if lang == "hi" else "Private instruction, never print"
    lines = []
    for number, (title, instruction) in enumerate(zip(RELATIONSHIP_SECTION_TITLES[lang], _SECTION_INSTRUCTIONS[lang]), 1):
        lines.append(f"{number}. {title}")
        lines.append(f"   [{label}: {instruction}]")
    return "\n".join(lines)


def build_love_premium_prompt(love_payload: Dict[str, Any]) -> str:
    if not isinstance(love_payload, dict):
        raise LovePromptBuilderError("Invalid love_payload")
    for key in ("compiled_report", "compatibility", "astro_facts"):
        if not isinstance(love_payload.get(key), dict):
            raise LovePromptBuilderError(f"{key} missing")
    language = "hi" if love_payload.get("language") == "hi" else "en"
    compatibility = love_payload["compatibility"]
    primary_name = _person_name(love_payload, "primary")
    partner_name = _person_name(love_payload, "partner")
    completeness, completeness_summary = _PARTNER_BIRTH_DATA.get(
        compatibility.get("case"), ("unavailable", "How complete the partner's birth data is has not been established."))
    # Allowlist excludes legacy compiler sections/signals and fallback scores. Internal mode names are never sent:
    # completeness is described in plain words instead.
    evidence: Dict[str, Any] = {}
    if primary_name or partner_name:
        evidence["people"] = {"primary_person": primary_name, "partner": partner_name}
    evidence["partner_birth_data"] = {"completeness": completeness, "summary": completeness_summary}
    evidence["ashtakoot"] = _customer_ashtakoot(compatibility.get("ashtakoot"))
    evidence["user_house_lord_facts"] = love_payload.get("user_house_lord_facts", [])
    evidence["user_dasha_context"] = love_payload.get("user_dasha_context") or {}
    names_line = _names_line(language, primary_name, partner_name)
    sections = _sections_block(language)
    if language == "hi":
        instructions = f"""आप एक समझदार और practical ज्योतिषी हैं, जो customer को उनका और उनके partner का chart मिलाकर समझा रहे हैं।
आपका सवाल: हम दोनों के उपलब्ध जन्म विवरण और असली Compatibility के प्रमाण हमारे Relationship के Outlook, Strengths, Challenges और Practical Guidance के बारे में क्या संकेत देते हैं?
{names_line}

==================================================
भाषा और लिखने का तरीका -- Modern Conversational Hindi (बहुत ज़रूरी)
==================================================
पूरी report सरल, बोलचाल वाली Hindi में, देवनागरी में लिखें -- जैसे कोई experienced astrologer सामने बैठकर customer को उनका chart समझा रहा हो: साफ़, गर्मजोशी वाली, modern और आसान।
- क्लिष्ट, संस्कृतनिष्ठ, academic या सरकारी-किताबी Hindi बिल्कुल न लिखें। सिर्फ इसलिए कोई कठिन शब्द न चुनें कि उसका Hindi अनुवाद मौजूद है।
- छोटे और सीधे वाक्य लिखें। एक वाक्य में एक ही बात रखें।
- जाने-पहचाने modern शब्द English में ही रखें, जैसे: Relationship, Compatibility, Marriage, Communication, Emotional, Practical, Current, Future, Timing, Period, Strengths, Challenges, Guidance, Decision, Growth.
- Astrology के शब्द भी आसान रखें: Lagna, Rashi, Moon, Nakshatra, Ashtakoot, Koota, Manglik, House, House Lord, 5th House, 7th House, Planet, Dasha, Mahadasha, Antardasha, Transit, Yog. "दशम भाव", "स्वामी", "स्थित", "अभिविन्यास", "प्रवृत्तियाँ" जैसे भारी शब्द न लिखें।
- Planet के नाम इस तरह लिखें: Sun (Surya), Moon (Chandra), Mars (Mangal), Mercury (Budh), Jupiter (Guru), Venus (Shukra), Saturn (Shani), Rahu, Ketu. पहली बार दोनों नाम दे सकते हैं, उसके बाद जहाँ natural लगे सिर्फ एक नाम रखें।
- House को "5th House", "7th House" की तरह लिखें। Sign के साथ "Aquarius राशि" लिखें। Dasha को "Mercury Mahadasha – Mercury Antardasha" की तरह लिखें और फिर आसान Hindi में मतलब समझाएँ।
- तारीखें: डेटा में जो तारीख YYYY-MM-DD में दी है, उसे बिल्कुल वैसे ही (exactly as given) लिखें। उसे किसी दूसरे numeric format में न बदलें और कोई नई तारीख न बनाएँ। तारीख को पढ़ने लायक शब्दों में system खुद दिखाएगा।
- भाषा आसान करें, Astrology की गहराई कम न करें। सारे facts -- Ashtakoot के अंक, House, Sign, Dasha की तारीखें -- नीचे दिए गए डेटा के अनुसार ही रखें। कोई नया fact न जोड़ें और डेटा में दिए fact को खुद calculate या बदलें नहीं।
- Tone encouraging और constructive रखें, जहाँ chart इसे support करे। डराने वाली या बढ़ा-चढ़ाकर बात न करें। Challenges को भी practical और सुलझाने लायक तरीके से बताएँ। कोई नकली positive बात न लिखें।
उदाहरण:
गलत: "भावनात्मक आवश्यकताएँ और लगाव की प्रवृत्तियाँ" -- सही: "आपकी Emotional Needs और Relationship में जुड़ने का तरीका"
गलत: "पंचम भाव के स्वामी शनि चतुर्थ भाव में स्थित हैं।" -- सही: "आपके 5th House का Lord Saturn है, जो 4th House में है।"

Customer के लिए नियम (सबसे ज़रूरी):
- आपकी लिखी हर बात एक paying customer पढ़ेगा। Internal field names, mode names, JSON keys, status labels और engine की technical भाषा कभी customer के सामने लिखने वाला content नहीं है। A_FULL_DUAL, B_DOB_ONLY_HYBRID, partner_data_mode, partner_birth_data, astro_facts, compiled_report, signals या verdict_level जैसे नाम, उनकी values या उनसे मिलता-जुलता कुछ भी कभी न लिखें।
- Evidence को आसान astrology भाषा में समझाएँ, engine के fields को दोहराएँ नहीं: "status pass", "status partial", raw remainder, raw position numbers या lookup keys कभी न लिखें। हर Koota के लिए उसका नाम, maximum में से मिला हुआ score और छोटा सा मतलब लिखें।
- जहाँ natural लगे, "bride/groom" की जगह पहले नाम इस्तेमाल करें। हर paragraph में नाम न दोहराएँ, लेकिन दोनों लोगों की बात करते समय नाम साफ़ लिखें। दोनों लोगों को कभी आपस में न बदलें।
- Partner का birth data कितना पूरा है, यह evidence के partner_birth_data field में है (यह सिर्फ आपके लिए है, customer के लिए नहीं)। अगर वह full कहता है: एक बार आसान शब्दों में बता सकते हैं कि दोनों लोगों के पूरे जन्म विवरण इस्तेमाल हुए हैं; DOB-only, Moon-only, fallback, hybrid या किसी mode का नाम न लिखें। अगर वह partial कहता है: सच-सच और साफ़ बताएँ कि partner का analysis सिर्फ जन्मतिथि से Moon के आधार पर है; partner का Lagna, House, जन्म समय या जन्म स्थान कभी न बनाएँ और यह न कहें कि पूरे विवरण इस्तेमाल हुए। अगर जानकारी उपलब्ध नहीं है, तो बिना अंदाज़ा लगाए साफ़ बता दें।
- जो evidence में दिया ही नहीं गया (जैसे Manglik की स्थिति), उसे न बनाएँ और न मानें।

JSON की keys और hero का label "Relationship Outlook" वैसा ही रखें, उसे Hindi में न बदलें। hero का value एक शांत, गुणात्मक वर्णन हो; कोई percentage, अंक (number) या पक्की भविष्यवाणी नहीं।
Evidence का क्रम: पहले असली Ashtakoot का result, फिर primary person के 5th/7th House के facts, फिर उपलब्ध असली Dasha का context। Ashtakoot का असली कुल score /36 सिर्फ supporting evidence है, hero value नहीं। जो Kootas उपलब्ध हैं, उनके असली अंक और details ही इस्तेमाल करें; कोई Koota या fact अपनी तरफ़ से न बनाएँ। total को percentage में न बदलें।
खाली 5th या 7th House को भी उसकी Rashi, House Lord और Lord की position से समझाएँ; Planets की मौजूदगी दूसरे नंबर पर है। ये primary person के Houses हैं, partner के नहीं। सिर्फ उपलब्ध Aspects का इस्तेमाल करें।
Dasha सिर्फ समझाने के लिए context है; Relationship शुरू होने, Marriage, दोबारा मिलने या अलग होने की कोई निश्चित तारीख, साल या उम्र न बताएँ। असली उपलब्ध तारीखें डेटा में दिए गए रूप (YYYY-MM-DD) में ही रखें।
किसी के निजी विचार, भावनाएँ, इरादे, निष्ठा या आगे के व्यवहार को जानने का दावा न करें। धोखे, बेवफाई, विश्वासघात, partner के छोड़ने या संबंध-विच्छेद की भविष्यवाणी न करें। अवसाद या चिंता का diagnosis न करें, आघात (trauma) का दावा न करें। Relationship खत्म करने की सलाह न दें। Marriage या दोबारा मिलने की गारंटी न दें। कोई gemstone या रत्न की सलाह न दें।
हर section में निष्कर्ष, उपलब्ध astrology का आधार और Practical मतलब दें। Depth असली दो-लोगों वाले Ashtakoot evidence से आए, बेवजह की लंबाई से नहीं।
नीचे ठीक 10 numbered sections हैं। हर numbered line customer के लिए heading है: उसे बिल्कुल वैसा ही, अपनी अलग line में, बिना कुछ जोड़े लिखें। उसके नीचे bracket वाली lines सिर्फ आपके लिए private instructions हैं: उन्हें follow करें, लेकिन उन्हें कभी न लिखें, न दोहराएँ और न किसी heading के साथ जोड़ें:
{sections}
नीचे दिया Disclaimer system खुद जोड़ेगा; उसे report में दोबारा न लिखें। कोई sales message न जोड़ें; आखिरी App Download वाला हिस्सा renderer खुद जोड़ेगा।"""
    else:
        instructions = f"""Purchased question: What do our available birth details and real compatibility evidence indicate about our relationship outlook, strengths, challenges and practical guidance?
{names_line}
Write in English. Keep hero label exactly Relationship Outlook. Its value is a calm qualitative synthesis, never a percentage, score, or deterministic future prediction.
Evidence hierarchy: real Ashtakoot evidence first, the primary person's 5th/7th house facts second, real available Dasha context third. Use the actual Ashtakoot total /36 as supporting evidence only, never the hero value. Use actual koota scores and details; never fabricate missing kootas or convert the total to a percentage.

CUSTOMER-FACING CONTRACT (highest priority)
- Everything you write is read by a paying customer. Internal field names, mode names, JSON keys, status labels and engine implementation terminology are never customer-facing content. Never write identifiers such as A_FULL_DUAL, B_DOB_ONLY_HYBRID, partner_data_mode, partner_birth_data, astro_facts, compiled_report, signals or verdict_level, their values, or anything like them.
- Interpret the evidence in plain astrology language; do not dump engine fields. Never write labels such as "status pass" or "status partial", raw remainders, raw position numbers or lookup keys. For each koota give its name, the obtained score out of its maximum and a concise interpretation.
- Where natural, use the first names instead of "bride" and "groom". Do not repeat names in every paragraph, but name the two individuals clearly wherever you discuss them, and never swap them.
- The evidence field partner_birth_data tells you how complete the partner's birth data is (for you only, not for the customer). If it says full: you may say once, in plain words, that full birth details for both people were used; do not mention DOB-only, Moon-only, fallback, hybrid or any mode name. If it says partial: state truthfully and clearly that the partner analysis is Moon-based from the date of birth only; never invent the partner's ascendant, houses, birth time or place, and never say that full details were used. If it says unavailable: say so plainly without guessing.
- Never state or imply anything that is not in the supplied evidence (for example a Manglik status).

An empty 5th/7th house remains analyzable through sign, lord and lord placement. Occupants are secondary. These are the primary person's house facts, not the partner's. Use aspects only where supplied.
Dasha is interpretive context only. No exact relationship event timing: never predict a meeting, marriage, reconciliation, separation or breakup date/year/age. Copy real supplied dates exactly as given (YYYY-MM-DD); never convert them to another numeric format.
No private-thought inference: do not infer another person's thoughts, feelings, intentions, fidelity or future actions. No cheating/betrayal certainty, partner-will-leave claim, breakup prediction, depression/anxiety diagnosis or trauma claim. Do not advise ending a relationship. Do not guarantee marriage or reconciliation. No gemstone recommendations.
For each section give the finding, supplied astrological basis and practical meaning. Depth must come from real two-person compatibility evidence, not filler.
Use exactly these ten numbered sections. Each numbered line is the CUSTOMER HEADING: copy it exactly, on its own line, with nothing added. The bracketed lines beneath are PRIVATE INSTRUCTIONS for you: follow them, but never print, paraphrase or attach them to a heading:
{sections}
The backend renders the exact disclaimer below; do not repeat it in the narrative. No sales CTA; the renderer supplies the final app-download component."""
    wire = """
Return exactly this machine-readable format. No Markdown fences.
===META===
{"hero":{"label":"Relationship Outlook","value":"<qualitative synthesis>","interpretation":"<evidence-grounded sentence>","evidence":["<actual supplied fact>"],"action_items":["<practical guidance>"]}}
===REPORT===
<full ten-section narrative>
Only the listed hero fields are allowed. Do not emit compatibility percentages or heuristic scores in metadata or narrative.
"""
    disclaimer = get_mandatory_disclaimer("relationship_future_non_certainty_mandatory", language)
    return instructions + wire + "\nDisclaimer:\n" + disclaimer + "\nDeterministic evidence:\n" + json.dumps(evidence, ensure_ascii=False)
