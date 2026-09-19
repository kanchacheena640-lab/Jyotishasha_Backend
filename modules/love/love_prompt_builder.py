"""Live bilingual Q3 prompt for the dedicated two-person report."""
from __future__ import annotations
import json
from typing import Any, Dict
from modules.payments.report_q3_batch1 import get_mandatory_disclaimer


class LovePromptBuilderError(Exception):
    pass


def build_love_premium_prompt(love_payload: Dict[str, Any]) -> str:
    if not isinstance(love_payload, dict):
        raise LovePromptBuilderError("Invalid love_payload")
    for key in ("compiled_report", "compatibility", "astro_facts"):
        if not isinstance(love_payload.get(key), dict):
            raise LovePromptBuilderError(f"{key} missing")
    language = "hi" if love_payload.get("language") == "hi" else "en"
    compatibility = love_payload["compatibility"]
    # Allowlist excludes legacy compiler sections/signals and fallback scores.
    evidence = {
        "partner_data_mode": compatibility.get("case"),
        "ashtakoot": compatibility.get("ashtakoot") or {},
        "user_house_lord_facts": love_payload.get("user_house_lord_facts", []),
        "user_dasha_context": love_payload.get("user_dasha_context") or {},
    }
    if language == "hi":
        instructions = """आप एक समझदार और practical ज्योतिषी हैं, जो customer को उनका और उनके partner का chart मिलाकर समझा रहे हैं।
आपका सवाल: हम दोनों के उपलब्ध जन्म विवरण और असली Compatibility के प्रमाण हमारे Relationship के Outlook, Strengths, Challenges और Practical Guidance के बारे में क्या संकेत देते हैं?

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
- कोई भी तारीख हमेशा DD/MM/YYYY format में लिखें (जैसे 01/07/2025)। डेटा में जो तारीख YYYY-MM-DD में दी है, उसे इसी format में बदलकर लिखें।
- भाषा आसान करें, Astrology की गहराई कम न करें। सारे facts -- Ashtakoot के अंक, House, Sign, Dasha की तारीखें -- नीचे दिए गए डेटा के अनुसार ही रखें। कोई नया fact न जोड़ें और डेटा में दिए fact को खुद calculate या बदलें नहीं।
- Tone encouraging और constructive रखें, जहाँ chart इसे support करे। डराने वाली या बढ़ा-चढ़ाकर बात न करें। Challenges को भी practical और सुलझाने लायक तरीके से बताएँ। कोई नकली positive बात न लिखें।
उदाहरण:
गलत: "भावनात्मक आवश्यकताएँ और लगाव की प्रवृत्तियाँ" -- सही: "आपकी Emotional Needs और Relationship में जुड़ने का तरीका"
गलत: "पंचम भाव के स्वामी शनि चतुर्थ भाव में स्थित हैं।" -- सही: "आपके 5th House का Lord Saturn है, जो 4th House में है।"

JSON की keys और hero का label "Relationship Outlook" वैसा ही रखें, उसे Hindi में न बदलें। hero का value एक शांत, गुणात्मक वर्णन हो; कोई percentage, अंक (number) या पक्की भविष्यवाणी नहीं।
Evidence का क्रम: पहले असली Ashtakoot का result, फिर user के 5th/7th House के facts, फिर उपलब्ध असली Dasha का context। Ashtakoot का असली कुल score /36 सिर्फ supporting evidence है, hero value नहीं। जो Kootas उपलब्ध हैं, उनके असली अंक और details ही इस्तेमाल करें; कोई Koota या fact अपनी तरफ़ से न बनाएँ। total को percentage में न बदलें।
A_FULL_DUAL का मतलब है कि partner के पूरे जन्म विवरण उपलब्ध हैं। B_DOB_ONLY_HYBRID का मतलब है कि partner की सिर्फ जन्मतिथि उपलब्ध है: Moon-based analysis की limitation साफ़ बताएँ, और partner का Lagna, House, जन्म समय या जन्म स्थान अपनी तरफ़ से न बनाएँ। अगर mode उपलब्ध न हो, तो अंदाज़ा न लगाएँ।
खाली 5th या 7th House को भी उसकी Rashi, House Lord और Lord की position से समझाएँ; Planets की मौजूदगी दूसरे नंबर पर है। ये user के Houses हैं, partner के नहीं। सिर्फ उपलब्ध Aspects का इस्तेमाल करें।
Dasha सिर्फ समझाने के लिए context है; Relationship शुरू होने, Marriage, दोबारा मिलने या अलग होने की कोई निश्चित तारीख, साल या उम्र न बताएँ। असली उपलब्ध तारीखें DD/MM/YYYY में रखें।
किसी के निजी विचार, भावनाएँ, इरादे, निष्ठा या आगे के व्यवहार को जानने का दावा न करें। धोखे, बेवफाई, विश्वासघात, partner के छोड़ने या संबंध-विच्छेद की भविष्यवाणी न करें। अवसाद या चिंता का diagnosis न करें, आघात (trauma) का दावा न करें। Relationship खत्म करने की सलाह न दें। Marriage या दोबारा मिलने की गारंटी न दें। कोई gemstone या रत्न की सलाह न दें।
हर section में निष्कर्ष, उपलब्ध astrology का आधार और Practical मतलब दें। Depth असली दो-लोगों वाले Ashtakoot evidence से आए, बेवजह की लंबाई से नहीं। नीचे के ठीक 10 numbered sections रखें:
1. आपके Relationship का Outlook
2. Compatibility का Snapshot — असली कुल /36 और partner details की limitation
3. Koota-wise Compatibility Evidence — हर उपलब्ध Koota का असली result
4. Emotional और Relationship Dynamics — evidence से समझाएँ, मन पढ़ने का दावा नहीं
5. 5th और 7th House का Context — user की Rashi, House Lord और Lord की position
6. Connection की Strengths
7. किन बातों पर ध्यान दें
8. Current Dasha का Context
9. Relationship के लिए Practical Guidance
10. Summary
नीचे दिया Disclaimer system खुद जोड़ेगा; उसे report में दोबारा न लिखें। कोई sales message न जोड़ें; आखिरी App Download वाला हिस्सा renderer खुद जोड़ेगा।"""
    else:
        instructions = """Purchased question: What do our available birth details and real compatibility evidence indicate about our relationship outlook, strengths, challenges and practical guidance?
Write in English. Keep hero label exactly Relationship Outlook. Its value is a calm qualitative synthesis, never a percentage, score, or deterministic future prediction.
Evidence hierarchy: real Ashtakoot evidence first, USER 5th/7th house facts second, real available Dasha context third. Use the actual Ashtakoot total /36 as supporting evidence only, never the hero value. Use actual koota scores and details; never fabricate missing kootas or convert the total to a percentage.
A_FULL_DUAL means full partner birth details. B_DOB_ONLY_HYBRID means DOB-only partner data: clearly explain the Moon-based limitation; never invent partner ascendant, houses, time or place. If the mode is unavailable, say so.
An empty 5th/7th house remains analyzable through sign, lord and lord placement. Occupants are secondary. These are USER house facts, not partner houses. Use aspects only where supplied.
Dasha is interpretive context only. No exact relationship event timing: never predict a meeting, marriage, reconciliation, separation or breakup date/year/age. Format real supplied dates DD/MM/YYYY.
No private-thought inference: do not infer another person's thoughts, feelings, intentions, fidelity or future actions. No cheating/betrayal certainty, partner-will-leave claim, breakup prediction, depression/anxiety diagnosis or trauma claim. Do not advise ending a relationship. Do not guarantee marriage or reconciliation. No gemstone recommendations.
For each section give the finding, supplied astrological basis and practical meaning. Depth must come from real two-person compatibility evidence, not filler. Use exactly these ten numbered sections:
1. Relationship Outlook
2. Compatibility Snapshot — actual total /36 and partner data completeness
3. Koota-Wise Compatibility Evidence — actual results for each available koota
4. Emotional & Relationship Dynamics — evidence-based interpretation, no mind-reading
5. 5th & 7th House Context — USER sign, lord and lord placement
6. Strengths in the Connection
7. Areas Requiring Attention
8. Current Dasha Context
9. Practical Relationship Guidance
10. Summary
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
