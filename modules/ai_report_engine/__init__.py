# modules/ai_report_engine/__init__.py

"""
AI Report Lifecycle Manager + Generation Pipeline package (Phases 2-3, 5).

Public surface:
    ReportLifecycleManager  -- the only entry point future callers use
    ReportGenerator          -- the interface every segment must implement
    GeneratedReport          -- what a generator returns
    ReportCacheRepository    -- DB access layer (used internally by the
                                manager; exposed for tests/tooling)
    BaseAIGenerator          -- reusable pipeline every concrete segment
                                generator inherits from (Phase 3)
    OpenAIExecutor           -- thin wrapper around the AI Prediction
                                Lab's existing OpenAI client
    OutputValidator          -- centralized output validation
    ResponseBuilder          -- wraps validated text into GeneratedReport
    GeneratorRegistry        -- registers/resolves generators by segment (Phase 5)
    get_default_registry     -- the process-wide registry, pre-populated
                                with every currently implemented generator

No concrete segment generator (LoveGenerator, CareerGenerator, ...) is
defined in this package -- see each segment's own module for that, once
built (LoveGenerator lives in modules/love/love_generator.py).
"""

from modules.ai_report_engine.base_generator import BaseAIGenerator
from modules.ai_report_engine.cache_repository import ReportCacheRepository
from modules.ai_report_engine.exceptions import (
    AIGenerationPipelineError,
    ContextBuildError,
    OpenAICallError,
    OutputValidationError,
    PromptBuildError,
)
from modules.ai_report_engine.generator_interface import GeneratedReport, ReportGenerator
from modules.ai_report_engine.lifecycle_manager import (
    ReportGenerationError,
    ReportLifecycleManager,
    UnknownSegmentError,
)
from modules.ai_report_engine.generator_registry import GeneratorRegistry, get_default_registry
from modules.ai_report_engine.openai_executor import OpenAIExecutor
from modules.ai_report_engine.output_validator import OutputValidator
from modules.ai_report_engine.response_builder import ResponseBuilder

__all__ = [
    "ReportLifecycleManager",
    "ReportGenerator",
    "GeneratedReport",
    "ReportCacheRepository",
    "ReportGenerationError",
    "UnknownSegmentError",
    "BaseAIGenerator",
    "OpenAIExecutor",
    "OutputValidator",
    "ResponseBuilder",
    "AIGenerationPipelineError",
    "ContextBuildError",
    "PromptBuildError",
    "OpenAICallError",
    "OutputValidationError",
    "GeneratorRegistry",
    "get_default_registry",
]
