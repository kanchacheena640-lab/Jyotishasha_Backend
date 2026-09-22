"""Explicit Foreign/Relocation keys, horizons and relevant natal houses."""
from types import MappingProxyType

FOREIGN_HORIZONS = MappingProxyType({
    "going_abroad_timing": 60,
    "foreign_work_timing": 60,
    "study_abroad": 12,
    "foreign_settlement_timing": 60,
    "relocation_timing": 60,
    "foreign_plans_delay_reason": 12,
})
FOREIGN_QUESTION_KEYS = tuple(FOREIGN_HORIZONS)
FOREIGN_HOUSES = MappingProxyType({
    "going_abroad_timing": (3, 9, 12),
    "foreign_work_timing": (3, 6, 9, 10, 12),
    "study_abroad": (4, 5, 9, 12),
    "foreign_settlement_timing": (4, 9, 12),
    "relocation_timing": (3, 4, 12),
    "foreign_plans_delay_reason": (3, 4, 9, 12),
})
