"""Validation and filtering for topology-only generated samples."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generator.component_index import (
    component_consumes_topics,
    component_provides_topics,
    component_roles,
)
from generator.planner import PlanningError, PlannedRole, build_abstract_plan
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
    failure_enabled = _failure_strategy_enabled(config)

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

        robot_prevs = [action.get("prev") for action in robot_actions]
        if not failure_enabled and len(robot_actions) != 1:
            _add_issue(
                issues,
                sample_id,
                "stage.robot_ctrl_count",
                "Each stage must contain exactly one ROBOT_CTRL start action.",
                f"{path}.component",
            )
        elif failure_enabled and len(robot_actions) < 1:
            _add_issue(
                issues,
                sample_id,
                "stage.robot_ctrl_count",
                "Each stage must contain at least one ROBOT_CTRL start action.",
                f"{path}.component",
            )

        if len(robot_actions) == 1:
            robot_action = robot_actions[0]
            context["robot_stage_by_name"].setdefault(robot_action.get("name"), expected_stage)

        for robot_action in robot_actions:
            context["robot_ctrl_names"].append(robot_action.get("name"))
            context["robot_ctrl_ids"].append(robot_action.get("id"))
            context["robot_action_records"].append(
                {
                    "id": robot_action.get("id"),
                    "name": robot_action.get("name"),
                    "prev": robot_action.get("prev"),
                    "stage": expected_stage,
                }
            )

        _validate_stage_svr_actions(
            actions,
            components,
            robot_prevs,
            expected_stage,
            issues,
            sample_id,
            path,
        )

    _validate_prev_references(stages, components, seen_ids, names_by_id, issues, sample_id)
    _collect_topology_component_context(stages, components, context)
    _populate_main_robot_context(context)
    _validate_guarded_robot_stages(
        context,
        config,
        failure_enabled,
        issues,
        sample_id,
    )
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
    stage_robot_prevs: list[Any],
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
        if action.get("prev") not in stage_robot_prevs:
            _add_issue(
                issues,
                sample_id,
                "svr.prev_mismatch_with_stage_robot",
                "SVR service should share one stage ROBOT_CTRL prev condition.",
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


def _populate_main_robot_context(context: dict[str, Any]) -> None:
    main_records = _main_robot_records(context["robot_action_records"])
    context["main_robot_ctrl_names"] = [record["name"] for record in main_records]
    context["main_robot_ctrl_ids"] = [record["id"] for record in main_records]


def _main_robot_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records_by_id = {
        record["id"]: record
        for record in records
        if isinstance(record.get("id"), str)
    }
    success_targets: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []

    for record in records:
        prev = record.get("prev")
        parsed = _parse_prev(prev)
        if parsed is None:
            roots.append(record)
            continue
        prev_id, event = parsed
        if event == "success":
            success_targets.setdefault(prev_id, []).append(record)

    if not roots:
        return []

    main: list[dict[str, Any]] = []
    current = roots[0]
    seen: set[str] = set()
    while isinstance(current.get("id"), str) and current["id"] not in seen:
        main.append(current)
        seen.add(current["id"])
        candidates = [
            candidate
            for candidate in success_targets.get(current["id"], [])
            if candidate.get("id") in records_by_id
        ]
        if not candidates:
            break
        current = sorted(candidates, key=lambda item: item.get("stage", 0))[0]
    return main


def _validate_guarded_robot_stages(
    topology_context: dict[str, Any],
    config: GeneratorConfig,
    failure_enabled: bool,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    records = topology_context["robot_action_records"]
    if not failure_enabled:
        _validate_failure_edges_disabled(records, issues, sample_id)
        return

    records_by_stage: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        stage = record.get("stage")
        if isinstance(stage, int):
            records_by_stage.setdefault(stage, []).append(record)

    guard_cache: dict[str, frozenset[tuple[str, str]]] = {}
    records_by_id = {
        record["id"]: record
        for record in records
        if isinstance(record.get("id"), str)
    }

    for stage, stage_records in records_by_stage.items():
        if len(stage_records) < 2:
            continue
        guards = [
            _path_guard(record, records_by_id, guard_cache)
            for record in stage_records
        ]
        for left_index, left_guard in enumerate(guards):
            for right_index in range(left_index + 1, len(guards)):
                if _guards_mutually_exclusive(left_guard, guards[right_index]):
                    continue
                _add_issue(
                    issues,
                    sample_id,
                    "stage.robot_ctrl_guards_not_mutually_exclusive",
                    "ROBOT_CTRL actions in the same stage must have mutually exclusive control guards.",
                    f"target_topology.stages[{stage}].component",
                )

    _validate_failure_branches(records, config, issues, sample_id)


def _validate_failure_edges_disabled(
    records: list[dict[str, Any]],
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    for record in records:
        parsed = _parse_prev(record.get("prev"))
        if parsed is None:
            continue
        _, event = parsed
        if event == "failed":
            _add_issue(
                issues,
                sample_id,
                "failure_strategy.disabled_failed_edge",
                "ROBOT_CTRL failed edges require enabled failure_strategy_rules.",
                "target_topology.stages",
            )


def _validate_failure_branches(
    records: list[dict[str, Any]],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    components = config.components
    records_by_id = {
        record["id"]: record
        for record in records
        if isinstance(record.get("id"), str)
    }
    main_ids = {
        record["id"]
        for record in _main_robot_records(records)
        if isinstance(record.get("id"), str)
    }
    policies = _failure_policies_by_name(config.params_space)

    for record in records:
        parsed = _parse_prev(record.get("prev"))
        if parsed is None:
            continue
        trigger_id, event = parsed
        if event != "failed":
            continue

        branch = _success_branch_records(record, records_by_id)
        branch_ids = {
            branch_record["id"]
            for branch_record in branch
            if isinstance(branch_record.get("id"), str)
        }
        if branch_ids & main_ids:
            _add_issue(
                issues,
                sample_id,
                "failure_branch.merge_not_supported",
                "Failure branches must not merge back into the main chain.",
                "target_topology.stages",
            )

        if not _branch_has_safe_terminal(branch, components):
            _add_issue(
                issues,
                sample_id,
                "failure_branch.missing_safe_terminal",
                "Failure branch must end in a safe terminal role such as flight.land.",
                "target_topology.stages",
            )

        trigger = records_by_id.get(trigger_id)
        if trigger and not _branch_matches_failure_policy(trigger, branch, components, policies):
            _add_issue(
                issues,
                sample_id,
                "failure_branch.policy_mismatch",
                "Failure branch does not match any configured failure strategy policy.",
                "target_topology.stages",
            )


def _parse_prev(prev: Any) -> tuple[str, str] | None:
    if not isinstance(prev, str):
        return None
    parts = prev.split(".")
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _path_guard(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
    cache: dict[str, frozenset[tuple[str, str]]],
) -> frozenset[tuple[str, str]]:
    record_id = record.get("id")
    if not isinstance(record_id, str):
        return frozenset()
    if record_id in cache:
        return cache[record_id]

    parsed = _parse_prev(record.get("prev"))
    if parsed is None:
        guard = frozenset()
    else:
        prev_id, event = parsed
        previous = records_by_id.get(prev_id)
        previous_guard = (
            _path_guard(previous, records_by_id, cache)
            if previous is not None
            else frozenset()
        )
        guard = previous_guard | frozenset({(prev_id, event)})

    cache[record_id] = guard
    return guard


def _guards_mutually_exclusive(
    left: frozenset[tuple[str, str]],
    right: frozenset[tuple[str, str]],
) -> bool:
    for left_source, left_event in left:
        for right_source, right_event in right:
            if left_source == right_source and left_event != right_event:
                return True
    return False


def _success_branch_records(
    start: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records = list(records_by_id.values())
    branch: list[dict[str, Any]] = []
    current = start
    seen: set[str] = set()

    while isinstance(current.get("id"), str) and current["id"] not in seen:
        branch.append(current)
        seen.add(current["id"])
        successors = [
            record
            for record in records
            if _parse_prev(record.get("prev")) == (current["id"], "success")
        ]
        if len(successors) != 1:
            break
        current = sorted(successors, key=lambda item: item.get("stage", 0))[0]

    return branch


def _branch_has_safe_terminal(
    branch: list[dict[str, Any]],
    components: dict[str, dict[str, Any]],
) -> bool:
    if not branch:
        return False
    role_sets = [
        set(component_roles(components.get(record.get("name"), {})))
        for record in branch
    ]
    if "flight.land" in role_sets[-1]:
        return True

    has_return = False
    for roles in role_sets:
        if "flight.return" in roles:
            has_return = True
        if has_return and "flight.land" in roles:
            return True
    return False


def _branch_matches_failure_policy(
    trigger: dict[str, Any],
    branch: list[dict[str, Any]],
    components: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, Any]],
) -> bool:
    trigger_roles = set(component_roles(components.get(trigger.get("name"), {})))
    branch_role_sets = [
        set(component_roles(components.get(record.get("name"), {})))
        for record in branch
    ]

    for policy in policies.values():
        trigger_policy_roles = set(_list_strings(policy.get("trigger_roles")))
        on_failed_roles = _list_strings(policy.get("on_failed"))
        if not trigger_roles & trigger_policy_roles:
            continue
        if len(on_failed_roles) != len(branch_role_sets):
            continue
        if all(role in branch_role_sets[index] for index, role in enumerate(on_failed_roles)):
            return True
    return False


def _failure_policies_by_name(params_space: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rules = params_space.get("failure_strategy_rules", {})
    if not isinstance(rules, dict):
        return {}
    policies = rules.get("policies", {})
    if not isinstance(policies, dict):
        return {}
    return {
        name: policy
        for name, policy in policies.items()
        if isinstance(name, str) and isinstance(policy, dict)
    }


def _validate_semantic_topology_alignment(
    semantic_input: dict[str, Any],
    topology_context: dict[str, Any],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    robot_ctrl_names = topology_context["main_robot_ctrl_names"]
    try:
        abstract_plan = build_abstract_plan(semantic_input, config)
    except PlanningError as exc:
        _add_issue(
            issues,
            sample_id,
            "alignment.plan_error",
            f"Cannot build abstract role plan: {exc}",
            "semantic_input",
        )
        return

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

    _validate_required_robot_roles_present(
        abstract_plan.robot_roles,
        robot_ctrl_names,
        config,
        issues,
        sample_id,
    )
    _validate_required_service_roles_present(
        abstract_plan.service_roles,
        topology_context["svr_names"],
        config,
        issues,
        sample_id,
    )
    _validate_topic_dependencies_satisfied(topology_context, config, issues, sample_id)
    _validate_unexpected_svr_roles(
        abstract_plan.service_roles,
        topology_context,
        config,
        issues,
        sample_id,
    )


def _validate_required_robot_roles_present(
    required_roles: tuple[PlannedRole, ...],
    robot_ctrl_names: list[str],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    expected_roles = [role.role for role in required_roles]
    if len(robot_ctrl_names) != len(expected_roles):
        _add_issue(
            issues,
            sample_id,
            "alignment.robot_role_chain_length_mismatch",
            f"ROBOT_CTRL role chain length mismatch. expected={len(expected_roles)}, actual={len(robot_ctrl_names)}",
            "target_topology.stages",
        )

    for index, expected_role in enumerate(expected_roles):
        if index >= len(robot_ctrl_names):
            _add_issue(
                issues,
                sample_id,
                "alignment.missing_robot_role",
                f"Missing required ROBOT_CTRL role: {expected_role}",
                "target_topology.stages",
            )
            continue

        component_name = robot_ctrl_names[index]
        component = config.components.get(component_name)
        actual_roles = component_roles(component or {})
        if expected_role not in actual_roles:
            _add_issue(
                issues,
                sample_id,
                "alignment.robot_role_mismatch",
                f"ROBOT_CTRL role mismatch at stage {index}. expected={expected_role}, actual_component={component_name}, actual_roles={list(actual_roles)}",
                f"target_topology.stages[{index}].component",
            )

    for index in range(len(expected_roles), len(robot_ctrl_names)):
        component_name = robot_ctrl_names[index]
        actual_roles = component_roles(config.components.get(component_name, {}))
        _add_issue(
            issues,
            sample_id,
            "alignment.unexpected_robot_role",
            f"Unexpected ROBOT_CTRL component at stage {index}: {component_name}, roles={list(actual_roles)}",
            f"target_topology.stages[{index}].component",
        )


def _validate_required_service_roles_present(
    required_roles: tuple[PlannedRole, ...],
    svr_names: list[str],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    service_role_to_components = _service_role_to_components(svr_names, config)
    for planned_role in required_roles:
        if planned_role.role in service_role_to_components:
            continue
        _add_issue(
            issues,
            sample_id,
            "alignment.missing_service_role",
            f"Missing required SVR service role: {planned_role.role}",
            "target_topology.stages",
        )


def _validate_topic_dependencies_satisfied(
    topology_context: dict[str, Any],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    components = config.components
    stage_by_component = topology_context["stage_by_component"]
    providers_by_topic = _providers_by_topic(topology_context["component_names"], config)

    for consumer_name in topology_context["component_names"]:
        consumer = components.get(consumer_name)
        if consumer is None:
            continue
        consumer_stage = stage_by_component.get(consumer_name)
        for topic in _required_consumed_topics(consumer):
            providers = providers_by_topic.get(topic, [])
            if not providers:
                _add_issue(
                    issues,
                    sample_id,
                    "alignment.missing_topic_provider",
                    f"Missing provider for topic {topic!r} consumed by {consumer_name}.",
                    "target_topology.stages",
                )
                continue

            if consumer_stage is None:
                continue
            provider_before_or_same_stage = any(
                stage_by_component.get(provider, consumer_stage + 1) <= consumer_stage
                for provider in providers
            )
            if not provider_before_or_same_stage:
                _add_issue(
                    issues,
                    sample_id,
                    "alignment.topic_provider_starts_late",
                    f"Provider for topic {topic!r} must start no later than consumer {consumer_name}.",
                    "target_topology.stages",
                )


def _validate_unexpected_svr_roles(
    required_roles: tuple[PlannedRole, ...],
    topology_context: dict[str, Any],
    config: GeneratorConfig,
    issues: list[ValidationIssue],
    sample_id: str | None,
) -> None:
    required_service_roles = {role.role for role in required_roles}
    required_topics = _required_topics(topology_context["component_names"], config)

    for service_name in topology_context["svr_names"]:
        component = config.components.get(service_name)
        if component is None:
            continue
        roles = set(component_roles(component))
        provided_topics = set(component_provides_topics(component))
        if roles & required_service_roles:
            continue
        if provided_topics & required_topics:
            continue
        _add_issue(
            issues,
            sample_id,
            "alignment.unexpected_svr_role",
            f"Unexpected SVR service for semantic input: {service_name}, roles={sorted(roles)}",
            "target_topology.stages",
        )


def _service_role_to_components(
    svr_names: list[str],
    config: GeneratorConfig,
) -> dict[str, list[str]]:
    role_to_components: dict[str, list[str]] = {}
    for service_name in svr_names:
        component = config.components.get(service_name)
        if component is None:
            continue
        for role in component_roles(component):
            role_to_components.setdefault(role, []).append(service_name)
    return role_to_components


def _providers_by_topic(
    component_names: list[str],
    config: GeneratorConfig,
) -> dict[str, list[str]]:
    providers: dict[str, list[str]] = {}
    for component_name in component_names:
        component = config.components.get(component_name)
        if component is None:
            continue
        for topic in component_provides_topics(component):
            providers.setdefault(topic, []).append(component_name)
    return providers


def _required_topics(
    component_names: list[str],
    config: GeneratorConfig,
) -> set[str]:
    topics: set[str] = set()
    for component_name in component_names:
        component = config.components.get(component_name)
        if component is None:
            continue
        topics.update(_required_consumed_topics(component))
    return topics


def _required_consumed_topics(component: dict[str, Any]) -> tuple[str, ...]:
    optional_topics = _optional_input_topics(component)
    return tuple(
        topic
        for topic in component_consumes_topics(component)
        if topic not in optional_topics
    )


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
        "main_robot_ctrl_names": [],
        "robot_ctrl_ids": [],
        "main_robot_ctrl_ids": [],
        "robot_action_records": [],
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


def _failure_strategy_enabled(config: GeneratorConfig) -> bool:
    rules = config.params_space.get("failure_strategy_rules", {})
    return isinstance(rules, dict) and bool(rules.get("enabled", False))


def _enabled_capabilities(semantic_input: dict[str, Any]) -> list[str]:
    return [
        capability
        for capability in semantic_input.get("capabilities", {})
        if _capability_enabled(semantic_input, capability)
    ]


def _list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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
