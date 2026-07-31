# modules/ai_report_engine/generator_registry.py

"""
Generator Registry -- the single source of truth for which
ReportGenerator handles which segment (LOVE, CAREER, FINANCE, HEALTH,
FAMILY, ALERTS).

This registry is completely generic: the `GeneratorRegistry` class
itself knows nothing about LOVE or any other segment -- it only stores
and resolves whatever it is given. The one place any segment is named
concretely is `_register_default_generators()` below, which is exactly
where a future generator gets added.

Relationship to the Lifecycle Manager: `ReportLifecycleManager` (Phase
2, NOT modified by this file) already takes a plain
`Dict[str, ReportGenerator]` in its constructor -- that shape is
unchanged. What changes is WHERE that dict comes from: instead of a
caller hand-writing `{"LOVE": LoveGenerator(), ...}` inline, it now
calls `get_default_registry().as_dict()`. The registry is the single
source of truth for registration; the manager's own code and
constructor signature are untouched, exactly as instructed.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from modules.ai_report_engine.generator_interface import ReportGenerator
from modules.ai_report_engine.lifecycle_manager import UnknownSegmentError


class GeneratorRegistry:
    def __init__(self):
        self._generators: Dict[str, ReportGenerator] = {}

    def register(self, segment: str, generator: ReportGenerator) -> None:
        """Adds (or replaces) the generator for `segment`. Segment is
        treated as an opaque string key -- this class assigns no
        meaning to it."""
        self._generators[segment] = generator

    def resolve(self, segment: str) -> ReportGenerator:
        """Returns the registered generator for `segment`, or raises
        UnknownSegmentError -- the same exception type
        ReportLifecycleManager already raises internally, so callers
        see one consistent error regardless of whether the manager or
        the registry detected the unknown segment."""
        generator = self._generators.get(segment)
        if generator is None:
            raise UnknownSegmentError(
                f"No generator registered for segment={segment!r}. "
                f"Registered segments: {self.registered_segments()}"
            )
        return generator

    def as_dict(self) -> Dict[str, ReportGenerator]:
        """The exact shape ReportLifecycleManager's constructor already
        expects -- a defensive copy, so mutating the returned dict never
        affects this registry's own state."""
        return dict(self._generators)

    def registered_segments(self) -> List[str]:
        return sorted(self._generators)


# ---------------------------------------------------------------
# Process-wide default registry. Built lazily so importing this module
# (e.g. to use the GeneratorRegistry class directly, or in a test) never
# forces LoveGenerator's own import chain (full_kundali_api, AppUser,
# the whole AI Prediction Lab) to load unless the default registry is
# actually requested.
# ---------------------------------------------------------------
_default_registry: Optional[GeneratorRegistry] = None


def get_default_registry() -> GeneratorRegistry:
    """
    Returns the single, process-wide registry with every currently
    implemented generator registered. This is what future callers
    (e.g. a future API layer) should use to build the dict passed into
    ReportLifecycleManager, instead of constructing one by hand:

        manager = ReportLifecycleManager(generators=get_default_registry().as_dict())
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = GeneratorRegistry()
        _register_default_generators(_default_registry)
    return _default_registry


def _register_default_generators(registry: GeneratorRegistry) -> None:
    """
    The ONE place segment -> generator wiring is declared. Adding a new
    segment later requires exactly two steps, and nothing else:
        1. Create the generator (e.g. modules/career/career_generator.py)
        2. Register it here: registry.register("CAREER", CareerGenerator())
    No change to GeneratorRegistry, ReportLifecycleManager, or the AI
    Generation Pipeline is ever required to add a segment.
    """
    from modules.love.love_generator import LoveGenerator

    registry.register("LOVE", LoveGenerator())

    # Future segments -- add one line each, in the same form, once each
    # generator exists:
    # registry.register("CAREER", CareerGenerator())
    # registry.register("FINANCE", FinanceGenerator())
    # registry.register("HEALTH", HealthGenerator())
    # registry.register("FAMILY", FamilyGenerator())
    # registry.register("ALERTS", AlertsGenerator())
