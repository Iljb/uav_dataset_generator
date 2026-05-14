"""Indexes over component library semantic annotations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


VALID_COMPONENT_TYPES = {"ROBOT_CTRL", "SVR"}
ACTIVE_STATUS = "active"
DEFERRED_STATUS = "deferred"


@dataclass(frozen=True)
class ComponentIndex:
    """Lookup indexes derived from ``component_library.json``."""

    components_by_id: dict[str, dict[str, Any]]
    component_ids: tuple[str, ...]
    components_by_type: dict[str, tuple[str, ...]]
    components_by_role: dict[str, tuple[str, ...]]
    topic_providers: dict[str, tuple[str, ...]]
    topic_consumers: dict[str, tuple[str, ...]]
    components_by_lifecycle: dict[str, tuple[str, ...]]
    components_by_status: dict[str, tuple[str, ...]]

    @classmethod
    def from_library(cls, component_library: dict[str, Any]) -> "ComponentIndex":
        """Build indexes from a loaded component library dictionary."""

        components = component_library.get("components", [])
        components_by_id: dict[str, dict[str, Any]] = {}
        component_ids: list[str] = []
        by_type: dict[str, list[str]] = defaultdict(list)
        by_role: dict[str, list[str]] = defaultdict(list)
        topic_providers: dict[str, list[str]] = defaultdict(list)
        topic_consumers: dict[str, list[str]] = defaultdict(list)
        by_lifecycle: dict[str, list[str]] = defaultdict(list)
        by_status: dict[str, list[str]] = defaultdict(list)

        for component in components:
            component_id = component.get("id")
            if not isinstance(component_id, str):
                continue
            components_by_id[component_id] = component
            component_ids.append(component_id)

            component_type = component.get("type")
            if isinstance(component_type, str):
                by_type[component_type].append(component_id)

            lifecycle = component.get("lifecycle")
            if isinstance(lifecycle, str):
                by_lifecycle[lifecycle].append(component_id)

            status = component.get("status")
            if isinstance(status, str):
                by_status[status].append(component_id)

            for role in component_roles(component):
                by_role[role].append(component_id)
            for topic in component_provides_topics(component):
                topic_providers[topic].append(component_id)
            for topic in component_consumes_topics(component):
                topic_consumers[topic].append(component_id)

        return cls(
            components_by_id=components_by_id,
            component_ids=tuple(component_ids),
            components_by_type=_freeze_index(by_type),
            components_by_role=_freeze_index(by_role),
            topic_providers=_freeze_index(topic_providers),
            topic_consumers=_freeze_index(topic_consumers),
            components_by_lifecycle=_freeze_index(by_lifecycle),
            components_by_status=_freeze_index(by_status),
        )

    def has_component(self, component_id: str) -> bool:
        return component_id in self.components_by_id

    def component(self, component_id: str) -> dict[str, Any]:
        return self.components_by_id[component_id]

    def component_type(self, component_id: str) -> str | None:
        component = self.components_by_id.get(component_id)
        if component is None:
            return None
        value = component.get("type")
        return value if isinstance(value, str) else None

    def is_enabled(self, component_id: str) -> bool:
        component = self.components_by_id.get(component_id)
        return bool(component and component.get("enabled", False))

    def is_deferred(self, component_id: str) -> bool:
        component = self.components_by_id.get(component_id)
        return bool(component and component.get("status") == DEFERRED_STATUS)

    def components_for_type(
        self,
        component_type: str,
        *,
        include_disabled: bool = True,
        include_deferred: bool = True,
    ) -> tuple[str, ...]:
        return self._filter_components(
            self.components_by_type.get(component_type, ()),
            include_disabled=include_disabled,
            include_deferred=include_deferred,
        )

    def components_for_role(
        self,
        role: str,
        *,
        component_type: str | None = None,
        include_disabled: bool = True,
        include_deferred: bool = True,
    ) -> tuple[str, ...]:
        return self._filter_components(
            self.components_by_role.get(role, ()),
            component_type=component_type,
            include_disabled=include_disabled,
            include_deferred=include_deferred,
        )

    def providers_for_topic(
        self,
        topic: str,
        *,
        component_type: str | None = None,
        include_disabled: bool = True,
        include_deferred: bool = True,
    ) -> tuple[str, ...]:
        return self._filter_components(
            self.topic_providers.get(topic, ()),
            component_type=component_type,
            include_disabled=include_disabled,
            include_deferred=include_deferred,
        )

    def consumers_for_topic(
        self,
        topic: str,
        *,
        component_type: str | None = None,
        include_disabled: bool = True,
        include_deferred: bool = True,
    ) -> tuple[str, ...]:
        return self._filter_components(
            self.topic_consumers.get(topic, ()),
            component_type=component_type,
            include_disabled=include_disabled,
            include_deferred=include_deferred,
        )

    def _filter_components(
        self,
        component_ids: tuple[str, ...],
        *,
        component_type: str | None = None,
        include_disabled: bool,
        include_deferred: bool,
    ) -> tuple[str, ...]:
        filtered: list[str] = []
        for component_id in component_ids:
            component = self.components_by_id.get(component_id)
            if component is None:
                continue
            if component_type is not None and component.get("type") != component_type:
                continue
            if not include_disabled and not component.get("enabled", False):
                continue
            if not include_deferred and component.get("status") == DEFERRED_STATUS:
                continue
            filtered.append(component_id)
        return tuple(filtered)


def build_component_index(component_library: dict[str, Any]) -> ComponentIndex:
    """Build a component index from a loaded component library."""

    return ComponentIndex.from_library(component_library)


def component_roles(component: dict[str, Any]) -> tuple[str, ...]:
    return _string_tuple(component.get("roles", []))


def component_consumes_topics(component: dict[str, Any]) -> tuple[str, ...]:
    if "consumes_topics" in component:
        return _string_tuple(component.get("consumes_topics", []))
    return _channel_topics(component.get("input_channels", []))


def component_provides_topics(component: dict[str, Any]) -> tuple[str, ...]:
    if "provides_topics" in component:
        return _string_tuple(component.get("provides_topics", []))
    return _channel_topics(component.get("output_channels", []))


def _channel_topics(channels: Any) -> tuple[str, ...]:
    topics: list[str] = []
    if not isinstance(channels, list):
        return ()
    for channel in channels:
        if isinstance(channel, dict) and isinstance(channel.get("topic"), str):
            topics.append(channel["topic"])
    return tuple(topics)


def _string_tuple(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str))


def _freeze_index(index: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    return {key: tuple(values) for key, values in sorted(index.items())}
