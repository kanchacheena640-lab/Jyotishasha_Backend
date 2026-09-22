"""Shared bilingual master, output schema and reusable section archetypes."""
import json
from pathlib import Path

from modules.focused_reports.prompt_contract import Archetype

PROMPT_DIR = Path(__file__).with_name("prompts")
SECTIONS = {
    Archetype.TIMING: (
        ("Direct Answer", "सीधा जवाब"), ("Why Your Chart Says This", "आपकी Chart ऐसा क्यों कहती है"),
        ("Strongest Periods", "सबसे मजबूत समय"), ("Slower or Watch Period", "धीमा या ध्यान रखने वाला समय"),
        ("What You Should Do", "आपको क्या करना चाहिए"), ("Bottom Line", "सीधी बात")),
    Archetype.DIAGNOSTIC: (
        ("Direct Answer", "सीधा जवाब"), ("Main Astrological Factors", "मुख्य ज्योतिषीय कारण"),
        ("Why This Phase Feels Difficult", "यह समय कठिन क्यों लगता है"), ("When Pressure May Ease", "दबाव कब कम हो सकता है"),
        ("What You Can Do", "आप क्या कर सकते हैं"), ("Bottom Line", "सीधी बात")),
    Archetype.DIRECTION: (
        ("Direct Answer", "सीधा जवाब"), ("Natural Strengths and Tendencies", "ताकतें और रुझान"),
        ("Most Relevant Directions", "सबसे उपयोगी दिशाएँ"), ("Current Timing Context", "अभी के समय का संदर्भ"),
        ("Practical Focus", "व्यावहारिक ध्यान"), ("Bottom Line", "सीधी बात")),
    Archetype.COMPATIBILITY: (
        ("Direct Answer", "सीधा जवाब"), ("Where Your Charts Support Each Other", "चार्ट में तालमेल के संकेत"),
        ("Differences That Need Care", "किन फर्कों पर ध्यान दें"), ("Practical Relationship Focus", "रिश्ते के लिए उपयोगी ध्यान"),
        ("Bottom Line", "सीधी बात")),
    Archetype.OBSTACLES: (
        ("Direct Answer", "सीधा जवाब"), ("Birth Chart Obstacles", "कुंडली की जन्मजात बाधाएँ"),
        ("Current Active Obstacles", "अभी सक्रिय बाधाएँ"), ("Remedies and What Helps", "उपाय और क्या मदद करता है"),
        ("Bottom Line", "सीधी बात")),
    Archetype.STRENGTHS_NOW: (
        ("Direct Answer", "सीधा जवाब"), ("Birth Chart Strengths", "कुंडली की जन्मजात शक्तियाँ"),
        ("Currently Active Strengths", "अभी सक्रिय शक्तियाँ"), ("How To Use Them Now", "अभी इनका इस्तेमाल कैसे करें"),
        ("Bottom Line", "सीधी बात")),
}

# Shared, conditional -- appended to the prompt only when a PromptSpec sets remedies=True (currently only
# kundali_obstacles/major_kundali_obstacles). ONE instruction block, never duplicated per question.
REMEDY_INSTRUCTION = {
    "en": (
        "Remedies: since this report identifies genuine challenges, add a few concise, practical remedies grounded "
        "in the supplied evidence. Prefer everyday practical or behavioural guidance; a simple Jyotish or spiritual "
        "practice (for example a specific mantra, a fasting day, or a modest charitable act tied to the relevant "
        "planet) may be added only when it is reasonably supported by the evidence. Never guarantee an outcome from "
        "a remedy, never prescribe a specific expensive gemstone, and never give medical, legal or financial advice."
    ),
    "hi": (
        "उपाय: यह report असली challenges बताती है, इसलिए ऊपर के प्रमाण से जुड़े कुछ संक्षिप्त, practical उपाय भी दें। रोज़मर्रा के "
        "practical या व्यवहार से जुड़े उपायों को प्राथमिकता दें; कोई साधारण Jyotish या spiritual उपाय (जैसे कोई खास mantra, कोई "
        "fasting day, या संबंधित planet से जुड़ा छोटा दान) सिर्फ तभी जोड़ें जब वह प्रमाण से सच में जुड़ा हो। किसी उपाय से पक्का "
        "नतीजा मिलने की गारंटी न दें, कोई महँगा gemstone prescribe न करें, और medical, legal या financial सलाह कभी न दें।"
    ),
}


def master_contract(language):
    return (PROMPT_DIR / f"master_{language}.txt").read_text(encoding="utf-8")


def output_contract(spec, language):
    label = "Promotion Outlook" if spec.question_key == "promotion_timing" else spec.title.get(language)
    # One schema for all questions. Only the human-facing label changes.
    example = json.dumps({"answer_hero": {
        "label": label, "value": "<short qualitative outlook, never a percentage, score or yes/no guarantee>",
        "interpretation": "<one calm sentence tied to the strongest supplied evidence>",
        "evidence": ["<a real fact from the data above>", "<a second real fact>"]},
        "action_items": ["<short practical guidance item>", "<short practical guidance item>"]}, ensure_ascii=False)
    headings = "\n".join(f"**{pair[language == 'hi']}**" for pair in SECTIONS[spec.archetype])
    return (
        "Return exactly the two markers below on their own lines. META must be valid JSON, no comments or trailing commas. "
        "Keep JSON keys unchanged; write all prose values and REPORT in the requested language. Keep the supplied hero label.\n"
        "===META===\n" + example + "\n===REPORT===\n<the report as plain text>\n\n"
        "Use these headings in this order, bold on their own lines:\n" + headings + "\n"
        "Direct Answer: 2 to 3 lines. Why: only the strongest relevant factors. Strongest Periods: a concise reason for each. "
        "Slower or Watch Period: include this section only if the astrology genuinely justifies it. "
        "Any timing section, including easing or Current Timing Context, is omitted when dated support is absent. "
        "Do not presume difficulty in a diagnostic answer if the evidence does not support it. "
        "Practical guidance: 2 to 3 concise practical actions. Bottom Line: 1 to 2 lines that answer the original question again. "
        "Do not repeat interpretations across sections."
    )
