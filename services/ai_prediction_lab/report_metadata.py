"""
services/ai_prediction_lab/report_metadata.py
-------------------------------------------------------------
Builds the small, user-facing informational metadata shown alongside
each Love Engine section (stable type/stability identifiers, footer
notes, and machine-readable dates). This is NOT part of the AI-generated
report text -- it is separate metadata for the frontend to render (as a
subtle footnote, info card, muted label, or badge) and to drive its own
locale-formatted date display.

No astrology calculation happens here. The two dates already exist in
the Current Love Phase context (current_love_phase_context.py's
`antardasha.end`, already derived from the backend's own dasha
calculation); the daily refresh date is a plain calendar computation
(today + 1 day), not an astrological one.

`type` and `stability` are stable backend identifiers -- they never
change with the UI language. The frontend maps them to its own
localized labels (see report_response.py for the top-level envelope
that also carries the `language` field).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

STABILITY_NOTE = (
    "Your Relationship DNA is based on your birth chart and reflects the "
    "relationship patterns you naturally carry throughout life. While life "
    "experiences help you grow and mature, these core tendencies usually "
    "remain consistent."
)

# Stable backend identifiers -- never presentation labels, never
# language-dependent. The frontend owns turning these into display text.
SECTION_TYPES = {
    "relationship_dna": {"type": "relationship_dna", "stability": "permanent"},
    "current_love_phase": {"type": "current_love_phase", "stability": "temporary"},
    "daily_love_insight": {"type": "daily_love_insight", "stability": "daily"},
}

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _iso(d: date) -> str:
    return d.isoformat()


def _friendly_month_year(d: date) -> str:
    """Used only inside the English `note` prose sentence -- not returned
    as a dedicated date field. Dedicated date fields (`valid_until`,
    `next_refresh`) are always ISO; presentation formatting is the
    frontend's job."""
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _friendly_full_date(d: date) -> str:
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def build_report_metadata(love_phase_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns the `metadata` object of the final response envelope:
        relationship_dna:   {type, stability, stability_note}
        current_love_phase: {type, stability, valid_until (ISO), note}
        daily_love_insight: {type, stability, next_refresh (ISO), note}
    """
    antardasha_end: Optional[str] = (love_phase_context.get("antardasha") or {}).get("end")
    valid_until_date = _parse_date(antardasha_end) if antardasha_end else None
    valid_until_iso = _iso(valid_until_date) if valid_until_date else None

    next_refresh_date = date.today() + timedelta(days=1)
    next_refresh_iso = _iso(next_refresh_date)

    return {
        "relationship_dna": {
            **SECTION_TYPES["relationship_dna"],
            "stability_note": STABILITY_NOTE,
        },
        "current_love_phase": {
            **SECTION_TYPES["current_love_phase"],
            "valid_until": valid_until_iso,
            "note": (
                f"This phase is expected to remain active until approximately "
                f"{_friendly_month_year(valid_until_date)}. Your relationship "
                f"outlook will be updated automatically when your next major "
                f"relationship cycle begins."
            ) if valid_until_date else None,
        },
        "daily_love_insight": {
            **SECTION_TYPES["daily_love_insight"],
            "next_refresh": next_refresh_iso,
            "note": (
                f"This daily guidance is refreshed regularly to reflect your "
                f"current relationship outlook. Your next update is expected "
                f"on {_friendly_full_date(next_refresh_date)}."
            ),
        },
    }
