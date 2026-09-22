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
