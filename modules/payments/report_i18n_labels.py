# modules/payments/report_i18n_labels.py

"""
report_i18n_labels.py -- Paid Report Platform, Q3 Batch 1 (visual QA
correction round).

Shared, renderer-level localization for the small set of FIXED English
UI strings that pdf_generator_weasy.py/templates/report_template.html
and tasks.py hardcoded for shared Q2.1 components (gemstone box,
answer-hero timing label, action-list heading, app-download CTA).

This is NOT astrology/business logic -- it is a plain label lookup
keyed by the report's own existing `language` value ("en"/"hi"), the
same value that already selects which prompt file and which font-face
CSS rule apply. No new per-language decision path is introduced
anywhere else; tasks.py and pdf_generator_weasy.py call get_label()
exactly the same way regardless of product or language, so the
underlying astrology/report-generation logic never branches on
language beyond what already existed.
"""

from __future__ import annotations

LABELS = {
    "recommended_gemstone": {
        "en": "Recommended Gemstone",
        "hi": "आपके लिए Recommended Gemstone",
    },
    "alternative_substone": {
        "en": "Alternative sub-stone",
        "hi": "Alternative Sub-stone",
    },
    "supporting_planet": {
        "en": "Supporting planet",
        "hi": "Supporting Planet",
    },
    "timing": {
        "en": "Timing",
        "hi": "Timing",
    },
    "suggested_next_steps": {
        "en": "Suggested Next Steps",
        "hi": "आपके लिए Next Steps",
    },
    "saturn_transit_window": {
        "en": "Current Saturn Transit Window",
        "hi": "अभी का Saturn Transit",
    },
    # Q3 Batch 5 -- sadhesati_report/jupiter_transit_report's own
    # deterministic timeline headings, same convention as
    # saturn_transit_window above.
    "sadhesati_window": {
        "en": "Sade Sati Phase Window",
        "hi": "Sade Sati का Phase",
    },
    "jupiter_transit_window": {
        "en": "Current Jupiter Transit Window",
        "hi": "अभी का Jupiter Transit",
    },
    # Q3 Batch 2 -- shared Dasha-window timeline component (marriage_
    # report, delay_in_marriage_report), see report_q3_batch2.py.
    "dasha_timeline_heading": {
        "en": "Current & Upcoming Dasha Windows",
        "hi": "अभी और आगे की Dasha Periods",
    },
    "current_dasha_window": {
        "en": "Current period",
        "hi": "अभी चल रही अवधि",
    },
    "upcoming_dasha_window": {
        "en": "Upcoming window",
        "hi": "आने वाली अवधि",
    },
    # Q4.2B -- timeline-entry notes shared by saturn_transit_report,
    # jupiter_transit_report and sadhesati_report. English values are
    # EXACTLY the strings those builders hardcoded before.
    "current_transit_note": {
        "en": "Current transit sign residency",
        "hi": "अभी का Transit",
    },
    "current_sadhesati_phase_note": {
        "en": "Current Sade Sati phase",
        "hi": "अभी चल रहा Phase",
    },
    "app_download_heading": {
        "en": "Continue Your Astrology Journey",
        "hi": "अपनी ज्योतिष यात्रा जारी रखें",
    },
    "app_download_body": {
        "en": "Get your personalized astrology insights, daily guidance and more in the Jyotishasha App.",
        "hi": "Jyotishasha App में पाएं अपनी Personalized Astrology Insights, Daily Guidance और बहुत कुछ।",
    },
    "app_download_action": {
        "en": "Download Jyotishasha App",
        "hi": "Jyotishasha App Download करें",
    },
    # Q4.2A -- modern-Hindi static labels for the cover / summary cards
    # that report_template.html previously hardcoded in English for
    # every language. English values below are EXACTLY the old literal
    # template strings (English output unchanged); only "hi" differs.
    "sample_badge": {
        "en": "Sample Report",
        "hi": "नमूना रिपोर्ट",
    },
    "prepared_for": {
        "en": "Prepared for:",
        "hi": "नाम:",
    },
    "report_date": {
        "en": "Report Date:",
        "hi": "Report की तारीख:",
    },
    "birth_chart_summary_heading": {
        "en": "Birth Chart Summary",
        "hi": "आपकी Birth Chart का Summary",
    },
    "mahadasha_summary_heading": {
        "en": "Mahadasha Summary",
        "hi": "आपकी Mahadasha का Summary",
    },
    "current_transit_summary_heading": {
        "en": "Current Transit Summary",
        "hi": "अभी का Transit Summary",
    },
    # Rendered with |safe in the template (developer-authored constant,
    # contains &nbsp; separators exactly like the old inline legend).
    "chart_legend": {
        "en": "Su = Sun &nbsp; Mo = Moon &nbsp; Ma = Mars &nbsp; Me = Mercury &nbsp; Ju = Jupiter &nbsp; Ve = Venus &nbsp; Sa = Saturn &nbsp; Ra = Rahu &nbsp; Ke = Ketu",
        "hi": "Su = Sun (Surya) &nbsp; Mo = Moon (Chandra) &nbsp; Ma = Mars (Mangal) &nbsp; Me = Mercury (Budh) &nbsp; Ju = Jupiter (Guru) &nbsp; Ve = Venus (Shukra) &nbsp; Sa = Saturn (Shani) &nbsp; Ra = Rahu &nbsp; Ke = Ketu",
    },
    # Q4.4B -- relationship_future_report's "who this report is for" block.
    "people_heading": {
        "en": "This Report Is For",
        "hi": "यह Report इनके लिए है",
    },
    "birth_date_label": {
        "en": "Date of Birth",
        "hi": "Date of Birth",
    },
    "birth_time_label": {
        "en": "Time of Birth",
        "hi": "Time of Birth",
    },
    "birth_place_label": {
        "en": "Place of Birth",
        "hi": "Place of Birth",
    },
    "google_play": {
        "en": "Google Play",
        "hi": "Google Play",
    },
    "app_store": {
        "en": "App Store",
        "hi": "App Store",
    },
}


def get_label(key: str, language: str) -> str:
    """Never raises, never returns None. Falls back to the English text
    for an unrecognized language code, and to an empty string for an
    unrecognized key (never crashes report generation over a missing
    label)."""
    entry = LABELS.get(key)
    if not entry:
        return ""
    return entry.get(language) or entry.get("en", "")


def labels_for_language(language: str) -> dict:
    """All labels resolved for one language, for passing straight into
    a Jinja render context as a single `labels` dict."""
    return {key: get_label(key, language) for key in LABELS}
