# modules/services/static_astrology_extractor.py

"""
U3B.1 -- the ONE authoritative place that converts an ALREADY-CALCULATED
full_kundali_api.py::calculate_full_kundali() result into the frozen
U3B static-astrology storage facts (Lagna/Moon Sign/Nakshatra/Pada +
sparse Yog/Dosh + calculated_at/version).

Architectural separation (U3B.1 task, Section 5), enforced by this
module's own shape:
    A. extraction from an existing Kundali result  -> this file
    B. calculation invocation (calculate_full_kundali())  -> the
       CALLER's responsibility (routes_profile_bootstrap.py,
       modules/user_service.py) -- this module NEVER imports or calls
       calculate_full_kundali() itself, so it is impossible for using
       this module to accidentally trigger a second calculation.
    C. persistence (assigning the returned dict onto an AppUser row,
       committing)  -> the CALLER's responsibility, also kept out of
       this file so extraction stays independently testable with a
       plain dict, no Flask app context, no database.

Frozen NULL/{}/sparse state contract (U3B storage architecture, frozen
and re-confirmed by the U3B.1 task):
  - NOT CALCULATED: all 5 static-astrology columns NULL. This module
    is simply never called in that case, OR build_not_calculated_
    snapshot() below is used to explicitly invalidate an existing
    snapshot.
  - CALCULATED: static_astrology_calculated_at is set (see
    build_static_astrology_snapshot()); static_yog/static_dosh are
    {} (calculated, nothing active/present) or a sparse dict of ONLY
    the active/present entries -- inactive Yog/absent Dosh are NEVER
    stored explicitly (U3B architecture's "Active vs Inactive storage"
    decision, Option 2).

Canonical machine keys (U3B architecture audit, Section 14/15, reused
verbatim here -- never re-derived from display text where an existing
stable engine id exists):
  - The 13 non-Panch-Mahapurush Yog: each evaluator's own `result["id"]`
    is used directly as the storage key.
  - Panch Mahapurush umbrella: `result["id"]` ("panch_mahapurush_rajyog")
    -- note this differs from the top-level dict key
    calculate_full_kundali() stores it under ("panch_mahapurush_yog");
    using `id` (not the dict key) is deliberate, per the architecture
    decision to prefer the evaluator's own stable id.
  - Panch Mahapurush's 5 sub-yogs: no stable per-sub-yog id exists in
    the engine's output (only display strings inside `sub_yogs`, e.g.
    "Ruchaka Yog") -- mapped via the architecture-frozen keys below,
    themselves derived from services/panch_mahapurush.py's own fixed,
    astrologically-canonical `planet_yog_map` (verified before use,
    not guessed from display text).
  - Manglik: no `id` field exists on that evaluator's result at all;
    "manglik" is the architecture-frozen adapted key. "Present" is
    defined as `strength in ("Strong", "Partial")` -- both "None" and
    "Cancelled" mean "not Manglik" per the evaluator's own human-
    readable labels (verified in the U3B architecture audit, not
    assumed).
  - Kaal Sarp: "kaal_sarp" is the architecture-frozen key; presence is
    read EXCLUSIVELY from `result["is_present"]` (U3B.0) -- never from
    heading/prose/localized text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# U3B.1 -- the ONE central version constant (Section 4 of the task).
# Bump only when this module's own extraction logic changes in a way
# that should invalidate previously-stored snapshots. Never scattered
# as a literal `1` anywhere else.
STATIC_ASTROLOGY_VERSION = 1

# The 13 Yog evaluator results (excluding the Panch Mahapurush umbrella,
# handled separately below) that calculate_full_kundali() already
# returns under these exact top-level dict keys.
_SIMPLE_YOG_RESULT_KEYS = (
    "budh_aditya_yog",
    "chandra_mangal_yog",
    "adhi_rajyog",
    "dhan_yog",
    "dharma_karmadhipati_rajyog",
    "gajakesari_yog",
    "kuber_rajyog",
    "lakshmi_yog",
    "neechbhang_rajyog",
    "parashari_rajyog",
    "rajya_sambandh_rajyog",
    "shubh_kartari_yog",
    "vipreet_rajyog",
)

# services/panch_mahapurush.py's own fixed planet_yog_map, mirrored here
# read-only (not imported, to keep this module independent of the
# evaluator's internals -- the mapping is astrologically canonical and
# stable, verified against the actual source before writing this).
_PANCH_MAHAPURUSH_SUB_YOG_KEYS = {
    "Ruchaka Yog": "panch_mahapurush_ruchaka",
    "Bhadra Yog": "panch_mahapurush_bhadra",
    "Hamsa Yog": "panch_mahapurush_hamsa",
    "Malavya Yog": "panch_mahapurush_malavya",
    "Shasha Yog": "panch_mahapurush_shasha",
}

# Manglik Dosh "present" rule -- see module docstring.
_MANGLIK_PRESENT_SEVERITIES = ("Strong", "Partial")

# U3B.3 -- the ONE authoritative registry of every machine key that can
# ever legally appear in a stored static_yog/static_dosh document.
# Derived directly from the SAME private tuples/dicts above (never a
# second, independently-retyped list) -- this is the exact "existing
# reusable canonical mapping" the U3B.3 Admin API's own filter
# validation is required to import, rather than hardcoding its own copy
# or deriving accepted values from frontend mock data.
CANONICAL_YOG_KEYS = frozenset(
    _SIMPLE_YOG_RESULT_KEYS
    + ("panch_mahapurush_rajyog",)
    + tuple(_PANCH_MAHAPURUSH_SUB_YOG_KEYS.values())
)
CANONICAL_DOSH_KEYS = frozenset({"manglik", "kaal_sarp"})


def extract_moon_static_facts(kundali: Dict[str, Any]) -> Dict[str, Optional[Any]]:
    """Lagna / Moon Sign / Nakshatra / Moon's Nakshatra Pada -- all
    reused from the supplied, already-computed `kundali` result; never
    recalculated, never fabricated. Returns
    {"lagna", "moon_sign", "nakshatra", "nakshatra_pada"}, each None if
    it cannot be resolved from this result (e.g. Moon missing from
    `planets`)."""
    lagna = kundali.get("lagna_sign")
    moon_sign = kundali.get("rashi")
    nakshatra = None
    pada = None
    for p in kundali.get("planets") or []:
        if isinstance(p, dict) and p.get("name") == "Moon":
            nakshatra = p.get("nakshatra")
            pada = p.get("pada")
            break
    return {
        "lagna": lagna,
        "moon_sign": moon_sign,
        "nakshatra": nakshatra,
        "nakshatra_pada": pada,
    }


def _yog_segmentation_entry(result: Dict[str, Any]) -> Dict[str, Any]:
    """The ONLY fields stored for an active Yog: `strength`, when the
    evaluator supplies a meaningful one. Never `reasons`/`positives`/
    `challenge`/`description`/`upsell`/`emoji`/`heading` -- those are
    report prose, not segmentation facts (U3B architecture decision,
    Section 6)."""
    strength = result.get("strength")
    return {"strength": strength} if strength else {}


def extract_static_yog(kundali: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Sparse map of ONLY the active Yog found in `kundali` -- {} when
    calculated but nothing is active. Includes the Panch Mahapurush
    umbrella (if active) AND its individually-detected sub-yogs (mapped
    via _PANCH_MAHAPURUSH_SUB_YOG_KEYS), each as its own top-level key."""
    active: Dict[str, Dict[str, Any]] = {}

    for key in _SIMPLE_YOG_RESULT_KEYS:
        result = kundali.get(key)
        if isinstance(result, dict) and result.get("is_active") is True:
            canonical_key = result.get("id") or key
            active[canonical_key] = _yog_segmentation_entry(result)

    panch = kundali.get("panch_mahapurush_yog")
    if isinstance(panch, dict) and panch.get("is_active") is True:
        canonical_key = panch.get("id") or "panch_mahapurush_rajyog"
        active[canonical_key] = _yog_segmentation_entry(panch)

        for sub_yog_name in panch.get("sub_yogs") or []:
            sub_key = _PANCH_MAHAPURUSH_SUB_YOG_KEYS.get(sub_yog_name)
            if sub_key:
                # No stable per-sub-yog strength exists in the engine's
                # output today -- presence only, never a fabricated value.
                active[sub_key] = {}

    return active


def extract_static_dosh(kundali: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Sparse map of ONLY the present Dosh found in `kundali` -- {}
    when calculated but neither supported Dosh is present."""
    present: Dict[str, Dict[str, Any]] = {}

    manglik = kundali.get("manglik_dosh")
    if isinstance(manglik, dict):
        status = manglik.get("status")
        severity = status.get("strength") if isinstance(status, dict) else None
        if severity in _MANGLIK_PRESENT_SEVERITIES:
            present["manglik"] = {"severity": severity}

    kaalsarp = kundali.get("kaalsarp_dosh")
    if isinstance(kaalsarp, dict) and kaalsarp.get("is_present") is True:
        present["kaal_sarp"] = {}

    return present


def build_static_astrology_snapshot(kundali: Dict[str, Any]) -> Dict[str, Any]:
    """The ONE function callers use after a SINGLE calculate_full_kundali()
    call. Returns a complete, internally-consistent snapshot -- every
    value below is derived from this SAME `kundali` argument, so a
    caller that assigns this whole dict onto an AppUser row (and only
    commits once every key has been assigned) can never end up with a
    new Moon Sign paired with a stale Yog/Dosh, or vice versa (U3B.1
    Section 15, Atomicity).

    Returns exactly these 8 keys:
        lagna, moon_sign, nakshatra, nakshatra_pada,
        static_yog, static_dosh,
        static_astrology_calculated_at, static_astrology_version
    """
    moon_facts = extract_moon_static_facts(kundali)
    return {
        "lagna": moon_facts["lagna"],
        "moon_sign": moon_facts["moon_sign"],
        "nakshatra": moon_facts["nakshatra"],
        "nakshatra_pada": moon_facts["nakshatra_pada"],
        "static_yog": extract_static_yog(kundali),
        "static_dosh": extract_static_dosh(kundali),
        "static_astrology_calculated_at": datetime.now(timezone.utc),
        "static_astrology_version": STATIC_ASTROLOGY_VERSION,
    }


def build_not_calculated_snapshot() -> Dict[str, Any]:
    """The explicit "invalidate everything" snapshot -- used whenever
    birth-detail inputs become incomplete/invalid after previously
    being complete (U3B.1 Section 14). Deliberately the SAME 8 keys as
    build_static_astrology_snapshot() so a caller can unconditionally
    apply whichever one applies without a separate code path per key.
    Never leaves a partial/mixed old+new state."""
    return {
        "lagna": None,
        "moon_sign": None,
        "nakshatra": None,
        "nakshatra_pada": None,
        "static_yog": None,
        "static_dosh": None,
        "static_astrology_calculated_at": None,
        "static_astrology_version": None,
    }


def apply_snapshot_to_app_user(app_user, snapshot: Dict[str, Any]) -> None:
    """Assigns every key of `snapshot` (from either builder above) onto
    `app_user` -- a single, tiny, shared assignment step so no caller
    hand-rolls its own partial `app_user.lagna = ...; app_user.static_yog = ...`
    sequence that could accidentally skip a field."""
    for field, value in snapshot.items():
        setattr(app_user, field, value)
