"""Explicit SELF Marriage registrations and internal evidence horizons."""
from types import MappingProxyType

MARRIAGE_HORIZONS = MappingProxyType({
    "strongest_marriage_periods": 60,
    "marriage_chances_timing": 60,
    "marriage_delay_reason": 12,
    "marriage_delay_easing": 60,
    "marriage_talks_current_period": 12,
    "relationship_to_marriage_window": 60,
})
MARRIAGE_QUESTION_KEYS = tuple(MARRIAGE_HORIZONS)
MARRIAGE_MULTI_YEAR_KEYS = tuple(key for key, months in MARRIAGE_HORIZONS.items() if months > 12)
