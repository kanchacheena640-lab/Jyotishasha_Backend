# services/sadhesati_classifier.py

"""
U4B.1 -- the ONE pure Sade Sati classification rule.

Extracted from services/sadhesati_report_generator.py's own delta/phase
logic (U4B.0's audit executed this exact rule against all 144
natal-Moon x current-Saturn sign combinations and found it
astrologically correct -- see test_sadhesati_classifier.py). This
module reproduces that math verbatim; it does NOT invent, adjust, or
"improve" any Vimshottari/Sade Sati formula.

PURE FUNCTION CONTRACT (U4B.1 Section 1/2):
    classify_sade_sati(natal_moon_sign, saturn_sign) performs ZERO
    ephemeris calls, ZERO I/O, ZERO imports of swisseph/
    smart_transit_engine/transit_engine/full_kundali_api. It depends on
    nothing but the two sign-name strings it is given -- no Lagna, no
    houses, no planet-filled payload, no DOB/TOB, no OpenAI. Resolving
    an ACTUAL current Saturn sign from live/current time is a SEPARATE
    concern, owned by services/current_saturn_resolver.py -- this
    module never resolves "now" itself.

SINGLE SOURCE OF TRUTH (U4B.1 Section 3):
    services/sadhesati_report_generator.py now imports
    SADE_SATI_SIGN_ORDER and classify_sade_sati() from here instead of
    maintaining its own local SATURN_RASHIS list and delta/phase
    assignment -- there is exactly ONE maintained copy of the
    12th/natal/2nd-sign -> 1st/2nd/3rd-Phase rule in the codebase after
    this change. generate_sadhesati_report()'s own externally-visible
    status/phase output is unchanged for identical inputs (see that
    module's own docstring for the compatibility mapping).

NULL / FAILURE SEMANTICS (U4B.1 Section 9, frozen):
    - natal_moon_sign missing or not one of the 12 canonical signs
      -> state=NOT_CALCULATED (active=None, phase=None). NEVER treated
      as inactive -- a profile whose Moon sign was never computed must
      never be silently reported as "not in Sade Sati".
    - saturn_sign missing or not one of the 12 canonical signs
      -> state=SATURN_UNAVAILABLE (active=None, phase=None). Distinct
      from NOT_CALCULATED (that's a Moon-sign problem) and from
      INACTIVE (that's a genuine, confidently-computed non-active
      result) -- callers must be able to tell "we don't know" apart
      from "we know, and it's no".
    - Both valid -> state=ACTIVE (phase is always exactly one of the 3
      canonical phase strings) or state=INACTIVE (phase is always
      None).
"""

from __future__ import annotations

from typing import Optional, TypedDict

# U4B.1 -- moved here verbatim from services/sadhesati_report_generator.py's
# own former local SATURN_RASHIS list. Deliberately kept in this exact
# rotated-from-Capricorn order (not "corrected" to a conventional
# Aries-first order) -- U4B.0's audit proved by execution that the
# starting point of this list has zero effect on correctness, since
# only the RELATIVE offset between two .index() lookups into the SAME
# list ever matters. Changing the order here would be unnecessary churn
# with zero behavior difference, and would not be "the same list" any
# more for anything that still expects this exact sequence.
SADE_SATI_SIGN_ORDER = [
    "Capricorn", "Aquarius", "Pisces", "Aries", "Taurus", "Gemini",
    "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius",
]

PHASE_FIRST = "1st Phase"    # Saturn in the 12th sign from natal Moon
PHASE_SECOND = "2nd Phase"   # Saturn in the natal Moon sign itself
PHASE_THIRD = "3rd Phase"    # Saturn in the 2nd sign from natal Moon

STATE_NOT_CALCULATED = "not_calculated"       # natal Moon sign missing/invalid
STATE_SATURN_UNAVAILABLE = "saturn_unavailable"  # current Saturn sign missing/invalid
STATE_ACTIVE = "active"
STATE_INACTIVE = "inactive"


class SadeSatiClassification(TypedDict):
    state: str                    # one of the 4 STATE_* constants above
    active: Optional[bool]        # True/False only for ACTIVE/INACTIVE; None otherwise
    phase: Optional[str]          # one of PHASE_FIRST/SECOND/THIRD only when active; None otherwise


def classify_sade_sati(natal_moon_sign: Optional[str], saturn_sign: Optional[str]) -> SadeSatiClassification:
    """The one pure Sade Sati rule. Reproduces
    services/sadhesati_report_generator.py's original delta computation
    exactly: delta = (saturn_index - moon_index) % 12; 11->1st Phase,
    0->2nd Phase, 1->3rd Phase, anything else->Inactive. No ephemeris
    call, no I/O -- a plain function of two sign-name strings."""
    if natal_moon_sign not in SADE_SATI_SIGN_ORDER:
        return {"state": STATE_NOT_CALCULATED, "active": None, "phase": None}

    if saturn_sign not in SADE_SATI_SIGN_ORDER:
        return {"state": STATE_SATURN_UNAVAILABLE, "active": None, "phase": None}

    moon_index = SADE_SATI_SIGN_ORDER.index(natal_moon_sign)
    saturn_index = SADE_SATI_SIGN_ORDER.index(saturn_sign)
    delta = (saturn_index - moon_index) % 12

    if delta == 11:
        return {"state": STATE_ACTIVE, "active": True, "phase": PHASE_FIRST}
    if delta == 0:
        return {"state": STATE_ACTIVE, "active": True, "phase": PHASE_SECOND}
    if delta == 1:
        return {"state": STATE_ACTIVE, "active": True, "phase": PHASE_THIRD}

    return {"state": STATE_INACTIVE, "active": False, "phase": None}
