"""
SNR-2B -- canonical 7th-sign spouse-nature layer (Spouse Nature Report,
rep_026, frozen astrology contract SNR-2A / SNR-2A.1).

ONE data source for the broad "Lagna -> 7th sign -> spouse tendency"
layer. It is consumed by:

  1. modules/payments/spouse_evidence.py -- the paid report's P2
     ("7th-house sign") nature evidence;
  2. (later phase) the free Lagna-based spouse-nature tool.

Both MUST read this module rather than keep their own interpretation, so
the free card and the paid report can never contradict each other.

Data only -- no chart calculation, no narrative copy (card wording is a
later frontend/content phase). Each sign contributes ONE vote per trait
dimension, derived from its element and modality (frozen SNR-2A section 3
/ SNR-2A.1 section 8):

  element  fire  -> temperament: dynamic,  communication: expressive
           earth -> temperament: steady,   approach_to_life: practical
           air   -> communication: expressive, sociability: outgoing
           water -> emotional_style: open,  sociability: home_centred
  modality movable -> independence: independent, temperament: dynamic
           fixed   -> temperament: steady,  responsibility: dutiful
           dual    -> communication: expressive, responsibility: flexible

One vote per source per dimension: when element and modality point to the
SAME pole that dimension still gets a single vote; when they point to
OPPOSITE poles (Leo/Capricorn temperament) the sign casts no vote on that
dimension -- a single source cannot vote for both poles.
"""

from __future__ import annotations

SIGN_ORDER = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)

# The 8 frozen trait dimensions and their two neutral poles (pole A, pole B).
TRAIT_DIMENSIONS = (
    ("temperament", ("steady", "dynamic")),
    ("communication", ("reserved", "expressive")),
    ("emotional_style", ("guarded", "open")),
    ("sociability", ("home_centred", "outgoing")),
    ("approach_to_life", ("practical", "idealistic")),
    ("responsibility", ("dutiful", "flexible")),
    ("independence", ("partnership_oriented", "independent")),
    ("convention", ("traditional", "unconventional")),
)
DIMENSION_POLES = dict(TRAIT_DIMENSIONS)

SIGN_ELEMENT = {
    "Aries": "fire", "Leo": "fire", "Sagittarius": "fire",
    "Taurus": "earth", "Virgo": "earth", "Capricorn": "earth",
    "Gemini": "air", "Libra": "air", "Aquarius": "air",
    "Cancer": "water", "Scorpio": "water", "Pisces": "water",
}
SIGN_MODALITY = {
    "Aries": "movable", "Cancer": "movable", "Libra": "movable", "Capricorn": "movable",
    "Taurus": "fixed", "Leo": "fixed", "Scorpio": "fixed", "Aquarius": "fixed",
    "Gemini": "dual", "Virgo": "dual", "Sagittarius": "dual", "Pisces": "dual",
}

ELEMENT_VOTES = {
    "fire": {"temperament": "dynamic", "communication": "expressive"},
    "earth": {"temperament": "steady", "approach_to_life": "practical"},
    "air": {"communication": "expressive", "sociability": "outgoing"},
    "water": {"emotional_style": "open", "sociability": "home_centred"},
}
MODALITY_VOTES = {
    "movable": {"independence": "independent", "temperament": "dynamic"},
    "fixed": {"temperament": "steady", "responsibility": "dutiful"},
    "dual": {"communication": "expressive", "responsibility": "flexible"},
}


def _combine_votes(element: str, modality: str) -> dict:
    """Deduplicated per-dimension votes for one sign (one vote per dimension;
    an element/modality conflict on the same dimension abstains)."""
    votes: dict = {}
    conflicts = set()
    for source in (ELEMENT_VOTES[element], MODALITY_VOTES[modality]):
        for dimension, pole in source.items():
            if dimension in conflicts:
                continue
            if dimension in votes and votes[dimension] != pole:
                conflicts.add(dimension)
                del votes[dimension]
            else:
                votes[dimension] = pole
    return {d: votes[d] for d, _ in TRAIT_DIMENSIONS if d in votes}


def _build_table() -> dict:
    table = {}
    for sign in SIGN_ORDER:
        element, modality = SIGN_ELEMENT[sign], SIGN_MODALITY[sign]
        table[sign] = {
            "sign": sign,
            "sign_card_id": f"seventh_sign_{sign.lower()}",
            "element": element,
            "modality": modality,
            "votes": _combine_votes(element, modality),
        }
    return table


# sign -> {sign, sign_card_id, element, modality, votes{dimension: pole}}
SEVENTH_SIGN_TABLE = _build_table()


def seventh_sign_for_lagna(lagna_sign: str) -> str:
    """Lagna sign -> 7th-house sign (whole-sign). Raises ValueError for an
    unrecognised Lagna -- never guesses."""
    if lagna_sign not in SIGN_ORDER:
        raise ValueError(f"Unrecognised Lagna sign: {lagna_sign!r}")
    return SIGN_ORDER[(SIGN_ORDER.index(lagna_sign) + 6) % 12]


def seventh_sign_layer(lagna_sign: str) -> dict:
    """The free-tool / P2 layer for a Lagna: the 7th sign's table entry."""
    return SEVENTH_SIGN_TABLE[seventh_sign_for_lagna(lagna_sign)]
