# modules/payments/report_q3_batch2.py

"""
report_q3_batch2.py -- Paid Report Platform, Q3 Batch 2.

Product-specific deterministic wiring for the 4 marriage-family
products (marriage_report, delay_in_marriage_report,
problem_in_marriage_report, second_marriage_report). Mirrors
report_q3_batch1.py's own precedent exactly: a small, per-batch sibling
module holding only what that batch's products need, never a second
parallel Q3 framework -- this file introduces no new AI call, no new
PDF component shape, and no new astrology calculation.

Only one deterministic helper is needed for this batch:
compute_dasha_window_timeline() -- a Q2.1 `timeline` component built
from real, already-computed Dasha dates (marriage_report and
delay_in_marriage_report are the only 2 of the 4 with timeline=True in
their registry entries). It reuses summary_blocks.py's own
_flatten_dasha_sequence() (the exact same walk dasha_window_summary's
own text already performs) rather than re-deriving anything.

Unlike Q3 Batch 1's saturn_transit_report/gemstone_consultation, none
of these 4 products override the answer_hero VALUE deterministically --
all 4 keep hero_value_source="ai" (a qualitative outlook/tier
descriptor synthesized by Luna from deterministic evidence, since no
marriage-scoring or marriage-timing-event engine exists in this
codebase -- see the Q3 Batch 2 audit). The two/three-tier enum
constraint on delay_in_marriage_report's and second_marriage_report's
own hero value ("Low"/"Moderate"/"Elevated") is enforced at the PROMPT
level only, the same precedent already established for
divorce_possibility_report in Q3 Batch 1 -- deliberately not a backend
enum validator, to avoid a new, fragile failure mode over a wording
choice.

The 2 new mandatory disclaimers this batch needs
(marriage_problem_non_certainty_mandatory,
second_marriage_non_certainty_mandatory) are NOT redefined here -- they
were added directly to report_q3_batch1.py's own DISCLAIMER_TEXT
dict/get_mandatory_disclaimer(), which is already generic and shared;
duplicating that mechanism in a second file was rejected as
unnecessary.
"""

from __future__ import annotations

from typing import Optional

from summary_blocks import _flatten_dasha_sequence
from modules.payments.report_date_format import format_customer_date_range
from modules.payments.report_i18n_labels import get_label


def compute_dasha_window_timeline(kundali: dict, language: str = "en") -> Optional[dict]:
    """Builds a Q2.1 `timeline` component from the current Dasha window
    plus up to 2 real upcoming Antardasha windows -- the exact same
    data summary_blocks.py's own dasha_window_summary sentence already
    walks (kundali["current_mahadasha"]/["current_antardasha"]/
    ["Mahadasha"], all already computed by calculate_full_kundali() for
    every order). Dates are formatted via the shared word-month
    presentation formatter in the report language (Q5.6B) -- the
    underlying ISO dates are never touched. Mahadasha/Antardasha lord names stay in their existing
    backend representation (English planet names) in both languages,
    matching the established convention for deterministic data
    throughout this codebase -- only the fixed heading/note labels
    around them are localized.

    Returns None (component omitted, matching every other optional-
    component convention here) when the current window cannot be
    located -- never a guessed or partially-built timeline."""
    current_maha = kundali.get("current_mahadasha") or {}
    current_antar = kundali.get("current_antardasha") or {}
    maha_lord = current_maha.get("mahadasha")
    antar_lord = current_antar.get("planet")
    antar_start = current_antar.get("start")
    antar_end = current_antar.get("end")

    if not (maha_lord and antar_lord and antar_start):
        return None

    flat = _flatten_dasha_sequence(kundali.get("Mahadasha"))
    current_index = None
    for i, window in enumerate(flat):
        if window["mahadasha"] == maha_lord and window["planet"] == antar_lord and window["start"] == antar_start:
            current_index = i
            break

    entries = [{
        "label": f"{maha_lord} Mahadasha – {antar_lord} Antardasha",
        "date_range": format_customer_date_range(antar_start, antar_end, language),
        "note": get_label("current_dasha_window", language),
        "current": True,
    }]

    if current_index is not None:
        for window in flat[current_index + 1: current_index + 3]:
            entries.append({
                "label": f"{window['mahadasha']} Mahadasha – {window['planet']} Antardasha",
                "date_range": format_customer_date_range(window["start"], window["end"], language),
                "note": get_label("upcoming_dasha_window", language),
                "current": False,
            })

    return {
        "heading": get_label("dasha_timeline_heading", language),
        "entries": entries,
    }
