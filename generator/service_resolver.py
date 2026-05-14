"""Resolve SVR service dependencies and stage placement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from generator.component_index import (
    ComponentIndex,
    build_component_index,
    component_consumes_topics,
    component_provides_topics,
    component_roles,
)
from generator.planner import build_abstract_plan
from generator.role_resolver import ResolvedRole, resolve_plan
from generator.template_generator import GeneratorConfig, load_configs


GLOBAL_SERVICE_ROLES = {
    "service.battery.level",
    "service.battery.warning",
}

SERVICE_STAGE_ROLE_PRIORITIES = {
    "service.position.gnss": ("navigation.point", "navigation.obstacle_avoid"),
    "service.position.local_pose": ("navigation.point", "navigation.obstacle_avoid"),
    "service.route.waypoint_list": (
        "navigation.path",
        "navigation.line",
        "navigation.area",
    ),
    "service.camera.visible": (
        "observation.hover",
        "navigation.path",
        "navigation.line",
        "navigation.area",
        "navigation.point",
        "navigation.obstacle_avoid",
        "tracking.target",
    ),
    "service.vision.detect": (
        "observation.hover",
        "navigation.path",
        "navigation.line",
        "navigation.area",
        "navigation.point",
        "navigation.obstacle_avoid",
        "tracking.target",
    ),
    "service.camera.thermal": (
        "observation.hover",
        "navigation.path",
        "navigation.line",
        "navigation.area",
        "navigation.point",
        "navigation.obstacle_avoid",
    ),
    "service.radar.scan": ("navigation.obstacle_avoid",),
}


@dataclass(frozen=True)
class ServicePlacement:
    """One resolved service component and the stage where it should start."""

    role: str
    component: str
    stage_index: int
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedServicePlan:
    """SVR services resolved from semantic roles and topic dependencies."""

    required_services: tuple[str, ...]
    placements: tuple[ServicePlacement, ...]
    stage_services: tuple[tuple[str, ...], ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_services": list(self.required_services),
            "placements": [placement.to_dict() for placement in self.placements],
            "stage_services": [list(services) for services in self.stage_services],
            "metadata": self.metadata,
        }


class ServiceResolutionError(ValueError):
    """Raised when service dependencies cannot be resolved."""


def resolve_service_plan(
    semantic_input: dict[str, Any],
    robot_ctrl_chain: list[str],
    config: GeneratorConfig | None = None,
    component_index: ComponentIndex | None = None,
) -> ResolvedServicePlan:
    """Resolve required SVR services and stage placement for a task."""

    cfg = config or load_configs()
    index = component_index or build_component_index(cfg.component_library)
    abstract_plan = build_abstract_plan(semantic_input, cfg)
    resolved_plan = resolve_plan(abstract_plan, cfg, index)
    resolved_robot_chain = tuple(
        role.component for role in resolved_plan.robot_components
    )
    if tuple(robot_ctrl_chain) != resolved_robot_chain:
        raise ServiceResolutionError(
            "robot_ctrl_chain does not match the semantic plan resolution."
        )

    robot_roles = tuple(role.role for role in resolved_plan.robot_components)
    resolved_services = _extend_with_topic_dependencies(
        tuple(resolved_plan.robot_components),
        list(resolved_plan.service_components),
        index,
    )

    placements: list[ServicePlacement] = []
    stage_services: list[list[str]] = [[] for _ in robot_ctrl_chain]
    for service in resolved_services:
        stage_index = _service_stage_index(
            service,
            robot_roles,
            robot_ctrl_chain,
            index,
        )
        placement = ServicePlacement(
            role=service.role,
            component=service.component,
            stage_index=stage_index,
            source=service.source,
        )
        placements.append(placement)
        if service.component not in stage_services[stage_index]:
            stage_services[stage_index].append(service.component)

    return ResolvedServicePlan(
        required_services=tuple(service.component for service in resolved_services),
        placements=tuple(placements),
        stage_services=tuple(tuple(services) for services in stage_services),
        metadata={
            "service_resolver_version": "0.1.0",
            "uses_service_roles": True,
            "uses_topic_dependencies": True,
            "legacy_component_name_rules_replaced": True,
        },
    )


def resolve_required_services(
    semantic_input: dict[str, Any],
    robot_ctrl_chain: list[str],
    config: GeneratorConfig | None = None,
    component_index: ComponentIndex | None = None,
) -> list[str]:
    """Return required SVR component ids in deterministic start order."""

    plan = resolve_service_plan(
        semantic_input,
        robot_ctrl_chain,
        config=config,
        component_index=component_index,
    )
    return list(plan.required_services)


def resolve_stage_services(
    semantic_input: dict[str, Any],
    robot_ctrl_chain: list[str],
    config: GeneratorConfig | None = None,
    component_index: ComponentIndex | None = None,
) -> list[tuple[str, ...]]:
    """Return per-stage SVR component ids."""

    plan = resolve_service_plan(
        semantic_input,
        robot_ctrl_chain,
        config=config,
        component_index=component_index,
    )
    return list(plan.stage_services)


def _extend_with_topic_dependencies(
    robot_components: tuple[ResolvedRole, ...],
    service_components: list[ResolvedRole],
    index: ComponentIndex,
) -> tuple[ResolvedRole, ...]:
    resolved_services = list(service_components)
    known_service_components = {service.component for service in resolved_services}
    cursor = 0

    while cursor < len(robot_components) + len(resolved_services):
        all_components = [*robot_components, *resolved_services]
        current = all_components[cursor]
        cursor += 1
        component = index.component(current.component)
        required_topics = _required_consumed_topics(component)
        for topic in required_topics:
            provider = _select_topic_provider(topic, index)
            if provider is None or provider in known_service_components:
                continue
            provider_component = index.component(provider)
            provider_role = _primary_role(provider_component)
            resolved_services.append(
                ResolvedRole(
                    role=provider_role,
                    kind="SVR",
                    component=provider,
                    source=f"topic_dependency.{topic}",
                )
            )
            known_service_components.add(provider)

    return tuple(resolved_services)


def _service_stage_index(
    service: ResolvedRole,
    robot_roles: tuple[str, ...],
    robot_ctrl_chain: list[str],
    index: ComponentIndex,
) -> int:
    if service.role in GLOBAL_SERVICE_ROLES:
        return 0

    role_stage = _first_role_stage(
        SERVICE_STAGE_ROLE_PRIORITIES.get(service.role, ()),
        robot_roles,
    )
    if role_stage is not None:
        return role_stage

    direct_stage = _first_direct_topic_consumer_stage(
        service.component,
        robot_ctrl_chain,
        index,
    )
    if direct_stage is not None:
        return direct_stage

    return 0


def _first_direct_topic_consumer_stage(
    service_component_id: str,
    robot_ctrl_chain: list[str],
    index: ComponentIndex,
) -> int | None:
    provided_topics = set(component_provides_topics(index.component(service_component_id)))
    if not provided_topics:
        return None

    for stage_index, robot_component_id in enumerate(robot_ctrl_chain):
        consumed_topics = set(
            _required_consumed_topics(index.component(robot_component_id))
        )
        if provided_topics & consumed_topics:
            return stage_index
    return None


def _first_role_stage(
    candidate_roles: tuple[str, ...],
    robot_roles: tuple[str, ...],
) -> int | None:
    for candidate in candidate_roles:
        if candidate in robot_roles:
            return robot_roles.index(candidate)
    return None


def _select_topic_provider(topic: str, index: ComponentIndex) -> str | None:
    providers = [
        provider
        for provider in index.providers_for_topic(
            topic,
            include_disabled=False,
            include_deferred=False,
        )
        if index.component(provider).get("type") == "SVR"
    ]
    if not providers:
        return None

    best_provider = providers[0]
    best_weight = _component_weight(index.component(best_provider))
    for provider in providers[1:]:
        weight = _component_weight(index.component(provider))
        if weight > best_weight:
            best_provider = provider
            best_weight = weight
    return best_provider


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


def _primary_role(component: dict[str, Any]) -> str:
    roles = component_roles(component)
    if not roles:
        raise ServiceResolutionError(
            f"Component {component.get('id')} has no semantic roles."
        )
    return roles[0]


def _component_weight(component: dict[str, Any]) -> float:
    weight = component.get("selection_weight", 1.0)
    if isinstance(weight, bool) or not isinstance(weight, int | float):
        return 0.0
    return float(weight)
