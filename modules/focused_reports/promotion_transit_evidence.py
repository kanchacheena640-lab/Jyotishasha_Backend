# modules/focused_reports/promotion_transit_evidence.py

"""
promotion_transit_evidence.py -- Focused Reports prototype: the concise transit
facts a "Will I get a promotion in the next 12 months?" report needs.

NO new transit engine. Everything is read from the existing, tested code:
  * transit_engine.get_current_positions()        -> today's sidereal sign
  * transit_engine.get_current_sign_residency()   -> how long the planet stays in that sign
  * transit_engine.get_next_12_rashi_segments()   -> the planet's upcoming sign changes
  * smart_transit_engine.get_planet_position_on() -> Direct/Retrograde on any date
  * summary_blocks._house_from_lagna              -> whole-sign house from the natal Lagna
  * report_date_format.format_customer_date(_range) -> the locked Q5.6 customer date format

SIGN RESIDENCE AND MOTION ARE TWO SEPARATE FACTS, each with its own dates:
  Sign residence  which sign / house a planet occupies and when it moves on.
  Motion          whether it is Direct or Retrograde, and when that changes.
A planet can stay in one sign through a whole retrograde cycle (Saturn, Jupiter),
so a single line such as "Retrograde, until <date>" is ambiguous and is never
produced. Motion boundaries are found by sampling the existing ephemeris helper
day by day over the requested horizon -- no date is hard-coded.

DATES: the structured evidence keeps internal ISO YYYY-MM-DD. Only the rendered
text (the block sent to Luna) uses the customer format ("21 September 2026",
Hindi "21 सितंबर 2026"), so Luna copies customer-format dates and no ISO date
reaches the customer.

WHICH PLANETS, AND WHY (deliberately minimal -- three, not nine)
  Jupiter  the planet of growth and opportunity. It stays about a year in a sign, so where it is
           (and when it changes sign) frames the whole 12-month window; retrograde motion can make
           it change sign twice.
  Saturn   the planet of career, responsibility and earned position. It stays 2-2.5 years in a sign,
           so it describes the working "climate" of the year and whether that climate shifts inside it.
  Rahu     the nodal planet of ambition, sudden rise and disruption. It stays about 1.5 years in a sign,
           and a sign change inside the 12 months moves the ambition axis to another house. Ketu is
           always in the sign directly opposite Rahu, so it is not sent separately.

NOT SENT: Sun/Mars/Mercury/Venus (a sign change every 1-6 weeks would need a long timeline), Moon
(changes sign every ~2.3 days), Ketu (mirror of Rahu). No daily positions are sent.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from modules.payments.report_date_format import format_customer_date, format_customer_date_range
from smart_transit_engine import get_planet_position_on
from summary_blocks import _house_from_lagna, _ordinal
from transit_engine import (
    get_current_positions,
    get_current_sign_residency,
    get_next_12_rashi_segments,
)

HORIZON_MONTHS = 12

PROMOTION_TRANSIT_PLANETS = ("Jupiter", "Saturn", "Rahu")

SELECTION_REASONS: Dict[str, str] = {
    "Jupiter": (
        "Planet of growth and opportunity; it stays about a year in a sign, so its sign and its sign "
        "changes (retrograde re-entries included) frame the supplied window."
    ),
    "Saturn": (
        "Planet of career, responsibility and earned position; it stays 2-2.5 years in a sign, so it "
        "describes the working climate of the year and whether that climate changes inside it."
    ),
    "Rahu": (
        "Nodal planet of ambition and sudden rise or disruption; a sign change inside the supplied period moves "
        "that axis to another house. Ketu is always opposite Rahu, so it is not sent separately."
    ),
}


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _iso(value: str) -> date:
    return date.fromisoformat(value)


def _motion_periods(planet: str, start: date, end: date) -> List[Dict[str, Any]]:
    """Direct/Retrograde periods across [start, end], from the existing ephemeris helper (one sample per day).
    `from` is None for the motion already in force on `start`; `through` is the last day of that motion inside the
    horizon; `continues_beyond_horizon` says whether it is still in force the day after `end`."""
    periods: List[Dict[str, Any]] = []
    day = start
    while day <= end:
        motion = get_planet_position_on(day.isoformat(), planet)["motion"]
        if periods and periods[-1]["motion"] == motion:
            periods[-1]["through"] = day.isoformat()
        else:
            periods.append({"motion": motion, "from": None if day == start else day.isoformat(), "through": day.isoformat()})
        day += timedelta(days=1)
    after_horizon = get_planet_position_on((end + timedelta(days=1)).isoformat(), planet)["motion"]
    for period in periods:
        period["continues_beyond_horizon"] = False
    periods[-1]["continues_beyond_horizon"] = after_horizon == periods[-1]["motion"]
    return periods


def build_promotion_transit_evidence(lagna_sign: str, *, horizon_months: int = HORIZON_MONTHS,
                                   selected_planets=PROMOTION_TRANSIT_PLANETS) -> Dict[str, Any]:
    """Selected transit facts from the engine's IST clock, defaulting to 12 months.
    Career's coming-years question uses 60 months with the same primitives.
    Dates stay internal ISO. Read-only over the existing engines."""
    if not isinstance(horizon_months, int) or not 1 <= horizon_months <= 60:
        raise ValueError("Career transit horizon must be between 1 and 60 months.")
    if not selected_planets or len(set(selected_planets)) != len(selected_planets) or any(
            planet not in PROMOTION_TRANSIT_PLANETS for planet in selected_planets):
        raise ValueError("Unsupported focused transit selection.")
    snapshot = get_current_positions()
    as_of = _iso(snapshot["timestamp_ist"][:10])
    horizon_end = _add_months(as_of, horizon_months)

    planets: List[Dict[str, Any]] = []
    for planet in selected_planets:
        position = snapshot["positions"][planet]
        residency = get_current_sign_residency(planet) or {}
        sign = position["rashi"]
        current_exit = residency.get("exit_date")
        current_since = residency.get("entering_date")

        changes: List[Dict[str, Any]] = []
        for event in get_next_12_rashi_segments(planet):
            entering = event["entering_date"]
            # an ingress that already happened earlier today is the current segment, not a future change
            if current_since and _iso(entering) <= _iso(current_since):
                continue
            if _iso(entering) > horizon_end:
                break
            exit_date = event["exit_date"]
            changes.append({
                "on": entering,
                "from_sign": event["from_rashi"],
                "to_sign": event["to_rashi"],
                "house_from_lagna": _house_from_lagna(event["to_rashi"], lagna_sign),
                "motion": event.get("motion"),          # motion on the day of the ingress only
                "until": exit_date,
                "continues_beyond_horizon": _iso(exit_date) > horizon_end,
            })

        current = {
            "sign": sign,
            "house_from_lagna": _house_from_lagna(sign, lagna_sign),
            "motion": position["motion"],
            "until": current_exit,
            "continues_beyond_horizon": bool(current_exit) and _iso(current_exit) > horizon_end,
        }

        # SIGN RESIDENCE: only the sign, the house and the sign-stay dates.
        sign_residence = [{
            "sign": current["sign"], "house_from_lagna": current["house_from_lagna"], "from": None,
            "through": current["until"], "continues_beyond_horizon": current["continues_beyond_horizon"],
        }] + [{
            "sign": change["to_sign"], "house_from_lagna": change["house_from_lagna"], "from": change["on"],
            "through": change["until"], "continues_beyond_horizon": change["continues_beyond_horizon"],
        } for change in changes]

        planets.append({
            "planet": planet,
            "reason": SELECTION_REASONS[planet],
            "current": current,
            "changes_in_horizon": changes,
            "sign_residence": sign_residence,
            # MOTION: only Direct/Retrograde and its own dates.
            "motion_periods": _motion_periods(planet, as_of, horizon_end),
        })

    return {
        "as_of": as_of.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "horizon_months": horizon_months,
        "planets": planets,
    }


def _house_text(house: Optional[int]) -> str:
    return f"{_ordinal(house)} house" if house else "house unknown"


def render_promotion_transit_summary(evidence: Dict[str, Any], language: str = "en") -> str:
    """The compact text block placed in the Luna prompt: English fact sentences, but every date in the locked
    customer format for `language` (never ISO). Sign residence and motion are separate lines."""
    def when(iso_date: str) -> str:
        return format_customer_date(iso_date, language)

    lines = [
        f"Transit facts calculated by the backend for {format_customer_date_range(evidence['as_of'], evidence['horizon_end'], language)} "
        f"(the next {evidence['horizon_months']} months). Sidereal (Lahiri) signs; houses are counted from your natal Lagna. "
        "For each planet, \"Sign residence\" says which sign and house it occupies and when it moves on; \"Motion\" says "
        "whether it is Direct or Retrograde and when that changes. They are separate facts with separate dates. "
        "\"Through\" means up to and including that day."
    ]
    for item in evidence["planets"]:
        residence = []
        for segment in item["sign_residence"]:
            part = f"{segment['sign']} ({_house_text(segment['house_from_lagna'])})"
            if segment["from"] and segment["continues_beyond_horizon"]:
                part += f" from {when(segment['from'])}, continuing beyond this period"
            elif segment["from"]:
                part += f" from {when(segment['from'])} through {when(segment['through'])}"
            elif segment["continues_beyond_horizon"]:
                part += ", continuing beyond this period"
            else:
                part += f" through {when(segment['through'])}"
            residence.append(part)

        motion_periods = item["motion_periods"]
        if len(motion_periods) == 1:
            motion_text = f"{motion_periods[0]['motion']} throughout this period"
        else:
            motion = []
            for index, period in enumerate(motion_periods):
                label = period["motion"] if index < 2 or period["motion"] != motion_periods[index - 2]["motion"] else f"{period['motion']} again"
                if period["from"] and period["continues_beyond_horizon"]:
                    motion.append(f"{label} from {when(period['from'])}, continuing beyond this period")
                elif period["from"]:
                    motion.append(f"{label} from {when(period['from'])} through {when(period['through'])}")
                else:
                    motion.append(f"{label} through {when(period['through'])}")
            motion_text = "; ".join(motion)

        lines.append(f"{item['planet']}\nSign residence: {'; '.join(residence)}.\nMotion: {motion_text}.")
    if any(item["planet"] == "Rahu" for item in evidence["planets"]):
        lines.append("Ketu is always in the sign directly opposite Rahu.")
    return "\n".join(lines)
