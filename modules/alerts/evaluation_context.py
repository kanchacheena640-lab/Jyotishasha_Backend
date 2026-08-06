# modules/alerts/evaluation_context.py

"""
Builds the EvaluationContext ("Planet Data", broadened for Phase 2) the
Rule Engine evaluates every rule against. Takes the same `kundali` dict
shape full_kundali_api.calculate_full_kundali() already returns -- the
one and only place this module reads natal facts (house lords, natal
planet aspects, Mahadasha/Antardasha, yoga results) from, all of them
already computed by the existing backend. Nothing here performs a new
astrology calculation.

Independent from the Premium Generators by design (see this package's
__init__.py) -- reuses services/full_kundali_service.derive_house_lords()
directly rather than through services/ai_prediction_lab, exactly the
same reasoning already documented in modules/alerts/planet_data.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.full_kundali_service import derive_house_lords

from modules.alerts.event_models import EvaluationContext
from modules.alerts.planet_data import build_planet_snapshots

# Every yoga key calculate_full_kundali() already computes and returns
# with a consistent `is_active` flag (confirmed across the CAREER,
# FINANCE, HEALTH, and FAMILY Premium Generator phases of this project
# -- see their own *_context_builder.py files' identical discovery).
# Tracking the full set here, rather than a per-event subset, is what
# lets config/micro_events.json reference ANY of them via `yoga_active`
# without a code change -- the set below is the one place that would
# need a new entry if a brand-new yoga evaluator is ever added to
# full_kundali_api.py's own return dict.
TRACKED_YOGA_KEYS: List[str] = [
    "dharma_karmadhipati_rajyog",
    "rajya_sambandh_rajyog",
    "parashari_rajyog",
    "panch_mahapurush_yog",
    "gajakesari_yog",
    "budh_aditya_yog",
    "dhan_yog",
    "kuber_rajyog",
    "lakshmi_yog",
    "chandra_mangal_yog",
    "neechbhang_rajyog",
    "vipreet_rajyog",
    "shubh_kartari_yog",
    "adhi_rajyog",
]


def _natal_planets_by_name(kundali: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    planets = kundali.get("planets") or kundali.get("Planets") or []
    return {p.get("name"): p for p in planets if p.get("name")}


def _active_yogas(kundali: Dict[str, Any]) -> Dict[str, bool]:
    return {
        key: bool((kundali.get(key) or {}).get("is_active"))
        for key in TRACKED_YOGA_KEYS
    }


def build_evaluation_context(kundali: Dict[str, Any]) -> EvaluationContext:
    """`kundali` must be the dict returned by
    full_kundali_api.calculate_full_kundali() -- this function does not
    call it itself, so the backend remains the single source of truth
    for when/how that payload is produced (same convention as every
    Premium Generator's own context builder)."""
    lagna_sign = kundali.get("lagna_sign")

    mahadasha = kundali.get("current_mahadasha") or {}
    antardasha = kundali.get("current_antardasha") or {}

    return EvaluationContext(
        lagna_sign=lagna_sign,
        planet_snapshots=build_planet_snapshots(lagna_sign),
        natal_planets_by_name=_natal_planets_by_name(kundali),
        house_lords=kundali.get("lords") or derive_house_lords(lagna_sign),
        mahadasha_lord=mahadasha.get("mahadasha"),
        antardasha_lord=antardasha.get("planet"),
        active_yogas=_active_yogas(kundali),
    )
