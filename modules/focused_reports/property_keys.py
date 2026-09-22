"""Explicit Property registrations, horizons and relevant natal houses."""
from types import MappingProxyType

PROPERTY_HORIZONS = MappingProxyType({
    "property_purchase_timing": 60,
    "property_current_period": 12,
    "property_strongest_period": 60,
    "property_delay_reason": 12,
    "own_home_timing": 60,
})
PROPERTY_QUESTION_KEYS = tuple(PROPERTY_HORIZONS)
PROPERTY_HOUSES = MappingProxyType({
    "property_purchase_timing": (2, 4, 11),
    "property_current_period": (2, 4, 11),
    "property_strongest_period": (2, 4, 11),
    "property_delay_reason": (2, 4, 6, 11),
    "own_home_timing": (2, 4, 11, 12),
})
