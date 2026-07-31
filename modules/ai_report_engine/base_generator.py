# modules/ai_report_engine/base_generator.py

"""
Base AI Generator -- the reusable AI Generation Pipeline every segment
generator (LoveGenerator, CareerGenerator, FinanceGenerator,
HealthGenerator, FamilyGenerator, AlertsGenerator) inherits from.

This class owns the COMPLETE workflow and satisfies the
`ReportGenerator` interface (Phase 2) so any subclass can be handed
directly to `ReportLifecycleManager`:

    Build Context -> Build Prompt -> Call OpenAI -> Validate Output
        -> Build GeneratedReport -> Return

`generate()` is intentionally NOT meant to be overridden -- concrete
subclasses implement ONLY:

    - build_context(...)   -- gather/shape whatever data this segment's
                               report needs (reusing existing backend
                               services -- never duplicated here)
    - build_prompt(...)    -- turn that context into a final prompt
                               string (reusing an existing prompt
                               template/builder -- never duplicated here)

and optionally override two narrow hooks:

    - compute_expires_at(...)  -- only segments with real domain
                                   knowledge of staleness (e.g. Love's
                                   CURRENT_PHASE knowing an Antardasha
                                   end date) need this; default is None,
                                   which defers to the Lifecycle
                                   Manager's generic report_type-based
                                   fallback (see lifecycle_manager.py).
    - PROMPT_VERSION / GENERATOR_VERSION class attributes -- provenance
      only, no behavior depends on them in this phase.

This class contains NO segment-specific logic, and NO OpenAI
client/model construction -- both of those are reused from elsewhere
(OpenAIExecutor wraps the AI Prediction Lab's own client; see that
module's docstring).
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

from modules.ai_report_engine.generator_interface import GeneratedReport, ReportGenerator
from modules.ai_report_engine.openai_executor import OpenAIExecutor
from modules.ai_report_engine.output_validator import OutputValidator
from modules.ai_report_engine.response_builder import ResponseBuilder


class BaseAIGenerator(ReportGenerator):
    # Concrete subclasses may override these two for provenance
    # tracking (see modules/models_ai_reports.py's
    # model_version/prompt_version/generator_version columns).
    PROMPT_VERSION: Optional[str] = None
    GENERATOR_VERSION: Optional[str] = None

    def __init__(
        self,
        executor: Optional[OpenAIExecutor] = None,
        validator: Optional[OutputValidator] = None,
        response_builder: Optional[ResponseBuilder] = None,
    ):
        # Constructor-injected, with sensible defaults, so tests (or a
        # future generator) can swap any stage without touching the
        # others -- none of these three carry segment-specific state.
        self._executor = executor or OpenAIExecutor()
        self._validator = validator or OutputValidator()
        self._response_builder = response_builder or ResponseBuilder()

    # ------------------------------------------------------------
    # Fixed workflow -- final, not meant to be overridden.
    # ------------------------------------------------------------
    def generate(
        self,
        *,
        profile_id: int,
        report_type: str,
        language: str,
    ) -> GeneratedReport:
        context = self.build_context(
            profile_id=profile_id, report_type=report_type, language=language,
        )

        prompt = self.build_prompt(
            context=context, report_type=report_type, language=language,
        )

        text, raw_openai_response = self._executor.run(prompt)

        validated_text = self._validator.validate(text)

        expires_at = self.compute_expires_at(context=context, report_type=report_type)

        return self._response_builder.build(
            text=validated_text,
            model_version=raw_openai_response.get("model"),
            prompt_version=self.PROMPT_VERSION,
            generator_version=self.GENERATOR_VERSION or type(self).__name__,
            expires_at=expires_at,
        )

    # ------------------------------------------------------------
    # What concrete generators MUST implement.
    # ------------------------------------------------------------
    @abstractmethod
    def build_context(
        self,
        *,
        profile_id: int,
        report_type: str,
        language: str,
    ) -> Dict[str, Any]:
        """
        Gather and shape whatever backend data this report needs.
        Must reuse existing backend services/context builders -- this
        pipeline does not calculate anything itself. Returns a plain
        dict; the base class treats it as opaque.
        """
        raise NotImplementedError

    @abstractmethod
    def build_prompt(
        self,
        *,
        context: Dict[str, Any],
        report_type: str,
        language: str,
    ) -> str:
        """
        Turn `context` into the final prompt string. Must reuse an
        existing prompt template/builder -- this pipeline does not own
        or duplicate prompt wording.
        """
        raise NotImplementedError

    # ------------------------------------------------------------
    # Optional hook -- default defers to the Lifecycle Manager's
    # generic, report_type-only fallback (see lifecycle_manager.py's
    # _default_expiry). Override only if this segment/report_type has
    # real domain knowledge of when its content goes stale.
    # ------------------------------------------------------------
    def compute_expires_at(
        self,
        *,
        context: Dict[str, Any],
        report_type: str,
    ) -> Optional[datetime]:
        return None
