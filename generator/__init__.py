"""Template-only dataset generator package."""

from generator.template_generator import (
    GeneratorConfig,
    TemplateGenerationError,
    generate_sample,
    generate_samples,
    load_configs,
    sample_semantic_input,
)

__all__ = [
    "GeneratorConfig",
    "TemplateGenerationError",
    "generate_sample",
    "generate_samples",
    "load_configs",
    "sample_semantic_input",
]
