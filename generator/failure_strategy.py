"""Optional failure-branch planning for resolved ROBOT_CTRL chains."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from generator.component_index import ComponentIndex, build_component_index
from generator.control_graph import ControlEdge, ControlGraph, ControlNode
from generator.template_generator import GeneratorConfig, load_configs


@dataclass(frozen=True)
class FailureStrategySelection:
    """A selected failure strategy attached to one main control node."""

    policy: str
    trigger_key: str
    trigger_role: str
    branch_id: str
    on_failed_roles: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "trigger_key": self.trigger_key,
            "trigger_role": self.trigger_role,
            "branch_id": self.branch_id,
            "on_failed_roles": list(self.on_failed_roles),
        }


class FailureStrategyError(ValueError):
    """Raised when configured failure strategies cannot be resolved."""


def apply_failure_strategies(
    graph: ControlGraph,
    semantic_input: dict[str, Any] | None = None,
    config: GeneratorConfig | None = None,
    component_index: ComponentIndex | None = None,
) -> ControlGraph:
    """Attach deterministic safety-oriented failure branches when enabled."""

    cfg = config or load_configs()
    rules = cfg.params_space.get("failure_strategy_rules", {})
    if not isinstance(rules, dict) or not rules.get("enabled", False):
        return graph

    index = component_index or build_component_index(cfg.component_library)
    max_branches = _positive_int(rules.get("max_branches_per_task"), default=1)
    policies = rules.get("policies", {})
    if not isinstance(policies, dict) or not policies:
        return graph

    selected = _select_strategies(
        graph,
        policies,
        _target_branch_count(semantic_input or {}, rules, max_branches),
        semantic_input or {},
        rules,
    )
    if not selected:
        return _with_failure_metadata(graph, [])

    nodes = list(graph.nodes)
    edges = list(graph.edges)

    for selection in selected:
        trigger_node = graph.node(selection.trigger_key)
        previous_key = selection.trigger_key
        previous_event = "failed"

        for offset, role in enumerate(selection.on_failed_roles):
            component = _resolve_robot_role(role, index)
            key = f"{selection.branch_id}_{offset}"
            nodes.append(
                ControlNode(
                    key=key,
                    role=role,
                    component=component,
                    stage_index=trigger_node.stage_index + offset + 1,
                    branch_kind="failure",
                    branch_id=selection.branch_id,
                    source_policy=selection.policy,
                )
            )
            edges.append(
                ControlEdge(
                    source=previous_key,
                    event=previous_event,
                    target=key,
                )
            )
            previous_key = key
            previous_event = "success"

    return ControlGraph(
        nodes=tuple(nodes),
        edges=tuple(edges),
        main_node_keys=graph.main_node_keys,
        metadata={
            **graph.metadata,
            "failure_strategy_enabled": True,
            "failure_branch_count": len(selected),
            "failure_policies": [selection.policy for selection in selected],
            "failure_strategy_selections": [
                selection.to_dict() for selection in selected
            ],
        },
    )


def _select_strategies(
    graph: ControlGraph,
    policies: dict[str, Any],
    target_count: int,
    semantic_input: dict[str, Any],
    rules: dict[str, Any],
) -> list[FailureStrategySelection]:
    selected: list[FailureStrategySelection] = []
    used_triggers: set[str] = set()

    if target_count <= 0:
        return selected

    candidates = _candidate_selections(graph, policies)
    if not candidates:
        return selected

    if rules.get("policy_selection") == "balanced_by_trigger_role":
        candidates = _balanced_candidate_order(candidates, semantic_input)

    used_policies: set[str] = set()
    for candidate in candidates:
        if len(selected) >= target_count:
            return _with_branch_ids(selected)
        if candidate.policy in used_policies:
            continue
        if candidate.trigger_key in used_triggers:
            continue
        selected.append(candidate)
        used_policies.add(candidate.policy)
        used_triggers.add(candidate.trigger_key)

    for candidate in candidates:
        if len(selected) >= target_count:
            break
        if candidate.trigger_key in used_triggers:
            continue
        selected.append(candidate)
        used_triggers.add(candidate.trigger_key)

    return _with_branch_ids(selected)


def _candidate_selections(
    graph: ControlGraph,
    policies: dict[str, Any],
) -> list[FailureStrategySelection]:
    candidates: list[FailureStrategySelection] = []
    for policy_name, policy in policies.items():
        if not isinstance(policy_name, str) or not isinstance(policy, dict):
            continue
        trigger_roles = set(_string_list(policy.get("trigger_roles")))
        on_failed_roles = tuple(_string_list(policy.get("on_failed")))
        if not trigger_roles or not on_failed_roles:
            continue

        for key in graph.main_node_keys:
            node = graph.node(key)
            if node.role not in trigger_roles:
                continue
            candidates.append(
                FailureStrategySelection(
                    policy=policy_name,
                    trigger_key=node.key,
                    trigger_role=node.role,
                    branch_id="",
                    on_failed_roles=on_failed_roles,
                )
            )
    return candidates


def _balanced_candidate_order(
    candidates: list[FailureStrategySelection],
    semantic_input: dict[str, Any],
) -> list[FailureStrategySelection]:
    policies = sorted({candidate.policy for candidate in candidates})
    if not policies:
        return candidates
    offset = _stable_int({"semantic": semantic_input, "scope": "policy_order"}) % len(policies)
    rotated_policies = policies[offset:] + policies[:offset]
    policy_rank = {
        policy: rank
        for rank, policy in enumerate(rotated_policies)
    }

    return sorted(
        candidates,
        key=lambda candidate: (
            policy_rank.get(candidate.policy, len(policy_rank)),
            _stable_int(
                {
                    "semantic": semantic_input,
                    "policy": candidate.policy,
                    "trigger": candidate.trigger_role,
                    "key": candidate.trigger_key,
                }
            ),
            candidate.trigger_key,
        ),
    )


def _with_branch_ids(
    selections: list[FailureStrategySelection],
) -> list[FailureStrategySelection]:
    return [
        FailureStrategySelection(
            policy=selection.policy,
            trigger_key=selection.trigger_key,
            trigger_role=selection.trigger_role,
            branch_id=f"f{index}",
            on_failed_roles=selection.on_failed_roles,
        )
        for index, selection in enumerate(selections)
    ]


def _first_matching_main_node(
    graph: ControlGraph,
    trigger_roles: set[str],
    used_triggers: set[str],
) -> ControlNode | None:
    for key in graph.main_node_keys:
        if key in used_triggers:
            continue
        node = graph.node(key)
        if node.role in trigger_roles:
            return node
    return None


def _target_branch_count(
    semantic_input: dict[str, Any],
    rules: dict[str, Any],
    max_branches: int,
) -> int:
    complexity = semantic_input.get("complexity", "medium")
    if not isinstance(complexity, str):
        complexity = "medium"

    configured = rules.get("branch_count_by_complexity", {})
    value = configured.get(complexity) if isinstance(configured, dict) else None
    if isinstance(value, list) and len(value) == 2:
        low, high = value
        if (
            not isinstance(low, bool)
            and not isinstance(high, bool)
            and isinstance(low, int)
            and isinstance(high, int)
        ):
            minimum = max(0, min(low, high))
            maximum = max(0, max(low, high))
            span = maximum - minimum + 1
            count = minimum + (_stable_int({"semantic": semantic_input, "scope": "branch_count"}) % span)
            return min(count, max_branches)
    if isinstance(value, int) and not isinstance(value, bool):
        return min(max(0, value), max_branches)
    return max_branches


def _resolve_robot_role(role: str, index: ComponentIndex) -> str:
    candidates = index.components_for_role(
        role,
        component_type="ROBOT_CTRL",
        include_disabled=False,
        include_deferred=False,
    )
    if not candidates:
        raise FailureStrategyError(
            f"No active ROBOT_CTRL component provides failure role {role!r}."
        )
    return _select_component(candidates, index)


def _select_component(candidates: tuple[str, ...], index: ComponentIndex) -> str:
    best = candidates[0]
    best_weight = _component_weight(index.component(best))
    for candidate in candidates[1:]:
        weight = _component_weight(index.component(candidate))
        if weight > best_weight:
            best = candidate
            best_weight = weight
    return best


def _with_failure_metadata(
    graph: ControlGraph,
    selections: list[FailureStrategySelection],
) -> ControlGraph:
    return ControlGraph(
        nodes=graph.nodes,
        edges=graph.edges,
        main_node_keys=graph.main_node_keys,
        metadata={
            **graph.metadata,
            "failure_strategy_enabled": True,
            "failure_branch_count": len(selections),
            "failure_policies": [selection.policy for selection in selections],
            "failure_strategy_selections": [
                selection.to_dict() for selection in selections
            ],
        },
    )


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _stable_int(value: Any) -> int:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return int(hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12], 16)


def _component_weight(component: dict[str, Any]) -> float:
    weight = component.get("selection_weight", 1.0)
    if isinstance(weight, bool) or not isinstance(weight, int | float):
        return 0.0
    return float(weight)
