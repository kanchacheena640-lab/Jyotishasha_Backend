"""
services/ai_prediction_lab/context_builder.py
-----------------------------------------------
Transforms an EXISTING backend kundali payload (as returned by
full_kundali_api.calculate_full_kundali()) into a compact, structured
"Love Profile" AI context.

This module performs NO astrology calculation of its own. It only reads
fields that the backend has already computed (planet positions, houses,
nakshatras, drishti/aspects, house lords) and reshapes them into a
smaller dict. Where a requested field does not exist anywhere in the
current backend output (see `retrograde` below), that is recorded
explicitly rather than recomputed here -- recomputing it would duplicate
planet-calculation logic the Lab is required never to duplicate.

Returns structured data only -- no prose, no interpretation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.full_kundali_service import derive_house_lords

LOVE_HOUSE = 5
MARRIAGE_HOUSE = 7


def _planets_list(kundali: Dict[str, Any]) -> List[Dict[str, Any]]:
    return kundali.get("planets") or kundali.get("Planets") or []


def _find_planet(planets: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    return next((p for p in planets if p.get("name") == name), None)


def _find_ascendant(planets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next(
        (p for p in planets if "Ascendant" in (p.get("name") or "")),
        None,
    )


def _planet_summary(p: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Direct passthrough of already-computed fields -- no derivation."""
    if not p:
        return {}
    return {
        "name": p.get("name"),
        "sign": p.get("sign"),
        "house": p.get("house"),
        "degree": p.get("degree"),
        "nakshatra": p.get("nakshatra"),
        "pada": p.get("pada"),
        "aspected_by": p.get("aspected_by") or [],
        "aspecting": p.get("aspecting") or [],
    }


def _planets_in_house(planets: List[Dict[str, Any]], house_number: int) -> List[Dict[str, Any]]:
    return [p for p in planets if p.get("house") == house_number]


def _aspects_on_house(planets: List[Dict[str, Any]], house_number: int) -> List[str]:
    """
    Aspects landing on a house are derived ONLY from the `aspected_by`
    field the backend already computed for whichever planets currently
    occupy that house. If the house is empty, this is empty -- the Lab
    does not re-run drishti math itself (that would duplicate aspect
    calculations already owned by full_kundali_api.py).
    """
    hits: List[str] = []
    for p in _planets_in_house(planets, house_number):
        hits.extend(p.get("aspected_by") or [])
    # de-dupe, keep order
    seen = set()
    out = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _conjunctions_with(planets: List[Dict[str, Any]], house_number: Optional[int], exclude_name: Optional[str] = None) -> List[str]:
    """
    Conjunction = sharing a house. This groups by the `house` field the
    backend already computed -- it is not a new astrological calculation.
    """
    if house_number is None:
        return []
    return [
        p["name"]
        for p in _planets_in_house(planets, house_number)
        if p.get("name") != exclude_name
    ]


def build_love_profile_context(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the Lifetime Love Profile AI context from an existing backend
    kundali payload. `kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- this function does not
    call it itself, so the backend remains the single source of truth
    for when/how that payload is produced.
    """
    planets = _planets_list(kundali)

    ascendant = _find_ascendant(planets)
    lagna_sign = kundali.get("lagna_sign") or (ascendant or {}).get("sign")

    fifth_house_planets = _planets_in_house(planets, LOVE_HOUSE)
    fifth_house_aspects = _aspects_on_house(planets, LOVE_HOUSE)

    # 7th House (Marriage & Partnerships) -- same reuse pattern as the
    # 5th House above, just a different house number.
    seventh_house_planets = _planets_in_house(planets, MARRIAGE_HOUSE)
    seventh_house_aspects = _aspects_on_house(planets, MARRIAGE_HOUSE)

    # House lords: whole-sign lordship, already computed by
    # services/full_kundali_service.derive_house_lords() -- not
    # recomputed here. derive_house_lords() already returns all 12
    # houses' lords in one call (both "5_house_lord" and
    # "7_house_lord" keys), so the 7th Lord requires no new lookup.
    lords = kundali.get("lords") or derive_house_lords(lagna_sign)
    fifth_lord_name = lords.get(f"{LOVE_HOUSE}_house_lord")
    fifth_lord = _find_planet(planets, fifth_lord_name) if fifth_lord_name else None

    seventh_lord_name = lords.get(f"{MARRIAGE_HOUSE}_house_lord")
    seventh_lord = _find_planet(planets, seventh_lord_name) if seventh_lord_name else None

    venus = _find_planet(planets, "Venus")
    mars = _find_planet(planets, "Mars")
    moon = _find_planet(planets, "Moon")
    mercury = _find_planet(planets, "Mercury")

    context = {
        "ascendant": {
            "sign": lagna_sign,
            "nakshatra": (ascendant or {}).get("nakshatra"),
            "pada": (ascendant or {}).get("pada"),
        },
        "fifth_house": {
            "house_number": LOVE_HOUSE,
            "planets": [_planet_summary(p) for p in fifth_house_planets],
            "aspects_on_house": fifth_house_aspects,
        },
        "fifth_lord": {
            "name": fifth_lord_name,
            **_planet_summary(fifth_lord),
            # NOT AVAILABLE: full_kundali_api.calculate_planet_positions()
            # only reads longitude (swe.calc(...)[0][0]) for natal planets
            # and never captures speed, so retrograde status cannot be
            # read from the existing backend output. Recomputing it here
            # would duplicate planet-calculation logic the Lab must never
            # own. Left explicit rather than guessed.
            "retrograde": "not_available_in_backend",
        },
        "seventh_house": {
            "house_number": MARRIAGE_HOUSE,
            "planets": [_planet_summary(p) for p in seventh_house_planets],
            "aspects_on_house": seventh_house_aspects,
        },
        "seventh_lord": {
            "name": seventh_lord_name,
            **_planet_summary(seventh_lord),
            # Same backend limitation as fifth_lord above -- retrograde is
            # never captured for natal planets anywhere in the backend.
            "retrograde": "not_available_in_backend",
        },
        "venus": _planet_summary(venus),
        "mars": _planet_summary(mars),
        "moon": _planet_summary(moon),
        "mercury": _planet_summary(mercury),
        "conjunctions": {
            "fifth_house": _conjunctions_with(planets, LOVE_HOUSE),
            "fifth_lord": _conjunctions_with(
                planets, (fifth_lord or {}).get("house"), exclude_name=fifth_lord_name
            ),
            "seventh_house": _conjunctions_with(planets, MARRIAGE_HOUSE),
            "seventh_lord": _conjunctions_with(
                planets, (seventh_lord or {}).get("house"), exclude_name=seventh_lord_name
            ),
            "venus": _conjunctions_with(planets, (venus or {}).get("house"), exclude_name="Venus"),
            "mars": _conjunctions_with(planets, (mars or {}).get("house"), exclude_name="Mars"),
            "moon": _conjunctions_with(planets, (moon or {}).get("house"), exclude_name="Moon"),
            "mercury": _conjunctions_with(planets, (mercury or {}).get("house"), exclude_name="Mercury"),
        },
    }

    return context
