# modules/payments/report_q3_batch5.py

"""
report_q3_batch5.py -- Paid Report Platform, Q3 Batch 5 (FINAL).

Product-specific deterministic wiring for the last 7 products
(sadhesati_report, foreign_travel_report, children_parenting_report,
jupiter_transit_report, lifestyle_analysis_report, property_report,
legal_disputes_report). Mirrors report_q3_batch1.py/report_q3_batch3.py/
report_q3_batch4.py's own established precedent exactly: a small,
per-batch sibling module holding only what THIS batch's products need,
never a second parallel Q3 framework.

Only 2 of the 7 products have a genuine deterministic answer_hero
`value` to source (sadhesati_report, jupiter_transit_report) -- both
helpers below are near-identical to report_q3_batch1.py::
compute_saturn_transit_hero() by design, reusing the exact same
primitives (summary_blocks._house_from_lagna/_ordinal, smart_transit_
engine.get_current_sign_residency(), report_date_format.
format_customer_date_range(), report_i18n_labels.get_label()) --
nothing here is a new astrology calculation.

The other 5 products (foreign_travel_report, children_parenting_
report, lifestyle_analysis_report, property_report, legal_disputes_
report) keep hero_value_source="ai" -- no deterministic classifier for
any of them exists anywhere in this codebase (confirmed in the Q3
Final-7 audit), exactly the same situation Q3 Batch 2's marriage_
report/delay_in_marriage_report and Q3 Batch 3's 6 products were
already in. All 7 reuse report_q3_batch2.py::compute_dasha_window_
timeline() unchanged for their own Dasha-window context, imported
directly by tasks.py, not re-exported here.

Sade Sati deterministic dates: this module deliberately reads
kundali["sadhesati"]["phase_dates"] via the SAME phase-label mapping
summary_blocks.py::_build_sadhesati_summary() already uses (imported
directly, not re-derived) -- NOT services/sadhesati_report_generator.
py's own internal (buggy) phase-date lookup. That underlying engine's
own phase-label-to-date-key mismatch (documented in summary_blocks.py's
own comment above _build_sadhesati_summary()) is out of this batch's
scope and is not touched here.

No new astrology calculation, no fertility/legal-outcome/health-
diagnosis classifier, no invented percentage, no exact life-event
timing -- none of that exists anywhere in this module, by design.
"""

from __future__ import annotations

from typing import Optional

from smart_transit_engine import get_current_sign_residency
from summary_blocks import _house_from_lagna, _ordinal, _SADHESATI_PHASE_KEY_MAP
from modules.payments.report_structured_output import ReportMetadataError
from modules.payments.report_date_format import format_customer_date_range
from modules.payments.report_i18n_labels import get_label

BATCH5_PRODUCT_SLUGS = frozenset({
    "sadhesati_report",
    "foreign_travel_report",
    "children_parenting_report",
    "jupiter_transit_report",
    "lifestyle_analysis_report",
    "property_report",
    "legal_disputes_report",
})


def compute_sadhesati_hero(kundali: dict, language: str = "en") -> dict:
    """sadhesati_report's answer_hero `value` plus an optional
    `timeline` component -- all deterministic, sourced from
    kundali["sadhesati"] (services/sadhesati_report_generator.py::
    classify_sade_sati(), already computed for every order).

    `value`: "Active -- <Nth Phase>" or "Inactive". This IS the
    purchased answer -- raises ReportMetadataError (same hard-failure
    class every other mandatory-deterministic-value product already
    uses) if kundali["sadhesati"]["status"] is not one of the two
    recognized values, since the purchased answer cannot be produced
    without it.

    `timing`/`timeline`: best-effort only, read from phase_dates via
    the SAME correctly-keyed mapping summary_blocks.py's own
    _build_sadhesati_summary() uses -- for Active, the current phase's
    own window; for Inactive, the next expected phase's window if the
    underlying engine supplied one. Missing/incomplete dates simply
    omit timing/timeline (never guessed), matching Batch 1's own "omit
    exact timing rather than guess" instruction. A timing gap never
    fails generation -- only the mandatory `value` above does.
    """
    info = kundali.get("sadhesati") or {}
    status = info.get("status")
    if status not in ("Active", "Inactive"):
        raise ReportMetadataError(
            "sadhesati_report: could not determine deterministic Sade Sati "
            "status from chart data."
        )

    phase = info.get("phase")
    phase_dates = info.get("phase_dates") or {}

    if status == "Active":
        value = f"Active -- {phase}" if phase else "Active"
        window_key = _SADHESATI_PHASE_KEY_MAP.get(phase) if phase else None
        window = phase_dates.get(window_key) if window_key else None
        current = True
        entry_label = f"{phase} of Sade Sati" if phase else "Current Sade Sati phase"
        entry_note = get_label("current_sadhesati_phase_note", language)
    else:
        value = "Inactive"
        window = phase_dates.get("first_phase")
        current = False
        entry_label = "Upcoming Sade Sati"
        entry_note = "Next expected Sade Sati window"

    timing = None
    timeline = None
    if window and window.get("start") and window.get("end"):
        timing = format_customer_date_range(window["start"], window["end"], language)
        timeline = {
            "heading": get_label("sadhesati_window", language),
            "entries": [{
                "label": entry_label,
                "date_range": timing,
                "note": entry_note,
                "current": current,
            }],
        }

    return {"value": value, "timing": timing, "timeline": timeline}


def compute_jupiter_transit_hero(kundali: dict, language: str = "en") -> dict:
    """jupiter_transit_report's answer_hero `value` plus an optional
    `timeline` component -- all deterministic. Mirrors report_q3_
    batch1.py::compute_saturn_transit_hero() exactly, parameterized for
    Jupiter -- SAME whole-sign-offset formula, SAME planet-generic
    smart_transit_engine.get_current_sign_residency() call (verified
    planet-generic; Jupiter is present in PLANET_IDS), no new engine.

    `value`/house: Jupiter's current Lagna-relative transit house --
    mandatory for the product's own answer, raises ReportMetadataError
    if it cannot be determined.

    `timing`: best-effort only, exactly like Saturn's own -- a
    boundary that cannot be resolved simply omits timing/timeline.
    """
    lagna_sign = kundali.get("lagna_sign")
    positions = (kundali.get("transit_summary") or {}).get("positions", {})
    jupiter_position = positions.get("Jupiter") or {}
    jupiter_rashi = jupiter_position.get("rashi")

    house = _house_from_lagna(jupiter_rashi, lagna_sign) if lagna_sign and jupiter_rashi else None
    if not house:
        raise ReportMetadataError(
            "jupiter_transit_report: could not determine Jupiter's current "
            "Lagna-relative transit house from deterministic chart data."
        )

    value = f"{_ordinal(house)} House from Lagna ({jupiter_rashi})"

    residency = None
    try:
        residency = get_current_sign_residency("Jupiter")
    except Exception:
        residency = None

    timing = None
    timeline = None
    if residency and residency.get("entering_date") and residency.get("exit_date"):
        timing = format_customer_date_range(residency["entering_date"], residency["exit_date"], language)
        timeline = {
            "heading": get_label("jupiter_transit_window", language),
            "entries": [{
                "label": f"Jupiter in {residency.get('to_rashi', jupiter_rashi)}",
                "date_range": timing,
                "note": get_label("current_transit_note", language),
                "current": True,
            }],
        }

    return {"value": value, "timing": timing, "timeline": timeline}
