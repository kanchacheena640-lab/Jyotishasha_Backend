"""Explicit Life registrations and minimum evidence selections."""
from types import MappingProxyType

LIFE_HORIZONS = MappingProxyType({
    "major_turning_points": 60,
    "next_life_change_period": 36,
    "important_years_ahead": 60,
    "current_phase_meaning": 12,
    "areas_needing_attention": 12,
    "natural_strengths": None,
    "life_direction": None,
    "focus_to_use_strengths": 12,
    "major_kundali_obstacles": 12,
    "major_kundali_strengths": 12,
})
LIFE_QUESTION_KEYS = tuple(LIFE_HORIZONS)
# All 12 houses (unfiltered, same as build_house_lord_facts()'s own full output) -- a "major obstacles/strengths in
# my kundali" report is deliberately whole-chart, not narrowed to a handful of pre-selected houses like the other 8.
_ALL_HOUSES = tuple(range(1, 13))
LIFE_HOUSES = MappingProxyType({
    "major_turning_points": (1, 4, 7, 9, 10),
    "next_life_change_period": (1, 4, 7, 10),
    "important_years_ahead": (1, 4, 7, 9, 10),
    "current_phase_meaning": (1, 4, 6, 10),
    "areas_needing_attention": (1, 2, 4, 6, 7, 10),
    "natural_strengths": (1, 3, 5, 9),
    "life_direction": (1, 5, 9, 10),
    "focus_to_use_strengths": (1, 3, 5, 6, 10),
    "major_kundali_obstacles": _ALL_HOUSES,
    "major_kundali_strengths": _ALL_HOUSES,
})
LIFE_NATAL_PLANETS = ("Sun", "Moon", "Mercury", "Jupiter", "Saturn")
# major_kundali_obstacles/strengths are whole-chart diagnostics: Mars and the nodes are classical obstacle/strength
# significators the other 8 (narrower) Life questions never needed to surface. Existing planet facts only -- no new
# calculation. The other 8 keys are untouched (LIFE_NATAL_PLANETS remains their only, unchanged planet set).
LIFE_ALL_NATAL_PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu")
LIFE_NATAL_PLANET_OVERRIDES = MappingProxyType({
    "major_kundali_obstacles": LIFE_ALL_NATAL_PLANETS,
    "major_kundali_strengths": LIFE_ALL_NATAL_PLANETS,
})
# Existing transit primitives, reused: the other 8 keys use Jupiter/Saturn only; these 2 whole-chart diagnostics
# also include Rahu (already supported by promotion_transit_evidence.PROMOTION_TRANSIT_PLANETS) as a current
# obstacle/opportunity-axis significator. No new transit engine or planet is introduced.
LIFE_TRANSIT_PLANETS_DEFAULT = ("Jupiter", "Saturn")
LIFE_TRANSIT_PLANET_OVERRIDES = MappingProxyType({
    "major_kundali_obstacles": ("Jupiter", "Saturn", "Rahu"),
    "major_kundali_strengths": ("Jupiter", "Saturn", "Rahu"),
})
# The 2 Birth + Current diagnostic keys, for the prompt_specs.py evidence-selection branch.
DIAGNOSTIC_BIRTH_CURRENT_KEYS = frozenset(LIFE_NATAL_PLANET_OVERRIDES)
