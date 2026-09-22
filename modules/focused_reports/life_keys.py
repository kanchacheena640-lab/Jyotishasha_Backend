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
})
LIFE_QUESTION_KEYS = tuple(LIFE_HORIZONS)
LIFE_HOUSES = MappingProxyType({
    "major_turning_points": (1, 4, 7, 9, 10),
    "next_life_change_period": (1, 4, 7, 10),
    "important_years_ahead": (1, 4, 7, 9, 10),
    "current_phase_meaning": (1, 4, 6, 10),
    "areas_needing_attention": (1, 2, 4, 6, 7, 10),
    "natural_strengths": (1, 3, 5, 9),
    "life_direction": (1, 5, 9, 10),
    "focus_to_use_strengths": (1, 3, 5, 6, 10),
})
LIFE_NATAL_PLANETS = ("Sun", "Moon", "Mercury", "Jupiter", "Saturn")
