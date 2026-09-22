"""Explicit Education registrations and minimum evidence horizons."""
from types import MappingProxyType

EDUCATION_HORIZONS = MappingProxyType({
    "study_strong_period": 12,
    "exam_preparation_period": 12,
    "higher_education_timing": 36,
    "study_progress_improvement": 12,
})
EDUCATION_QUESTION_KEYS = tuple(EDUCATION_HORIZONS)
EDUCATION_HOUSES = MappingProxyType({
    "study_strong_period": (4, 5, 9),
    "exam_preparation_period": (3, 4, 5, 6),
    "higher_education_timing": (4, 5, 9, 11),
    "study_progress_improvement": (3, 4, 5, 6, 9),
})
