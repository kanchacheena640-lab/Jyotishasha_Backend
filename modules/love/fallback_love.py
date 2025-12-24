# Path: modules/love/fallback_love.py
from __future__ import annotations
from typing import Dict, Any


class FallbackLoveError(Exception):
    pass


def _require_kundali_fields(kundali: Dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [f for f in fields if f not in kundali or kundali.get(f) is None]
    if missing:
        raise FallbackLoveError(f"Kundali missing fields: {', '.join(missing)}")


def compute_vedic_fallback(user_kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule:
    User 5th house is treated as Lover's Lagna.
    """

    _require_kundali_fields(user_kundali, ("houses", "planets", "lagna"))

    houses: Dict[str, Any] = user_kundali["houses"]
    planets: Dict[str, Any] = user_kundali["planets"]

    fifth_house = houses.get("5")
    if not isinstance(fifth_house, dict):
        raise FallbackLoveError("5th house data missing")

    lover_lagna_sign = fifth_house.get("sign")
    lover_lagna_lord = fifth_house.get("lord")

    if not lover_lagna_sign or not lover_lagna_lord:
        raise FallbackLoveError("5th house sign/lord missing")

    fifth_house_planets = [
        {
            "name": p.get("name"),
            "sign": p.get("sign"),
            "degree": p.get("degree"),
            "house": p.get("house"),
        }
        for p in planets.values()
        if p.get("house") == 5
    ]

    lord_planet = planets.get(lover_lagna_lord)
    lord_house = lord_planet.get("house") if isinstance(lord_planet, dict) else None
    lord_sign = lord_planet.get("sign") if isinstance(lord_planet, dict) else None

    return {
        "method": "vedic_fallback_5th_house_as_lagna",
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
