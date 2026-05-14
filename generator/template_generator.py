"""Rule-based template generator for topology-only UAV samples.

The generator turns one preallocated single-UAV semantic task description into a
compact staged component topology. The output intentionally contains no
component parameters and no runtime UUIDs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GENERATOR_VERSION = "0.1.0"


@dataclass(frozen=True)
class GeneratorConfig:
    """Loaded configuration needed by the template generator."""

    component_library: dict[str, Any]
    params_space: dict[str, Any]
    task_types: dict[str, Any]
    task_templates: dict[str, Any]

    @property
    def components(self) -> dict[str, dict[str, Any]]:
        return {
            component["id"]: component
            for component in self.component_library["components"]
        }

    @property
    def task_profiles(self) -> dict[str, dict[str, Any]]:
        return self.params_space["task_profiles"]


@dataclass(frozen=True)
class StageDraft:
    """A control stage before local component ids are assigned."""

    robot_ctrl: str
    svr_services: tuple[str, ...] = ()


class TemplateGenerationError(ValueError):
    """Raised when semantic input cannot be converted into a valid topology."""


def load_configs(config_dir: Path | str = "config") -> GeneratorConfig:
    """Load JSON configs and Python template rules from the config directory."""

    config_path = _resolve_config_dir(config_dir)
    component_library = _read_json(config_path / "component_library.json")
    params_space = _read_json(config_path / "params_space.json")
    task_types = _read_json(config_path / "task_types.json")
    task_templates = _load_task_templates(config_path / "task_templates.py")
    return GeneratorConfig(
        component_library=component_library,
        params_space=params_space,
        task_types=task_types,
        task_templates=task_templates,
    )


def generate_sample(
    semantic_input: dict[str, Any],
    config: GeneratorConfig | None = None,
) -> dict[str, Any]:
    """Generate one topology-only training sample from a semantic task."""

    cfg = config or load_configs()
    normalized_input = _normalize_semantic_input(semantic_input)
    _validate_semantic_input(normalized_input, cfg)

    control_graph = build_control_graph(normalized_input, cfg)
    robot_ctrl_chain = _main_robot_ctrl_chain(control_graph)
    required_svr = resolve_required_svr(normalized_input, robot_ctrl_chain, cfg)
    stage_drafts = attach_svr_services(
        robot_ctrl_chain,
        required_svr,
        normalized_input,
        cfg,
    )
    target_topology = build_topology_from_control_graph(control_graph, stage_drafts)

    sample = {
        "sample_id": _sample_id(normalized_input, target_topology),
        "semantic_input": normalized_input,
        "target_topology": target_topology,
        "metadata": {
            "generator_version": GENERATOR_VERSION,
            "template_id": normalized_input["task_type"],
            "route_mode": normalized_input["route_mode"],
            "payload": normalized_input["payload"],
            "failure_strategy": _failure_strategy_metadata(control_graph),
        },
    }
    assert_generation_invariants(sample, cfg)
    return sample


def generate_samples(
    count: int,
    seed: int | None = None,
    config: GeneratorConfig | None = None,
) -> list[dict[str, Any]]:
    """Generate a deterministic batch of valid topology-only samples."""

    cfg = config or load_configs()
    random_seed = (
        cfg.params_space.get("sampling", {}).get("default_random_seed", 42)
        if seed is None
        else seed
    )
    rng = random.Random(random_seed)
    samples: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    attempts = 0
    max_attempts = max(count * 10, 20)
    while len(samples) < count and attempts < max_attempts:
        attempts += 1
        semantic_input = sample_semantic_input(rng, cfg)
        sample = generate_sample(semantic_input, cfg)
        if sample["sample_id"] in seen_ids:
            continue
        samples.append(sample)
        seen_ids.add(sample["sample_id"])

    if len(samples) < count:
        raise TemplateGenerationError(
            f"Only generated {len(samples)} unique samples after {attempts} attempts."
        )
    return samples


def sample_semantic_input(
    rng: random.Random,
    config: GeneratorConfig | None = None,
) -> dict[str, Any]:
    """Sample one valid semantic task description from params_space."""

    cfg = config or load_configs()
    params = cfg.params_space["semantic_params"]
    task_type = rng.choice(params["task_type"])
    profile = cfg.task_profiles[task_type]
    target_type = profile["target_types"][0]
    assigned_area = _sample_assigned_target(rng, cfg, target_type)
    payload = rng.choice(profile["payloads"])
    capabilities = _sample_capabilities(rng, cfg, payload)

    return {
        "uav_id": rng.choice(params["uav_id"]),
        "task_type": task_type,
        "role": rng.choice(profile["roles"]),
        "assigned_area": assigned_area,
        "route_mode": rng.choice(profile["route_modes"]),
        "payload": payload,
        "complexity": rng.choice(params.get("complexity", ["medium"])),
        "flight": {
            "height_level": rng.choice(cfg.params_space["flight"]["height_level"]),
            "speed_level": rng.choice(cfg.params_space["flight"]["speed_level"]),
            "hover_required": task_type == "single_uav_fixed_point_observation",
            "return_home": True,
        },
        "capabilities": capabilities,
        "safety": {
            "preflight_check": True,
            "battery_monitor": True,
            "battery_risk_level": rng.choice(
                cfg.params_space["safety"]["battery_risk_level"]
            ),
            "gps_required": True,
        },
    }


def build_robot_ctrl_chain(
    semantic_input: dict[str, Any],
    config: GeneratorConfig | None = None,
) -> list[str]:
    """Build the flight-control backbone through abstract role planning."""

    return _main_robot_ctrl_chain(build_control_graph(semantic_input, config))


def build_control_graph(
    semantic_input: dict[str, Any],
    config: GeneratorConfig | None = None,
) -> Any:
    """Build the resolved ROBOT_CTRL control graph for one task."""

    cfg = config or load_configs()
    from generator.component_index import build_component_index
    from generator.control_graph import build_main_control_graph
    from generator.failure_strategy import apply_failure_strategies
    from generator.planner import build_abstract_plan
    from generator.role_resolver import resolve_plan

    component_index = build_component_index(cfg.component_library)
    abstract_plan = build_abstract_plan(semantic_input, cfg)
    resolved_plan = resolve_plan(abstract_plan, cfg, component_index)
    control_graph = build_main_control_graph(list(resolved_plan.robot_components))
    return apply_failure_strategies(control_graph, semantic_input, cfg, component_index)


def resolve_required_svr(
    semantic_input: dict[str, Any],
    robot_ctrl_chain: list[str],
    config: GeneratorConfig | None = None,
) -> list[str]:
    """Resolve all SVR service nodes through service roles and topics."""

    cfg = config or load_configs()
    from generator.service_resolver import resolve_required_services

    return resolve_required_services(semantic_input, robot_ctrl_chain, cfg)


def attach_svr_services(
    robot_ctrl_chain: list[str],
    required_svr: list[str],
    semantic_input: dict[str, Any],
    config: GeneratorConfig | None = None,
) -> list[StageDraft]:
    """Attach each SVR service through resolved service placement."""

    cfg = config or load_configs()
    from generator.service_resolver import resolve_service_plan

    service_plan = resolve_service_plan(semantic_input, robot_ctrl_chain, cfg)
    if list(service_plan.required_services) != required_svr:
        raise TemplateGenerationError("Resolved SVR services changed between planning steps.")

    return [
        StageDraft(robot_ctrl=robot_ctrl, svr_services=service_plan.stage_services[index])
        for index, robot_ctrl in enumerate(robot_ctrl_chain)
    ]


def build_topology(stage_drafts: list[StageDraft]) -> dict[str, Any]:
    """Assign local ids and build the staged component-action topology."""

    stages: list[dict[str, Any]] = []
    previous_robot_id: str | None = None
    next_id = 0

    for stage_index, draft in enumerate(stage_drafts):
        prev = None if previous_robot_id is None else f"{previous_robot_id}.success"

        robot_id = f"c{next_id}"
        next_id += 1
        component_actions = [make_action(robot_id, draft.robot_ctrl, prev)]

        for service in draft.svr_services:
            service_id = f"c{next_id}"
            next_id += 1
            component_actions.append(make_action(service_id, service, prev))

        stages.append({"stage": stage_index, "component": component_actions})
        previous_robot_id = robot_id

    return {"stages": stages}


def build_topology_from_control_graph(
    control_graph: Any,
    stage_drafts: list[StageDraft],
) -> dict[str, Any]:
    """Assign local ids and build topology from a guarded control graph."""

    stages: list[dict[str, Any]] = []
    next_id = 0
    id_by_node_key: dict[str, str] = {}
    edge_by_target = {
        edge.target: edge
        for edge in control_graph.edges
    }
    nodes_by_stage = control_graph.nodes_by_stage()
    max_stage = max(nodes_by_stage) if nodes_by_stage else -1

    for stage_index in range(max_stage + 1):
        component_actions: list[dict[str, Any]] = []
        stage_nodes = list(nodes_by_stage.get(stage_index, ()))
        main_prev: str | None = None

        for node in stage_nodes:
            edge = edge_by_target.get(node.key)
            prev = None
            if edge is not None:
                prev = f"{id_by_node_key[edge.source]}.{edge.event}"
            robot_id = f"c{next_id}"
            next_id += 1
            id_by_node_key[node.key] = robot_id
            component_actions.append(make_action(robot_id, node.component, prev))
            if node.branch_kind == "main":
                main_prev = prev

        if main_prev is None and component_actions:
            main_prev = component_actions[0]["prev"]

        if stage_index < len(stage_drafts):
            for service in stage_drafts[stage_index].svr_services:
                service_id = f"c{next_id}"
                next_id += 1
                component_actions.append(make_action(service_id, service, main_prev))

        if component_actions:
            stages.append({"stage": stage_index, "component": component_actions})

    return {"stages": stages}


def _main_robot_ctrl_chain(control_graph: Any) -> list[str]:
    return [
        control_graph.node(key).component
        for key in control_graph.main_node_keys
    ]


def _failure_strategy_metadata(control_graph: Any) -> dict[str, Any]:
    return {
        "enabled": bool(control_graph.metadata.get("failure_strategy_enabled", False)),
        "branch_count": int(control_graph.metadata.get("failure_branch_count", 0)),
        "policies": list(control_graph.metadata.get("failure_policies", [])),
    }


def make_action(component_id: str, name: str, prev: str | None) -> dict[str, Any]:
    """Create a compact component action."""

    return {
        "id": component_id,
        "name": name,
        "cmd": "start",
        "prev": prev,
    }


def assert_generation_invariants(
    sample: dict[str, Any],
    config: GeneratorConfig | None = None,
) -> None:
    """Lightweight generator-side consistency checks."""

    cfg = config or load_configs()
    components = cfg.components
    topology = sample["target_topology"]
    seen_ids: set[str] = set()
    seen_names_by_id: dict[str, str] = {}
    seen_svr_names: set[str] = set()
    robot_ids: set[str] = set()
    prev_pattern = "{id}.{event}"
    failure_enabled = _failure_strategy_enabled(cfg)

    for expected_stage, stage in enumerate(topology.get("stages", [])):
        if stage.get("stage") != expected_stage:
            raise TemplateGenerationError("Stage indexes must be continuous from 0.")

        robot_start_count = 0
        for action in stage.get("component", []):
            component_name = action.get("name")
            if component_name not in components:
                raise TemplateGenerationError(f"Unknown component: {component_name}")
            if action.get("cmd") != "start":
                raise TemplateGenerationError("First-version templates emit start only.")

            component_type = components[component_name]["type"]
            if component_type == "ROBOT_CTRL":
                robot_start_count += 1
                robot_ids.add(action["id"])
            else:
                if component_name in seen_svr_names:
                    raise TemplateGenerationError(
                        f"SVR service appears more than once: {component_name}"
                    )
                seen_svr_names.add(component_name)

            prev = action.get("prev")
            if prev is not None:
                if not isinstance(prev, str):
                    raise TemplateGenerationError("prev must be null or a string.")
                try:
                    prev_id, event = prev.split(".", 1)
                except ValueError as exc:
                    raise TemplateGenerationError(
                        f"prev must match {prev_pattern}: {prev}"
                    ) from exc
                if event not in {"success", "failed"}:
                    raise TemplateGenerationError(f"Invalid prev event: {prev}")
                if prev_id not in seen_ids:
                    raise TemplateGenerationError(f"prev references unknown id: {prev}")
                prev_name = seen_names_by_id[prev_id]
                if components[prev_name]["type"] != "ROBOT_CTRL":
                    raise TemplateGenerationError(f"prev references SVR: {prev}")

            seen_ids.add(action["id"])
            seen_names_by_id[action["id"]] = component_name

        if not failure_enabled and robot_start_count != 1:
            raise TemplateGenerationError(
                f"Stage {stage.get('stage')} has {robot_start_count} ROBOT_CTRL starts."
            )
        if failure_enabled and robot_start_count < 1:
            raise TemplateGenerationError(
                f"Stage {stage.get('stage')} has no ROBOT_CTRL starts."
            )

    if not topology.get("stages"):
        raise TemplateGenerationError("Generated topology has no stages.")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_config_dir(config_dir: Path | str) -> Path:
    path = Path(config_dir)
    if path.is_absolute() or path.exists():
        return path
    return Path(__file__).resolve().parents[1] / path


def _load_task_templates(path: Path) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("task_templates_config", path)
    if spec is None or spec.loader is None:
        raise TemplateGenerationError(f"Cannot load task template config: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "TASK_TEMPLATES": module.TASK_TEMPLATES,
        "SVR_GROUPS": module.SVR_GROUPS,
        "ROUTE_MODE_RULES": module.ROUTE_MODE_RULES,
        "CAPABILITY_RULES": module.CAPABILITY_RULES,
        "MOTION_VARIANT_RULES": module.MOTION_VARIANT_RULES,
        "SVR_SERVICE_RULES": module.SVR_SERVICE_RULES,
        "TOPOLOGY_ASSEMBLY_RULES": module.TOPOLOGY_ASSEMBLY_RULES,
    }


def _normalize_semantic_input(semantic_input: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(semantic_input, ensure_ascii=False))
    normalized.setdefault("flight", {})
    normalized.setdefault("capabilities", {})
    normalized.setdefault("safety", {})
    return normalized


def _validate_semantic_input(
    semantic_input: dict[str, Any],
    config: GeneratorConfig,
) -> None:
    required_fields = set(
        config.task_types["semantic_input_contract"]["required_fields"]
    )
    missing = required_fields - set(semantic_input)
    if missing:
        raise TemplateGenerationError(f"Missing semantic fields: {sorted(missing)}")

    task_type = semantic_input["task_type"]
    if task_type not in config.task_profiles:
        raise TemplateGenerationError(f"Unsupported task_type: {task_type}")

    profile = config.task_profiles[task_type]
    route_mode = semantic_input["route_mode"]
    if route_mode not in profile["route_modes"]:
        raise TemplateGenerationError(
            f"route_mode {route_mode} is not allowed for {task_type}"
        )

    target = config.params_space["assigned_targets"].get(semantic_input["assigned_area"])
    if target is None:
        raise TemplateGenerationError(
            f"Unknown assigned_area: {semantic_input['assigned_area']}"
        )
    if target["type"] not in profile["target_types"]:
        raise TemplateGenerationError(
            f"assigned_area type {target['type']} is not allowed for {task_type}"
        )

    payload = semantic_input["payload"]
    payload_rule = config.params_space["payloads"].get(payload)
    if payload_rule is None:
        raise TemplateGenerationError(f"Unsupported payload: {payload}")

    supported_capabilities = set(payload_rule["supports"])
    for capability in _enabled_capabilities(semantic_input):
        if capability not in supported_capabilities:
            raise TemplateGenerationError(
                f"Capability {capability} is not supported by payload {payload}"
            )

    if _capability_enabled(semantic_input, "target_tracking") and not _capability_enabled(
        semantic_input, "object_detection"
    ):
        raise TemplateGenerationError("target_tracking requires object_detection")


def _enabled_capabilities(semantic_input: dict[str, Any]) -> list[str]:
    return [
        capability
        for capability in semantic_input.get("capabilities", {})
        if _capability_enabled(semantic_input, capability)
    ]


def _capability_enabled(semantic_input: dict[str, Any], capability: str) -> bool:
    value = semantic_input.get("capabilities", {}).get(capability, False)
    if isinstance(value, dict):
        return bool(value.get("enabled", False))
    return bool(value)


def _failure_strategy_enabled(config: GeneratorConfig) -> bool:
    rules = config.params_space.get("failure_strategy_rules", {})
    return isinstance(rules, dict) and bool(rules.get("enabled", False))


def _sample_assigned_target(
    rng: random.Random,
    config: GeneratorConfig,
    target_type: str,
) -> str:
    candidates = [
        target_id
        for target_id, target in config.params_space["assigned_targets"].items()
        if target["type"] == target_type
    ]
    return rng.choice(candidates)


def _sample_capabilities(
    rng: random.Random,
    config: GeneratorConfig,
    payload: str,
) -> dict[str, dict[str, Any]]:
    capability_defs = config.params_space["capabilities"]
    supported = set(config.params_space["payloads"][payload]["supports"])
    capabilities: dict[str, dict[str, Any]] = {}

    for capability in capability_defs:
        capabilities[capability] = {"enabled": False}

    if payload == "visible_camera":
        mode = rng.choice(["capture", "detect", "track"])
        target_class = rng.choice(capability_defs["target_tracking"]["target_class"])
        capabilities["image_capture"] = {
            "enabled": mode == "capture",
            "capture_mode": rng.choice(capability_defs["image_capture"]["capture_mode"]),
        }
        capabilities["object_detection"] = {
            "enabled": mode in {"detect", "track"},
            "target_classes": [target_class],
            "confidence_level": rng.choice(
                capability_defs["object_detection"]["confidence_level"]
            ),
        }
        capabilities["target_tracking"] = {
            "enabled": mode == "track",
            "target_class": target_class,
            "tracking_priority": rng.choice(
                capability_defs["target_tracking"]["tracking_priority"]
            ),
        }
    elif payload == "infrared_camera":
        capabilities["thermal_scan"] = {
            "enabled": True,
            "scan_mode": rng.choice(capability_defs["thermal_scan"]["scan_mode"]),
            "target_temperature_hint": rng.choice(
                capability_defs["thermal_scan"]["target_temperature_hint"]
            ),
        }
    elif payload == "radar":
        radar_mode = rng.choice(["scan", "scan", "avoid"])
        capabilities["radar_scan"] = {
            "enabled": True,
            "scan_mode": rng.choice(capability_defs["radar_scan"]["scan_mode"]),
            "detection_range_level": rng.choice(
                capability_defs["radar_scan"]["detection_range_level"]
            ),
        }
        capabilities["obstacle_avoidance"] = {
            "enabled": radar_mode == "avoid",
            "obstacle_level": rng.choice(
                capability_defs["obstacle_avoidance"]["obstacle_level"]
            ) if radar_mode == "avoid" else None,
        }

    for capability in list(capabilities):
        if capability not in supported:
            capabilities[capability] = {"enabled": False}
    return capabilities


def _sample_id(
    semantic_input: dict[str, Any],
    target_topology: dict[str, Any],
) -> str:
    payload = json.dumps(
        {"semantic_input": semantic_input, "target_topology": target_topology},
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"sample_{digest}"
