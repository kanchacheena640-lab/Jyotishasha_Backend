"""
SNR-2B -- deterministic spouse-evidence engine (Spouse Nature Report,
rep_026). Implements the FROZEN astrology contract SNR-2A + SNR-2A.1
exactly; it does not add astrology of its own.

Input : the dict returned by full_kundali_api.calculate_full_kundali()
        (only `lagna_sign` and `planets` -- name/sign/longitude -- are read).
Output: a machine-readable `spouse_evidence_v1` payload of chart facts,
        classified evidence and limitations. No narrative prose, no
        probabilities, no AI. The same input always gives the same output,
        and the input is never mutated.

Reused existing Jyotishasha conventions (never re-invented here):
  * whole-sign houses from the Lagna sign;
  * summary_blocks.SIGN_LORDS (traditional lords);
  * full_kundali_api.DRISHTI_RULES (Saturn 3/7/10, Mars 4/7/8, Jupiter
    5/7/9, Rahu/Ketu 5/7/9, everyone else 7) -- house based, no orb;
  * services.neechbhang_rajyog EXALTATIONS / DEBILITATIONS (7 planets).
The planet list's "Ascendant (Lagna)" record is NEVER treated as a planet
here (no aspects, occupancy, conjunction or trait votes) -- inside this
engine only; the global aspect helpers are deliberately left unchanged.

Deferred / prohibited in v1 (frozen): Upapada, retrograde, combustion,
functional lordship, the placeholder shadbala, moolatrikona, friend/enemy
signs, the spouse's 8th (native 2nd) for health, the spouse's 9th
(native 3rd) for wealth.
"""

from __future__ import annotations

from typing import Optional

from full_kundali_api import DRISHTI_RULES
from services.neechbhang_rajyog import DEBILITATIONS, EXALTATIONS
from summary_blocks import SIGN_LORDS
from modules.payments.spouse_sign_table import (
    DIMENSION_POLES,
    SEVENTH_SIGN_TABLE,
    SIGN_ORDER,
    TRAIT_DIMENSIONS,
)

SCHEMA_VERSION = "spouse_evidence_v1"


class SpouseEvidenceError(ValueError):
    """Raised for input the engine refuses to guess about (e.g. an
    unrecognised Lagna or a planet without a full-precision longitude)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GRAHAS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
CLASSICAL = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
KARAKA_PLANETS = CLASSICAL  # frozen 7-karaka scheme: Rahu/Ketu excluded
NODES = ("Rahu", "Ketu")

# Frozen valence fallback (SNR-2A.1 section 4).
NATURAL_SUPPORT = frozenset({"Jupiter", "Venus"})
NATURAL_STRESS = frozenset({"Saturn", "Mars", "Rahu", "Ketu"})  # also the "natural malefics" of step 4
# Sun, Moon, Mercury -> NEUTRAL

# Spouse-relative placements, expressed as NATIVE houses (native 7th = spouse 1st).
SPOUSE_KENDRA_NATIVE = frozenset({7, 10, 1, 4})
SPOUSE_TRIKONA_NATIVE = frozenset({7, 11, 3})
SPOUSE_SUPPORT_PLACEMENT_NATIVE = SPOUSE_KENDRA_NATIVE | SPOUSE_TRIKONA_NATIVE
SPOUSE_DUSTHANA_USED_NATIVE = frozenset({12, 6})   # spouse 6th / 12th
SPOUSE_GROWTH_NATIVE = frozenset({9, 12, 4, 5})     # spouse 3rd / 6th / 10th / 11th
NATIVE_HOUSE_EXCLUDED = 2                            # spouse 8th -> always NONE in v1

# Navamsa: one segment = 3 deg 20 min = 12000 arcsec. Longitudes are resolved
# to integer micro-arcseconds (far finer than ephemeris accuracy), so every
# segment test is exact integer arithmetic, lower-inclusive/upper-exclusive.
UAS_PER_DEGREE = 3_600_000_000
NAVAMSA_UAS = 12_000 * 1_000_000
SIGN_UAS = 30 * UAS_PER_DEGREE
CIRCLE_UAS = 360 * UAS_PER_DEGREE

# Planet nature -> trait votes (frozen SNR-2A section 3; directions only, no
# value judgement). One vote per dimension per planet.
PLANET_VOTES = {
    "Sun": {"independence": "independent", "responsibility": "dutiful"},
    "Moon": {"emotional_style": "open", "sociability": "home_centred"},
    "Mars": {"temperament": "dynamic", "communication": "expressive"},
    "Mercury": {"communication": "expressive", "responsibility": "flexible"},
    "Jupiter": {"approach_to_life": "idealistic", "convention": "traditional"},
    "Venus": {"emotional_style": "open", "sociability": "outgoing", "approach_to_life": "idealistic"},
    "Saturn": {"responsibility": "dutiful", "communication": "reserved", "approach_to_life": "practical"},
    "Rahu": {"convention": "unconventional", "temperament": "dynamic"},
    "Ketu": {"emotional_style": "guarded", "independence": "independent", "convention": "unconventional"},
}

LIMITATIONS = (
    "no_upapada_v1",
    "no_retrograde_v1",
    "no_combustion_v1",
    "no_functional_lordship_v1",
    "no_shadbala",
    "tendencies_not_certainties",
)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------
def sign_index(sign: str) -> int:
    if sign not in SIGN_ORDER:
        raise SpouseEvidenceError(f"Unrecognised sign: {sign!r}")
    return SIGN_ORDER.index(sign)


def house_sign(lagna_sign: str, house: int) -> str:
    """Sign of whole-sign house `house` (1..12) for a Lagna -- always derivable,
    whether or not anything occupies the house."""
    return SIGN_ORDER[(sign_index(lagna_sign) + house - 1) % 12]


def house_of_sign(lagna_sign: str, sign: str) -> int:
    return (sign_index(sign) - sign_index(lagna_sign)) % 12 + 1


def native_house_for_spouse_house(n: int) -> int:
    """Spouse's nth house (native 7th = spouse 1st) as a native D1 house."""
    if not 1 <= n <= 12:
        raise SpouseEvidenceError(f"House must be 1..12, got {n!r}")
    return ((6 + n - 1) % 12) + 1


def spouse_house_for_native_house(native_house: int) -> int:
    """Inverse of native_house_for_spouse_house(): a native house counted from the 7th."""
    return ((native_house - 7) % 12) + 1


def aspect_targets(planet: str, house: int) -> list:
    """Houses a planet in `house` aspects, by the existing DRISHTI_RULES."""
    return [((house + n - 1) % 12) or 12 for n in DRISHTI_RULES.get(planet, [7])]


def dignity(planet: str, sign: str) -> Optional[str]:
    """EXALTED / DEBILITATED / OWN / NEUTRAL for the 7 classical planets;
    None for Rahu/Ketu (no dignity in v1)."""
    if planet not in CLASSICAL:
        return None
    if EXALTATIONS.get(planet) == sign:
        return "EXALTED"
    if DEBILITATIONS.get(planet) == sign:
        return "DEBILITATED"
    if SIGN_LORDS.get(sign) == planet:
        return "OWN"
    return "NEUTRAL"


def to_uas(longitude: float) -> int:
    """Sidereal longitude (degrees) -> integer micro-arcseconds in [0, 360 deg)."""
    return int(round(float(longitude) * UAS_PER_DEGREE)) % CIRCLE_UAS


def navamsa_sign_from_longitude(longitude: float) -> str:
    """Frozen rule: d9_index = floor(arcsec(longitude) / 12000) mod 12."""
    return SIGN_ORDER[(to_uas(longitude) // NAVAMSA_UAS) % 12]


# ---------------------------------------------------------------------------
# Chart model (read-only view over the kundali input)
# ---------------------------------------------------------------------------
class _Chart:
    def __init__(self, kundali: dict):
        lagna = kundali.get("lagna_sign")
        planets = kundali.get("planets") or []
        if lagna not in SIGN_ORDER:
            raise SpouseEvidenceError(f"Lagna missing or unrecognised: {lagna!r}")
        self.lagna = lagna

        asc = next((p for p in planets if "Ascendant" in str(p.get("name", ""))), None)
        if asc is None or asc.get("longitude") is None:
            raise SpouseEvidenceError("Ascendant record with full-precision `longitude` is required.")
        if asc.get("sign") != lagna:
            raise SpouseEvidenceError(f"Ascendant record sign {asc.get('sign')!r} disagrees with lagna_sign {lagna!r}.")
        self.asc_longitude = float(asc["longitude"])

        self.sign = {}
        self.longitude = {}
        for p in planets:
            name = p.get("name")
            if name not in GRAHAS:
                continue  # skips the Ascendant record and anything unknown
            if p.get("sign") not in SIGN_ORDER or p.get("longitude") is None:
                raise SpouseEvidenceError(f"{name}: sign and full-precision `longitude` are required.")
            self.sign[name] = p["sign"]
            self.longitude[name] = float(p["longitude"])
        missing = [g for g in GRAHAS if g not in self.sign]
        if missing:
            raise SpouseEvidenceError(f"Planet records missing: {missing}")

        # Whole-sign house of every graha, derived from its sign (never from occupancy lists).
        self.house = {g: house_of_sign(self.lagna, s) for g, s in self.sign.items()}
        # All 12 houses, ALWAYS present; occupants optional.
        self.houses = {}
        for h in range(1, 13):
            s = house_sign(self.lagna, h)
            self.houses[h] = {
                "house": h,
                "sign": s,
                "lord": SIGN_LORDS[s],
                "occupants": [g for g in GRAHAS if self.house[g] == h],
            }

    # -- relations --------------------------------------------------------
    def lord_of(self, house: int) -> str:
        return self.houses[house]["lord"]

    def occupants(self, house: int) -> list:
        return list(self.houses[house]["occupants"])

    def aspecting_house(self, house: int) -> list:
        return [g for g in GRAHAS if house in aspect_targets(g, self.house[g])]

    def conjunct_with(self, planet: str) -> list:
        return [g for g in GRAHAS if g != planet and self.sign[g] == self.sign[planet]]

    def aspecting_planet(self, planet: str) -> list:
        return [g for g in self.aspecting_house(self.house[planet]) if g != planet]

    def dignity(self, planet: str) -> Optional[str]:
        return dignity(planet, self.sign[planet])


# ---------------------------------------------------------------------------
# Valence (frozen SNR-2A.1 section 4)
# ---------------------------------------------------------------------------
def planet_valence(chart: _Chart, planet: str, target_native_house: int, context: str) -> dict:
    """Valence of `planet` influencing the native house `target_native_house`
    (by occupancy, aspect or conjunction). context: "health" | "wealth" |
    "generic". Returns {"valence": SUPPORT|STRESS|NEUTRAL, "rule": ..., "tags": [...]}."""
    tags = ["unconventional"] if (context == "wealth" and planet in NODES) else []
    if chart.lord_of(target_native_house) == planet:
        return {"valence": "SUPPORT", "rule": "owns_target", "tags": tags}
    d = chart.dignity(planet)
    if d in ("EXALTED", "OWN"):
        return {"valence": "SUPPORT", "rule": "dignified", "tags": tags}
    if d == "DEBILITATED":
        return {"valence": "STRESS", "rule": "debilitated", "tags": tags}
    if target_native_house in SPOUSE_GROWTH_NATIVE and planet in NATURAL_STRESS:
        return {"valence": "NEUTRAL", "rule": "growth_house_malefic", "tags": tags}
    if planet in NATURAL_SUPPORT:
        return {"valence": "SUPPORT", "rule": "natural_benefic", "tags": tags}
    if planet in NODES and context == "wealth":
        return {"valence": "NEUTRAL", "rule": "node_wealth_neutral", "tags": tags}
    if planet in NATURAL_STRESS:
        return {"valence": "STRESS", "rule": "natural_malefic", "tags": tags}
    return {"valence": "NEUTRAL", "rule": "natural_neutral", "tags": tags}


def _influences_on_house(chart: _Chart, house: int, context: str) -> list:
    out = []
    for g in chart.occupants(house):
        out.append({"planet": g, "via": "occupies", **planet_valence(chart, g, house, context)})
    for g in chart.aspecting_house(house):
        out.append({"planet": g, "via": "aspect", **planet_valence(chart, g, house, context)})
    return out


def _influences_on_lord(chart: _Chart, ruled_house: int, context: str) -> list:
    """Influences on the lord of `ruled_house`, valued w.r.t. the house it rules."""
    lord = chart.lord_of(ruled_house)
    out = []
    for g in chart.conjunct_with(lord):
        out.append({"planet": g, "via": "conjunct_lord", **planet_valence(chart, g, ruled_house, context)})
    for g in chart.aspecting_planet(lord):
        out.append({"planet": g, "via": "aspects_lord", **planet_valence(chart, g, ruled_house, context)})
    return out


def _resolve(influences: list) -> str:
    vals = {i["valence"] for i in influences}
    if "SUPPORT" in vals and "STRESS" in vals:
        return "MIXED"
    if "SUPPORT" in vals:
        return "SUPPORT"
    if "STRESS" in vals:
        return "STRESS"
    return "NONE"


def _placement_result(native_house: int) -> str:
    if native_house == NATIVE_HOUSE_EXCLUDED:
        return "NONE"
    if native_house in SPOUSE_SUPPORT_PLACEMENT_NATIVE:
        return "SUPPORT"
    if native_house in SPOUSE_DUSTHANA_USED_NATIVE:
        return "STRESS"
    return "NONE"


def _dignity_result(d: Optional[str]) -> str:
    if d in ("EXALTED", "OWN"):
        return "SUPPORT"
    if d == "DEBILITATED":
        return "STRESS"
    return "NONE"


# ---------------------------------------------------------------------------
# D1 / D9 / Darakaraka facts
# ---------------------------------------------------------------------------
def _d1_facts(chart: _Chart) -> dict:
    lord = chart.lord_of(7)
    lord_house = chart.house[lord]

    def karaka(planet: str) -> dict:
        links = []
        if chart.house[planet] == 7:
            links.append("occupies_7th")
        if 7 in aspect_targets(planet, chart.house[planet]):
            links.append("aspects_7th")
        if planet != lord and chart.sign[planet] == chart.sign[lord]:
            links.append("conjunct_7th_lord")
        if planet == lord:
            links.append("is_7th_lord")
        return {"sign": chart.sign[planet], "house": chart.house[planet],
                "dignity": chart.dignity(planet), "link_to_7th": links}

    return {
        "lagna": chart.lagna,
        "houses": [dict(chart.houses[h], occupants=list(chart.houses[h]["occupants"])) for h in range(1, 13)],
        "seventh_sign": chart.houses[7]["sign"],
        "seventh_lord": lord,
        "seventh_lord_sign": chart.sign[lord],
        "seventh_lord_house": lord_house,
        "seventh_lord_house_from_seventh": spouse_house_for_native_house(lord_house),
        "seventh_lord_dignity": chart.dignity(lord),
        "occupants_7th": chart.occupants(7),
        "aspects_on_7th": chart.aspecting_house(7),
        "conjunct_with_7th_lord": chart.conjunct_with(lord),
        "aspects_on_7th_lord": chart.aspecting_planet(lord),
        "venus": karaka("Venus"),
        "jupiter": karaka("Jupiter"),
    }


def _d9_facts(chart: _Chart) -> dict:
    d9_sign = {g: navamsa_sign_from_longitude(chart.longitude[g]) for g in GRAHAS}
    d9_lagna = navamsa_sign_from_longitude(chart.asc_longitude)
    d9_house = {g: house_of_sign(d9_lagna, s) for g, s in d9_sign.items()}
    seventh = house_sign(d9_lagna, 7)
    lord = SIGN_LORDS[seventh]
    return {
        "lagna": d9_lagna,
        "planet_signs": {g: d9_sign[g] for g in GRAHAS},
        "planet_houses": {g: d9_house[g] for g in GRAHAS},
        "seventh_sign": seventh,
        "seventh_lord": lord,
        "seventh_lord_d9_sign": d9_sign[lord],
        "seventh_lord_d9_house": d9_house[lord],
        "seventh_lord_d9_dignity": dignity(lord, d9_sign[lord]),
        "occupants_d9_7th": [g for g in GRAHAS if d9_house[g] == 7],
    }


def _darakaraka(chart: _Chart) -> dict:
    in_sign = {g: to_uas(chart.longitude[g]) % SIGN_UAS for g in KARAKA_PLANETS}
    lowest = min(in_sign.values())
    planets = [g for g in KARAKA_PLANETS if in_sign[g] == lowest]
    lord = chart.lord_of(7)
    entries = []
    for g in planets:
        links = []
        if chart.house[g] == 7:
            links.append("occupies_7th")
        if 7 in aspect_targets(g, chart.house[g]):
            links.append("aspects_7th")
        if g == lord:
            links.append("is_7th_lord")
        elif chart.sign[g] == chart.sign[lord]:
            links.append("conjunct_7th_lord")
        entries.append({"planet": g, "sign": chart.sign[g], "link_to_7th": links})
    return {
        "scheme": "7_karaka",
        "planet": planets[0] if len(planets) == 1 else None,
        "planets": planets,
        "tie": len(planets) > 1,
        "status": "DK_TIE" if len(planets) > 1 else "OK",
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Nature traits
# ---------------------------------------------------------------------------
def _expression_quality_for(d: Optional[str]) -> Optional[str]:
    if d in ("EXALTED", "OWN"):
        return "well_supported"
    if d == "DEBILITATED":
        return "uneven"
    return None


def _nature_sources(chart: _Chart, d9: dict, dk: dict) -> list:
    """Every trait vote, one per (source, dimension). Each source is a distinct
    factor; the 7th lord is counted once (P3) even if it also sits in or aspects
    the 7th, and Venus/Jupiter only ever vote through their link to the 7th."""
    lord = chart.lord_of(7)
    sources = []

    def add(source_id, factor, tier, chart_name, votes, planet=None, sign=None, quality_dignity=None):
        sources.append({
            "source": source_id, "factor": factor, "tier": tier, "chart": chart_name,
            "planet": planet, "sign": sign, "votes": dict(votes),
            "expression_quality": _expression_quality_for(quality_dignity),
        })

    # P1 -- 7th occupants (the 7th lord, if it occupies, is counted under P3 instead).
    for g in chart.occupants(7):
        if g == lord:
            continue
        add(f"p1_occupant:{g}", "occupant_7th", "P", "D1", PLANET_VOTES[g], planet=g, quality_dignity=chart.dignity(g))
    # P2 -- 7th sign, element/modality only (shared table; no lord colouring).
    seventh = chart.houses[7]["sign"]
    add("p2_seventh_sign", "seventh_sign", "P", "D1", SEVENTH_SIGN_TABLE[seventh]["votes"], sign=seventh)
    # P3 -- the 7th lord's own nature.
    add(f"p3_seventh_lord:{lord}", "seventh_lord", "P", "D1", PLANET_VOTES[lord], planet=lord, quality_dignity=chart.dignity(lord))
    # S1 -- planets aspecting the 7th (not the lord: already P3).
    for g in chart.aspecting_house(7):
        if g == lord:
            continue
        add(f"s1_aspect_7th:{g}", "aspect_on_7th", "S", "D1", PLANET_VOTES[g], planet=g, quality_dignity=chart.dignity(g))
    # S2 -- planets conjunct or aspecting the 7th lord (one source per planet).
    s2 = []
    for g in chart.conjunct_with(lord) + chart.aspecting_planet(lord):
        if g not in s2 and g != lord:
            s2.append(g)
    for g in s2:
        add(f"s2_on_seventh_lord:{g}", "influence_on_7th_lord", "S", "D1", PLANET_VOTES[g], planet=g, quality_dignity=chart.dignity(g))
    # S3 -- Navamsa: D9 7th sign, D9 7th lord, planets in the D9 7th (lord counted once).
    add("s3_d9_seventh_sign", "d9_seventh_sign", "S", "D9", SEVENTH_SIGN_TABLE[d9["seventh_sign"]]["votes"], sign=d9["seventh_sign"])
    d9_lord = d9["seventh_lord"]
    add(f"s3_d9_seventh_lord:{d9_lord}", "d9_seventh_lord", "S", "D9", PLANET_VOTES[d9_lord], planet=d9_lord,
        quality_dignity=d9["seventh_lord_d9_dignity"])
    for g in d9["occupants_d9_7th"]:
        if g == d9_lord:
            continue
        add(f"s3_d9_occupant:{g}", "d9_occupant_7th", "S", "D9", PLANET_VOTES[g], planet=g)
    # T1 -- Venus/Jupiter: they vote ONLY through the link sources above (P1/P3/S1/S2);
    # an unlinked Venus/Jupiter is chart context only. No separate (duplicate) vote.
    # T2 -- Darakaraka (each planet on an exact tie).
    for g in dk["planets"]:
        add(f"t2_darakaraka:{g}", "darakaraka", "T", "D1", PLANET_VOTES[g], planet=g, quality_dignity=chart.dignity(g))
    return sources


def classify_dimension(dimension: str, sources: list) -> dict:
    pole_a, pole_b = DIMENSION_POLES[dimension]
    votes = []
    for s in sources:
        pole = s["votes"].get(dimension)
        if pole:
            votes.append({
                "source": s["source"], "factor": s["factor"], "tier": s["tier"], "chart": s["chart"],
                "planet": s["planet"], "sign": s["sign"], "pole": pole,
                "expression_quality": s["expression_quality"],
            })

    def count(pole, tiers, charts=("D1",)):
        return sum(1 for v in votes if v["pole"] == pole and v["tier"] in tiers and v["chart"] in charts)

    other = {pole_a: pole_b, pole_b: pole_a}
    d1_primary = {p: count(p, ("P",)) for p in (pole_a, pole_b)}
    d1_secondary = {p: count(p, ("S",)) for p in (pole_a, pole_b)}
    d1_support = {p: count(p, ("S", "T")) for p in (pole_a, pole_b)}
    d9 = {p: count(p, ("S",), ("D9",)) for p in (pole_a, pole_b)}

    # Step 1 -- D1 base class (frozen order: DOMINANT, SUPPORTED, MIXED, NOT_INDICATED).
    base, direction = "NOT_INDICATED", None
    for p in (pole_a, pole_b):
        if d1_primary[p] >= 2 and d1_primary[other[p]] == 0:
            base, direction = "DOMINANT", p
            break
    else:
        for p in (pole_a, pole_b):
            if d1_primary[p] == 1 and d1_primary[other[p]] == 0 and d1_support[p] >= 1:
                base, direction = "SUPPORTED", p
                break
        else:
            both_sides = all(d1_primary[p] + d1_secondary[p] >= 1 for p in (pole_a, pole_b))
            if both_sides:
                base = "MIXED"
            else:
                for p in (pole_a, pole_b):
                    if d1_primary[p] >= 1 and d1_primary[other[p]] == 0:
                        direction = p  # a single unsupported primary vote: a D1 direction, not yet a trait

    # Step 2 -- D9 direction.
    d9_dir = None
    if d9[pole_a] and not d9[pole_b]:
        d9_dir = pole_a
    elif d9[pole_b] and not d9[pole_a]:
        d9_dir = pole_b

    # Step 3 -- reconciliation (D9 confirms/refines only; never overrides D1).
    final = base
    if base == "MIXED":
        reconciliation = "D1_ONLY"
    elif direction is not None:
        has_primary = d1_primary[direction] >= 1
        if d9_dir == direction:
            reconciliation = "CONFIRMED"
            if base == "SUPPORTED":
                final = "DOMINANT"
            elif base == "NOT_INDICATED":
                final = "SUPPORTED"  # 1 primary + a matching (secondary-tier) D9 vote
        elif d9_dir is not None and has_primary:
            reconciliation = "OUTER_INNER_CONTRAST"
            final = "MIXED"
        else:
            reconciliation = "D1_ONLY"
    elif d9_dir is not None:
        if d1_primary[other[d9_dir]] + d1_secondary[other[d9_dir]] >= 1:
            # D1 (secondary) evidence opposes D9: evidence on both poles is MIXED
            # (frozen MIXED rule; D9 is secondary tier) -- D9 never overrides D1.
            reconciliation = "OUTER_INNER_CONTRAST"
            final = "MIXED"
        else:
            reconciliation = "REFINEMENT"
            direction = d9_dir
            final = "SUPPORTED" if d9[d9_dir] >= 2 else "NOT_INDICATED"
    else:
        reconciliation = "D1_ONLY"

    # MIXED has no single direction. NOT_INDICATED keeps any weak direction for
    # debugging only (reportable=False below, so narrative omits it).
    out_direction = None if final == "MIXED" else direction

    # expression_quality: presence/conflict of dignity among the planet votes
    # supporting the reported direction -- never a vote-count majority.
    quality = "neutral"
    if final in ("DOMINANT", "SUPPORTED") and out_direction:
        states = {v["expression_quality"] for v in votes if v["pole"] == out_direction and v["expression_quality"]}
        if states == {"well_supported"}:
            quality = "well_supported"
        elif states == {"uneven"}:
            quality = "uneven"
        # both present (conflict) or neither -> "neutral"

    return {
        "dimension": dimension,
        "class": final,
        "direction": out_direction,
        "d1_d9": reconciliation,
        "expression_quality": quality,
        "reportable": final in ("DOMINANT", "SUPPORTED", "MIXED"),
        "evidence": votes,
    }


def _nature(chart: _Chart, d9: dict, dk: dict) -> dict:
    sources = _nature_sources(chart, d9, dk)
    traits = [classify_dimension(dim, sources) for dim, _ in TRAIT_DIMENSIONS]
    order = {dim: i for i, (dim, _) in enumerate(TRAIT_DIMENSIONS)}
    rank = {"DOMINANT": 0, "SUPPORTED": 1}
    ranked = sorted(
        (t for t in traits if t["class"] in rank),
        key=lambda t: (rank[t["class"]], -len([v for v in t["evidence"] if v["pole"] == t["direction"]]), order[t["dimension"]]),
    )
    snapshot = [{"dimension": t["dimension"], "direction": t["direction"], "class": t["class"]} for t in ranked[:3]]
    return {"traits": traits, "snapshot_traits": snapshot}


# ---------------------------------------------------------------------------
# Health (frozen SNR-2A.1 section 9)
# ---------------------------------------------------------------------------
def classify_health_counts(primary_support: int, primary_stress: int, secondary_stress: int) -> str:
    """Frozen health classes. A primary MIXED item is neither SUPPORT nor STRESS."""
    ps, pt, st = primary_support, primary_stress, secondary_stress
    if (pt >= 2 and ps == 0) or (pt >= 1 and ps == 0 and st >= 1):
        return "NEEDS_ATTENTION"
    if ps >= 2 and pt == 0 and st == 0:
        return "SUPPORTIVE"
    return "MIXED"


def _health(chart: _Chart) -> dict:
    lord = chart.lord_of(7)
    lord_house = chart.house[lord]
    d = chart.dignity(lord)

    infl_7 = _influences_on_house(chart, 7, "health")
    infl_lord = _influences_on_lord(chart, 7, "health")
    primary = [
        {"id": "P-a", "item": "seventh_lord_dignity", "result": _dignity_result(d),
         "evidence": [{"planet": lord, "dignity": d}]},
        {"id": "P-b", "item": "seventh_lord_placement_from_spouse", "result": _placement_result(lord_house),
         "evidence": [{"planet": lord, "native_house": lord_house,
                       "spouse_house": spouse_house_for_native_house(lord_house)}]},
        {"id": "P-c", "item": "influences_on_native_7th", "result": _resolve(infl_7), "evidence": infl_7},
        {"id": "P-d", "item": "influences_on_7th_lord", "result": _resolve(infl_lord), "evidence": infl_lord},
    ]

    def dusthana_lord_item(item_id: str, native_house: int, spouse_house: int) -> dict:
        dl = chart.lord_of(native_house)
        ev = {"planet": dl, "rules_native_house": native_house, "rules_spouse_house": spouse_house,
              "native_house": chart.house[dl], "conjunct_7th_lord": dl != lord and chart.sign[dl] == chart.sign[lord]}
        if dl == lord:
            result = "NONE"
            ev["exception"] = "also_seventh_lord"
        elif chart.house[dl] == 7 or ev["conjunct_7th_lord"]:
            result = "STRESS"
        else:
            result = "NONE"
        return {"id": item_id, "item": f"lord_of_native_{native_house}_joins_spouse_1st", "result": result, "evidence": [ev]}

    secondary = [
        dusthana_lord_item("S-a", 12, 6),
        dusthana_lord_item("S-b", 6, 12),
    ]

    ps = sum(1 for i in primary if i["result"] == "SUPPORT")
    pt = sum(1 for i in primary if i["result"] == "STRESS")
    st = sum(1 for i in secondary if i["result"] == "STRESS")
    klass = classify_health_counts(ps, pt, st)
    return {
        "class": klass,
        "counts": {"primary_support": ps, "primary_stress": pt, "secondary_stress": st},
        "primary_items": primary,
        "secondary_items": secondary,
        "supportive_evidence": [i["id"] for i in primary if i["result"] == "SUPPORT"],
        "stress_evidence": [i["id"] for i in primary + secondary if i["result"] == "STRESS"],
        "derived_houses": {"spouse_1st": 7, "spouse_6th": 12, "spouse_12th": 6, "spouse_8th_excluded": 2},
    }


# ---------------------------------------------------------------------------
# Wealth (frozen SNR-2A.1 section 10)
# ---------------------------------------------------------------------------
WEALTH_DIMENSIONS = (
    # key, spouse house, role
    ("resources", 2, "primary"),
    ("income_growth", 11, "primary"),
    ("professional_standing", 10, "secondary"),
)


def _wealth_dimension(chart: _Chart, key: str, spouse_house: int, role: str) -> dict:
    native = native_house_for_spouse_house(spouse_house)
    lord = chart.lord_of(native)
    lord_house = chart.house[lord]
    d = chart.dignity(lord)
    items = [
        {"item": "lord_dignity", "planet": lord, "dignity": d, "result": _dignity_result(d)},
        {"item": "lord_placement_from_spouse", "planet": lord, "native_house": lord_house,
         "spouse_house": spouse_house_for_native_house(lord_house), "result": _placement_result(lord_house)},
    ]
    influences = _influences_on_house(chart, native, "wealth")
    signals = [i["result"] for i in items] + [i["valence"] for i in influences]
    has_s = "SUPPORT" in signals
    has_t = "STRESS" in signals
    state = "MIXED" if (has_s and has_t) else "SUPPORTED" if has_s else "STRAINED" if has_t else "NEUTRAL"

    node_on_house = [g for g in NODES if g in chart.occupants(native) or g in chart.aspecting_house(native)]
    node_on_lord = [g for g in NODES if g != lord and (chart.sign[g] == chart.sign[lord] or g in chart.aspecting_planet(lord))]
    return {
        "key": key, "role": role, "spouse_house": spouse_house, "native_house": native,
        "sign": chart.houses[native]["sign"], "lord": lord,
        "state": state, "lord_items": items, "influences": influences,
        "node_influence": sorted(set(node_on_house + node_on_lord), key=GRAHAS.index),
    }


def classify_wealth_states(resources: str, income_growth: str) -> str:
    """Frozen wealth labels, applied in order. States: SUPPORTED/STRAINED/MIXED/NEUTRAL."""
    r, g = resources, income_growth
    if r == "SUPPORTED" and g != "STRAINED":
        return "STEADY"
    if g == "SUPPORTED" and r in ("NEUTRAL", "MIXED"):
        return "GROWTH_ORIENTED"
    if (r == "STRAINED" and g != "SUPPORTED") or (g == "STRAINED" and r != "SUPPORTED"):
        # covers "both STRAINED" and "one STRAINED, the other not SUPPORTED"
        return "EFFORT_BUILT"
    return "MIXED"


def _wealth(chart: _Chart) -> dict:
    dims = {key: _wealth_dimension(chart, key, sh, role) for key, sh, role in WEALTH_DIMENSIONS}
    klass = classify_wealth_states(dims["resources"]["state"], dims["income_growth"]["state"])
    node_dims = sum(1 for d in dims.values() if d["node_influence"])
    return {
        "class": klass,
        "dimensions": dims,
        "unconventional_pattern": node_dims >= 2,
        "standing_note": dims["professional_standing"]["state"],
        "excluded": {"spouse_9th_native_3rd": "removed_v1"},
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_spouse_evidence(kundali: dict) -> dict:
    """Deterministic spouse_evidence_v1 payload for a calculate_full_kundali()
    result. Never mutates `kundali`; raises SpouseEvidenceError rather than
    guessing on unusable input."""
    if not isinstance(kundali, dict):
        raise SpouseEvidenceError("kundali must be a dict")
    chart = _Chart(kundali)
    d1 = _d1_facts(chart)
    d9 = _d9_facts(chart)
    dk = _darakaraka(chart)
    seventh = d1["seventh_sign"]
    return {
        "schema_version": SCHEMA_VERSION,
        "chart_facts": {"d1": d1, "d9": d9, "darakaraka": dk},
        "nature": _nature(chart, d9, dk),
        "health": _health(chart),
        "wealth": _wealth(chart),
        "free_tool_layer": {"seventh_sign": seventh, "sign_card_id": SEVENTH_SIGN_TABLE[seventh]["sign_card_id"]},
        "limitations": list(LIMITATIONS),
    }
