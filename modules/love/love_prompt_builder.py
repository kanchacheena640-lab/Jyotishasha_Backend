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
        instructions = """खरीदा गया प्रश्न: हमारे उपलब्ध जन्म विवरण और वास्तविक अनुकूलता प्रमाण हमारे संबंध की संभावनाओं, खूबियों, चुनौतियों और व्यावहारिक मार्गदर्शन के बारे में क्या संकेत देते हैं?
पूरी रिपोर्ट स्वाभाविक हिंदी में लिखें; JSON कुंजियाँ और hero का label Relationship Outlook ही रखें। value शांत, गुणात्मक आकलन हो; कोई प्रतिशत, अंक या निश्चित भविष्यवाणी नहीं।
प्रमाण का क्रम: वास्तविक अष्टकूट परिणाम, फिर उपयोगकर्ता के पाँचवें/सातवें भाव के तथ्य, फिर उपलब्ध वास्तविक दशा संदर्भ। अष्टकूट का वास्तविक कुल /36 केवल सहायक प्रमाण है, hero value नहीं। उपलब्ध कूटों के वास्तविक अंक और विवरण ही इस्तेमाल करें; गायब कूट या तथ्य न बनाएँ। प्रतिशत में न बदलें।
A_FULL_DUAL में साथी के पूर्ण जन्म विवरण उपलब्ध हैं। B_DOB_ONLY_HYBRID में साथी की केवल जन्मतिथि उपलब्ध है: चंद्र-आधारित आकलन की सीमा बताएँ, साथी का लग्न, भाव, जन्म समय या स्थान न गढ़ें। मोड उपलब्ध न हो तो अनुमान न लगाएँ।
खाली पाँचवाँ/सातवाँ भाव भी राशि, स्वामी और स्वामी की स्थिति से समझाएँ; ग्रहों की उपस्थिति द्वितीयक है। ये उपयोगकर्ता के भाव हैं, साथी के नहीं। केवल उपलब्ध दृष्टियों का प्रयोग करें।
दशा केवल व्याख्यात्मक संदर्भ है; संबंध बनने, विवाह, पुनर्मिलन या अलगाव की निश्चित तारीख, वर्ष या उम्र न बताएँ। वास्तविक उपलब्ध तारीखें DD/MM/YYYY में रखें।
किसी के निजी विचार, भावनाएँ, इरादे, निष्ठा या भविष्य का व्यवहार जानने का दावा न करें। धोखे, बेवफाई, विश्वासघात, साथी के छोड़ने या संबंध-विच्छेद की भविष्यवाणी न करें। अवसाद/चिंता का निदान या आघात का दावा न करें। संबंध खत्म करने की सलाह न दें। विवाह या पुनर्मिलन की गारंटी न दें। रत्न की सलाह न दें।
हर खंड में निष्कर्ष, उपलब्ध ज्योतिषीय आधार और व्यावहारिक अर्थ दें। गहराई वास्तविक दो-व्यक्ति अष्टकूट प्रमाण से आए, अनावश्यक विस्तार से नहीं। नीचे के ठीक दस क्रमांकित खंड रखें:
1. संबंध की संभावनाएँ
2. अनुकूलता का सार — वास्तविक कुल /36 और साथी के विवरण की सीमा
3. कूटवार अनुकूलता प्रमाण — प्रत्येक उपलब्ध कूट का वास्तविक परिणाम
4. भावनात्मक और संबंध संबंधी गतिशीलता — प्रमाण से व्याख्या, मन पढ़ने का दावा नहीं
5. पाँचवें और सातवें भाव का संदर्भ — उपयोगकर्ता की राशि, स्वामी, स्वामी की स्थिति
6. संबंध की खूबियाँ
7. ध्यान देने योग्य क्षेत्र
8. वर्तमान दशा का संदर्भ
9. संबंध के लिए व्यावहारिक मार्गदर्शन
10. सारांश
नीचे दिया अस्वीकरण backend जोड़ेगा; मुख्य विवरण में उसे दोहराएँ नहीं। कोई बिक्री संदेश न जोड़ें; अंतिम ऐप डाउनलोड घटक रेंडरर जोड़ेगा।"""
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
