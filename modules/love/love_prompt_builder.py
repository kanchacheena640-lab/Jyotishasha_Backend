# Path: modules/love/love_prompt_builder.py
# Jyotishasha — Love Premium Prompt Builder (FINAL | LOCKED)

from __future__ import annotations
from typing import Dict, Any


class LovePromptBuilderError(Exception):
    pass


def build_love_premium_prompt(love_payload: Dict[str, Any]) -> str:
    if not isinstance(love_payload, dict):
        raise LovePromptBuilderError("Invalid love_payload")

    language = love_payload.get("language", "en")
    language = "hi" if language == "hi" else "en"

    compiled = love_payload.get("compiled_report")
    compatibility = love_payload.get("compatibility")
    astro = love_payload.get("astro_facts")

    if not isinstance(compiled, dict):
        raise LovePromptBuilderError("compiled_report missing")
    if not isinstance(compatibility, dict):
        raise LovePromptBuilderError("compatibility missing")
    if not isinstance(astro, dict):
        raise LovePromptBuilderError(
            "astro_facts missing — premium narration requires astrological grounding"
        )

    verdict = compiled.get("verdict", {})
    sections = compiled.get("sections", [])
    disclaimers = compiled.get("disclaimers", [])

    # ================= HEADER =================
    if language == "hi":
        header = (
            "आप एक अनुभवी, व्यावहारिक और ईमानदार वैदिक ज्योतिषी हैं।\n"
            "नीचे दिए गए *केवल* संरचित ज्योतिषीय तथ्यों के आधार पर "
            "एक गहन, grounded और non-generic Love → Marriage Life Report लिखें।\n\n"
            "कड़े नियम:\n"
            "- केवल दिए गए ग्रह, भाव, दशा और आपसी संबंधों पर आधारित निष्कर्ष दें\n"
            "- कोई अनुमान, डर या गारंटी नहीं\n"
            "- हर सेक्शन स्पष्ट ज्योतिषीय कारणों से जुड़ा हो\n"
            "- रिपोर्ट ₹299 की प्रीमियम रिपोर्ट जैसी लगे\n"
            "- यदि किसी बिंदु का डेटा न हो, तो neutral और सीमित भाषा रखें\n\n"
        )
    else:
        header = (
            "You are an experienced, grounded Vedic astrologer.\n"
            "Using ONLY the structured astrological facts below, "
            "write a deep, non-generic Love → Marriage Life Report.\n\n"
            "Strict rules:\n"
            "- Conclusions must be tied to provided planets, houses, dashas, links\n"
            "- No fear-based language or guarantees\n"
            "- Every section must cite clear astrological reasons\n"
            "- Must feel worth a ₹299 premium report\n"
            "- If data is missing, remain neutral (do not generalize)\n\n"
        )

    body: list[str] = []

    # ================= OVERALL VERDICT =================
    body.append("# OVERALL RELATIONSHIP VERDICT")
    body.append(
        f"Compatibility Level: {verdict.get('level')}\n"
        f"Verdict Basis: {verdict.get('reason_line')}"
    )

    # ================= CORE COMPATIBILITY =================
    body.append("\n# CORE COMPATIBILITY (ASHTAKOOT)")
    body.append(
        "Analyse emotional bonding, mental alignment, physical harmony, "
        "and marriage stability strictly using the following Ashtakoot data:\n"
        f"{compatibility}"
    )

    # ================= LOVE → MARRIAGE FLOW =================
    lf = astro.get("love_flow", {})
    body.append("\n# LOVE → MARRIAGE FLOW")
    body.append(
        f"""
5th House Lord: {lf.get('lord_5')}
5th Lord Position (House/Sign): {lf.get('lord_5_position')}

7th House Lord: {lf.get('lord_7')}
7th Lord Position (House/Sign): {lf.get('lord_7_position')}

Planets in 5th House: {lf.get('planets_in_5')}
Planets in 7th House: {lf.get('planets_in_7')}

5–7 House Connection / Aspect: {lf.get('connection_5_7')}
Current Dasha Related to 5th/7th Lord: {lf.get('current_dasha_related')}

Explain how love initiates, deepens, faces obstacles, and converts (or delays) into marriage.
Every statement must be justified from the above facts.
"""
    )

    # ================= LOVE vs ARRANGED =================
    lva = astro.get("love_vs_arranged", {})
    body.append("\n# LOVE vs ARRANGED MARRIAGE PROBABILITY")
    body.append(
        f"""
Rahu in 5th or 7th House: {lva.get('rahu_in_5_or_7')}
Venus Involvement (placement/support): {lva.get('venus_involved')}
Direct 5–7 Lord Connection: {lva.get('direct_5_7_link')}
Family House Support (2/7/11): {lva.get('family_house_support')}

Clearly conclude whether love marriage, arranged marriage,
or a mixed path is more likely — with reasons.
"""
    )

    # ================= STRENGTHS & RISKS =================
    sr = astro.get("strength_risk", {})
    body.append("\n# STRENGTHS & RISKS")
    body.append(
        f"""
Benefic Planetary Support: {sr.get('benefic_support')}
Malefic Afflictions: {sr.get('malefic_affliction')}
Manglik Presence: {sr.get('manglik')}
Overall Relationship Verdict Level: {sr.get('verdict_level')}

Highlight genuine strengths and practical risks without exaggeration.
"""
    )

    # ================= REMEDIES & GUIDANCE =================
    rm = astro.get("remedies", {})
    body.append("\n# REMEDIES & GUIDANCE")
    body.append(
        f"""
Weak House (if any): {rm.get('weak_house')}
Weak Lord (if any): {rm.get('weak_lord')}
Current Mahadasha / Antardasha: {rm.get('current_dasha')}

Suggest only relevant, practical Vedic remedies.
Avoid superstition or generic advice.
"""
    )

    # ================= EXTRA INSIGHTS (FROM COMPILER) =================
    if sections:
        body.append("\n# ADDITIONAL ASTROLOGICAL INSIGHTS")
        for sec in sections:
            body.append(f"\n## {sec.get('title')}")
            body.append(f"Context: {sec.get('summary')}")
            for b in (sec.get("bullets") or []):
                body.append(f"- {b}")

    # ================= DISCLAIMERS =================
    if disclaimers:
        body.append("\n# IMPORTANT NOTES")
        for d in disclaimers:
            body.append(f"- {d.get('text')}")

    # ================= FOOTER =================
    if language == "hi":
        footer = (
            "\n\nअब ऊपर दिए गए सभी ज्योतिषीय तथ्यों को जोड़कर "
            "एक साफ़, flowing और भरोसेमंद रिपोर्ट लिखें।\n"
            "हर सेक्शन के लिए स्पष्ट heading रखें।\n"
            "Raw data, JSON या technical शब्द न दिखाएँ।\n"
            "यह एक final paid astrology report है।"
        )
    else:
        footer = (
            "\n\nNow combine everything above into a clear, flowing, reader-friendly report.\n"
            "Use proper headings. Do not expose raw data or technical terms.\n"
            "This is a final paid astrology report."
        )

    return header + "\n".join(body) + footer
