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
        "hi": "अनुशंसित रत्न",
    },
    "alternative_substone": {
        "en": "Alternative sub-stone",
        "hi": "उपरत्न (विकल्प)",
    },
    "supporting_planet": {
        "en": "Supporting planet",
        "hi": "सहायक ग्रह",
    },
    "timing": {
        "en": "Timing",
        "hi": "समयावधि",
    },
    "suggested_next_steps": {
        "en": "Suggested Next Steps",
        "hi": "सुझाए गए अगले कदम",
    },
    "saturn_transit_window": {
        "en": "Current Saturn Transit Window",
        "hi": "वर्तमान शनि गोचर अवधि",
    },
    # Q3 Batch 2 -- shared Dasha-window timeline component (marriage_
    # report, delay_in_marriage_report), see report_q3_batch2.py.
    "dasha_timeline_heading": {
        "en": "Current & Upcoming Dasha Windows",
        "hi": "वर्तमान एवं आगामी दशा अवधि",
    },
    "current_dasha_window": {
        "en": "Current period",
        "hi": "वर्तमान अवधि",
    },
    "upcoming_dasha_window": {
        "en": "Upcoming window",
        "hi": "आगामी अवधि",
    },
    "app_download_heading": {
        "en": "Continue Your Astrology Journey",
        "hi": "अपनी ज्योतिष यात्रा जारी रखें",
    },
    "app_download_body": {
        "en": "Get your personalized astrology insights, daily guidance and more in the Jyotishasha App.",
        "hi": "Jyotishasha ऐप में पाएं अपनी व्यक्तिगत ज्योतिष जानकारी, दैनिक मार्गदर्शन और भी बहुत कुछ।",
    },
    "app_download_action": {
        "en": "Download Jyotishasha App",
        "hi": "Jyotishasha ऐप डाउनलोड करें",
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
