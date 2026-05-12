"""Validation and filtering for topology-only generated samples."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generator.template_generator import GeneratorConfig, load_configs


VALID_PREV_EVENTS = {"success", "failed"}


@dataclass(frozen=True)
class ValidationIssue:
    """One validation finding for a generated sample."""

    sample_id: str | None
    code: str
    message: str
    path: str
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    """Validation output with filtered samples and a compact report."""

    valid_samples: list[dict[str, Any]]
    invalid_samples: list[dict[str, Any]]
    issues: list[ValidationIssue]
    report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid_samples": self.valid_samples,
            "invalid_samples": self.invalid_samples,
            "issues": [issue.to_dict() for issue in self.issues],
            "report": self.report,
        }


def load_samples(path: Path | str) -> list[dict[str, Any]]:
    """Load a JSON array of generated samples."""

    sample_path = Path(path)
    data = json.loads(sample_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON array in {sample_path}")
    return data


def validate_sample(
    sample: dict[str, Any],
    config: GeneratorConfig | None = None,
) -> list[ValidationIssue]:
    """Validate one sample and return all issues found."""

    cfg = config or load_configs()
    issues: list[ValidationIssue] = []
    sample_id = _sample_id(sample)

    if not isinstance(sample, dict):
        return [
            ValidationIssue(
                sample_id=None,
                code="sample.not_object",
                message="Sample must be a JSON object.",
                path="$",
            )
        ]

    _validate_outer_schema(sample, issues)
    semantic_input = sample.get("semantic_input")
    target_topology = sample.get("target_topology")

    if isinstance(semantic_input, dict):
        _validate_semantic_input(semantic_input, cfg, issues, sample_id)
    if isinstance(target_topology, dict):
        topology_context = _validate_topology(target_topology, cfg, issues, sample_id)
    else:
        topology_context = _empty_topology_context()

    if isinstance(semantic_input, dict) and isinstance(target_topology, dict):
        _validate_semantic_topology_alignment(
            semantic_input,
            topology_context,
            cfg,
            issues,
            sample_id,
        )

    return issues


def validate_samples(
    samples: list[dict[str, Any]],
    config: GeneratorConfig | None = None,
) -> ValidationResult:
    """Validate and split generated samples into valid and invalid groups."""

    cfg = config or load_configs()
    valid_samples: list[dict[str, Any]] = []
    invalid_samples: list[dict[str, Any]] = []
    all_issues: list[ValidationIssue] = []
    seen_sample_ids: set[str] = set()

    for index, sample in enumerate(samples):
        sample_issues = validate_sample(sample, cfg)
        sample_id = _sample_id(sample)
        if sample_id is None:
            sample_id = f"index_{index}"
        if sample_id in seen_sample_ids:
            sample_issues.append(
                ValidationIssue(
                    sample_id=sample_id,
                    code="sample.duplicate_id",
                    message=f"Duplicate sample_id: {sample_id}",
                    path="sample_id",
                )
            )
        seen_sample_ids.add(sample_id)

        if sample_issues:
            invalid_samples.append(
                {
                    "sample": sample,
                    "issues": [issue.to_dict() for issue in sample_issues],
                }
            )
            all_issues.extend(sample_issues)
        else:
            valid_samples.append(sample)

    report = _build_report(samples, valid_samples, invalid_samples, all_issues)
    return ValidationResult(
        valid_samples=valid_samples,
        invalid_samples=invalid_samples,
        issues=all_issues,
        report=report,
    )


def filter_valid_samples(
    samples: list[dict[str, Any]],
    config: GeneratorConfig | None = None,
) -> list[dict[str, Any]]:
    """Return only valid samples."""

    return validate_samples(samples, config).valid_samples


def validate_file(
    input_path: Path | str = "raw/template_generated.json",
    output_dir: Path | str = "processed",
    report_path: Path | str = "stats/validation_report.json",
    config: GeneratorConfig | None = None,
) -> ValidationResult:
    """Validate a sample file and save filtered outputs plus a report."""

    cfg = config or load_configs()
    samples = load_samples(input_path)
    result = validate_samples(samples, cfg)
    save_validation_outputs(result, output_dir=output_dir, report_path=report_path)
    return result


def save_validation_outputs(
    result: ValidationResult,
    output_dir: Path | str = "processed",
    report_path: Path | str = "stats/validation_report.json",
) -> None:
    """Persist valid samples, invalid samples, and the validation report."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    report_file = Path(report_path)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report = dict(result.report)
    report["output_files"] = {
        "valid_samples": str(output_path / "validated_samples.json"),
        "invalid_samples": str(output_path / "invalid_samples.json"),
        "report": str(report_file),
    }

    _write_json(output_path / "validated_samples.json", result.valid_samples)
    _write_json(output_path / "invalid_samples.json", result.invalid_samples)
    _write_json(report_file, report)


def _validate_outer_schema(
    sample: dict[str, Any],
    issues: list[ValidationIssue],
) -> None:
    sample_id = _sample_id(sample)
    for key in ("sample_id", "semantic_input", "target_topology"):
        if key not in sample:
            issues.append(
                ValidationIssue(
                    sample_id=sample_id,
                    code=f"sample.missing_{key}",
                    message=f"Missing required sample field: {key}",
                    path=key,
                )
            )

    if "sample_id" in sample and not isinstance(sample["sample_id"], str):
        issues.append(
            ValidationIssue(
                sample_id=sample_id,
                code="sample.sample_id_not_string",
                message="sample_id must be a string.",
                path="sample_id",
            )
        )
    if "semantic_input" in sample and not isinstance(sample["semantic_input"], dict):
        issues.append(
            ValidationIssue(
                sample_id=sample_id,
                code="sample.semantic_input_not_object",
                message="semantic_input must be an object.",
                path="semantic_input",
            )
        )
    if "target_topology" in sample and not isinstance(sample["target_topology"], dict):
        issues.append(
            ValidationIssue(
                sample_id=sample_id,
                code="sample.target_topology_not_object",
                message="target_topology must be an object.",
                path="target_topology",
            )
        )


def _validate_semantic_input(
    semantic_input: dict[str, Any],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    required = config.task_types["semantic_input_contract"]["required_fields"]
    for field in required:
        if field not in semantic_input:
            _add_issue(
                issues,
                sample_id,
                "semantic.missing_field",
                f"Missing semantic field: {field}",
                f"semantic_input.{field}",
            )

    task_type = semantic_input.get("task_type")
    if task_type not in config.task_profiles:
        _add_issue(
            issues,
            sample_id,
            "semantic.unsupported_task_type",
            f"Unsupported task_type: {task_type}",
            "semantic_input.task_type",
        )
        return

    profile = config.task_profiles[task_type]
    role = semantic_input.get("role")
    if role not in profile["roles"]:
        _add_issue(
            issues,
            sample_id,
            "semantic.invalid_role",
            f"Role {role} is not allowed for {task_type}.",
            "semantic_input.role",
        )

    route_mode = semantic_input.get("route_mode")
    if route_mode not in profile["route_modes"]:
        _add_issue(
            issues,
            sample_id,
            "semantic.invalid_route_mode",
            f"route_mode {route_mode} is not allowed for {task_type}.",
            "semantic_input.route_mode",
        )

    assigned_area = semantic_input.get("assigned_area")
    target = config.params_space["assigned_targets"].get(assigned_area)
    if target is None:
        _add_issue(
            issues,
            sample_id,
            "semantic.unknown_assigned_area",
            f"Unknown assigned_area: {assigned_area}",
            "semantic_input.assigned_area",
        )
    elif target["type"] not in profile["target_types"]:
        _add_issue(
            issues,
            sample_id,
            "semantic.assigned_area_type_mismatch",
            f"assigned_area type {target['type']} does not match {task_type}.",
            "semantic_input.assigned_area",
        )

    payload = semantic_input.get("payload")
    payload_rule = config.params_space["payloads"].get(payload)
    if payload_rule is None:
        _add_issue(
            issues,
            sample_id,
            "semantic.unsupported_payload",
            f"Unsupported payload: {payload}",
            "semantic_input.payload",
        )
    else:
        supported = set(payload_rule["supports"])
        for capability in _enabled_capabilities(semantic_input):
            if capability not in supported:
                _add_issue(
                    issues,
                    sample_id,
                    "semantic.capability_payload_mismatch",
                    f"Capability {capability} is not supported by payload {payload}.",
                    f"semantic_input.capabilities.{capability}",
                )

    if _capability_enabled(semantic_input, "object_detection"):
        target_classes = semantic_input.get("capabilities", {}).get(
            "object_detection", {}
        ).get("target_classes", [])
        if not target_classes:
            _add_issue(
                issues,
                sample_id,
                "semantic.object_detection_missing_targets",
                "object_detection requires non-empty target_classes.",
                "semantic_input.capabilities.object_detection.target_classes",
            )

    if _capability_enabled(semantic_input, "target_tracking"):
        if not _capability_enabled(semantic_input, "object_detection"):
            _add_issue(
                issues,
                sample_id,
                "semantic.target_tracking_without_detection",
                "target_tracking requires object_detection.",
                "semantic_input.capabilities.target_tracking",
            )
        target_class = semantic_input.get("capabilities", {}).get(
            "target_tracking", {}
        ).get("target_class")
        if not target_class:
            _add_issue(
                issues,
                sample_id,
                "semantic.target_tracking_missing_target",
                "target_tracking requires target_class.",
                "semantic_input.capabilities.target_tracking.target_class",
            )


def _validate_topology(
    target_topology: dict[str, Any],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> dict[str, Any]:
    components = config.components
    context = _empty_topology_context()
    stages = target_topology.get("stages")

    if not isinstance(stages, list) or not stages:
        _add_issue(
            issues,
            sample_id,
            "topology.empty_or_invalid_stages",
            "target_topology.stages must be a non-empty array.",
            "target_topology.stages",
        )
        return context

    seen_ids: set[str] = set()
    names_by_id: dict[str, str] = {}
    stage_robot_prev_by_index: dict[int, Any] = {}

    for expected_stage, stage in enumerate(stages):
        path = f"target_topology.stages[{expected_stage}]"
        if not isinstance(stage, dict):
            _add_issue(issues, sample_id, "stage.not_object", "Stage must be an object.", path)
            continue
        if stage.get("stage") != expected_stage:
            _add_issue(
                issues,
                sample_id,
                "stage.non_continuous_index",
                "Stage indexes must be continuous from 0.",
                f"{path}.stage",
            )
        actions = stage.get("component")
        if not isinstance(actions, list) or not actions:
            _add_issue(
                issues,
                sample_id,
                "stage.empty_component",
                "stage.component must be a non-empty array.",
                f"{path}.component",
            )
            continue

        robot_actions: list[dict[str, Any]] = []
        for action_index, action in enumerate(actions):
            action_path = f"{path}.component[{action_index}]"
            if not isinstance(action, dict):
                _add_issue(
                    issues,
                    sample_id,
                    "component_action.not_object",
                    "Component action must be an object.",
                    action_path,
                )
                continue
            _validate_component_action(
                action,
                action_path,
                components,
                seen_ids,
                names_by_id,
                issues,
                sample_id,
            )
            name = action.get("name")
            if name in components and components[name]["type"] == "ROBOT_CTRL":
                robot_actions.append(action)

        if len(robot_actions) != 1:
            _add_issue(
                issues,
                sample_id,
                "stage.robot_ctrl_count",
                "Each stage must contain exactly one ROBOT_CTRL start action.",
                f"{path}.component",
            )
            stage_robot_prev = None
        else:
            robot_action = robot_actions[0]
            stage_robot_prev = robot_action.get("prev")
            context["robot_ctrl_names"].append(robot_action.get("name"))
            context["robot_ctrl_ids"].append(robot_action.get("id"))
            context["robot_stage_by_name"].setdefault(
                robot_action.get("name"), expected_stage
            )
            stage_robot_prev_by_index[expected_stage] = stage_robot_prev

        _validate_stage_svr_actions(
            actions,
            components,
            stage_robot_prev,
            expected_stage,
            issues,
            sample_id,
            path,
        )

    _validate_prev_references(stages, components, seen_ids, names_by_id, issues, sample_id)
    _collect_topology_component_context(stages, components, context)
    return context


def _validate_component_action(
    action: dict[str, Any],
    action_path: str,
    components: dict[str, dict[str, Any]],
    seen_ids: set[str],
    names_by_id: dict[str, str],
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    required_keys = {"id", "name", "cmd", "prev"}
    missing = required_keys - set(action)
    for key in sorted(missing):
        _add_issue(
            issues,
            sample_id,
            "component_action.missing_field",
            f"Missing component action field: {key}",
            f"{action_path}.{key}",
        )

    action_id = action.get("id")
    if not isinstance(action_id, str):
        _add_issue(
            issues,
            sample_id,
            "component_action.id_not_string",
            "Component action id must be a string.",
            f"{action_path}.id",
        )
    elif action_id in seen_ids:
        _add_issue(
            issues,
            sample_id,
            "component_action.duplicate_id",
            f"Duplicate component id: {action_id}",
            f"{action_path}.id",
        )
    else:
        seen_ids.add(action_id)

    name = action.get("name")
    if name not in components:
        _add_issue(
            issues,
            sample_id,
            "component_action.unknown_component",
            f"Unknown component: {name}",
            f"{action_path}.name",
        )
    elif isinstance(action_id, str):
        names_by_id[action_id] = name

    if action.get("cmd") != "start":
        _add_issue(
            issues,
            sample_id,
            "component_action.invalid_cmd",
            "First-version topology samples may emit only start commands.",
            f"{action_path}.cmd",
        )

    forbidden_keys = {"params", "uuid", "component_uuid", "component_params"}
    for key in sorted(forbidden_keys & set(action)):
        _add_issue(
            issues,
            sample_id,
            "component_action.forbidden_runtime_field",
            f"Component action must not contain runtime field: {key}",
            f"{action_path}.{key}",
        )


def _validate_prev_references(
    stages: list[Any],
    components: dict[str, dict[str, Any]],
    seen_ids: set[str],
    names_by_id: dict[str, str],
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    known_ids_before_action: set[str] = set()

    for stage_index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        actions = stage.get("component")
        if not isinstance(actions, list):
            continue
        for action_index, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            action_path = f"target_topology.stages[{stage_index}].component[{action_index}]"
            for prev in _prev_values(action.get("prev")):
                if not isinstance(prev, str):
                    _add_issue(
                        issues,
                        sample_id,
                        "prev.not_string",
                        "prev values must be strings.",
                        f"{action_path}.prev",
                    )
                    continue
                parts = prev.split(".")
                if len(parts) != 2:
                    _add_issue(
                        issues,
                        sample_id,
                        "prev.invalid_format",
                        "prev must use '<component_id>.<success|failed>' format.",
                        f"{action_path}.prev",
                    )
                    continue
                prev_id, event = parts
                if event not in VALID_PREV_EVENTS:
                    _add_issue(
                        issues,
                        sample_id,
                        "prev.invalid_event",
                        "prev event must be success or failed.",
                        f"{action_path}.prev",
                    )
                if prev_id not in known_ids_before_action:
                    _add_issue(
                        issues,
                        sample_id,
                        "prev.unknown_or_future_id",
                        f"prev references an unknown or future id: {prev_id}",
                        f"{action_path}.prev",
                    )
                    continue
                prev_name = names_by_id.get(prev_id)
                if prev_name in components and components[prev_name]["type"] != "ROBOT_CTRL":
                    _add_issue(
                        issues,
                        sample_id,
                        "prev.references_svr",
                        "prev must not reference an SVR component.",
                        f"{action_path}.prev",
                    )
            action_id = action.get("id")
            if isinstance(action_id, str):
                known_ids_before_action.add(action_id)


def _validate_stage_svr_actions(
    actions: list[Any],
    components: dict[str, dict[str, Any]],
    stage_robot_prev: Any,
    stage_index: int,
    issues: list[ValidationIssue],
    sample_id: str | None,
    stage_path: str,
) -> None:
    for action_index, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        name = action.get("name")
        if name not in components or components[name]["type"] != "SVR":
            continue
        if action.get("prev") != stage_robot_prev:
            _add_issue(
                issues,
                sample_id,
                "svr.prev_mismatch_with_stage_robot",
                "SVR service should share the stage ROBOT_CTRL prev condition.",
                f"{stage_path}.component[{action_index}].prev",
            )
        if action.get("cmd") != "start":
            _add_issue(
                issues,
                sample_id,
                "svr.non_start_cmd",
                "SVR service nodes must only start in generated topology.",
                f"{stage_path}.component[{action_index}].cmd",
            )


def _collect_topology_component_context(
    stages: list[Any],
    components: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> None:
    for stage_index, stage in enumerate(stages):
        if not isinstance(stage, dict) or not isinstance(stage.get("component"), list):
            continue
        for action in stage["component"]:
            if not isinstance(action, dict):
                continue
            name = action.get("name")
            if name not in components:
                continue
            context["component_names"].append(name)
            context["stage_by_component"].setdefault(name, stage_index)
            if components[name]["type"] == "SVR":
                context["svr_names"].append(name)


def _validate_semantic_topology_alignment(
    semantic_input: dict[str, Any],
    topology_context: dict[str, Any],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    component_names = set(topology_context["component_names"])
    robot_ctrl_names = topology_context["robot_ctrl_names"]
    expected_robot_chain = _expected_robot_ctrl_chain(semantic_input, config)
    if expected_robot_chain and robot_ctrl_names != expected_robot_chain:
        _add_issue(
            issues,
            sample_id,
            "alignment.robot_ctrl_chain_mismatch",
            f"ROBOT_CTRL chain mismatch. expected={expected_robot_chain}, actual={robot_ctrl_names}",
            "target_topology.stages",
        )

    expected_svr = _expected_svr_services(semantic_input, expected_robot_chain, config)
    for service in expected_svr:
        if service not in component_names:
            _add_issue(
                issues,
                sample_id,
                "alignment.missing_svr",
                f"Missing required SVR service: {service}",
                "target_topology.stages",
            )

    for service in topology_context["svr_names"]:
        if service not in expected_svr:
            _add_issue(
                issues,
                sample_id,
                "alignment.unexpected_svr",
                f"Unexpected SVR service for semantic input: {service}",
                "target_topology.stages",
            )

    duplicates = [
        service
        for service, count in Counter(topology_context["svr_names"]).items()
        if count > 1
    ]
    for service in duplicates:
        _add_issue(
            issues,
            sample_id,
            "alignment.duplicate_svr",
            f"SVR service appears more than once: {service}",
            "target_topology.stages",
        )

    _validate_required_component_presence(semantic_input, component_names, issues, sample_id)


def _validate_required_component_presence(
    semantic_input: dict[str, Any],
    component_names: set[str],
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    route_mode = semantic_input.get("route_mode")
    obstacle = _capability_enabled(semantic_input, "obstacle_avoidance")

    if obstacle:
        _require_components(
            {"obstacle_avoid_flight", "sensor_radar_scan"},
            component_names,
            issues,
            sample_id,
            "alignment.obstacle_avoidance_missing_component",
        )
    elif route_mode == "goto_point":
        _require_components(
            {"goto_point"},
            component_names,
            issues,
            sample_id,
            "alignment.goto_point_missing_component",
        )
    elif route_mode == "hover":
        _require_components(
            {"goto_point", "hover"},
            component_names,
            issues,
            sample_id,
            "alignment.hover_missing_component",
        )
    elif route_mode in {"line_follow", "waypoint", "grid", "lawnmower"}:
        _require_components(
            {"waypoint_flight", "waypoint_list_create"},
            component_names,
            issues,
            sample_id,
            "alignment.waypoint_missing_component",
        )

    if semantic_input.get("flight", {}).get("return_home", True):
        _require_components(
            {"return_home", "land"},
            component_names,
            issues,
            sample_id,
            "alignment.return_home_missing_component",
        )

    if semantic_input.get("safety", {}).get("battery_monitor", False):
        _require_components(
            {"battery_level", "battery_warning"},
            component_names,
            issues,
            sample_id,
            "alignment.battery_monitor_missing_component",
        )

    if _capability_enabled(semantic_input, "image_capture"):
        _require_components(
            {"sensor_camera_scan"},
            component_names,
            issues,
            sample_id,
            "alignment.image_capture_missing_component",
        )
    if _capability_enabled(semantic_input, "object_detection"):
        _require_components(
            {"sensor_camera_scan", "object_detect"},
            component_names,
            issues,
            sample_id,
            "alignment.object_detection_missing_component",
        )
    if _capability_enabled(semantic_input, "target_tracking"):
        _require_components(
            {"target_tracking", "sensor_camera_scan", "object_detect"},
            component_names,
            issues,
            sample_id,
            "alignment.target_tracking_missing_component",
        )
    if _capability_enabled(semantic_input, "thermal_scan"):
        _require_components(
            {"sensor_ir_scan"},
            component_names,
            issues,
            sample_id,
            "alignment.thermal_scan_missing_component",
        )


def _expected_robot_ctrl_chain(
    semantic_input: dict[str, Any],
    config: GeneratorConfig,
) -> list[str]:
    route_mode = semantic_input.get("route_mode")
    route_rule = config.params_space["route_to_robot_ctrl"].get(route_mode)
    if route_rule is None:
        return []

    route_sequence = list(route_rule["sequence"])
    if _capability_enabled(semantic_input, "obstacle_avoidance"):
        route_sequence = _replace_primary_navigation(route_sequence)

    chain = ["preflight_check", "takeoff"]
    chain.extend(_height_entry_variants(semantic_input))
    chain.extend(route_sequence)
    if _capability_enabled(semantic_input, "target_tracking"):
        chain.append("target_tracking")
    chain.extend(_height_exit_variants(semantic_input))
    chain.extend(["return_home", "land"])
    return chain


def _expected_svr_services(
    semantic_input: dict[str, Any],
    robot_ctrl_chain: list[str],
    config: GeneratorConfig,
) -> list[str]:
    expected: list[str] = []
    if semantic_input.get("safety", {}).get("battery_monitor", False):
        _extend_unique(expected, config.params_space["safety_to_component"]["battery_monitor"])

    if any(component in robot_ctrl_chain for component in ("goto_point", "obstacle_avoid_flight")):
        _extend_unique(expected, ["get_gnss_position", "gnss_to_position_3d"])
    if "waypoint_flight" in robot_ctrl_chain:
        _extend_unique(expected, ["waypoint_list_create"])

    for capability, services in config.params_space["capability_to_svr"].items():
        if _capability_enabled(semantic_input, capability):
            _extend_unique(expected, services)
    return expected


def _replace_primary_navigation(route_sequence: list[str]) -> list[str]:
    replaced = False
    output: list[str] = []
    for component in route_sequence:
        if component in {"waypoint_flight", "goto_point"} and not replaced:
            output.append("obstacle_avoid_flight")
            replaced = True
        else:
            output.append(component)
    if not replaced:
        output.append("obstacle_avoid_flight")
    return output


def _height_entry_variants(semantic_input: dict[str, Any]) -> list[str]:
    height_level = semantic_input.get("flight", {}).get("height_level")
    if height_level in {"medium", "high"}:
        return ["ascend"]
    return []


def _height_exit_variants(semantic_input: dict[str, Any]) -> list[str]:
    height_level = semantic_input.get("flight", {}).get("height_level")
    if height_level == "high":
        return ["descend"]
    return []


def _build_report(
    samples: list[dict[str, Any]],
    valid_samples: list[dict[str, Any]],
    invalid_samples: list[dict[str, Any]],
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    by_task_type = Counter()
    by_payload = Counter()
    by_route_mode = Counter()
    for sample in valid_samples:
        semantic_input = sample.get("semantic_input", {})
        by_task_type[semantic_input.get("task_type", "unknown")] += 1
        by_payload[semantic_input.get("payload", "unknown")] += 1
        by_route_mode[semantic_input.get("route_mode", "unknown")] += 1

    issue_counts = Counter(issue.code for issue in issues)
    total = len(samples)
    valid = len(valid_samples)
    invalid = len(invalid_samples)
    return {
        "validated_at": datetime.now(UTC).isoformat(),
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "valid_rate": (valid / total) if total else 0.0,
        "issue_count": len(issues),
        "issue_counts": dict(sorted(issue_counts.items())),
        "by_task_type": dict(sorted(by_task_type.items())),
        "by_payload": dict(sorted(by_payload.items())),
        "by_route_mode": dict(sorted(by_route_mode.items())),
        "output_files": {
            "valid_samples": "processed/validated_samples.json",
            "invalid_samples": "processed/invalid_samples.json",
            "report": "stats/validation_report.json",
        },
    }


def _empty_topology_context() -> dict[str, Any]:
    return {
        "component_names": [],
        "robot_ctrl_names": [],
        "robot_ctrl_ids": [],
        "svr_names": [],
        "stage_by_component": {},
        "robot_stage_by_name": {},
    }


def _prev_values(prev: Any) -> list[Any]:
    if prev is None:
        return []
    if isinstance(prev, list):
        return prev
    return [prev]


def _sample_id(sample: Any) -> str | None:
    if isinstance(sample, dict) and isinstance(sample.get("sample_id"), str):
        return sample["sample_id"]
    return None


def _capability_enabled(semantic_input: dict[str, Any], capability: str) -> bool:
    value = semantic_input.get("capabilities", {}).get(capability, False)
    if isinstance(value, dict):
        return bool(value.get("enabled", False))
    return bool(value)


def _enabled_capabilities(semantic_input: dict[str, Any]) -> list[str]:
    return [
        capability
        for capability in semantic_input.get("capabilities", {})
        if _capability_enabled(semantic_input, capability)
    ]


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _require_components(
    required: set[str],
    component_names: set[str],
    issues: list[ValidationIssue],
    sample_id: str | None,
    code: str,
) -> None:
    for component in sorted(required - component_names):
        _add_issue(
            issues,
            sample_id,
            code,
            f"Missing required component: {component}",
            "target_topology.stages",
        )


def _add_issue(
    issues: list[ValidationIssue],
    sample_id: str | None,
    code: str,
    message: str,
    path: str,
) -> None:
    issues.append(
        ValidationIssue(
            sample_id=sample_id,
            code=code,
            message=message,
            path=path,
        )
    )


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated UAV topology samples.")
    parser.add_argument("--input", default="raw/template_generated.json")
    parser.add_argument("--output-dir", default="processed")
    parser.add_argument("--report", default="stats/validation_report.json")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    config = load_configs(args.config_dir)
    result = validate_file(
        input_path=args.input,
        output_dir=args.output_dir,
        report_path=args.report,
        config=config,
    )
    print(
        json.dumps(
            {
                "total": result.report["total"],
                "valid": result.report["valid"],
                "invalid": result.report["invalid"],
                "valid_rate": result.report["valid_rate"],
                "report": args.report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.report["invalid"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
