"""Abstract role planner for single-UAV topology generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from generator.template_generator import GeneratorConfig, load_configs, sample_semantic_input


RoleKind = Literal["ROBOT_CTRL", "SVR"]

PREFLIGHT_ROLE = "flight.preflight"
TAKEOFF_ROLE = "flight.takeoff"
ALTITUDE_UP_ROLE = "flight.altitude_up"
ALTITUDE_DOWN_ROLE = "flight.altitude_down"
RETURN_ROLE = "flight.return"
LAND_ROLE = "flight.land"
OBSTACLE_AVOID_ROLE = "navigation.obstacle_avoid"
TARGET_TRACKING_ROLE = "tracking.target"

OBSERVATION_CAPABILITIES = (
    "image_capture",
    "thermal_scan",
    "object_detection",
    "target_tracking",
)
MEDIUM_HEIGHT_ASCEND_PROBABILITY = {
    "simple": 0.45,
    "medium": 0.70,
    "complex": 0.90,
}
HIGH_HEIGHT_DESCEND_PROBABILITY = {
    "simple": 0.45,
    "medium": 0.65,
    "complex": 0.85,
}
OBSERVATION_STABILIZATION_PROBABILITY = {
    "simple": 0.20,
    "medium": 0.45,
    "complex": 0.75,
}

POSITION_SERVICE_ROLES = ("service.position.gnss", "service.position.local_pose")
WAYPOINT_SERVICE_ROLES = ("service.route.waypoint_list",)
BATTERY_SERVICE_ROLES = ("service.battery.level", "service.battery.warning")

ROUTE_SERVICE_ROLES = {
    "navigation.point": POSITION_SERVICE_ROLES,
    "navigation.orbit": POSITION_SERVICE_ROLES,
    "navigation.obstacle_avoid": POSITION_SERVICE_ROLES,
    "navigation.path": WAYPOINT_SERVICE_ROLES,
    "navigation.line": WAYPOINT_SERVICE_ROLES,
    "navigation.area": WAYPOINT_SERVICE_ROLES,
    "navigation.line.corridor": WAYPOINT_SERVICE_ROLES,
    "navigation.area.perimeter": WAYPOINT_SERVICE_ROLES,
    "navigation.area.spiral": POSITION_SERVICE_ROLES,
    "navigation.area.expanding_square": POSITION_SERVICE_ROLES,
    "observation.orbit": POSITION_SERVICE_ROLES,
}

CAPABILITY_SERVICE_ROLES = {
    "image_capture": ("service.camera.visible",),
    "thermal_scan": ("service.camera.thermal",),
    "object_detection": ("service.camera.visible", "service.vision.detect"),
    "target_tracking": ("service.camera.visible", "service.vision.detect"),
    "radar_scan": ("service.radar.scan",),
    "obstacle_avoidance": ("service.radar.scan",),
}


@dataclass(frozen=True)
class PlannedRole:
    """One abstract role required by the semantic input."""

    role: str
    kind: RoleKind
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AbstractPlan:
    """Abstract plan before concrete component resolution."""

    task_type: str
    route_mode: str
    payload: str
    robot_roles: tuple[PlannedRole, ...]
    service_roles: tuple[PlannedRole, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "route_mode": self.route_mode,
            "payload": self.payload,
            "robot_roles": [role.to_dict() for role in self.robot_roles],
            "service_roles": [role.to_dict() for role in self.service_roles],
            "metadata": self.metadata,
        }


class PlanningError(ValueError):
    """Raised when semantic input cannot be planned into abstract roles."""


def build_abstract_plan(
    semantic_input: dict[str, Any],
    config: GeneratorConfig | None = None,
) -> AbstractPlan:
    """Build an abstract role plan from a semantic task description.

    This planner is intentionally not connected to the current generator yet.
    It mirrors the existing main-chain semantics at the role level so the
    role-driven refactor can be validated before replacing component-level
    generation.
    """

    cfg = config or load_configs()
    task_type = _required_string(semantic_input, "task_type")
    route_mode = _required_string(semantic_input, "route_mode")
    payload = _required_string(semantic_input, "payload")

    robot_roles: list[PlannedRole] = []
    service_roles: list[PlannedRole] = []

    _append_role(robot_roles, PREFLIGHT_ROLE, "ROBOT_CTRL", "base.preflight")
    _append_role(robot_roles, TAKEOFF_ROLE, "ROBOT_CTRL", "base.takeoff")

    for role in _height_entry_roles(semantic_input):
        _append_role(robot_roles, role, "ROBOT_CTRL", "flight.height_level")

    route_roles = _route_roles(semantic_input, cfg)
    for role in route_roles:
        _append_role(robot_roles, role, "ROBOT_CTRL", f"route_mode.{route_mode}")

    if _should_add_observation_stabilization(semantic_input, robot_roles):
        _append_role(
            robot_roles,
            "observation.hover",
            "ROBOT_CTRL",
            "variant.observation_stabilization",
        )

    if _capability_enabled(semantic_input, "target_tracking"):
        _append_role(
            robot_roles,
            TARGET_TRACKING_ROLE,
            "ROBOT_CTRL",
            "capability.target_tracking",
        )

    for role in _height_exit_roles(semantic_input):
        _append_role(robot_roles, role, "ROBOT_CTRL", "flight.height_level")

    if semantic_input.get("flight", {}).get("return_home", True):
        _append_role(robot_roles, RETURN_ROLE, "ROBOT_CTRL", "mission_tail.return_home")
    _append_role(robot_roles, LAND_ROLE, "ROBOT_CTRL", "mission_tail.land")

    for role in _safety_service_roles(semantic_input):
        _append_unique_role(service_roles, role, "SVR", "safety")
    for role in _route_service_roles(route_roles):
        _append_unique_role(service_roles, role, "SVR", "route_support")
    for role in _capability_service_roles(semantic_input):
        _append_unique_role(service_roles, role, "SVR", "capability")

    return AbstractPlan(
        task_type=task_type,
        route_mode=route_mode,
        payload=payload,
        robot_roles=tuple(robot_roles),
        service_roles=tuple(service_roles),
        metadata={
            "planner_version": "0.2.0",
            "contains_component_ids": False,
            "component_resolution": "deferred",
            "legacy_generator_replaced": False,
            "uses_default_diversity_variants": True,
        },
    )


def build_abstract_plans(
    semantic_inputs: list[dict[str, Any]],
    config: GeneratorConfig | None = None,
) -> list[AbstractPlan]:
    """Build abstract plans for a list of semantic task descriptions."""

    cfg = config or load_configs()
    return [build_abstract_plan(semantic_input, cfg) for semantic_input in semantic_inputs]


def _route_roles(semantic_input: dict[str, Any], config: GeneratorConfig) -> list[str]:
    route_mode = _required_string(semantic_input, "route_mode")
    route_rule = config.params_space.get("route_to_roles", {}).get(route_mode)
    if route_rule is None:
        raise PlanningError(f"Missing route_to_roles rule for route_mode: {route_mode}")

    roles = list(route_rule.get("sequence", []))
    if not all(isinstance(role, str) for role in roles):
        raise PlanningError(f"route_to_roles.{route_mode}.sequence must be strings.")

    if _capability_enabled(semantic_input, "obstacle_avoidance"):
        roles = _replace_primary_navigation_role(roles)
    return roles


def _replace_primary_navigation_role(route_roles: list[str]) -> list[str]:
    replaced = False
    output: list[str] = []
    for role in route_roles:
        if role.startswith("navigation.") and not replaced:
            output.append(OBSTACLE_AVOID_ROLE)
            replaced = True
        else:
            output.append(role)
    if not replaced:
        output.append(OBSTACLE_AVOID_ROLE)
    return output


def _height_entry_roles(semantic_input: dict[str, Any]) -> list[str]:
    height_level = semantic_input.get("flight", {}).get("height_level")
    if height_level == "high":
        return [ALTITUDE_UP_ROLE]
    if height_level == "medium" and _stable_probability_enabled(
        semantic_input,
        "height.medium.ascend",
        MEDIUM_HEIGHT_ASCEND_PROBABILITY,
    ):
        return [ALTITUDE_UP_ROLE]
    return []


def _height_exit_roles(semantic_input: dict[str, Any]) -> list[str]:
    height_level = semantic_input.get("flight", {}).get("height_level")
    if height_level == "high" and _stable_probability_enabled(
        semantic_input,
        "height.high.descend",
        HIGH_HEIGHT_DESCEND_PROBABILITY,
    ):
        return [ALTITUDE_DOWN_ROLE]
    return []


def _should_add_observation_stabilization(
    semantic_input: dict[str, Any],
    robot_roles: list[PlannedRole],
) -> bool:
    if any(
        role.role in {"observation.hover", "observation.orbit"}
        for role in robot_roles
    ):
        return False
    if not any(
        _capability_enabled(semantic_input, capability)
        for capability in OBSERVATION_CAPABILITIES
    ):
        return False
    return _stable_probability_enabled(
        semantic_input,
        "observation.stabilization_hover",
        OBSERVATION_STABILIZATION_PROBABILITY,
    )


def _safety_service_roles(semantic_input: dict[str, Any]) -> tuple[str, ...]:
    if semantic_input.get("safety", {}).get("battery_monitor", False):
        return BATTERY_SERVICE_ROLES
    return ()


def _route_service_roles(route_roles: list[str]) -> tuple[str, ...]:
    service_roles: list[str] = []
    for role in route_roles:
        for service_role in ROUTE_SERVICE_ROLES.get(role, ()):
            if service_role not in service_roles:
                service_roles.append(service_role)
    return tuple(service_roles)


def _capability_service_roles(semantic_input: dict[str, Any]) -> tuple[str, ...]:
    service_roles: list[str] = []
    for capability, roles in CAPABILITY_SERVICE_ROLES.items():
        if not _capability_enabled(semantic_input, capability):
            continue
        for role in roles:
            if role not in service_roles:
                service_roles.append(role)
    return tuple(service_roles)


def _append_role(
    target: list[PlannedRole],
    role: str,
    kind: RoleKind,
    source: str,
) -> None:
    target.append(PlannedRole(role=role, kind=kind, source=source))


def _append_unique_role(
    target: list[PlannedRole],
    role: str,
    kind: RoleKind,
    source: str,
) -> None:
    if any(existing.role == role for existing in target):
        return
    target.append(PlannedRole(role=role, kind=kind, source=source))


def _required_string(values: dict[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value:
        raise PlanningError(f"semantic_input.{field} must be a non-empty string.")
    return value


def _capability_enabled(semantic_input: dict[str, Any], capability: str) -> bool:
    value = semantic_input.get("capabilities", {}).get(capability, False)
    if isinstance(value, dict):
        return bool(value.get("enabled", False))
    return bool(value)


def _stable_probability_enabled(
    semantic_input: dict[str, Any],
    scope: str,
    probabilities: dict[str, float],
) -> bool:
    complexity = _complexity(semantic_input)
    threshold = probabilities.get(complexity, probabilities.get("medium", 0.0))
    return _stable_unit_interval({"semantic": semantic_input, "scope": scope}) < threshold


def _complexity(semantic_input: dict[str, Any]) -> str:
    value = semantic_input.get("complexity", "medium")
    return value if isinstance(value, str) else "medium"


def _stable_unit_interval(value: Any) -> float:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build abstract role plans.")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cfg = load_configs(args.config_dir)
    rng = random.Random(args.seed)
    plans = [
        build_abstract_plan(sample_semantic_input(rng, cfg), cfg).to_dict()
        for _ in range(args.count)
    ]
    print(json.dumps(plans, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
