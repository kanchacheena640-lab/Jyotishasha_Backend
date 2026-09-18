# modules/payments/report_q3_batch1.py

"""
report_q3_batch1.py -- Paid Report Platform, Q3 Batch 1.

Product-specific deterministic wiring for the first 4 Q3-enabled
products (gemstone_consultation, saturn_transit_report,
mood_mental_health_report, divorce_possibility_report). Kept OUT of
tasks.py's own core function to avoid growing that one function with a
4th large per-product special-case block.

DISCLAIMER_TEXT/get_mandatory_disclaimer() below are generic and
shared -- Q3 Batches 2, 3, 4 and 5 (modules/payments/
report_q3_batch2.py, report_q3_batch3.py, report_q3_batch4.py,
report_q3_batch5.py) all reuse them unchanged for their own mandatory
disclaimer types rather than duplicating the mechanism; module name is
historical, not a scope boundary.

Does NOT redesign Batch 0's architecture: everything here is either a
thin, product-specific deterministic-value computation feeding
modules/payments/report_structured_output.py::assemble_answer_hero()'s
existing `deterministic_value`/`deterministic_timing` parameters, or a
fixed backend disclaimer-text lookup fed into pdf_generator_weasy.py's
existing `disclaimer` parameter (Q2/Q2.1, frozen) -- never a new AI
call, never a new PDF component shape, never a new astrology
calculation.
"""

from __future__ import annotations

from typing import Optional

from smart_transit_engine import get_current_sign_residency
from summary_blocks import _house_from_lagna, _ordinal
from modules.payments.report_structured_output import ReportMetadataError
from modules.payments.report_date_format import format_customer_date_range
from modules.payments.report_i18n_labels import get_label


# ------------------------------------------------------------------
# Mandatory, backend-controlled disclaimers.
#
# Luna never decides whether these appear: report_product_intelligence
# .py's `disclaimer_type` field selects one of these keys, and tasks.py
# passes the resulting fixed text into generate_pdf_report_weasy(
# disclaimer=...) UNCONDITIONALLY for these two products, regardless of
# what the AI response contained. get_mandatory_disclaimer() returns
# None for every other disclaimer_type (including "none"), so calling
# it for all 25 products is safe and inert for the other 23.
# ------------------------------------------------------------------
DISCLAIMER_TEXT = {
    "mental_health_mandatory": {
        "en": (
            "This report provides astrology-based insight into emotional "
            "tendencies. It is not a medical or psychological diagnosis or "
            "treatment. If you are experiencing significant emotional "
            "distress, consider seeking support from a qualified "
            "healthcare professional."
        ),
        "hi": (
            "यह रिपोर्ट भावनात्मक प्रवृत्तियों के बारे में ज्योतिष-आधारित "
            "जानकारी देती है। यह कोई चिकित्सीय या मानसिक स्वास्थ्य निदान अथवा "
            "उपचार नहीं है। यदि आप गंभीर भावनात्मक तनाव महसूस कर रहे हैं, तो "
            "कृपया किसी योग्य स्वास्थ्य विशेषज्ञ से सहायता लें।"
        ),
    },
    "divorce_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based assessment of relationship stress "
            "tendencies, not a prediction or guarantee of divorce or any "
            "legal outcome. Important relationship or legal decisions "
            "should be based on your real circumstances and, where "
            "needed, appropriate professional advice."
        ),
        "hi": (
            "यह रिपोर्ट संबंधों में तनाव की प्रवृत्तियों का ज्योतिष-आधारित "
            "आकलन है; यह तलाक या किसी कानूनी परिणाम की भविष्यवाणी या गारंटी "
            "नहीं है। महत्वपूर्ण पारिवारिक या कानूनी निर्णय आपकी वास्तविक "
            "परिस्थितियों और आवश्यकता होने पर उचित पेशेवर सलाह के आधार पर ही "
            "लिए जाने चाहिए।"
        ),
    },
    # Q3 Batch 2 -- problem_in_marriage_report. Never a divorce
    # prediction, never a claim about the partner's private thoughts or
    # intentions.
    "marriage_problem_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based view of relationship friction "
            "tendencies, not a diagnosis of your relationship or a "
            "prediction of separation or divorce. It says nothing about "
            "your partner's private thoughts or intentions. Important "
            "relationship decisions should be based on your real "
            "circumstances and, where helpful, a qualified counsellor."
        ),
        "hi": (
            "यह रिपोर्ट संबंधों में संभावित तनाव की प्रवृत्तियों का "
            "ज्योतिष-आधारित आकलन है; यह आपके रिश्ते का निदान या "
            "अलगाव/तलाक की भविष्यवाणी नहीं है। यह आपके साथी के निजी "
            "विचारों या इरादों के बारे में कुछ नहीं बताती। महत्वपूर्ण "
            "निर्णय आपकी वास्तविक परिस्थितियों और आवश्यकता होने पर किसी "
            "योग्य परामर्शदाता की सलाह के आधार पर लिए जाने चाहिए।"
        ),
    },
    # Q3 Batch 2 -- second_marriage_report. Never a guarantee, never a
    # statement about the outcome/ending of any current marriage.
    "second_marriage_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based tendency reading about the "
            "possibility of a second marriage or a significant later "
            "union -- not a guarantee, and not a statement about the "
            "outcome or ending of any current marriage. Personal and "
            "legal decisions should rest on your real circumstances."
        ),
        "hi": (
            "यह दूसरे विवाह या किसी महत्वपूर्ण बाद के संबंध की संभावना के "
            "बारे में ज्योतिष-आधारित प्रवृत्ति है -- यह कोई गारंटी नहीं है, "
            "और न ही यह किसी वर्तमान विवाह के परिणाम या समाप्ति के बारे में "
            "कोई कथन है। व्यक्तिगत और कानूनी निर्णय आपकी वास्तविक "
            "परिस्थितियों पर आधारित होने चाहिए।"
        ),
    },
    # Q3 Batch 3 -- financial_report / financial_stability_report.
    # Never financial/investment/tax advice, never a profit/wealth
    # guarantee, never a specific investment/security recommendation.
    "financial_advice_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based view of financial tendencies, "
            "not financial, investment, or tax advice, and not a "
            "guarantee of profit, income, or wealth. It does not "
            "recommend any specific investment or security. Important "
            "financial decisions should be based on your real "
            "circumstances and, where needed, a qualified financial "
            "advisor."
        ),
        "hi": (
            "यह रिपोर्ट वित्तीय प्रवृत्तियों का ज्योतिष-आधारित आकलन है, "
            "यह वित्तीय, निवेश या कर संबंधी सलाह नहीं है, और न ही यह आय, "
            "लाभ या धन-संपत्ति की कोई गारंटी है। यह किसी विशेष निवेश या "
            "सिक्योरिटी की सिफारिश नहीं करती। महत्वपूर्ण वित्तीय निर्णय "
            "आपकी वास्तविक परिस्थितियों और आवश्यकता होने पर किसी योग्य "
            "वित्तीय सलाहकार की सलाह के आधार पर लिए जाने चाहिए।"
        ),
    },
    # Q3 Batch 3 -- government_job_report. Never a prediction/guarantee
    # of exam success, selection, or appointment.
    "government_job_selection_non_certainty_mandatory": {
        "en": (
            "This report describes astrological tendencies related to "
            "government or public-sector work, not a prediction or "
            "guarantee of exam success, selection, or appointment. "
            "Outcomes depend on your preparation, eligibility, and the "
            "actual selection process."
        ),
        "hi": (
            "यह रिपोर्ट सरकारी या सार्वजनिक क्षेत्र से जुड़ी ज्योतिषीय "
            "प्रवृत्तियों का वर्णन करती है। यह परीक्षा में सफलता, चयन या "
            "नियुक्ति की भविष्यवाणी या गारंटी नहीं है। परिणाम आपकी "
            "तैयारी, पात्रता और वास्तविक चयन प्रक्रिया पर निर्भर करते हैं।"
        ),
    },
    # Q3 Batch 3 -- business_report / startup_suggestion_report. Never
    # a guarantee of business success, revenue, funding, or
    # profitability.
    "business_outcome_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based view of business and "
            "entrepreneurial tendencies, not a guarantee of business "
            "success, revenue, funding, or profitability. Do not make "
            "high-stakes business or financial decisions based on this "
            "report alone."
        ),
        "hi": (
            "यह रिपोर्ट व्यवसाय और उद्यमिता से जुड़ी प्रवृत्तियों का "
            "ज्योतिष-आधारित आकलन है। यह व्यावसायिक सफलता, राजस्व, फंडिंग "
            "या लाभ की कोई गारंटी नहीं है। केवल इस रिपोर्ट के आधार पर "
            "कोई बड़ा व्यावसायिक या वित्तीय निर्णय न लें।"
        ),
    },
    # Q3 Batch 4: backend-controlled relationship disclaimers.
    "relationship_pattern_general": {
        "en": (
            "This is an astrology-based interpretation of relationship tendencies, not a "
            "prediction of another person's thoughts, feelings, intentions, fidelity, or "
            "future actions. Relationship outcomes depend on the people involved and their "
            "real circumstances."
        ),
        "hi": (
            "यह संबंधों से जुड़ी प्रवृत्तियों का ज्योतिष-आधारित आकलन है। यह किसी अन्य "
            "व्यक्ति के विचारों, भावनाओं, इरादों, निष्ठा या भविष्य के व्यवहार की भविष्यवाणी "
            "नहीं करता। संबंधों के परिणाम संबंधित लोगों और उनकी वास्तविक परिस्थितियों पर "
            "निर्भर करते हैं।"
        ),
    },
    "love_disappointment_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based view of emotional and relationship patterns, not a "
            "mental-health diagnosis and not a prediction of betrayal, cheating, breakup, "
            "or another person's private thoughts or intentions. Important relationship "
            "decisions should be based on your real circumstances."
        ),
        "hi": (
            "यह भावनात्मक और संबंधों से जुड़ी प्रवृत्तियों का ज्योतिष-आधारित आकलन है। यह "
            "मानसिक स्वास्थ्य का निदान नहीं है और न ही विश्वासघात, बेवफाई, संबंध-विच्छेद या "
            "किसी अन्य व्यक्ति के निजी विचारों या इरादों की भविष्यवाणी करता है। महत्वपूर्ण "
            "संबंध निर्णय आपकी वास्तविक परिस्थितियों के आधार पर लिए जाने चाहिए।"
        ),
    },
    "relationship_future_non_certainty_mandatory": {
        "en": (
            "This report combines astrology-based compatibility evidence with interpretive "
            "relationship guidance. It does not reveal or predict another person's private "
            "thoughts, feelings, intentions, fidelity, or future actions, and it does not "
            "guarantee marriage, reconciliation, separation, or breakup. Important "
            "relationship decisions should be based on your real circumstances and "
            "communication with the person involved."
        ),
        "hi": (
            "यह रिपोर्ट ज्योतिष-आधारित अनुकूलता प्रमाणों को संबंध संबंधी व्याख्यात्मक "
            "मार्गदर्शन के साथ प्रस्तुत करती है। यह किसी अन्य व्यक्ति के निजी विचारों, "
            "भावनाओं, इरादों, निष्ठा या भविष्य के व्यवहार को जानने या उनकी भविष्यवाणी करने "
            "का दावा नहीं करती, और न ही विवाह, पुनर्मिलन, अलगाव या संबंध-विच्छेद की गारंटी "
            "देती है। महत्वपूर्ण संबंध निर्णय आपकी वास्तविक परिस्थितियों और संबंधित व्यक्ति "
            "के साथ संवाद के आधार पर लिए जाने चाहिए।"
        ),
    },
    # Q3 Batch 5 (FINAL) -- the last 5 mandatory disclaimers: sadhesati_
    # report, children_parenting_report, lifestyle_analysis_report,
    # property_report, legal_disputes_report. Reuses this exact same
    # generic mechanism unchanged -- no new disclaimer framework.
    "sadhesati_non_certainty_mandatory": {
        "en": (
            "This report describes astrology-based Saturn transit themes and periods, "
            "not a prediction or guarantee of hardship, illness, job loss, financial "
            "loss, or any other negative event. Its purpose is awareness and "
            "preparation, not fear."
        ),
        "hi": (
            "यह रिपोर्ट ज्योतिष-आधारित शनि गोचर की प्रवृत्तियों और अवधियों का वर्णन करती "
            "है। यह कठिनाई, बीमारी, नौकरी छूटने, आर्थिक हानि या किसी अन्य नकारात्मक घटना "
            "की भविष्यवाणी या गारंटी नहीं है। इसका उद्देश्य जागरूकता और तैयारी है, भय नहीं।"
        ),
    },
    "children_parenting_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based view of parenting tendencies and parent-child "
            "dynamics. It is not a prediction or guarantee about fertility, pregnancy, "
            "conception timing, a child's health, or a child's sex, and it is not "
            "medical advice."
        ),
        "hi": (
            "यह पालन-पोषण की प्रवृत्तियों और माता-पिता-बच्चे के संबंधों का ज्योतिष-आधारित "
            "आकलन है। यह प्रजनन क्षमता, गर्भधारण, गर्भधारण के समय, बच्चे के स्वास्थ्य या "
            "बच्चे के लिंग की भविष्यवाणी या गारंटी नहीं है, और न ही यह चिकित्सीय सलाह है।"
        ),
    },
    "lifestyle_health_non_certainty_mandatory": {
        "en": (
            "This report describes astrology-based lifestyle and habit tendencies. It "
            "is not a medical diagnosis, not a treatment recommendation, and does not "
            "guarantee any health or longevity outcome. For health concerns, consult a "
            "qualified healthcare professional."
        ),
        "hi": (
            "यह रिपोर्ट ज्योतिष-आधारित जीवनशैली और आदतों की प्रवृत्तियों का वर्णन करती "
            "है। यह कोई चिकित्सीय निदान या उपचार सुझाव नहीं है, और न ही यह किसी स्वास्थ्य "
            "या दीर्घायु परिणाम की गारंटी देती है। स्वास्थ्य संबंधी चिंताओं के लिए किसी "
            "योग्य स्वास्थ्य विशेषज्ञ से परामर्श करें।"
        ),
    },
    "property_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based view of property-related tendencies, not a "
            "guarantee of purchase, price appreciation, investment return, or legal "
            "title outcome. Important property and legal decisions should be based on "
            "your real circumstances and, where needed, qualified legal and financial "
            "advice."
        ),
        "hi": (
            "यह संपत्ति से जुड़ी प्रवृत्तियों का ज्योतिष-आधारित आकलन है, यह खरीद, मूल्य "
            "वृद्धि, निवेश लाभ या कानूनी स्वामित्व परिणाम की गारंटी नहीं है। महत्वपूर्ण "
            "संपत्ति और कानूनी निर्णय आपकी वास्तविक परिस्थितियों और आवश्यकता होने पर योग्य "
            "कानूनी एवं वित्तीय सलाह के आधार पर लिए जाने चाहिए।"
        ),
    },
    "legal_dispute_non_certainty_mandatory": {
        "en": (
            "This is an astrology-based view of dispute-pressure tendencies, not a "
            "prediction or guarantee of court victory, defeat, arrest, conviction, or "
            "acquittal, and not legal advice. Important legal decisions should be based "
            "on your real circumstances and a qualified legal professional."
        ),
        "hi": (
            "यह विवाद-दबाव की प्रवृत्तियों का ज्योतिष-आधारित आकलन है, यह अदालती जीत, "
            "हार, गिरफ्तारी, दोषसिद्धि या दोषमुक्ति की भविष्यवाणी या गारंटी नहीं है, और न "
            "ही यह कानूनी सलाह है। महत्वपूर्ण कानूनी निर्णय आपकी वास्तविक परिस्थितियों और "
            "किसी योग्य कानूनी विशेषज्ञ की सलाह के आधार पर लिए जाने चाहिए।"
        ),
    },
}


def get_mandatory_disclaimer(disclaimer_type: Optional[str], language: str) -> Optional[str]:
    """Fixed backend disclaimer text for a mandatory disclaimer_type, or
    None for any other type (including "none") -- never sourced from AI
    output. Falls back to the English text if `language` has no entry
    (never renders a blank disclaimer for an unexpected language code)."""
    entry = DISCLAIMER_TEXT.get(disclaimer_type or "")
    if not entry:
        return None
    return entry.get(language) or entry.get("en")


def compute_gemstone_hero_value(gemstone_suggestion: Optional[dict]) -> Optional[str]:
    """gemstone_consultation's answer_hero `value` -- ALWAYS the
    deterministic gemstone name from kundali["gemstone_suggestion"],
    never Luna's own reproduction of it. Returns None when the
    deterministic recommendation itself is unavailable/incomplete --
    tasks.py treats that as a hard failure for this one product, since
    the gemstone recommendation IS the purchased answer."""
    if not gemstone_suggestion:
        return None
    return gemstone_suggestion.get("gemstone") or None


def compute_saturn_transit_hero(kundali: dict, language: str = "en") -> dict:
    """saturn_transit_report's answer_hero `value`/`timing` plus an
    optional `timeline` component -- all deterministic.

    `value`/house: Saturn's current Lagna-relative transit house, using
    the SAME whole-sign-offset formula summary_blocks.py's own
    _build_transit_facts_summary() already uses (reused here via direct
    import, not reimplemented) against kundali["lagna_sign"] and the
    Saturn position already computed earlier in this request
    (kundali["transit_summary"]["positions"]["Saturn"]). This is
    mandatory for the product's own answer -- raises ReportMetadataError
    (the same hard-failure class Batch 0 already uses for missing
    structured metadata) if it cannot be determined, since the
    purchased answer cannot be produced without it.

    `timing`: best-effort only. smart_transit_engine.
    get_current_sign_residency("Saturn") (Q3A/Q3B-verified
    planet-generic; delegates to transit_engine.py's own canonical
    boundary-detection -- no new astrology calculation) may legitimately
    return None, or raise, for a boundary that cannot be resolved; in
    either case timing/timeline are simply omitted, per Batch 1's own
    "omit exact timing rather than guess" instruction. A timing failure
    never fails generation -- only the mandatory `value` above does.
    """
    lagna_sign = kundali.get("lagna_sign")
    positions = (kundali.get("transit_summary") or {}).get("positions", {})
    saturn_position = positions.get("Saturn") or {}
    saturn_rashi = saturn_position.get("rashi")

    house = _house_from_lagna(saturn_rashi, lagna_sign) if lagna_sign and saturn_rashi else None
    if not house:
        raise ReportMetadataError(
            "saturn_transit_report: could not determine Saturn's current "
            "Lagna-relative transit house from deterministic chart data."
        )

    value = f"{_ordinal(house)} House from Lagna ({saturn_rashi})"

    residency = None
    try:
        residency = get_current_sign_residency("Saturn")
    except Exception:
        residency = None

    # Q3 Batch 1 (visual QA correction) -- customer-facing dates use the
    # shared DD/MM/YYYY formatter; the raw ISO dates from
    # get_current_sign_residency() are never displayed directly. The
    # timeline heading is looked up via the same renderer-level label
    # system tasks.py/pdf_generator_weasy.py use -- no separate Hindi
    # decision logic, just a language-keyed string lookup.
    timing = None
    timeline = None
    if residency and residency.get("entering_date") and residency.get("exit_date"):
        timing = format_customer_date_range(residency["entering_date"], residency["exit_date"])
        timeline = {
            "heading": get_label("saturn_transit_window", language),
            "entries": [{
                "label": f"Saturn in {residency.get('to_rashi', saturn_rashi)}",
                "date_range": timing,
                "note": "Current transit sign residency",
                "current": True,
            }],
        }

    return {"value": value, "timing": timing, "timeline": timeline}
