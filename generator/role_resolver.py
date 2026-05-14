"""Resolve abstract planner roles to concrete component ids."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from generator.component_index import ComponentIndex, build_component_index
from generator.planner import AbstractPlan, PlannedRole
from generator.template_generator import GeneratorConfig, load_configs


@dataclass(frozen=True)
class ResolvedRole:
    """One abstract role resolved to a concrete component."""

    role: str
    kind: str
    component: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedPlan:
    """A concrete component plan derived from an abstract role plan."""

    task_type: str
    route_mode: str
    payload: str
    robot_components: tuple[ResolvedRole, ...]
    service_components: tuple[ResolvedRole, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "route_mode": self.route_mode,
            "payload": self.payload,
            "robot_components": [role.to_dict() for role in self.robot_components],
            "service_components": [role.to_dict() for role in self.service_components],
            "metadata": self.metadata,
        }


class RoleResolutionError(ValueError):
    """Raised when an abstract role cannot be resolved to a component."""


def resolve_plan(
    plan: AbstractPlan,
    config: GeneratorConfig | None = None,
    component_index: ComponentIndex | None = None,
) -> ResolvedPlan:
    """Resolve all roles in an abstract plan to concrete component ids."""

    cfg = config or load_configs()
    index = component_index or build_component_index(cfg.component_library)
    robot_components = tuple(
        _resolve_planned_role(role, index) for role in plan.robot_roles
    )
    service_components = tuple(
        _resolve_planned_role(role, index) for role in plan.service_roles
    )
    return ResolvedPlan(
        task_type=plan.task_type,
        route_mode=plan.route_mode,
        payload=plan.payload,
        robot_components=robot_components,
        service_components=service_components,
        metadata={
            "resolver_version": "0.1.0",
            "abstract_planner_version": plan.metadata.get("planner_version"),
            "selection_policy": "highest_weight_then_component_order",
        },
    )


def resolve_robot_role_chain(
    plan: AbstractPlan,
    config: GeneratorConfig | None = None,
    component_index: ComponentIndex | None = None,
) -> list[str]:
    """Resolve only the ROBOT_CTRL role chain to component ids."""

    resolved = resolve_plan(plan, config=config, component_index=component_index)
    return [role.component for role in resolved.robot_components]


def resolve_service_roles(
    plan: AbstractPlan,
    config: GeneratorConfig | None = None,
    component_index: ComponentIndex | None = None,
) -> list[str]:
    """Resolve only service roles to component ids."""

    resolved = resolve_plan(plan, config=config, component_index=component_index)
    return [role.component for role in resolved.service_components]


def _resolve_planned_role(role: PlannedRole, index: ComponentIndex) -> ResolvedRole:
    candidates = index.components_for_role(
        role.role,
        component_type=role.kind,
        include_disabled=False,
        include_deferred=False,
    )
    if not candidates:
        raise RoleResolutionError(
            f"No active {role.kind} component provides role {role.role!r}."
        )

    component_id = _select_component(candidates, index)
    return ResolvedRole(
        role=role.role,
        kind=role.kind,
        component=component_id,
        source=role.source,
    )


def _select_component(candidates: tuple[str, ...], index: ComponentIndex) -> str:
    """Pick a candidate deterministically by weight, then library order."""

    best_component = candidates[0]
    best_weight = _component_weight(index.component(best_component))
    for component_id in candidates[1:]:
        weight = _component_weight(index.component(component_id))
        if weight > best_weight:
            best_component = component_id
            best_weight = weight
    return best_component


def _component_weight(component: dict[str, Any]) -> float:
    weight = component.get("selection_weight", 1.0)
    if isinstance(weight, bool) or not isinstance(weight, int | float):
        return 0.0
    return float(weight)
