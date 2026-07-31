# modules/ai_report_engine/exceptions.py

"""
Shared exception types for the AI Generation Pipeline. Centralized here
so every stage of the pipeline (context, prompt, OpenAI call,
validation) raises from the same small hierarchy, and the Lifecycle
Manager's existing broad `except Exception` (see lifecycle_manager.py)
catches all of them uniformly without needing to know this module
exists.
"""


class AIGenerationPipelineError(Exception):
    """Base class for every error this pipeline raises."""


class ContextBuildError(AIGenerationPipelineError):
    """Raised when a concrete generator's `build_context()` fails."""


class PromptBuildError(AIGenerationPipelineError):
    """Raised when a concrete generator's `build_prompt()` fails."""


class OpenAICallError(AIGenerationPipelineError):
    """Raised when the OpenAI call itself fails."""


class OutputValidationError(AIGenerationPipelineError):
    """Raised when the AI's raw output fails centralized validation."""
