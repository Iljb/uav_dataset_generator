"""Configuration linting for the UAV dataset generator."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from generator.component_index import (
    ACTIVE_STATUS,
    DEFERRED_STATUS,
    VALID_COMPONENT_TYPES,
    ComponentIndex,
    build_component_index,
    component_consumes_topics,
    component_provides_topics,
    component_roles,
)
from generator.template_generator import GeneratorConfig, load_configs


REQUIRED_SEMANTIC_FIELDS = {
    "roles",
    "consumes_topics",
    "provides_topics",
    "lifecycle",
    "selection_weight",
    "enabled",
    "status",
}

VALID_LIFECYCLES = {"control_once", "service_persistent"}
VALID_STATUSES = {ACTIVE_STATUS, DEFERRED_STATUS}

REQUIRED_ACTIVE_ROLES = {
    "flight.preflight": "ROBOT_CTRL",
    "flight.takeoff": "ROBOT_CTRL",
    "flight.altitude_up": "ROBOT_CTRL",
    "flight.altitude_down": "ROBOT_CTRL",
    "flight.return": "ROBOT_CTRL",
    "flight.land": "ROBOT_CTRL",
    "navigation.point": "ROBOT_CTRL",
    "navigation.orbit": "ROBOT_CTRL",
    "navigation.path": "ROBOT_CTRL",
    "navigation.line": "ROBOT_CTRL",
    "navigation.line.corridor": "ROBOT_CTRL",
    "navigation.area": "ROBOT_CTRL",
    "navigation.area.perimeter": "ROBOT_CTRL",
    "navigation.area.grid": "ROBOT_CTRL",
    "navigation.area.lawnmower": "ROBOT_CTRL",
    "navigation.area.spiral": "ROBOT_CTRL",
    "navigation.area.expanding_square": "ROBOT_CTRL",
    "navigation.obstacle_avoid": "ROBOT_CTRL",
    "observation.hover": "ROBOT_CTRL",
    "observation.orbit": "ROBOT_CTRL",
    "tracking.target": "ROBOT_CTRL",
    "service.battery.level": "SVR",
    "service.battery.warning": "SVR",
    "service.position.gnss": "SVR",
    "service.position.local_pose": "SVR",
    "service.route.waypoint_list": "SVR",
    "service.camera.visible": "SVR",
    "service.camera.thermal": "SVR",
    "service.radar.scan": "SVR",
    "service.vision.detect": "SVR",
}


@dataclass(frozen=True)
class ConfigLintIssue:
    """One configuration lint finding."""

    code: str
    message: str
    path: str
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConfigLintResult:
    """Full configuration lint result."""

    issues: list[ConfigLintIssue]
    report: dict[str, Any]

    @property
    def errors(self) -> list[ConfigLintIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ConfigLintIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [issue.to_dict() for issue in self.issues],
            "report": self.report,
        }


class ConfigLintError(RuntimeError):
    """Raised when configuration linting finds errors."""

    def __init__(self, result: ConfigLintResult) -> None:
        self.result = result
        super().__init__(
            f"Configuration lint failed with {len(result.errors)} error(s)."
        )


def lint_config(config: GeneratorConfig | None = None) -> ConfigLintResult:
    """Validate loaded generator configuration and return lint findings."""

    cfg = config or load_configs()
    issues: list[ConfigLintIssue] = []
    component_library = cfg.component_library
    _lint_component_library(component_library, issues)
    index = build_component_index(component_library)
    _lint_required_roles(index, issues)
    _lint_topic_dependencies(index, issues)
    _lint_params_space_mappings(cfg.params_space, index, issues)
    _lint_task_template_mappings(cfg.task_templates, index, issues)
    report = _build_report(cfg, index, issues)
    return ConfigLintResult(issues=issues, report=report)


def assert_valid_config(config: GeneratorConfig | None = None) -> ConfigLintResult:
    """Run config linting and raise if any errors are found."""

    result = lint_config(config)
    if result.has_errors:
        raise ConfigLintError(result)
    return result


def lint_config_dir(config_dir: Path | str = "config") -> ConfigLintResult:
    """Load and lint configuration from a config directory."""

    return lint_config(load_configs(config_dir))


def _lint_component_library(
    component_library: dict[str, Any],
    issues: list[ConfigLintIssue],
) -> None:
    components = component_library.get("components")
    if not isinstance(components, list):
        _add_issue(
            issues,
            "component_library.components_not_list",
            "`components` must be a list.",
            "component_library.components",
        )
        return

    metadata = component_library.get("metadata", {})
    if isinstance(metadata, dict):
        expected_count = metadata.get("component_count")
        if isinstance(expected_count, int) and expected_count != len(components):
            _add_issue(
                issues,
                "component_library.component_count_mismatch",
                f"metadata.component_count={expected_count}, actual={len(components)}.",
                "component_library.metadata.component_count",
            )

    ids = [component.get("id") for component in components if isinstance(component, dict)]
    for component_id, count in Counter(ids).items():
        if isinstance(component_id, str) and count > 1:
            _add_issue(
                issues,
                "component.duplicate_id",
                f"Duplicate component id: {component_id}",
                "component_library.components",
            )

    robot_ctrl_count = 0
    svr_count = 0
    for index, component in enumerate(components):
        path = f"component_library.components[{index}]"
        if not isinstance(component, dict):
            _add_issue(
                issues,
                "component.not_object",
                "Component entry must be an object.",
                path,
            )
            continue
        component_type = component.get("type")
        if component_type == "ROBOT_CTRL":
            robot_ctrl_count += 1
        elif component_type == "SVR":
            svr_count += 1
        _lint_component(component, path, issues)

    if isinstance(metadata, dict):
        _check_metadata_count(
            metadata,
            "robot_ctrl_count",
            robot_ctrl_count,
            "component_library.metadata.robot_ctrl_count",
            issues,
        )
        _check_metadata_count(
            metadata,
            "svr_count",
            svr_count,
            "component_library.metadata.svr_count",
            issues,
        )


def _lint_component(
    component: dict[str, Any],
    path: str,
    issues: list[ConfigLintIssue],
) -> None:
    component_id = component.get("id")
    if not isinstance(component_id, str) or not component_id:
        _add_issue(issues, "component.invalid_id", "Component id must be a string.", f"{path}.id")

    component_type = component.get("type")
    if component_type not in VALID_COMPONENT_TYPES:
        _add_issue(
            issues,
            "component.invalid_type",
            f"Component type must be one of {sorted(VALID_COMPONENT_TYPES)}.",
            f"{path}.type",
        )

    missing = REQUIRED_SEMANTIC_FIELDS - set(component)
    for field in sorted(missing):
        _add_issue(
            issues,
            "component.missing_semantic_field",
            f"Missing semantic annotation field: {field}",
            f"{path}.{field}",
        )

    _lint_string_list(component.get("roles"), f"{path}.roles", "component.invalid_roles", issues, non_empty=True)
    _lint_string_list(
        component.get("consumes_topics"),
        f"{path}.consumes_topics",
        "component.invalid_consumes_topics",
        issues,
    )
    _lint_string_list(
        component.get("provides_topics"),
        f"{path}.provides_topics",
        "component.invalid_provides_topics",
        issues,
    )

    lifecycle = component.get("lifecycle")
    if lifecycle not in VALID_LIFECYCLES:
        _add_issue(
            issues,
            "component.invalid_lifecycle",
            f"Lifecycle must be one of {sorted(VALID_LIFECYCLES)}.",
            f"{path}.lifecycle",
        )
    elif component_type == "ROBOT_CTRL" and lifecycle != "control_once":
        _add_issue(
            issues,
            "component.robot_ctrl_lifecycle_mismatch",
            "ROBOT_CTRL components should use lifecycle=control_once.",
            f"{path}.lifecycle",
        )
    elif component_type == "SVR" and lifecycle != "service_persistent":
        _add_issue(
            issues,
            "component.svr_lifecycle_mismatch",
            "SVR components should use lifecycle=service_persistent.",
            f"{path}.lifecycle",
        )

    status = component.get("status")
    if status not in VALID_STATUSES:
        _add_issue(
            issues,
            "component.invalid_status",
            f"Status must be one of {sorted(VALID_STATUSES)}.",
            f"{path}.status",
        )

    if not isinstance(component.get("enabled"), bool):
        _add_issue(
            issues,
            "component.invalid_enabled",
            "enabled must be a boolean.",
            f"{path}.enabled",
        )

    weight = component.get("selection_weight")
    if isinstance(weight, bool) or not isinstance(weight, int | float) or weight < 0:
        _add_issue(
            issues,
            "component.invalid_selection_weight",
            "selection_weight must be a non-negative number.",
            f"{path}.selection_weight",
        )

    _lint_channel_topic_match(
        component,
        source_key="input_channels",
        semantic_key="consumes_topics",
        path=path,
        code="component.consumes_topics_mismatch",
        issues=issues,
    )
    _lint_channel_topic_match(
        component,
        source_key="output_channels",
        semantic_key="provides_topics",
        path=path,
        code="component.provides_topics_mismatch",
        issues=issues,
    )

    control_outputs = component.get("control_outputs")
    if component_type == "ROBOT_CTRL":
        outputs = set(control_outputs or [])
        if not {"success", "failed"}.issubset(outputs):
            _add_issue(
                issues,
                "component.robot_ctrl_missing_control_outputs",
                "ROBOT_CTRL components must expose success and failed control outputs.",
                f"{path}.control_outputs",
            )
    elif component_type == "SVR" and control_outputs not in ([], None):
        _add_issue(
            issues,
            "component.svr_has_control_outputs",
            "SVR components must not expose control outputs.",
            f"{path}.control_outputs",
        )


def _lint_required_roles(index: ComponentIndex, issues: list[ConfigLintIssue]) -> None:
    for role, component_type in sorted(REQUIRED_ACTIVE_ROLES.items()):
        candidates = index.components_for_role(
            role,
            component_type=component_type,
            include_disabled=False,
            include_deferred=False,
        )
        if not candidates:
            _add_issue(
                issues,
                "role.missing_active_component",
                f"No active {component_type} component provides required role: {role}",
                f"roles.{role}",
            )


def _lint_topic_dependencies(index: ComponentIndex, issues: list[ConfigLintIssue]) -> None:
    for component_id in index.component_ids:
        component = index.component(component_id)
        if not component.get("enabled", False) or component.get("status") == DEFERRED_STATUS:
            continue
        optional_topics = _optional_input_topics(component)
        for topic in component_consumes_topics(component):
            providers = index.providers_for_topic(
                topic,
                include_disabled=False,
                include_deferred=False,
            )
            if providers:
                continue
            severity = "warning" if topic in optional_topics else "error"
            _add_issue(
                issues,
                "topic.missing_active_provider",
                f"No active component provides consumed topic {topic!r} for {component_id}.",
                f"component_library.components.{component_id}.consumes_topics",
                severity=severity,
            )

    for topic, providers in sorted(index.topic_providers.items()):
        active_providers = index.providers_for_topic(
            topic,
            include_disabled=False,
            include_deferred=False,
        )
        if len(active_providers) > 1:
            _add_issue(
                issues,
                "topic.multiple_active_providers",
                f"Topic {topic!r} has multiple active providers: {list(active_providers)}.",
                f"topics.{topic}.providers",
                severity="warning",
            )


def _lint_params_space_mappings(
    params_space: dict[str, Any],
    index: ComponentIndex,
    issues: list[ConfigLintIssue],
) -> None:
    route_to_robot_ctrl = params_space.get("route_to_robot_ctrl", {})
    route_to_roles = params_space.get("route_to_roles")
    if not isinstance(route_to_roles, dict):
        _add_issue(
            issues,
            "params_space.missing_route_to_roles",
            "params_space.route_to_roles must be defined for abstract planning.",
            "params_space.route_to_roles",
        )
        route_to_roles = {}

    for route_mode, rule in params_space.get("route_to_robot_ctrl", {}).items():
        for component_id in _list_value(rule.get("sequence")):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"params_space.route_to_robot_ctrl.{route_mode}.sequence",
                default_selection=True,
            )

    if isinstance(route_to_robot_ctrl, dict):
        missing_role_routes = set(route_to_robot_ctrl) - set(route_to_roles)
        for route_mode in sorted(missing_role_routes):
            _add_issue(
                issues,
                "params_space.route_to_roles_missing_route_mode",
                f"route_to_roles is missing route_mode: {route_mode}",
                f"params_space.route_to_roles.{route_mode}",
            )

    for route_mode, rule in route_to_roles.items():
        if not isinstance(rule, dict):
            _add_issue(
                issues,
                "params_space.invalid_route_to_roles_rule",
                "route_to_roles entries must be objects.",
                f"params_space.route_to_roles.{route_mode}",
            )
            continue
        for role in _list_value(rule.get("sequence")):
            _lint_role_reference(
                role,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"params_space.route_to_roles.{route_mode}.sequence",
                default_selection=True,
            )

    for capability, services in params_space.get("capability_to_svr", {}).items():
        for component_id in _list_value(services):
            _lint_component_reference(
                component_id,
                expected_type="SVR",
                index=index,
                issues=issues,
                path=f"params_space.capability_to_svr.{capability}",
                default_selection=True,
            )

    for capability, components in params_space.get("capability_to_robot_ctrl", {}).items():
        for component_id in _list_value(components):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"params_space.capability_to_robot_ctrl.{capability}",
                default_selection=True,
            )

    for key, components in params_space.get("safety_to_component", {}).items():
        for component_id in _list_value(components):
            _lint_component_reference(
                component_id,
                expected_type=None,
                index=index,
                issues=issues,
                path=f"params_space.safety_to_component.{key}",
                default_selection=True,
            )

    for key, components in params_space.get("mission_tail", {}).items():
        for component_id in _list_value(components):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"params_space.mission_tail.{key}",
                default_selection=True,
            )

    _lint_failure_strategy_rules(params_space, index, issues)

    for payload, payload_rule in params_space.get("payloads", {}).items():
        for component_id in _list_value(payload_rule.get("candidate_svr_components")):
            _lint_component_reference(
                component_id,
                expected_type="SVR",
                index=index,
                issues=issues,
                path=f"params_space.payloads.{payload}.candidate_svr_components",
                default_selection=False,
            )
        for component_id in _list_value(payload_rule.get("candidate_robot_ctrl_components")):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"params_space.payloads.{payload}.candidate_robot_ctrl_components",
                default_selection=False,
            )


def _lint_failure_strategy_rules(
    params_space: dict[str, Any],
    index: ComponentIndex,
    issues: list[ConfigLintIssue],
) -> None:
    rules = params_space.get("failure_strategy_rules", {})
    if not isinstance(rules, dict):
        _add_issue(
            issues,
            "failure_strategy.invalid_rules",
            "failure_strategy_rules must be an object when defined.",
            "params_space.failure_strategy_rules",
        )
        return

    enabled = rules.get("enabled", False)
    if not isinstance(enabled, bool):
        _add_issue(
            issues,
            "failure_strategy.invalid_enabled",
            "failure_strategy_rules.enabled must be a boolean.",
            "params_space.failure_strategy_rules.enabled",
        )

    max_branches = rules.get("max_branches_per_task", 1)
    if isinstance(max_branches, bool) or not isinstance(max_branches, int) or max_branches < 1:
        _add_issue(
            issues,
            "failure_strategy.invalid_max_branches",
            "failure_strategy_rules.max_branches_per_task must be a positive integer.",
            "params_space.failure_strategy_rules.max_branches_per_task",
        )

    policy_selection = rules.get("policy_selection", "balanced_by_trigger_role")
    if policy_selection not in {"balanced_by_trigger_role"}:
        _add_issue(
            issues,
            "failure_strategy.invalid_policy_selection",
            "failure_strategy_rules.policy_selection must be balanced_by_trigger_role.",
            "params_space.failure_strategy_rules.policy_selection",
        )

    _lint_branch_count_by_complexity(rules, max_branches, issues)

    policies = rules.get("policies", {})
    if not isinstance(policies, dict):
        _add_issue(
            issues,
            "failure_strategy.invalid_policies",
            "failure_strategy_rules.policies must be an object.",
            "params_space.failure_strategy_rules.policies",
        )
        return

    default_policy = rules.get("default_policy", "none")
    if default_policy != "none" and default_policy not in policies:
        _add_issue(
            issues,
            "failure_strategy.invalid_default_policy",
            f"default_policy references unknown policy: {default_policy}",
            "params_space.failure_strategy_rules.default_policy",
        )

    for policy_name, policy in policies.items():
        path = f"params_space.failure_strategy_rules.policies.{policy_name}"
        if not isinstance(policy, dict):
            _add_issue(
                issues,
                "failure_strategy.invalid_policy",
                "Each failure strategy policy must be an object.",
                path,
            )
            continue

        trigger_roles = _list_value(policy.get("trigger_roles"))
        on_failed_roles = _list_value(policy.get("on_failed"))
        if not trigger_roles:
            _add_issue(
                issues,
                "failure_strategy.missing_trigger_roles",
                "failure strategy policy must define trigger_roles.",
                f"{path}.trigger_roles",
            )
        if not on_failed_roles:
            _add_issue(
                issues,
                "failure_strategy.missing_on_failed",
                "failure strategy policy must define on_failed roles.",
                f"{path}.on_failed",
            )

        for role in trigger_roles:
            _lint_role_reference(
                role,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"{path}.trigger_roles",
                default_selection=True,
            )
        for role in on_failed_roles:
            _lint_role_reference(
                role,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"{path}.on_failed",
                default_selection=True,
            )

        weight = policy.get("selection_weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, int | float):
            _add_issue(
                issues,
                "failure_strategy.invalid_selection_weight",
                "selection_weight must be numeric.",
                f"{path}.selection_weight",
            )


def _lint_branch_count_by_complexity(
    rules: dict[str, Any],
    max_branches: Any,
    issues: list[ConfigLintIssue],
) -> None:
    value = rules.get("branch_count_by_complexity", {})
    if not isinstance(value, dict):
        _add_issue(
            issues,
            "failure_strategy.invalid_branch_count_by_complexity",
            "branch_count_by_complexity must be an object.",
            "params_space.failure_strategy_rules.branch_count_by_complexity",
        )
        return

    effective_max = max_branches if isinstance(max_branches, int) and not isinstance(max_branches, bool) else 1
    for complexity, range_value in value.items():
        path = f"params_space.failure_strategy_rules.branch_count_by_complexity.{complexity}"
        if not isinstance(range_value, list) or len(range_value) != 2:
            _add_issue(
                issues,
                "failure_strategy.invalid_branch_count_range",
                "Each complexity branch count must be a two-item [min, max] array.",
                path,
            )
            continue
        low, high = range_value
        if (
            isinstance(low, bool)
            or isinstance(high, bool)
            or not isinstance(low, int)
            or not isinstance(high, int)
            or low < 0
            or high < low
            or high > effective_max
        ):
            _add_issue(
                issues,
                "failure_strategy.invalid_branch_count_range",
                "Branch count ranges must satisfy 0 <= min <= max <= max_branches_per_task.",
                path,
            )


def _lint_task_template_mappings(
    task_templates: dict[str, Any],
    index: ComponentIndex,
    issues: list[ConfigLintIssue],
) -> None:
    for group_name, components in task_templates.get("SVR_GROUPS", {}).items():
        for component_id in _list_value(components):
            _lint_component_reference(
                component_id,
                expected_type="SVR",
                index=index,
                issues=issues,
                path=f"task_templates.SVR_GROUPS.{group_name}",
                default_selection=False,
            )

    for service_name, rule in task_templates.get("SVR_SERVICE_RULES", {}).items():
        for component_id in _list_value(rule.get("components")):
            _lint_component_reference(
                component_id,
                expected_type="SVR",
                index=index,
                issues=issues,
                path=f"task_templates.SVR_SERVICE_RULES.{service_name}.components",
                default_selection=True,
            )

    for route_mode, rule in task_templates.get("ROUTE_MODE_RULES", {}).items():
        for component_id in _list_value(rule.get("robot_ctrl_sequence")):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"task_templates.ROUTE_MODE_RULES.{route_mode}.robot_ctrl_sequence",
                default_selection=True,
            )
        for group in _list_value(rule.get("support_svr_groups")):
            if group not in task_templates.get("SVR_GROUPS", {}):
                _add_issue(
                    issues,
                    "mapping.unknown_svr_group",
                    f"Unknown SVR group: {group}",
                    f"task_templates.ROUTE_MODE_RULES.{route_mode}.support_svr_groups",
                )

    for capability, rule in task_templates.get("CAPABILITY_RULES", {}).items():
        for group in _list_value(rule.get("svr_groups")):
            if group not in task_templates.get("SVR_GROUPS", {}):
                _add_issue(
                    issues,
                    "mapping.unknown_svr_group",
                    f"Unknown SVR group: {group}",
                    f"task_templates.CAPABILITY_RULES.{capability}.svr_groups",
                )
        for component_id in _list_value(rule.get("robot_ctrl_components")):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"task_templates.CAPABILITY_RULES.{capability}.robot_ctrl_components",
                default_selection=True,
            )
        override = rule.get("robot_ctrl_override")
        if isinstance(override, str):
            _lint_component_reference(
                override,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"task_templates.CAPABILITY_RULES.{capability}.robot_ctrl_override",
                default_selection=True,
            )

    for rule_name, rule in task_templates.get("MOTION_VARIANT_RULES", {}).items():
        component_id = rule.get("component")
        if isinstance(component_id, str):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"task_templates.MOTION_VARIANT_RULES.{rule_name}.component",
                default_selection=rule.get("status") != "deferred",
            )

    assembly = task_templates.get("TOPOLOGY_ASSEMBLY_RULES", {})
    obstacle_policy = assembly.get("obstacle_avoidance_policy", {})
    robot_ctrl = obstacle_policy.get("robot_ctrl")
    if isinstance(robot_ctrl, str):
        _lint_component_reference(
            robot_ctrl,
            expected_type="ROBOT_CTRL",
            index=index,
            issues=issues,
            path="task_templates.TOPOLOGY_ASSEMBLY_RULES.obstacle_avoidance_policy.robot_ctrl",
            default_selection=True,
        )
    for component_id in _list_value(obstacle_policy.get("required_svr")):
        _lint_component_reference(
            component_id,
            expected_type="SVR",
            index=index,
            issues=issues,
            path="task_templates.TOPOLOGY_ASSEMBLY_RULES.obstacle_avoidance_policy.required_svr",
            default_selection=True,
        )

    for template_id, template in task_templates.get("TASK_TEMPLATES", {}).items():
        for component_id in _list_value(template.get("robot_ctrl_backbone")):
            _lint_component_reference(
                component_id,
                expected_type="ROBOT_CTRL",
                index=index,
                issues=issues,
                path=f"task_templates.TASK_TEMPLATES.{template_id}.robot_ctrl_backbone",
                default_selection=True,
            )


def _lint_component_reference(
    component_id: str,
    *,
    expected_type: str | None,
    index: ComponentIndex,
    issues: list[ConfigLintIssue],
    path: str,
    default_selection: bool,
) -> None:
    if not isinstance(component_id, str):
        _add_issue(
            issues,
            "mapping.invalid_component_reference",
            f"Component reference must be a string: {component_id!r}",
            path,
        )
        return
    if not index.has_component(component_id):
        _add_issue(
            issues,
            "mapping.unknown_component",
            f"Unknown component reference: {component_id}",
            path,
        )
        return
    if expected_type is not None and index.component_type(component_id) != expected_type:
        _add_issue(
            issues,
            "mapping.component_type_mismatch",
            f"{component_id} must be a {expected_type} component.",
            path,
        )
    if default_selection and index.is_deferred(component_id):
        _add_issue(
            issues,
            "mapping.deferred_component_selected_by_default",
            f"Deferred component {component_id} must not be selected by default rules.",
            path,
        )


def _lint_role_reference(
    role: Any,
    *,
    expected_type: str,
    index: ComponentIndex,
    issues: list[ConfigLintIssue],
    path: str,
    default_selection: bool,
) -> None:
    if not isinstance(role, str):
        _add_issue(
            issues,
            "mapping.invalid_role_reference",
            f"Role reference must be a string: {role!r}",
            path,
        )
        return

    candidates = index.components_for_role(
        role,
        component_type=expected_type,
        include_disabled=False,
        include_deferred=not default_selection,
    )
    if not candidates:
        _add_issue(
            issues,
            "mapping.role_without_active_component",
            f"No active {expected_type} component provides role: {role}",
            path,
        )


def _build_report(
    config: GeneratorConfig,
    index: ComponentIndex,
    issues: list[ConfigLintIssue],
) -> dict[str, Any]:
    issue_counts = Counter(issue.code for issue in issues)
    severity_counts = Counter(issue.severity for issue in issues)
    component_types = Counter(
        component.get("type", "unknown")
        for component in config.component_library.get("components", [])
        if isinstance(component, dict)
    )
    statuses = Counter(
        component.get("status", "unknown")
        for component in config.component_library.get("components", [])
        if isinstance(component, dict)
    )
    lifecycles = Counter(
        component.get("lifecycle", "unknown")
        for component in config.component_library.get("components", [])
        if isinstance(component, dict)
    )
    return {
        "valid": not any(issue.severity == "error" for issue in issues),
        "issue_count": len(issues),
        "error_count": severity_counts.get("error", 0),
        "warning_count": severity_counts.get("warning", 0),
        "issue_counts": dict(sorted(issue_counts.items())),
        "component_count": len(index.component_ids),
        "component_types": dict(sorted(component_types.items())),
        "component_statuses": dict(sorted(statuses.items())),
        "component_lifecycles": dict(sorted(lifecycles.items())),
        "role_count": len(index.components_by_role),
        "provided_topic_count": len(index.topic_providers),
        "consumed_topic_count": len(index.topic_consumers),
    }


def _check_metadata_count(
    metadata: dict[str, Any],
    key: str,
    actual: int,
    path: str,
    issues: list[ConfigLintIssue],
) -> None:
    expected = metadata.get(key)
    if isinstance(expected, int) and expected != actual:
        _add_issue(
            issues,
            "component_library.metadata_count_mismatch",
            f"{key}={expected}, actual={actual}.",
            path,
        )


def _lint_string_list(
    values: Any,
    path: str,
    code: str,
    issues: list[ConfigLintIssue],
    *,
    non_empty: bool = False,
) -> None:
    if not isinstance(values, list):
        _add_issue(issues, code, "Value must be a list of strings.", path)
        return
    if non_empty and not values:
        _add_issue(issues, code, "Value must contain at least one string.", path)
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value:
            _add_issue(
                issues,
                code,
                "List entries must be non-empty strings.",
                f"{path}[{index}]",
            )


def _lint_channel_topic_match(
    component: dict[str, Any],
    *,
    source_key: str,
    semantic_key: str,
    path: str,
    code: str,
    issues: list[ConfigLintIssue],
) -> None:
    channel_topics = sorted(_channel_topics(component.get(source_key)))
    semantic_topics = sorted(component_consumes_topics(component) if semantic_key == "consumes_topics" else component_provides_topics(component))
    if channel_topics != semantic_topics:
        _add_issue(
            issues,
            code,
            f"{semantic_key} must match {source_key} topics.",
            f"{path}.{semantic_key}",
        )


def _channel_topics(channels: Any) -> list[str]:
    if not isinstance(channels, list):
        return []
    return [
        channel["topic"]
        for channel in channels
        if isinstance(channel, dict) and isinstance(channel.get("topic"), str)
    ]


def _optional_input_topics(component: dict[str, Any]) -> set[str]:
    optional: set[str] = set()
    channels = component.get("input_channels", [])
    if not isinstance(channels, list):
        return optional
    for channel in channels:
        if (
            isinstance(channel, dict)
            and channel.get("optional") is True
            and isinstance(channel.get("topic"), str)
        ):
            optional.add(channel["topic"])
    return optional


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _add_issue(
    issues: list[ConfigLintIssue],
    code: str,
    message: str,
    path: str,
    *,
    severity: str = "error",
) -> None:
    issues.append(
        ConfigLintIssue(
            code=code,
            message=message,
            path=path,
            severity=severity,
        )
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint UAV generator configuration.")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--report", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = lint_config_dir(args.config_dir)
    payload = {
        **result.report,
        "issues": [issue.to_dict() for issue in result.issues],
    }
    if args.report is not None:
        _write_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if result.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
