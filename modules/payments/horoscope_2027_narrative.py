"""Personalized Horoscope 2027 -- prompts, AI-output validation and PDF assembly.

Division of labour (same principle as the Spouse Nature Report):
  * horoscope_2027_evidence.py computes every planetary fact;
  * Luna (the shared paid-report AI client) writes interpretation only, in two
    calls (part A: overview, chart summary + 2-3 themes, dasha, transits;
    part B: 12 structured months, guidance, summary) so each response stays a
    manageable size;
  * validate_part() rejects a response only for structural gaps, banned
    guarantee/fear wording, or a PROVEN contradiction of the evidence (a
    planet stated in a house/sign it never occupies, an unknown date, a
    year outside the evidence). A rejection raises ReportMetadataError ->
    report_stage="Failed" (recoverable); nothing is repaired or guessed;
  * assemble_horoscope_2027_report() builds the PDF payload: deterministic
    tables, a deterministic "2027 at a glance" box, and a numbered narrative.
    The customer sees a plain-language chart summary (key factors + 2-3
    themes), not a house table or house-by-house reading; the full house
    facts (lords, occupants, aspects) stay in the prompt and the checks.
    Every month is Focus / Do / Don't / Why, and a month with no new major
    transit (evidence "continues_previous") says so and carries the previous
    month's focus forward instead of inventing a new prediction.

The prompt never contains the customer's name, e-mail or birth details --
only derived chart facts.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from data.name_mappings import nakshatra_names_hi, planet_labels_hi, sign_labels_hi
from modules.payments.horoscope_2027_evidence import GRAHAS, PRODUCT_SLUG, SIGNS, YEAR
from modules.payments.report_ai_client import ReportAICompletion
from modules.payments.report_date_format import EN_MONTHS, HI_MONTHS, format_customer_date, format_customer_date_range
from modules.payments.report_structured_output import ReportMetadataError

LANGUAGES = ("en", "hi")
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "prompts")
# 13-15 page claim, measured with the real PDF renderer (pdf_generator_weasy) on
# a fictional chart with every AI text cut proportionally: EN 1,975 words ->
# 14 pages, 1,103 -> 13; HI 2,446 -> 14, 1,594 -> 13. The prompts target
# ~2,000 (EN) / ~2,450 (HI) words; these floors keep a report at 13+ pages.
MIN_TOTAL_WORDS = {"en": 1300, "hi": 1700}
MIN_SECTION_WORDS = 25          # long free-text sections (chart summary)
MIN_WHY_WORDS = 18              # each month's explanation
MIN_ITEM_WORDS = 4              # each Do / Don't item and the month focus
GUIDANCE_ITEMS = (4, 8)
THEME_ITEMS = (2, 3)
DO_ITEMS = (2, 3)
DONT_ITEMS = (1, 2)
EN_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th", 7: "7th", 8: "8th", 9: "9th",
               10: "10th", 11: "11th", 12: "12th"}
HI_ORDINALS = {1: "पहला", 2: "दूसरा", 3: "तीसरा", 4: "चौथा", 5: "पाँचवाँ", 6: "छठा", 7: "सातवाँ", 8: "आठवाँ",
               9: "नौवाँ", 10: "दसवाँ", 11: "ग्यारहवाँ", 12: "बारहवाँ"}
HI_ORDINALS_OBLIQUE = {1: "पहले", 2: "दूसरे", 3: "तीसरे", 4: "चौथे", 5: "पाँचवें", 6: "छठे", 7: "सातवें", 8: "आठवें",
                       9: "नौवें", 10: "दसवें", 11: "ग्यारहवें", 12: "बारहवें"}

UI = {
    "en": {
        "subtitle": "Your personal year ahead, read from your birth chart",
        "hero_label": "Your 2027 at a Glance",
        "maha": "{planet} Mahadasha", "antar": "{planet} Antardasha",
        "hero_jupiter": "Jupiter in 2027 (from your Lagna): {items}",
        "hero_saturn": "Saturn in 2027 (from your Lagna): {items}",
        "hero_house_item": "{house} house ({range})",
        "hero_sade_sati": "Sade Sati in 2027: {items}", "hero_no_sade_sati": "No Sade Sati in 2027.",
        "hero_dhaiya": "Saturn Dhaiya in 2027: {items}",
        "t_transits": "Major Planetary Movements in 2027",
        "h_transits": ["Planet", "Sign", "Period", "House from Lagna", "House from Moon"],
        "t_dashas": "Your Dasha Periods in 2027",
        "h_dashas": ["Mahadasha", "Antardasha", "Period"],
        "t_eclipses": "Eclipses in 2027",
        "h_eclipses": ["Date", "Eclipse", "Sign", "House from Lagna", "In India"],
        "none": "None",
        "vis_yes": "Visible", "vis_partial": "Visible as partial", "vis_no": "Not visible",
        "solar": "Solar", "lunar": "Lunar",
        "s_overview": "Your 2027 Overview", "s_chart": "Your Chart in Brief",
        "c_lagna": "Rising sign (Lagna): {sign}, ruled by {lord}, which sits in your {house} house",
        "c_moon": "Moon sign: {sign} (nakshatra {nakshatra}), in your {house} house",
        "c_cluster": "{planets} together in your {house} house",
        "c_dasha": "Running through 2027: {items}",
        "dasha_period": "{maha} Mahadasha, {antar} Antardasha",
        "and": "and",
        "themes_label": "Your main themes for 2027",
        "m_focus": "Focus", "m_do": "Do", "m_dont": "Don't", "m_why": "Why this month",
        "m_continue": "No new major transit this month",
        "m_continue_body": "continue {month}'s focus. Still active: {items}.",
        "m_active_planet": "{planet} in {sign} (your {house} house)",
        "m_active_dasha": "the {maha}–{antar} period",
        "p_new_major": "NEW MAJOR CHANGE THIS MONTH: {items}. Base this month's focus on it.",
        "p_opening": "THE YEAR OPENS: base this month's focus on what is active: {items}.",
        "p_continue": ("NO NEW MAJOR TRANSIT THIS MONTH: continue the previous month's focus. Still active: {items}. "
                       "Explain what remains active; do not invent a new prediction."),
        "p_change_transit": "{planet} {type} {sign} on {date}",
        "p_change_eclipse": "{kind} eclipse on {date}",
        "p_change_dasha": "{maha}–{antar} period begins on {date}",
        "p_types": {"ingress": "enters", "retrograde": "turns retrograde in", "direct": "turns direct in"},
        "s_dasha": "Your Dasha Periods in 2027", "s_transits": "Major Transits of 2027",
        "s_month": "{month} 2027", "s_summary": "Your 2027 in Summary",
        "f_house": "{sign} · lord {lord} (in your {lord_house} house) · planets: {planets} · aspects: {aspects}",
        "f_empty": "none (empty house)",
        "f_transit": "2027 transits: {items}",
        "f_no_transit": "2027 transits: no Jupiter, Saturn, Rahu or Ketu transit",
        "f_dasha": "{maha} Mahadasha, {antar} Antardasha: {range}",
        "f_slow": "{planet} in {sign}: {range} ({hl} from Lagna, {hm} from Moon)",
        "f_sade_sati": "Sade Sati ({phase} phase): Saturn in {sign}, {range}",
        "f_dhaiya": "Saturn Dhaiya ({kind}): Saturn in {sign}, {range}",
        "f_no_saturn_cycle": "No Sade Sati or Dhaiya is active for your Moon sign in 2027.",
        "f_eclipse": "{date}: {kind} eclipse ({type}) in {sign} ({hl} from Lagna), {vis}",
        "f_event_ingress": "{date}: {planet} enters {sign} ({hl} from Lagna, {hm} from Moon)",
        "f_event_retrograde": "{date}: {planet} turns retrograde in {sign}",
        "f_event_direct": "{date}: {planet} turns direct in {sign}",
        "f_month_dasha": "Dasha: {items}", "dasha_from": "{period} from {date}",
        "f_month_quiet": "No sign change or station of the major planets this month.",
        "phases": {"rising": "rising", "peak": "peak", "setting": "setting"},
        "dhaiya_kinds": {"kantaka": "4th from Moon", "ashtama": "8th from Moon"},
        "guidance": "Guidance for 2027",
        "notice_sade_sati": "Saturn's Sade Sati",
        "notice_dhaiya": "Saturn's Dhaiya",
        "notice_body": "{items}. This calls for patience and steady effort; it is a period of responsibility, not a prediction of misfortune.",
        "disclaimer": (
            "This report interprets your birth chart and the 2027 planetary movements using Vedic astrology "
            "(Lahiri ayanamsa, whole-sign houses). Planetary positions and dates are calculated, not estimated. "
            "Astrology describes tendencies and timing, not certainties; use it for guidance alongside your own "
            "judgement. It is not a substitute for medical, legal or financial advice."
        ),
    },
    "hi": {
        "subtitle": "आपकी जन्म कुंडली पर आधारित 2027 का व्यक्तिगत वर्षफल",
        "hero_label": "आपका 2027 एक नज़र में",
        "maha": "{planet} महादशा", "antar": "{planet} अंतर्दशा",
        "hero_jupiter": "2027 में गुरु (लग्न से): {items}",
        "hero_saturn": "2027 में शनि (लग्न से): {items}",
        "hero_house_item": "{house} भाव ({range})",
        "hero_sade_sati": "2027 में साढ़ेसाती: {items}", "hero_no_sade_sati": "2027 में साढ़ेसाती नहीं है।",
        "hero_dhaiya": "2027 में शनि की ढैया: {items}",
        "t_transits": "2027 के प्रमुख ग्रह गोचर",
        "h_transits": ["ग्रह", "राशि", "अवधि", "लग्न से भाव", "चंद्र से भाव"],
        "t_dashas": "2027 में आपकी दशा",
        "h_dashas": ["महादशा", "अंतर्दशा", "अवधि"],
        "t_eclipses": "2027 के ग्रहण",
        "h_eclipses": ["तिथि", "ग्रहण", "राशि", "लग्न से भाव", "भारत में"],
        "none": "कोई नहीं",
        "vis_yes": "दिखाई देगा", "vis_partial": "आंशिक रूप में दिखाई देगा", "vis_no": "दिखाई नहीं देगा",
        "solar": "सूर्य", "lunar": "चंद्र",
        "s_overview": "आपका 2027: एक परिचय", "s_chart": "आपकी कुंडली संक्षेप में",
        "c_lagna": "लग्न: {sign}, जिसके स्वामी {lord} आपके {house} भाव में हैं",
        "c_moon": "चंद्र राशि: {sign} (नक्षत्र {nakshatra}), आपके {house} भाव में",
        "c_cluster": "{planets} एक साथ आपके {house} भाव में",
        "c_dasha": "पूरे 2027 में: {items}",
        "dasha_period": "{maha} महादशा, {antar} अंतर्दशा",
        "and": "और",
        "themes_label": "2027 में आपके मुख्य विषय",
        "m_focus": "मुख्य ध्यान", "m_do": "करें", "m_dont": "न करें", "m_why": "इस महीने ऐसा क्यों",
        "m_continue": "इस महीने कोई नया बड़ा गोचर नहीं",
        "m_continue_body": "{month} का मुख्य ध्यान जारी रखें। अभी भी सक्रिय: {items}।",
        "m_active_planet": "{planet} {sign} राशि में (आपके {house} भाव में)",
        "m_active_dasha": "{maha}–{antar} दशा",
        "p_new_major": "इस महीने नया बड़ा बदलाव: {items}। इस महीने का मुख्य ध्यान इसी पर आधारित करें।",
        "p_opening": "वर्ष का आरंभ: इस महीने का मुख्य ध्यान इन सक्रिय स्थितियों पर आधारित करें: {items}।",
        "p_continue": ("इस महीने कोई नया बड़ा गोचर नहीं: पिछले महीने का मुख्य ध्यान जारी रखें। अभी भी सक्रिय: {items}। "
                       "बताएँ कि क्या सक्रिय है; कोई नई भविष्यवाणी न गढ़ें।"),
        "p_change_transit": "{date} को {planet} {sign} राशि में {type}",
        "p_change_eclipse": "{date} को {kind} ग्रहण",
        "p_change_dasha": "{date} से {maha}–{antar} दशा आरंभ",
        "p_types": {"ingress": "प्रवेश", "retrograde": "वक्री", "direct": "मार्गी"},
        "s_dasha": "2027 में आपकी दशा", "s_transits": "2027 के प्रमुख गोचर",
        "s_month": "{month} 2027", "s_summary": "आपका 2027: सार",
        "f_house": "{sign} · स्वामी {lord} (आपके {lord_house} भाव में) · ग्रह: {planets} · दृष्टि: {aspects}",
        "f_empty": "कोई नहीं (खाली भाव)",
        "f_transit": "2027 का गोचर: {items}",
        "f_no_transit": "2027 का गोचर: गुरु, शनि, राहु या केतु का गोचर नहीं",
        "f_dasha": "{maha} महादशा, {antar} अंतर्दशा: {range}",
        "f_slow": "{planet} {sign} राशि में: {range} (लग्न से {hl}, चंद्र से {hm} भाव)",
        "f_sade_sati": "साढ़ेसाती ({phase} चरण): शनि {sign} राशि में, {range}",
        "f_dhaiya": "शनि की ढैया ({kind}): शनि {sign} राशि में, {range}",
        "f_no_saturn_cycle": "2027 में आपकी चंद्र राशि पर साढ़ेसाती या ढैया नहीं है।",
        "f_eclipse": "{date}: {kind} ग्रहण ({type}) {sign} राशि में (लग्न से {hl} भाव), {vis}",
        "f_event_ingress": "{date}: {planet} का {sign} राशि में प्रवेश (लग्न से {hl}, चंद्र से {hm} भाव)",
        "f_event_retrograde": "{date}: {planet} {sign} राशि में वक्री",
        "f_event_direct": "{date}: {planet} {sign} राशि में मार्गी",
        "f_month_dasha": "दशा: {items}", "dasha_from": "{date} से {period}",
        "f_month_quiet": "इस महीने प्रमुख ग्रहों का कोई राशि परिवर्तन या वक्री-मार्गी परिवर्तन नहीं है।",
        "phases": {"rising": "पहला", "peak": "दूसरा (मध्य)", "setting": "तीसरा"},
        "dhaiya_kinds": {"kantaka": "चंद्र से चौथा", "ashtama": "चंद्र से आठवाँ"},
        "guidance": "2027 के लिए मार्गदर्शन",
        "notice_sade_sati": "शनि की साढ़ेसाती",
        "notice_dhaiya": "शनि की ढैया",
        "notice_body": "{items}। यह धैर्य और निरंतर प्रयास का समय है; यह ज़िम्मेदारी की अवधि है, किसी अनिष्ट की भविष्यवाणी नहीं।",
        "disclaimer": (
            "यह रिपोर्ट वैदिक ज्योतिष (लाहिड़ी अयनांश, संपूर्ण राशि भाव पद्धति) के आधार पर आपकी जन्म कुंडली और 2027 के "
            "ग्रह गोचर की व्याख्या करती है। ग्रहों की स्थिति और तिथियाँ गणना से निकाली गई हैं, अनुमान से नहीं। ज्योतिष "
            "प्रवृत्तियों और समय का संकेत देता है, निश्चितता का नहीं; इसे अपने विवेक के साथ मार्गदर्शन के रूप में लें। "
            "यह चिकित्सीय, कानूनी या वित्तीय सलाह का विकल्प नहीं है।"
        ),
    },
}
ECLIPSE_TYPES_HI = {"Total": "पूर्ण", "Annular": "वलयाकार", "Partial": "आंशिक", "Penumbral": "उपच्छाया", "Hybrid": "संकर"}


def _lang(language: str) -> str:
    return "hi" if language == "hi" else "en"


def P(planet: str, language: str) -> str:
    return planet_labels_hi[planet] if language == "hi" else planet


def S(sign: str, language: str) -> str:
    return sign_labels_hi[sign] if language == "hi" else sign


def ordinal(n: int, language: str, oblique: bool = True) -> str:
    if language == "hi":
        return (HI_ORDINALS_OBLIQUE if oblique else HI_ORDINALS)[n]
    return EN_ORDINALS[n]


def D(iso: str, language: str) -> str:
    return format_customer_date(iso, language)


def R(start: str, end: str, language: str) -> str:
    return format_customer_date_range(start, end, language) or ""


def _join(items: List[str], language: str) -> str:
    return ", ".join(items) if items else UI[language]["none"]


# ---------------------------------------------------------------------------
# Deterministic fact lines (used both in the prompt and in the PDF)
# ---------------------------------------------------------------------------
def house_fact_lines(evidence: dict, number: int, language: str) -> List[str]:
    u = UI[language]
    h = evidence["houses"][number - 1]
    planets = ", ".join(P(p, language) for p in h["occupants"]) or u["f_empty"]
    aspects = ", ".join(P(p, language) for p in h["aspected_by"]) or u["none"]
    lines = [u["f_house"].format(sign=S(h["sign"], language), lord=P(h["lord"], language),
                                 lord_house=ordinal(h["lord_house"], language), planets=planets, aspects=aspects)]
    transits = [f"{P(planet, language)} ({R(r['from'], r['to'], language)})"
                for planet in ("Jupiter", "Saturn", "Rahu", "Ketu")
                for r in evidence["slow_transits"][planet] if r["house_from_lagna"] == number]
    lines.append(u["f_transit"].format(items="; ".join(transits)) if transits else u["f_no_transit"])
    return lines


def dasha_fact_lines(evidence: dict, language: str) -> List[str]:
    u = UI[language]
    return [u["f_dasha"].format(maha=P(d["mahadasha"], language), antar=P(d["antardasha"], language),
                                range=R(d["from"], d["to"], language)) for d in evidence["dashas"]]


def _saturn_cycle_lines(evidence: dict, language: str) -> List[str]:
    u = UI[language]
    lines = [u["f_sade_sati"].format(phase=u["phases"][s["phase"]], sign=S(s["sign"], language),
                                     range=R(s["from"], s["to"], language)) for s in evidence["sade_sati"]]
    lines += [u["f_dhaiya"].format(kind=u["dhaiya_kinds"][d["kind"]], sign=S(d["sign"], language),
                                   range=R(d["from"], d["to"], language)) for d in evidence["dhaiya"]]
    return lines or [u["f_no_saturn_cycle"]]


def _eclipse_line(e: dict, language: str) -> str:
    u = UI[language]
    vis = u["vis_partial"] if e["partial_in_india"] else (u["vis_yes"] if e["visible_in_india"] else u["vis_no"])
    etype = ECLIPSE_TYPES_HI.get(e["type"], e["type"]) if language == "hi" else e["type"]
    return u["f_eclipse"].format(date=D(e["date"], language), kind=u[e["kind"]], type=etype,
                                 sign=S(e["sign"], language), hl=ordinal(e["house_from_lagna"], language), vis=vis)


def transit_fact_lines(evidence: dict, language: str) -> List[str]:
    u = UI[language]
    lines = []
    for planet in ("Jupiter", "Saturn", "Rahu", "Ketu"):
        for r in evidence["slow_transits"][planet]:
            lines.append(u["f_slow"].format(planet=P(planet, language), sign=S(r["sign"], language),
                                            range=R(r["from"], r["to"], language),
                                            hl=ordinal(r["house_from_lagna"], language),
                                            hm=ordinal(r["house_from_moon"], language)))
    lines += _saturn_cycle_lines(evidence, language)
    lines += [_eclipse_line(e, language) for e in evidence["eclipses"]]
    return lines


def _event_line(e: dict, language: str) -> str:
    u = UI[language]
    return u[f"f_event_{e['type']}"].format(date=D(e["date"], language), planet=P(e["planet"], language),
                                            sign=S(e["sign"], language), hl=ordinal(e["house_from_lagna"], language),
                                            hm=ordinal(e["house_from_moon"], language))


def _is_key_event(e: dict) -> bool:
    """Events shown in the monthly sections: every Jupiter/Saturn/Mars/Venus
    change, Mercury's retrograde/direct stations only, and no Sun ingresses
    (monthly by nature). The evidence keeps all events, so a date Luna takes
    from a less prominent event is still accepted by the validator."""
    if e["planet"] in ("Jupiter", "Saturn", "Mars", "Venus"):
        return True
    return e["planet"] == "Mercury" and e["type"] in ("retrograde", "direct")


def month_fact_lines(evidence: dict, month: int, language: str) -> List[str]:
    u = UI[language]
    m = evidence["months"][month - 1]
    dashas = []
    for i, d in enumerate(m["dashas"]):
        period = f"{P(d['mahadasha'], language)}–{P(d['antardasha'], language)}"
        # A period that starts inside this month shows its start date.
        dashas.append(u["dasha_from"].format(period=period, date=D(d["from"], language))
                      if i > 0 or d["from"] > m["from"] else period)
    lines = [u["f_month_dasha"].format(items="; ".join(dashas))]
    shown = [e for e in m["events"] if _is_key_event(e)]
    lines += [_event_line(e, language) for e in shown]
    lines += [_eclipse_line(e, language) for e in m["eclipses"]]
    if not shown and not m["eclipses"]:
        lines.append(u["f_month_quiet"])
    return lines


def natal_fact_lines(evidence: dict, language: str) -> List[str]:
    lines = []
    nak = (lambda n: nakshatra_names_hi.get(n, n)) if language == "hi" else (lambda n: n)
    for g in GRAHAS:
        p = evidence["planets"][g]
        lines.append(f"{P(g, language)}: {S(p['sign'], language)}, {ordinal(p['house'], language)} "
                     f"{'भाव' if language == 'hi' else 'house'}, {p['degree']}°, {nak(p['nakshatra'])}")
    lagna, moon = evidence["lagna"], evidence["moon"]
    if language == "hi":
        lines.insert(0, f"लग्न: {S(lagna['sign'], language)} (स्वामी {P(lagna['lord'], language)}, "
                        f"{ordinal(lagna['lord_house'], language)} भाव में); चंद्र राशि: {S(moon['sign'], language)}, "
                        f"नक्षत्र {nak(moon['nakshatra'])}")
    else:
        lines.insert(0, f"Lagna (Ascendant): {lagna['sign']} (lord {lagna['lord']}, in the "
                        f"{ordinal(lagna['lord_house'], language)} house); Moon sign: {moon['sign']}, "
                        f"nakshatra {moon['nakshatra']}")
    return lines


def _and_join(items: List[str], language: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {UI[language]['and']} {items[-1]}"


def chart_factor_lines(evidence: dict, language: str) -> List[str]:
    """The customer-facing key chart factors, in plain language: rising sign and
    its ruler, Moon sign, any house holding two or more planets, and the dasha
    running through 2027. (The full house table stays internal.)"""
    u = UI[language]
    lagna, moon = evidence["lagna"], evidence["moon"]
    lines = [
        u["c_lagna"].format(sign=S(lagna["sign"], language), lord=P(lagna["lord"], language),
                            house=ordinal(lagna["lord_house"], language)),
        u["c_moon"].format(sign=S(moon["sign"], language),
                           nakshatra=(nakshatra_names_hi.get(moon["nakshatra"], moon["nakshatra"])
                                      if language == "hi" else moon["nakshatra"]),
                           house=ordinal(moon["house"], language)),
    ]
    for h in evidence["houses"]:
        if len(h["occupants"]) >= 2:
            lines.append(u["c_cluster"].format(planets=_and_join([P(p, language) for p in h["occupants"]], language),
                                               house=ordinal(h["house"], language)))
    periods = [u["dasha_period"].format(maha=P(d["mahadasha"], language), antar=P(d["antardasha"], language))
               + f" ({R(d['from'], d['to'], language)})" for d in evidence["dashas"]]
    lines.append(u["c_dasha"].format(items="; ".join(periods)))
    return lines


def month_still_active(evidence: dict, month: int, language: str) -> List[str]:
    """What carries a continuation month: each slow planet's position (from the
    Lagna) and the dasha period(s) active in that month."""
    u = UI[language]
    m = evidence["months"][month - 1]
    items = [u["m_active_planet"].format(planet=P(planet, language), sign=S(rows[0]["sign"], language),
                                         house=ordinal(rows[0]["house_from_lagna"], language))
             for planet, rows in m["slow_planets"].items() if rows]
    items += [u["m_active_dasha"].format(maha=P(d["mahadasha"], language), antar=P(d["antardasha"], language))
              for d in m["dashas"]]
    return items


def month_prompt_line(evidence: dict, month: int, language: str) -> str:
    """Tells the AI whether this month starts a new focus or continues the last one."""
    u = UI[language]
    m = evidence["months"][month - 1]
    if m["continues_previous"]:
        return u["p_continue"].format(items="; ".join(month_still_active(evidence, month, language)))
    changes = []
    for c in m["major_changes"]:
        if c["kind"] == "transit":
            changes.append(u["p_change_transit"].format(planet=P(c["planet"], language), sign=S(c["sign"], language),
                                                        type=u["p_types"][c["type"]], date=D(c["date"], language)))
        elif c["kind"] == "eclipse":
            kind = next(e["kind"] for e in m["eclipses"] if e["date"] == c["date"])
            changes.append(u["p_change_eclipse"].format(kind=u[kind], date=D(c["date"], language)))
        else:
            changes.append(u["p_change_dasha"].format(maha=P(c["mahadasha"], language), antar=P(c["antardasha"], language),
                                                      date=D(c["date"], language)))
    if not changes:  # January: the year opens, so its focus comes from what is active
        return u["p_opening"].format(items="; ".join(month_still_active(evidence, month, language)))
    return u["p_new_major"].format(items="; ".join(changes))


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def build_facts_block(evidence: dict, language: str) -> str:
    def section(title, lines):
        return title + "\n" + "\n".join(f"- {line}" for line in lines)

    month_names = HI_MONTHS if language == "hi" else EN_MONTHS
    blocks = [
        section("NATAL CHART", natal_fact_lines(evidence, language)),
        section("KEY CHART FACTORS (printed in the PDF above your chart summary)",
                chart_factor_lines(evidence, language)),
        *[section(f"HOUSE {n} (background only)", house_fact_lines(evidence, n, language)) for n in range(1, 13)],
        section("DASHA PERIODS OVERLAPPING 2027", dasha_fact_lines(evidence, language)),
        section("2027 SLOW-PLANET TRANSITS, SATURN CYCLE AND ECLIPSES", transit_fact_lines(evidence, language)),
        *[section(f"MONTH {m} ({month_names[m - 1]} 2027)",
                  month_fact_lines(evidence, m, language) + [month_prompt_line(evidence, m, language)])
          for m in range(1, 13)],
    ]
    return "\n\n".join(blocks)


PART_KEYS = {
    "A": ("headline", "overview", "chart_summary", "themes", "dasha", "transits"),
    "B": ("months", "guidance", "summary"),
}
MONTH_KEYS = ("focus", "do", "dont", "why")


def build_horoscope_2027_prompts(evidence: dict, language: str) -> Tuple[str, str]:
    language = _lang(language)
    with open(os.path.join(PROMPTS_DIR, f"{PRODUCT_SLUG}_{language}.txt"), encoding="utf-8") as f:
        template = f.read()
    facts = build_facts_block(evidence, language)
    return tuple(template.format(facts_block=facts, part=part) for part in ("A", "B"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def parse_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ReportMetadataError("horoscope 2027: AI response is not a JSON object")
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ReportMetadataError(f"horoscope 2027: AI response is not valid JSON ({exc.msg})") from exc
    if not isinstance(value, dict):
        raise ReportMetadataError("horoscope 2027: AI response is not a JSON object")
    return value


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def total_word_count(value) -> int:
    """Words in any (nested) section value: str, list or dict."""
    if isinstance(value, str):
        return word_count(value)
    if isinstance(value, dict):
        return sum(total_word_count(v) for v in value.values())
    if isinstance(value, list):
        return sum(total_word_count(v) for v in value)
    return 0


_PLANET_EN = r"(Sun|Moon|Mars|Mercury|Jupiter|Venus|Saturn|Rahu|Ketu)"
_ALLOW_EN = (r"(?:\s+(?:is|was|will|be|been|has|had|remains|remain|stays|stay|sits|sit|placed|positioned|located|"
             r"moves|move|moving|transits|transit|transiting|travels|travel|travelling|traveling|passes|pass|"
             r"passing|now|also|still|then|again|back|returns|return|returning|currently|continues|continue|"
             r"to|natally|already|while|,))*")
_ORD_EN = (r"(\d{1,2})(?:st|nd|rd|th)|(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
           r"eleventh|twelfth)")
_ORD_WORDS = {w: i for i, w in enumerate(
    ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh",
     "twelfth"), start=1)}
EN_HOUSE_CLAIM = re.compile(_PLANET_EN + _ALLOW_EN + r"\s+(?:in|into|through)\s+(?:your|the)\s+(?:" + _ORD_EN
                            + r")\s+house", re.IGNORECASE)
EN_SIGN_CLAIM = re.compile(_PLANET_EN + _ALLOW_EN + r"\s+(?:in|into|enters|entering|enter)\s+("
                           + "|".join(SIGNS) + r")\b", re.IGNORECASE)

_DEV = r"ऀ-ॿ"
_HI_PLANETS = {"सूर्य": "Sun", "चंद्रमा": "Moon", "चंद्र": "Moon", "चन्द्र": "Moon", "मंगल": "Mars", "बुध": "Mercury",
               "गुरु": "Jupiter", "बृहस्पति": "Jupiter", "शुक्र": "Venus", "शनि": "Saturn", "राहु": "Rahu", "केतु": "Ketu"}
_HI_ORD = {**{w: n for n, w in HI_ORDINALS_OBLIQUE.items()}, "पांचवें": 5,
           **{w: n for n, w in enumerate(("प्रथम", "द्वितीय", "तृतीय", "चतुर्थ", "पंचम", "षष्ठ", "सप्तम", "अष्टम",
                                           "नवम", "दशम", "एकादश", "द्वादश"), start=1)}}
_ALLOW_HI = r"(?:\s+(?:का|की|के|गोचर|आपके|आपकी|अब|फिर|भी|अपने))*"
_HI_PLANET_RE = "(" + "|".join(sorted(_HI_PLANETS, key=len, reverse=True)) + ")"
HI_HOUSE_CLAIM = re.compile(rf"(?<![{_DEV}]){_HI_PLANET_RE}(?![{_DEV}]){_ALLOW_HI}\s+("
                            + "|".join(sorted(_HI_ORD, key=len, reverse=True)) + r"|(\d{1,2})(?:वें|वे))\s+भाव\s+में")
HI_SIGN_CLAIM = re.compile(rf"(?<![{_DEV}]){_HI_PLANET_RE}(?![{_DEV}]){_ALLOW_HI}\s+("
                           + "|".join(sign_labels_hi[s] for s in SIGNS) + r")\s+राशि\s+में")
_HI_SIGN_TO_EN = {sign_labels_hi[s]: s for s in SIGNS}

_EN_MONTH_RE = "|".join(EN_MONTHS)
_HI_MONTH_VARIANTS = {**{m: i for i, m in enumerate(HI_MONTHS, start=1)}, "फरवरी": 2, "सितम्बर": 9, "अक्तूबर": 10,
                      "नवम्बर": 11, "दिसम्बर": 12}
EN_DATE_DMY = re.compile(r"\b(\d{1,2})\s+(" + _EN_MONTH_RE + r")(?:,?\s+(\d{4}))?\b")
EN_DATE_MDY = re.compile(r"\b(" + _EN_MONTH_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b")
HI_DATE = re.compile(r"(?<!\d)(\d{1,2})\s+(" + "|".join(sorted(_HI_MONTH_VARIANTS, key=len, reverse=True))
                     + r")(?:\s+(\d{4}))?")
YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")

BANNED = {
    "en": re.compile(r"\b(guarantee[sd]?|definitely|certainly|death|dies|die|fatal|accidents?|curse[sd]?)\b|\d+\s*%",
                     re.IGNORECASE),
    "hi": re.compile(r"गारंटी|निश्चित रूप से|अवश्य ही|मृत्यु|मौत|दुर्घटना|श्राप|\d+\s*%|प्रतिशत"),
}


@dataclass
class _Checker:
    evidence: dict
    language: str

    def __post_init__(self):
        self.allowed = self.evidence["allowed_placements"]
        self.allowed_dates = set(self.evidence["allowed_dates"])
        # Month start/end dates are always legitimate in monthly sections.
        for m in self.evidence["months"]:
            self.allowed_dates.update({m["from"], m["to"]})
        self.allowed_day_months = {(int(d[8:10]), int(d[5:7])) for d in self.allowed_dates}
        self.allowed_years = {int(d[:4]) for d in self.allowed_dates} | {YEAR, YEAR + 1}

    def problems(self, label: str, text: str) -> List[str]:
        found = []
        if BANNED[self.language].search(text):
            found.append(f"{label}: banned guarantee/fear wording {BANNED[self.language].search(text).group(0)!r}")
        found += self._placements(label, text)
        found += self._dates(label, text)
        return found

    def _placements(self, label, text):
        found = []
        if self.language == "en":
            for m in EN_HOUSE_CLAIM.finditer(text):
                planet = m.group(1).capitalize()
                house = int(m.group(2)) if m.group(2) else _ORD_WORDS[m.group(3).lower()]
                if house not in self.allowed[planet]["houses"]:
                    found.append(f"{label}: '{m.group(0)}' -- {planet} is never in house {house} in this chart/2027")
            for m in EN_SIGN_CLAIM.finditer(text):
                planet, sign = m.group(1).capitalize(), m.group(2).capitalize()
                if sign not in self.allowed[planet]["signs"]:
                    found.append(f"{label}: '{m.group(0)}' -- {planet} is never in {sign} in this chart/2027")
        else:
            for m in HI_HOUSE_CLAIM.finditer(text):
                planet = _HI_PLANETS[m.group(1)]
                house = int(m.group(3)) if m.group(3) else _HI_ORD.get(m.group(2))
                if house and house not in self.allowed[planet]["houses"]:
                    found.append(f"{label}: '{m.group(0)}' -- {planet} is never in house {house} in this chart/2027")
            for m in HI_SIGN_CLAIM.finditer(text):
                planet, sign = _HI_PLANETS[m.group(1)], _HI_SIGN_TO_EN[m.group(2)]
                if sign not in self.allowed[planet]["signs"]:
                    found.append(f"{label}: '{m.group(0)}' -- {planet} is never in {sign} in this chart/2027")
        return found

    def _date_ok(self, day: int, month: int, year: Optional[int]) -> bool:
        if year is None:
            return (day, month) in self.allowed_day_months
        try:
            return date(year, month, day).isoformat() in self.allowed_dates
        except ValueError:
            return False

    def _dates(self, label, text):
        found = []
        months = {m.lower(): i for i, m in enumerate(EN_MONTHS, start=1)}
        candidates = []
        if self.language == "en":
            for m in EN_DATE_DMY.finditer(text):
                candidates.append((m.group(0), int(m.group(1)), months[m.group(2).lower()], m.group(3)))
            for m in EN_DATE_MDY.finditer(text):
                candidates.append((m.group(0), int(m.group(2)), months[m.group(1).lower()], m.group(3)))
        else:
            for m in HI_DATE.finditer(text):
                candidates.append((m.group(0), int(m.group(1)), _HI_MONTH_VARIANTS[m.group(2)], m.group(3)))
        for m in ISO_DATE_RE.finditer(text):  # the PDF renderer would show these as customer dates
            candidates.append((m.group(0), int(m.group(3)), int(m.group(2)), m.group(1)))
        for raw, day, month, year in candidates:
            if not self._date_ok(day, month, int(year) if year else None):
                found.append(f"{label}: date '{raw}' is not in the report's calculated dates")
        for m in YEAR_RE.finditer(text):
            if int(m.group(1)) not in self.allowed_years:
                found.append(f"{label}: year {m.group(1)} is outside the report's calculated periods")
        return found


def validate_part(part: str, raw: str, evidence: dict, language: str) -> dict:
    language = _lang(language)
    data = parse_json_object(raw)
    problems = []
    missing = [k for k in PART_KEYS[part] if k not in data]
    if missing:
        raise ReportMetadataError(f"horoscope 2027 part {part}: missing key(s) {', '.join(missing)}")

    texts: Dict[str, str] = {}

    def text_list(label, value, bounds, min_words):
        if not isinstance(value, list) or not (bounds[0] <= len(value) <= bounds[1]):
            problems.append(f"{label}: expected {bounds[0]}-{bounds[1]} items")
            return
        for i, v in enumerate(value, start=1):
            if not isinstance(v, str) or word_count(v) < min_words:
                problems.append(f"{label}[{i}]: missing or too short")
            texts[f"{label}[{i}]"] = v if isinstance(v, str) else ""

    for key in PART_KEYS[part]:
        value = data[key]
        if key == "months":
            if not isinstance(value, dict) or set(map(str, value)) != {str(n) for n in range(1, 13)}:
                raise ReportMetadataError(f"horoscope 2027 part {part}: 'months' must have exactly the keys 1-12")
            for n in range(1, 13):
                month = value.get(str(n)) if str(n) in value else value.get(n)
                if not isinstance(month, dict) or any(k not in month for k in MONTH_KEYS):
                    raise ReportMetadataError(f"horoscope 2027 part {part}: months[{n}] must have keys "
                                              + ", ".join(MONTH_KEYS))
                for field, min_words in (("focus", MIN_ITEM_WORDS), ("why", MIN_WHY_WORDS)):
                    text = month[field]
                    if not isinstance(text, str) or word_count(text) < min_words:
                        problems.append(f"months[{n}].{field}: missing or too short")
                    texts[f"months[{n}].{field}"] = text if isinstance(text, str) else ""
                text_list(f"months[{n}].do", month["do"], DO_ITEMS, MIN_ITEM_WORDS)
                text_list(f"months[{n}].dont", month["dont"], DONT_ITEMS, MIN_ITEM_WORDS)
                if evidence["months"][n - 1]["continues_previous"]:
                    problems += _continuation_problems(n, month, evidence, language)
        elif key == "themes":
            if not isinstance(value, list) or not (THEME_ITEMS[0] <= len(value) <= THEME_ITEMS[1]):
                problems.append(f"themes: expected {THEME_ITEMS[0]}-{THEME_ITEMS[1]} items")
                value = []
            for i, theme in enumerate(value, start=1):
                if not isinstance(theme, dict) or not isinstance(theme.get("title"), str) \
                        or not theme["title"].strip() or not isinstance(theme.get("text"), str) \
                        or word_count(theme["text"]) < MIN_WHY_WORDS:
                    problems.append(f"themes[{i}]: needs a title and a text of at least {MIN_WHY_WORDS} words")
                    continue
                texts[f"themes[{i}].title"], texts[f"themes[{i}].text"] = theme["title"], theme["text"]
        elif key == "guidance":
            text_list("guidance", value, GUIDANCE_ITEMS, 1)
        else:
            min_words = MIN_SECTION_WORDS if key == "chart_summary" else 1
            if not isinstance(value, str) or word_count(value) < min_words:
                problems.append(f"{key}: missing or too short")
            texts[key] = value if isinstance(value, str) else ""

    checker = _Checker(evidence, language)
    for label, text in texts.items():
        problems += checker.problems(label, text)
    if problems:
        raise ReportMetadataError("horoscope 2027 part " + part + ": " + "; ".join(problems[:12]))
    return {k: data[k] for k in PART_KEYS[part]}


def _continuation_problems(n: int, month: dict, evidence: dict, language: str) -> List[str]:
    """A month without a new major transit must explain what remains active,
    so its focus/why has to name at least one still-active slow planet or
    dasha lord."""
    m = evidence["months"][n - 1]
    active = {p for p, rows in m["slow_planets"].items() if rows}
    active |= {d[k] for d in m["dashas"] for k in ("mahadasha", "antardasha")}
    text = f"{month.get('focus') or ''} {month.get('why') or ''}"
    if language == "hi":
        named = {_HI_PLANETS[w] for w in _HI_PLANETS if re.search(rf"(?<![{_DEV}]){w}(?![{_DEV}])", text)}
    else:
        named = {p for p in GRAHAS if re.search(rf"\b{p}\b", text, re.IGNORECASE)}
    if not named & active:
        return [f"months[{n}]: no new major transit, but the text does not say what remains active"]
    return []


def generate_horoscope_2027_sections(prompts: Tuple[str, str], evidence: dict, language: str,
                                     completion_fn: Callable[[str], ReportAICompletion]):
    """Two AI calls, each validated before the next is spent. Returns the merged
    sections plus one aggregate completion (tokens/duration summed) for the
    existing report_generation_completed observability event."""
    language = _lang(language)
    completions, sections = [], {}
    for part, prompt in zip(("A", "B"), prompts):
        completion = completion_fn(prompt)
        completions.append(completion)
        sections.update(validate_part(part, completion.content, evidence, language))
    total_words = total_word_count(sections)
    if total_words < MIN_TOTAL_WORDS[language]:
        raise ReportMetadataError(
            f"horoscope 2027: report too short ({total_words} words, minimum {MIN_TOTAL_WORDS[language]})")

    def total(attr):
        values = [getattr(c, attr) for c in completions]
        return None if any(v is None for v in values) else sum(values)

    aggregate = ReportAICompletion(
        content=json.dumps(sections, ensure_ascii=False),
        model=completions[-1].model,
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        total_tokens=total("total_tokens"),
        duration_seconds=sum(c.duration_seconds for c in completions),
    )
    return sections, aggregate


# ---------------------------------------------------------------------------
# PDF assembly
# ---------------------------------------------------------------------------
def _tables(evidence: dict, language: str) -> List[dict]:
    """Natal placements are already in the Birth Chart Summary card; the
    technical 12-house table (lords, occupants, aspects) is not shown to the
    customer, so the tables cover only the 2027 timing facts."""
    u = UI[language]
    transits =[[P(planet, language), S(r["sign"], language), R(r["from"], r["to"], language),
                 ordinal(r["house_from_lagna"], language, oblique=False),
                 ordinal(r["house_from_moon"], language, oblique=False)]
                for planet in ("Jupiter", "Saturn", "Rahu", "Ketu") for r in evidence["slow_transits"][planet]]
    dashas = [[P(d["mahadasha"], language), P(d["antardasha"], language), R(d["from"], d["to"], language)]
              for d in evidence["dashas"]]
    eclipses = [[D(e["date"], language),
                 f"{u[e['kind']]} ({ECLIPSE_TYPES_HI.get(e['type'], e['type']) if language == 'hi' else e['type']})",
                 S(e["sign"], language), ordinal(e["house_from_lagna"], language, oblique=False),
                 u["vis_partial"] if e["partial_in_india"] else (u["vis_yes"] if e["visible_in_india"] else u["vis_no"])]
                for e in evidence["eclipses"]]
    return [
        {"heading": u["t_transits"], "headers": u["h_transits"], "rows": transits},
        {"heading": u["t_dashas"], "headers": u["h_dashas"], "rows": dashas},
        {"heading": u["t_eclipses"], "headers": u["h_eclipses"], "rows": eclipses},
    ]


def _answer_hero(sections: dict, evidence: dict, language: str) -> dict:
    u = UI[language]
    mahas = list(dict.fromkeys(d["mahadasha"] for d in evidence["dashas"]))
    antars = list(dict.fromkeys(d["antardasha"] for d in evidence["dashas"]))
    value = " · ".join([" → ".join(u["maha"].format(planet=P(m, language)) for m in mahas),
                        " → ".join(u["antar"].format(planet=P(a, language)) for a in antars)])

    def planet_items(planet):
        return ", ".join(u["hero_house_item"].format(house=ordinal(r["house_from_lagna"], language, oblique=False),
                                                     range=R(r["from"], r["to"], language))
                         for r in evidence["slow_transits"][planet])

    points = [u["hero_jupiter"].format(items=planet_items("Jupiter")),
              u["hero_saturn"].format(items=planet_items("Saturn"))]
    if evidence["sade_sati"]:
        points.append(u["hero_sade_sati"].format(items=", ".join(
            f"{u['phases'][s['phase']]} ({R(s['from'], s['to'], language)})" for s in evidence["sade_sati"])))
    else:
        points.append(u["hero_no_sade_sati"])
    if evidence["dhaiya"]:
        points.append(u["hero_dhaiya"].format(items=", ".join(
            f"{u['dhaiya_kinds'][d['kind']]} ({R(d['from'], d['to'], language)})" for d in evidence["dhaiya"])))
    return {"label": u["hero_label"], "value": value, "interpretation": sections["headline"].strip(), "evidence": points}


def _clean(text: str) -> str:
    """One line of AI text for the PDF: no markdown markers, no line breaks,
    no leading bullet (the renderer adds its own)."""
    text = re.sub(r"\s+", " ", (text or "").replace("**", "")).strip()
    return re.sub(r"^(?:[-*•]\s*)+", "", text)


def _section(number: int, title: str, facts: List[str], body: str) -> str:
    parts = [f"**{number}. {title}**", ""]
    if facts:
        parts += [f"- {line}" for line in facts] + [""]
    parts.append(body.strip())
    return "\n".join(parts)


def _chart_section(number: int, sections: dict, evidence: dict, language: str) -> str:
    u = UI[language]
    parts = [f"**{number}. {u['s_chart']}**", ""]
    parts += [f"- {line}" for line in chart_factor_lines(evidence, language)] + [""]
    # Sub-headings (not "**Label:**" lead-ins): the template keeps an H3 with the
    # text below it across a page break, and its accent colour marks the label
    # in Hindi too (only the Regular Devanagari face is bundled).
    parts += [sections["chart_summary"].strip(), "", f"### {u['themes_label']}"]
    parts += [f"**{_clean(t['title']).rstrip(':')}:** {_clean(t['text'])}" for t in sections["themes"]]
    return "\n".join(parts)


def _month_section(number: int, month: int, data: dict, evidence: dict, language: str) -> str:
    u = UI[language]
    month_names = HI_MONTHS if language == "hi" else EN_MONTHS
    parts = [f"**{number}. {u['s_month'].format(month=month_names[month - 1])}**", ""]
    parts += [f"- {line}" for line in month_fact_lines(evidence, month, language)] + [""]
    if evidence["months"][month - 1]["continues_previous"]:
        body = u["m_continue_body"].format(month=month_names[month - 2],
                                           items="; ".join(month_still_active(evidence, month, language)))
        parts += [f"**{u['m_continue']}:** {body}", ""]
    parts += [f"**{u['m_focus']}:** {_clean(data['focus'])}", f"### {u['m_do']}"]
    parts += [f"- {_clean(item)}" for item in data["do"]]
    parts += [f"### {u['m_dont']}"]
    parts += [f"- {_clean(item)}" for item in data["dont"]]
    parts += [f"**{u['m_why']}:** {_clean(data['why'])}"]
    return "\n".join(parts)


def _notices(evidence: dict, language: str) -> List[dict]:
    u = UI[language]
    notices = []
    if evidence["sade_sati"]:
        items = "; ".join(f"{u['phases'][s['phase']]}: {R(s['from'], s['to'], language)}" for s in evidence["sade_sati"])
        notices.append({"heading": u["notice_sade_sati"], "text": u["notice_body"].format(items=items)})
    if evidence["dhaiya"]:
        items = "; ".join(f"{u['dhaiya_kinds'][d['kind']]}: {R(d['from'], d['to'], language)}" for d in evidence["dhaiya"])
        notices.append({"heading": u["notice_dhaiya"], "text": u["notice_body"].format(items=items)})
    return notices


def assemble_horoscope_2027_report(sections: dict, evidence: dict, language: str) -> dict:
    language = _lang(language)
    u = UI[language]
    months = {str(k): v for k, v in sections["months"].items()}
    blocks = [
        _section(1, u["s_overview"], [], sections["overview"]),
        _chart_section(2, sections, evidence, language),
        _section(3, u["s_dasha"], dasha_fact_lines(evidence, language), sections["dasha"]),
        _section(4, u["s_transits"], transit_fact_lines(evidence, language), sections["transits"]),
    ]
    for m in range(1, 13):
        blocks.append(_month_section(4 + m, m, months[str(m)], evidence, language))
    blocks.append(_section(17, u["s_summary"], [], sections["summary"]))
    return {
        "answer_hero": _answer_hero(sections, evidence, language),
        "narrative": "\n\n".join(blocks),
        "action_list": {"heading": u["guidance"], "items": [_clean(g) for g in sections["guidance"]]},
        "disclaimer": u["disclaimer"],
        "pdf_kwargs": {
            # Long sections must be allowed to break across pages (same as the
            # Spouse Nature Report); card shells strand headings in English PDFs.
            "narrative_style": "plain",
            "report_subtitle": u["subtitle"],
            "tables": _tables(evidence, language),
            "notices": _notices(evidence, language),
        },
    }
