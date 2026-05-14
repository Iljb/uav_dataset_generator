"""Template-only dataset generator package."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_TEMPLATE_EXPORTS = {
    "GeneratorConfig",
    "TemplateGenerationError",
    "build_control_graph",
    "build_topology_from_control_graph",
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

_COMPONENT_INDEX_EXPORTS = {
    "ComponentIndex",
    "build_component_index",
    "component_consumes_topics",
    "component_provides_topics",
    "component_roles",
}

_CONFIG_LINTER_EXPORTS = {
    "ConfigLintError",
    "ConfigLintIssue",
    "ConfigLintResult",
    "assert_valid_config",
    "lint_config",
    "lint_config_dir",
}

_PLANNER_EXPORTS = {
    "AbstractPlan",
    "PlannedRole",
    "PlanningError",
    "build_abstract_plan",
    "build_abstract_plans",
}

_ROLE_RESOLVER_EXPORTS = {
    "ResolvedPlan",
    "ResolvedRole",
    "RoleResolutionError",
    "resolve_plan",
    "resolve_robot_role_chain",
    "resolve_service_roles",
}

_SERVICE_RESOLVER_EXPORTS = {
    "ResolvedServicePlan",
    "ServicePlacement",
    "ServiceResolutionError",
    "resolve_required_services",
    "resolve_service_plan",
    "resolve_stage_services",
}

_CONTROL_GRAPH_EXPORTS = {
    "ControlEdge",
    "ControlGraph",
    "ControlNode",
    "build_main_control_graph",
}

_FAILURE_STRATEGY_EXPORTS = {
    "FailureStrategyError",
    "FailureStrategySelection",
    "apply_failure_strategies",
}

__all__ = sorted(
    _TEMPLATE_EXPORTS
    | _VALIDATOR_EXPORTS
    | _PIPELINE_EXPORTS
    | _COMPONENT_INDEX_EXPORTS
    | _CONFIG_LINTER_EXPORTS
    | _PLANNER_EXPORTS
    | _ROLE_RESOLVER_EXPORTS
    | _SERVICE_RESOLVER_EXPORTS
    | _CONTROL_GRAPH_EXPORTS
    | _FAILURE_STRATEGY_EXPORTS
)


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
    if name in _COMPONENT_INDEX_EXPORTS:
        module = import_module(".component_index", __name__)
        return getattr(module, name)
    if name in _CONFIG_LINTER_EXPORTS:
        module = import_module(".config_linter", __name__)
        return getattr(module, name)
    if name in _PLANNER_EXPORTS:
        module = import_module(".planner", __name__)
        return getattr(module, name)
    if name in _ROLE_RESOLVER_EXPORTS:
        module = import_module(".role_resolver", __name__)
        return getattr(module, name)
    if name in _SERVICE_RESOLVER_EXPORTS:
        module = import_module(".service_resolver", __name__)
        return getattr(module, name)
    if name in _CONTROL_GRAPH_EXPORTS:
        module = import_module(".control_graph", __name__)
        return getattr(module, name)
    if name in _FAILURE_STRATEGY_EXPORTS:
        module = import_module(".failure_strategy", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
