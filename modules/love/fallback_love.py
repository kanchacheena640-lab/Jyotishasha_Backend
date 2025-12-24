from __future__ import annotations
from typing import Dict, Any


class FallbackLoveError(Exception):
    pass


def compute_vedic_fallback(
    user_kundali: Dict[str, Any],
    *,
    safe_mode: bool = True
) -> Dict[str, Any]:
    """
    SAFE fallback for partial partner data.

    Rule:
    - If full kundali structure missing → return soft fallback (NO crash)
    - If available → use 5th house as Lover Lagna
    """

    # ---------- SAFE MODE ----------
    if safe_mode:
        houses = user_kundali.get("houses")
        planets = user_kundali.get("planets")

        if not isinstance(houses, dict) or not isinstance(planets, dict):
            return {
                "method": "vedic_fallback_safe",
                "status": "skipped",
                "reason": "Incomplete kundali structure",
                "disclaimer": "Fallback skipped due to partial data",
            }

        fifth_house = houses.get("5")
        if not isinstance(fifth_house, dict):
            return {
                "method": "vedic_fallback_safe",
                "status": "skipped",
                "reason": "5th house missing",
                "disclaimer": "Fallback skipped due to partial data",
            }

        lover_lagna_sign = fifth_house.get("sign")
        lover_lagna_lord = fifth_house.get("lord")

        if not lover_lagna_sign or not lover_lagna_lord:
            return {
                "method": "vedic_fallback_safe",
                "status": "skipped",
                "reason": "5th house sign/lord missing",
                "disclaimer": "Fallback skipped due to partial data",
            }

        fifth_house_planets = [
            {
                "name": p.get("name"),
                "sign": p.get("sign"),
                "degree": p.get("degree"),
                "house": p.get("house"),
            }
            for p in planets.values()
            if isinstance(p, dict) and p.get("house") == 5
        ]

        lord_planet = planets.get(lover_lagna_lord, {})
        lord_house = lord_planet.get("house")
        lord_sign = lord_planet.get("sign")

        return {
            "method": "vedic_fallback_5th_house_as_lagna",
            "status": "ok",
            "lover_lagna": {
                "source": "user_5th_house",
                "sign": lover_lagna_sign,
                "lord": lover_lagna_lord,
                "lord_house": lord_house,
                "lord_sign": lord_sign,
            },
            "fifth_house_influence": {
                "planets_present": fifth_house_planets
            },
            "disclaimer": "Derived without partner birth time/place",
        }

    # ---------- STRICT MODE (future use) ----------
    raise FallbackLoveError("Strict fallback mode not enabled")
