"""Control graph primitives for main and failure branches."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ControlNode:
    """One ROBOT_CTRL action before local topology ids are assigned."""

    key: str
    role: str
    component: str
    stage_index: int
    branch_kind: str = "main"
    branch_id: str | None = None
    source_policy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlEdge:
    """One control event from a ROBOT_CTRL node to another."""

    source: str
    event: str
    target: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlGraph:
    """Resolved ROBOT_CTRL graph with optional failure branches."""

    nodes: tuple[ControlNode, ...]
    edges: tuple[ControlEdge, ...]
    main_node_keys: tuple[str, ...]
    metadata: dict[str, Any]

    def node(self, key: str) -> ControlNode:
        for node in self.nodes:
            if node.key == key:
                return node
        raise KeyError(key)

    def edge_to(self, target: str) -> ControlEdge | None:
        for edge in self.edges:
            if edge.target == target:
                return edge
        return None

    def nodes_by_stage(self) -> dict[int, tuple[ControlNode, ...]]:
        grouped: dict[int, list[ControlNode]] = {}
        for node in self.nodes:
            grouped.setdefault(node.stage_index, []).append(node)
        return {
            stage: tuple(sorted(nodes, key=_node_sort_key))
            for stage, nodes in sorted(grouped.items())
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "main_node_keys": list(self.main_node_keys),
            "metadata": self.metadata,
        }


def build_main_control_graph(robot_components: list[Any]) -> ControlGraph:
    """Build a linear success-only graph from resolved ROBOT_CTRL roles."""

    nodes: list[ControlNode] = []
    edges: list[ControlEdge] = []
    main_node_keys: list[str] = []

    for index, resolved_role in enumerate(robot_components):
        key = f"m{index}"
        nodes.append(
            ControlNode(
                key=key,
                role=resolved_role.role,
                component=resolved_role.component,
                stage_index=index,
            )
        )
        main_node_keys.append(key)
        if index > 0:
            edges.append(
                ControlEdge(
                    source=main_node_keys[index - 1],
                    event="success",
                    target=key,
                )
            )

    return ControlGraph(
        nodes=tuple(nodes),
        edges=tuple(edges),
        main_node_keys=tuple(main_node_keys),
        metadata={
            "control_graph_version": "0.1.0",
            "failure_strategy_enabled": False,
            "failure_branch_count": 0,
            "failure_policies": [],
        },
    )


def _node_sort_key(node: ControlNode) -> tuple[int, int, str]:
    branch_rank = 0 if node.branch_kind == "main" else 1
    return (node.stage_index, branch_rank, node.key)
