"""Template-only dataset generator package."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_TEMPLATE_EXPORTS = {
    "GeneratorConfig",
    "TemplateGenerationError",
    "generate_sample",
    "generate_samples",
    "load_configs",
    "sample_semantic_input",
}

_VALIDATOR_EXPORTS = {
    "ValidationIssue",
    "ValidationResult",
    "filter_valid_samples",
    "load_samples",
    "save_validation_outputs",
    "validate_file",
    "validate_sample",
    "validate_samples",
}

_PIPELINE_EXPORTS = {
    "PipelineConfig",
    "PipelineError",
    "PipelineResult",
    "deduplicate_samples",
    "run_pipeline",
    "split_samples",
}

__all__ = sorted(_TEMPLATE_EXPORTS | _VALIDATOR_EXPORTS | _PIPELINE_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _TEMPLATE_EXPORTS:
        module = import_module(".template_generator", __name__)
        return getattr(module, name)
    if name in _VALIDATOR_EXPORTS:
        module = import_module(".validator", __name__)
        return getattr(module, name)
    if name in _PIPELINE_EXPORTS:
        module = import_module(".pipeline", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
