"""Explicit dual-person registrations and minimum evidence selections."""
from types import MappingProxyType

RELATIONSHIP_QUESTION_KEYS = (
    "relationship_lead_to_marriage", "long_term_compatibility",
    "kundali_match_for_marriage", "right_time_to_consider_marriage",
    "relationship_strengths_risks", "conflict_areas", "emotional_communication_fit",
    "strengthen_relationship", "relationship_care_periods",
)
RELATIONSHIP_TIMING_KEYS = frozenset((
    "relationship_lead_to_marriage", "right_time_to_consider_marriage", "relationship_care_periods",
))
RELATIONSHIP_HORIZONS = MappingProxyType({
    key: 12 if key in RELATIONSHIP_TIMING_KEYS else None for key in RELATIONSHIP_QUESTION_KEYS
})
# Existing Ashtakoot component names, not a new scoring or interpretation engine.
ALL_KOOTAS = ("varna", "vashya", "tara", "yoni", "graha_maitri", "gana", "bhakoot", "nadi")
RELATIONSHIP_SELECTIONS = MappingProxyType({
    "relationship_lead_to_marriage": ((2, 5, 7, 11), ("graha_maitri", "gana", "bhakoot", "nadi")),
    "long_term_compatibility": ((2, 4, 7), ("graha_maitri", "gana", "bhakoot", "yoni")),
    "kundali_match_for_marriage": ((2, 5, 7), ALL_KOOTAS),
    "right_time_to_consider_marriage": ((2, 5, 7, 11), ("graha_maitri", "gana", "bhakoot")),
    "relationship_strengths_risks": ((3, 4, 7), ("graha_maitri", "gana", "bhakoot", "yoni")),
    "conflict_areas": ((3, 4, 7), ("graha_maitri", "gana", "bhakoot")),
    "emotional_communication_fit": ((3, 4, 7), ("graha_maitri", "gana")),
    "strengthen_relationship": ((3, 4, 7), ("graha_maitri", "gana", "bhakoot")),
    "relationship_care_periods": ((3, 4, 7), ("graha_maitri", "gana", "bhakoot")),
})
