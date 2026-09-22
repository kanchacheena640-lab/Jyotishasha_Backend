"""Typed prompt definitions. Availability describes facts, never sellability."""
from dataclasses import dataclass
from enum import Enum

from modules.intents.intent_contract import LocalizedText, PERSON_MODES


class Capability(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    EVIDENCE_AVAILABLE = "EVIDENCE_AVAILABLE"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"


class Archetype(str, Enum):
    TIMING = "TIMING"
    DIAGNOSTIC = "DIAGNOSTIC"
    DIRECTION = "DIRECTION"
    COMPATIBILITY = "COMPATIBILITY"


@dataclass(frozen=True)
class EvidenceRequirement:
    key: str
    label: str
    focus: str
    sources: tuple[str, ...]
    group: str = ""
    missing: str = ""

    def __post_init__(self):
        if not all((self.key, self.label, self.focus)) or not (self.sources or self.missing):
            raise ValueError("Evidence needs an identity, scope and source or explicit missing fact.")


@dataclass(frozen=True)
class PromptSpec:
    question_key: str
    intent_slug: str
    person_mode: str
    title: LocalizedText
    question: LocalizedText
    analysis_objective: str
    astrological_focus: str
    timing_requirement: str
    evidence_requirements: tuple[EvidenceRequirement, ...]
    output_emphasis: str
    boundaries: tuple[str, ...]
    archetype: Archetype
    capability: Capability

    def __post_init__(self):
        if self.person_mode not in PERSON_MODES:
            raise ValueError("Prompt person mode is not supported by the catalog.")
        if not all((self.question_key, self.intent_slug, self.analysis_objective,
                    self.astrological_focus, self.timing_requirement, self.output_emphasis, self.boundaries)):
            raise ValueError("Prompt spec has an empty instruction field.")
        keys = [r.key for r in self.evidence_requirements]
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("Evidence requirements must be nonempty and unique.")
        if not isinstance(self.archetype, Archetype) or not isinstance(self.capability, Capability):
            raise ValueError("Invalid prompt archetype or capability.")
        if bool(self.missing_evidence) != (self.capability == Capability.EVIDENCE_MISSING):
            raise ValueError("Capability must agree with the missing facts.")

    @property
    def missing_evidence(self):
        return tuple(r.missing for r in self.evidence_requirements if r.missing)
