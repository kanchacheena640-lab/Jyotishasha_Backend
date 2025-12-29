# Path: modules/love/love_prompt_builder.py
# Jyotishasha — Love Premium Prompt Builder (LOCKED)

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

    if not isinstance(compiled, dict):
        raise LovePromptBuilderError("compiled_report missing")
    if not isinstance(compatibility, dict):
        raise LovePromptBuilderError("compatibility missing")

    verdict = compiled.get("verdict", {})
    sections = compiled.get("sections", [])
    disclaimers = compiled.get("disclaimers", [])

    # ================= HEADER =================
    if language == "hi":
        header = (
            "आप एक अनुभवी और व्यावहारिक वैदिक ज्योतिषी हैं।\n"
            "नीचे दिए गए संरचित ज्योतिषीय डेटा के आधार पर "
            "एक गहन, ईमानदार और संतुलित Love → Marriage Life Report लिखें।\n\n"
            "महत्वपूर्ण निर्देश:\n"
            "- रिपोर्ट वास्तविक और grounded हो\n"
            "- कोई डराने वाली या गारंटी देने वाली भाषा न हो\n"
            "- प्रेम, विवाह, स्थिरता और भविष्य की दिशा पर फोकस हो\n"
            "- यह ₹299 की प्रीमियम रिपोर्ट लगे\n"
            "- अनुमान नहीं, केवल दिए गए डेटा पर आधारित निष्कर्ष हों\n\n"
        )
    else:
        header = (
            "You are an experienced, grounded Vedic astrologer.\n"
            "Using ONLY the structured astrological data below, "
            "write a deep, honest, and balanced Love → Marriage Life Report.\n\n"
            "Important rules:\n"
            "- Be realistic and grounded\n"
            "- No fear-based language or guaranteed claims\n"
            "- Focus on love, marriage potential, stability, and future direction\n"
            "- Must feel worth a ₹299 premium report\n"
            "- Do NOT invent facts beyond the provided data\n\n"
        )

    # ================= CORE DATA =================
    body: list[str] = []

    # ---- Verdict ----
    body.append("=== OVERALL RELATIONSHIP VERDICT ===")
    body.append(
        f"Compatibility Level: {verdict.get('level')}\n"
        f"Summary: {verdict.get('reason_line')}"
    )

    # ---- Core Compatibility ----
    body.append("\n=== CORE COMPATIBILITY INSIGHTS ===")
    body.append(
        "Use the following compatibility data to judge emotional bond, "
        "mental alignment, physical harmony, and long-term stability.\n"
        f"{compatibility}"
    )

    # ---- Structured Sections ----
    body.append("\n=== REPORT SECTIONS (WRITE IN THIS ORDER) ===")
    for sec in sections:
        title = sec.get("title")
        summary = sec.get("summary")
        bullets = sec.get("bullets") or []

        body.append(f"\n## {title}")
        body.append(f"Context: {summary}")

        if bullets:
            body.append("Key Points:")
            for b in bullets:
                body.append(f"- {b}")

    # ---- Disclaimers ----
    if disclaimers:
        body.append("\n=== IMPORTANT NOTES (MENTION NATURALLY) ===")
        for d in disclaimers:
            body.append(f"- {d.get('text')}")

    # ================= FOOTER =================
    if language == "hi":
        footer = (
            "\n\nअब ऊपर दिए गए सभी बिंदुओं को मिलाकर "
            "एक स्पष्ट, reader-friendly और flowing रिपोर्ट लिखें।\n"
            "हर section के लिए heading रखें, "
            "लेकिन raw data, JSON या technical शब्द न दिखाएँ।\n"
            "Tone: समझदार, मार्गदर्शक और भरोसेमंद।\n"
            "यह एक final paid astrology report है।"
        )
    else:
        footer = (
            "\n\nNow combine all the above points into a clear, flowing, reader-friendly report.\n"
            "Use proper section headings, but do NOT expose raw data or JSON.\n"
            "Tone: mature, guiding, and trustworthy.\n"
            "This is a final paid astrology report."
        )

    final_prompt = header + "\n".join(body) + footer
    return final_prompt
