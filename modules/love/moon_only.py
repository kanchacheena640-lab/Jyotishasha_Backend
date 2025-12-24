# Path: modules/love/moon_only.py
from __future__ import annotations

from typing import Dict, Any
from datetime import date


def derive_partner_moon_from_dob(dob: str) -> Dict[str, Any]:
    """
    Input: dob = YYYY-MM-DD
    Output: { rashi, nakshatra, degree }
    """

    year, month, day = _parse_dob(dob)
    moon = _calculate_moon_noon_ist(year, month, day)

    return {
        "rashi": moon["rashi"],
        "nakshatra": moon["nakshatra"],
        "degree": moon.get("degree"),
    }


def _parse_dob(dob: str) -> tuple[int, int, int]:
    try:
        d = date.fromisoformat(dob)
        return d.year, d.month, d.day
    except Exception:
        raise ValueError("Invalid DOB format. Expected YYYY-MM-DD")


def _calculate_moon_noon_ist(year: int, month: int, day: int) -> Dict[str, Any]:
    """
    Noon IST Moon calculation.
    Replace internals with real engine.
    """
    raise NotImplementedError("Moon-only engine not wired yet")
