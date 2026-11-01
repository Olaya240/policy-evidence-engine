"""Bounded offline planning for synthetic challenge impact.

This module consumes a validated EvidenceDependencyGraph and returns an
immutable review plan. It does not change graph state, create challenge
events, recompute policy, or connect to an API, UI, persistence layer, or
provider. Exact citation provenance is never treated as semantic support.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

import policy_dependency_graph as graph_module
from policy_dependency_graph import (
    ApplicabilityCondition,
    ChallengeEvent,
    Claim,
    ComparisonRelation,
    Conclusion,
    DependencyGraphError,
    EdgeType,
    EvidenceDependencyGraph,
    GraphEdge,
    GraphNode,
    MAX_GRAPH_EDGES,
    NodeType,
    SourcePassage,
)


MAX_EXPLANATION_CHARS = 1_000
MAX_EVIDENCE_REFS = 64
MAX_EVENT_ORDER = 2_147_483_647
MAX_VISITED_NODES = 1_000
MAX_TRAVERSED_EDGES = 3_000
MAX_PATH_LENGTH = 32
MAX_PATHS_PER_NODE = 4
MAX_TOTAL_PATH_ENTRIES = 6_000

_TARGET_TYPES = frozenset({
    NodeType.SOURCE_PASSAGE,
    NodeType.APPLICABILITY_CONDITION,
    NodeType.CLAIM,
    NodeType.COMPARISON_RELATION,
    NodeType.CONCLUSION,
})
_TARGET_CLASSES = (SourcePassage, ApplicabilityCondition, Claim,
                   ComparisonRelation, Conclusion)


class ChallengePropagationError(ValueError):
    """Fixed-message validation error; request contents are not echoed."""

    _MESSAGES = {
        "invalid_request": "Challenge request is invalid.",
        "invalid_graph": "Evidence dependency graph is invalid for planning.",
        "missing_target": "Challenge target is not present in the graph.",
        "target_type_mismatch": "Challenge target type does not match the graph.",
        "comparison_mismatch": "Challenge comparison does not match the graph.",
        "invalid_evidence_ref": "Challenge evidence reference is not a source passage in the graph.",
        "invalid_result": "Challenge impact plan failed integrity validation.",
    }

    def __init__(self, code: str) -> None:
        if code not in self._MESSAGES:
            code = "invalid_request"
        self.code = code
        super().__init__(self._MESSAGES[code])


class ChallengeCategory(str, Enum):
    PROVENANCE = "PROVENANCE"
    TEXT_ACCURACY = "TEXT_ACCURACY"
    APPLICABILITY = "APPLICABILITY"
    TEMPORAL_SCOPE = "TEMPORAL_SCOPE"
    SEMANTIC_INTERPRETATION = "SEMANTIC_INTERPRETATION"
    OTHER = "OTHER"


class ImpactState(str, Enum):
    """Impact interpretation within the planner's permitted graph scope.

    ``INCONCLUSIVE`` is reserved for an impact path that reaches a condition
    whose scope or applicability assessment is explicitly unknown.
    ``UNCHANGED`` means no supported path was found in a complete bounded
    graph search; it is not proof of global independence or semantic non-impact.
    """

    DIRECTLY_CHALLENGED = "DIRECTLY_CHALLENGED"
    REASSESSMENT_REQUIRED = "REASSESSMENT_REQUIRED"
    POTENTIALLY_AFFECTED = "POTENTIALLY_AFFECTED"
    UNCHANGED = "UNCHANGED"
    BLOCKED_BY_MISSING_PROVENANCE = "BLOCKED_BY_MISSING_PROVENANCE"
    INCONCLUSIVE = "INCONCLUSIVE"


class TraversalDirection(str, Enum):
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"


class PlannerLimit(str, Enum):
    VISITED_NODES = "MAX_VISITED_NODES"
    TRAVERSED_EDGES = "MAX_TRAVERSED_EDGES"
    PATH_LENGTH = "MAX_PATH_LENGTH"
    PATHS_PER_NODE = "MAX_PATHS_PER_NODE"
    TOTAL_PATH_ENTRIES = "MAX_TOTAL_PATH_ENTRIES"


_BLOCKER_CODES = frozenset({"MISSING_PROVENANCE", "CROSS_CANDIDATE_BOUNDARY"})


@dataclass(frozen=True, slots=True)
class ChallengeRequest:
    """A bounded request; event_order is descriptive and never reorders history."""

    challenge_id: str
    comparison_id: str
    target_node_id: str
    target_node_type: NodeType
    category: ChallengeCategory
    explanation: str
    evidence_refs: tuple[str, ...] = ()
    event_order: int = 0

    def __post_init__(self) -> None:
        if (type(self.challenge_id) is not str or not self.challenge_id.strip()
                or len(self.challenge_id) > 120 or "\x00" in self.challenge_id
                or type(self.comparison_id) is not str
                or len(self.comparison_id) > 120
                or not self.comparison_id
                or type(self.target_node_id) is not str
                or not self.target_node_id or len(self.target_node_id) > 2_000
                or "\x00" in self.target_node_id
                or type(self.target_node_type) is not NodeType
                or self.target_node_type not in _TARGET_TYPES
                or type(self.category) is not ChallengeCategory
                or type(self.explanation) is not str
                or not self.explanation.strip()
                or len(self.explanation) > MAX_EXPLANATION_CHARS
                or "\x00" in self.explanation
                or type(self.evidence_refs) is not tuple
                or len(self.evidence_refs) > MAX_EVIDENCE_REFS
                or any(type(ref) is not str or not ref or len(ref) > 2_000 or "\x00" in ref
                       for ref in self.evidence_refs)
                or len(set(self.evidence_refs)) != len(self.evidence_refs)
                or type(self.event_order) is not int
                or not 0 <= self.event_order <= MAX_EVENT_ORDER):
            raise ChallengePropagationError("invalid_request")


@dataclass(frozen=True, slots=True)
class PathStep:
    """One existing graph edge, with explicit traversal orientation."""

    edge_id: str
    from_node_id: str
    to_node_id: str
    direction: TraversalDirection

    def __post_init__(self) -> None:
        if (type(self.edge_id) is not str or not self.edge_id or len(self.edge_id) > 4_500
                or "\x00" in self.edge_id
                or type(self.from_node_id) is not str or not self.from_node_id
                or len(self.from_node_id) > 2_000
                or "\x00" in self.from_node_id
                or type(self.to_node_id) is not str or not self.to_node_id
                or len(self.to_node_id) > 2_000
                or "\x00" in self.to_node_id
                or type(self.direction) is not TraversalDirection):
            raise ChallengePropagationError("invalid_result")


@dataclass(frozen=True, slots=True)
class NodeImpact:
    node_id: str
    node_type: NodeType
    state: ImpactState
    reason: str
    challenge_id: str
    paths: tuple[tuple[PathStep, ...], ...]

    def __post_init__(self) -> None:
        if (type(self.node_id) is not str or not self.node_id or len(self.node_id) > 2_000
                or "\x00" in self.node_id
                or type(self.node_type) is not NodeType
                or type(self.state) is not ImpactState
                or type(self.reason) is not str or not self.reason or len(self.reason) > 500
                or type(self.challenge_id) is not str or not self.challenge_id
                or len(self.challenge_id) > 120 or "\x00" in self.challenge_id
                or type(self.paths) is not tuple or len(self.paths) > MAX_PATHS_PER_NODE
                or any(type(path) is not tuple or len(path) > MAX_PATH_LENGTH
                       or any(type(step) is not PathStep for step in path)
                       for path in self.paths)):
            raise ChallengePropagationError("invalid_result")
        if self.state is ImpactState.UNCHANGED and self.paths:
            raise ChallengePropagationError("invalid_result")
        if self.state is ImpactState.DIRECTLY_CHALLENGED and self.paths != ((),):
            raise ChallengePropagationError("invalid_result")


@dataclass(frozen=True, slots=True)
class PlanBlocker:
    code: str
    node_id: str | None
    detail: str

    def __post_init__(self) -> None:
        if (type(self.code) is not str or self.code not in _BLOCKER_CODES
                or (self.node_id is not None and
                    (type(self.node_id) is not str or not self.node_id or len(self.node_id) > 2_000
                     or "\x00" in self.node_id))
                or type(self.detail) is not str or not self.detail or len(self.detail) > 500):
            raise ChallengePropagationError("invalid_result")


@dataclass(frozen=True, slots=True)
class TraversalCompleteness:
    """Report traversal work and the scope in which impact was assessed.

    ``preprocessed_edges`` counts every graph edge inspected once while building
    the bounded adjacency index. ``traversed_edges`` counts eligible transition
    candidates examined while expanding the traversal frontier; graph validation
    passes are excluded. ``examined_node_ids`` are nodes expanded by traversal.
    A complete search
    proves no supported path reaches other graph nodes within ``scope_note``;
    it does not mean those nodes were individually visited or are globally
    independent of the challenge.
    """

    complete: bool
    limit_reached: PlannerLimit | None
    visited_nodes: int
    traversed_edges: int
    examined_node_ids: tuple[str, ...]
    unexplored_node_ids: tuple[str, ...]
    preprocessed_edges: int
    scope_note: str

    def __post_init__(self) -> None:
        if (type(self.complete) is not bool
                or (self.limit_reached is not None and type(self.limit_reached) is not PlannerLimit)
                or (self.complete and self.limit_reached is not None)
                or (not self.complete and self.limit_reached is None)
                or type(self.visited_nodes) is not int or not 0 <= self.visited_nodes <= MAX_VISITED_NODES
                or type(self.traversed_edges) is not int
                or not 0 <= self.traversed_edges <= MAX_TRAVERSED_EDGES
                or type(self.preprocessed_edges) is not int
                or not 0 <= self.preprocessed_edges <= MAX_GRAPH_EDGES
                or type(self.examined_node_ids) is not tuple
                or any(type(item) is not str or not item or len(item) > 2_000 or "\x00" in item
                       for item in self.examined_node_ids)
                or tuple(sorted(set(self.examined_node_ids))) != self.examined_node_ids
                or len(self.examined_node_ids) != self.visited_nodes
                or type(self.unexplored_node_ids) is not tuple
                or any(type(item) is not str or not item or len(item) > 2_000 or "\x00" in item
                       for item in self.unexplored_node_ids)
                or tuple(sorted(set(self.unexplored_node_ids))) != self.unexplored_node_ids
                or set(self.examined_node_ids).intersection(self.unexplored_node_ids)
                or (self.complete and self.unexplored_node_ids)
                or type(self.scope_note) is not str or not self.scope_note
                or len(self.scope_note) > 1_000):
            raise ChallengePropagationError("invalid_result")


@dataclass(frozen=True, slots=True)
class ChallengeImpactPlan:
    comparison_id: str
    challenge_id: str
    event_order: int
    event_order_note: str
    evidence_refs: tuple[str, ...]
    impacts: tuple[NodeImpact, ...]
    blockers: tuple[PlanBlocker, ...]
    traversal: TraversalCompleteness
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if (type(self.comparison_id) is not str or not self.comparison_id
                or len(self.comparison_id) > 120 or "\x00" in self.comparison_id
                or type(self.challenge_id) is not str or not self.challenge_id
                or len(self.challenge_id) > 120 or "\x00" in self.challenge_id
                or type(self.event_order) is not int or not 0 <= self.event_order <= MAX_EVENT_ORDER
                or type(self.event_order_note) is not str or not self.event_order_note
                or len(self.event_order_note) > 300
                or type(self.evidence_refs) is not tuple or len(self.evidence_refs) > MAX_EVIDENCE_REFS
                or any(type(item) is not str or not item or len(item) > 2_000 or "\x00" in item
                       for item in self.evidence_refs)
                or len(set(self.evidence_refs)) != len(self.evidence_refs)
                or type(self.impacts) is not tuple
                or any(type(item) is not NodeImpact for item in self.impacts)
                or tuple(sorted(self.impacts, key=lambda item: item.node_id)) != self.impacts
                or len({item.node_id for item in self.impacts}) != len(self.impacts)
                or type(self.blockers) is not tuple
                or any(type(item) is not PlanBlocker for item in self.blockers)
                or tuple(sorted(self.blockers, key=lambda item: (
                    item.code, item.node_id or "", item.detail,
                ))) != self.blockers
                or type(self.traversal) is not TraversalCompleteness
                or type(self.limitations) is not tuple
                or any(type(item) is not str or not item or len(item) > 500
                       for item in self.limitations)):
            raise ChallengePropagationError("invalid_result")
        direct = tuple(item for item in self.impacts
                       if item.state is ImpactState.DIRECTLY_CHALLENGED)
        if len(direct) != 1 or direct[0].paths != ((),):
            raise ChallengePropagationError("invalid_result")
        if (not self.traversal.complete
                and any(item.state is ImpactState.UNCHANGED for item in self.impacts)):
            raise ChallengePropagationError("invalid_result")
        for impact in self.impacts:
            if impact.challenge_id != self.challenge_id:
                raise ChallengePropagationError("invalid_result")
            if impact.state in (ImpactState.DIRECTLY_CHALLENGED, ImpactState.UNCHANGED):
                continue
            if not impact.paths or any(
                not path or path[0].from_node_id != direct[0].node_id
                or path[-1].to_node_id != impact.node_id
                or any(path[index - 1].to_node_id != path[index].from_node_id
                       for index in range(1, len(path)))
                for path in impact.paths
            ):
                raise ChallengePropagationError("invalid_result")


@dataclass(frozen=True, slots=True)
class _Transition:
    edge: GraphEdge
    destination: str
    direction: TraversalDirection
    state: ImpactState
    mode: str


def _node_class(node: GraphNode) -> type:
    return type(node)


def _candidate_id(node: GraphNode) -> str | None:
    if type(node) in (Claim, ComparisonRelation, Conclusion):
        return node.candidate_id
    return None


def _node_comparison_id(node: GraphNode) -> str | None:
    if type(node) in (Claim, ApplicabilityCondition, ComparisonRelation,
                      Conclusion, ChallengeEvent):
        return node.comparison_id
    return None


def _applicability_is_unresolved(node: ApplicabilityCondition) -> bool:
    """The structured scope or the recorded applicability assessment is unknown."""
    return node.scope_state == "UNKNOWN" or node.applicability_status == "UNKNOWN"


def _make_transitions(
    node: GraphNode,
    mode: str,
    incoming: dict[str, list[GraphEdge]],
    outgoing: dict[str, list[GraphEdge]],
) -> tuple[_Transition, ...]:
    """Select typed impact paths. AFFECTS and CONTAINS are intentionally absent."""
    node_id = node.node_id
    rules: list[_Transition] = []

    def add(edge: GraphEdge, *, destination: str, direction: TraversalDirection,
            state: ImpactState, next_mode: str) -> None:
        rules.append(_Transition(edge, destination, direction, state, next_mode))

    def incoming_dependency() -> None:
        for edge in incoming.get(node_id, ()):
            if edge.edge_type is EdgeType.DEPENDS_ON:
                add(edge, destination=edge.source_id, direction=TraversalDirection.REVERSE,
                    state=ImpactState.REASSESSMENT_REQUIRED, next_mode="dependent")

    if mode == "prerequisite":
        # A prerequisite is identified for context, but propagation does not
        # fan out through its own provenance or other consumers.
        return ()
    if mode == "dependent":
        # Only propagate to dependents. Do not fan from a reviewed candidate
        # through its citations into unrelated claims sharing source text.
        incoming_dependency()
    elif type(node) is SourcePassage:
        for edge in incoming.get(node_id, ()):
            if edge.edge_type is EdgeType.DERIVED_FROM:
                add(edge, destination=edge.source_id, direction=TraversalDirection.REVERSE,
                    state=ImpactState.REASSESSMENT_REQUIRED, next_mode="dependent")
        for edge in outgoing.get(node_id, ()):
            if edge.edge_type in (EdgeType.SUPPORTS, EdgeType.CONTRADICTS):
                add(edge, destination=edge.target_id, direction=TraversalDirection.FORWARD,
                    state=ImpactState.REASSESSMENT_REQUIRED, next_mode="dependent")
    elif type(node) in (Claim, ApplicabilityCondition):
        for edge in outgoing.get(node_id, ()):
            if edge.edge_type is EdgeType.DERIVED_FROM:
                add(edge, destination=edge.target_id, direction=TraversalDirection.FORWARD,
                    state=ImpactState.POTENTIALLY_AFFECTED, next_mode="prerequisite")
        incoming_dependency()
        for edge in incoming.get(node_id, ()):
            if edge.edge_type in (EdgeType.SUPPORTS, EdgeType.CONTRADICTS):
                add(edge, destination=edge.source_id, direction=TraversalDirection.REVERSE,
                    state=ImpactState.POTENTIALLY_AFFECTED, next_mode="prerequisite")
    elif type(node) is ComparisonRelation:
        for edge in outgoing.get(node_id, ()):
            if edge.edge_type is EdgeType.DEPENDS_ON:
                add(edge, destination=edge.target_id, direction=TraversalDirection.FORWARD,
                    state=ImpactState.POTENTIALLY_AFFECTED, next_mode="prerequisite")
        incoming_dependency()
        for edge in incoming.get(node_id, ()):
            if edge.edge_type in (EdgeType.SUPPORTS, EdgeType.CONTRADICTS):
                add(edge, destination=edge.source_id, direction=TraversalDirection.REVERSE,
                    state=ImpactState.POTENTIALLY_AFFECTED, next_mode="prerequisite")
    elif type(node) is Conclusion:
        for edge in outgoing.get(node_id, ()):
            if edge.edge_type is EdgeType.DEPENDS_ON:
                add(edge, destination=edge.target_id, direction=TraversalDirection.FORWARD,
                    state=ImpactState.POTENTIALLY_AFFECTED, next_mode="prerequisite")
    return tuple(sorted(rules, key=lambda item: (
        item.edge.edge_type.value, item.edge.edge_id, item.destination,
        item.direction.value, item.mode,
    )))


def _reason(state: ImpactState) -> str:
    return {
        ImpactState.DIRECTLY_CHALLENGED: "This node is the request's direct target.",
        ImpactState.REASSESSMENT_REQUIRED: "A typed provenance, proposal, or dependency path reaches this node for review.",
        ImpactState.POTENTIALLY_AFFECTED: "This node is a recorded prerequisite or proposed evidence relationship; no semantic conclusion is inferred.",
        ImpactState.UNCHANGED: "No supported impact path was found within the completed bounded graph scope; this does not establish global independence or semantic non-impact.",
        ImpactState.BLOCKED_BY_MISSING_PROVENANCE: "A dependency reaches this node, but required source provenance is absent.",
        ImpactState.INCONCLUSIVE: "This path reaches an applicability condition with unknown scope or assessment; applicability remains unresolved.",
    }[state]


def _validate_plan(plan: ChallengeImpactPlan, graph: EvidenceDependencyGraph,
                   request: ChallengeRequest, nodes: dict[str, GraphNode],
                   edges: dict[str, GraphEdge]) -> None:
    if (type(plan) is not ChallengeImpactPlan
            or plan.comparison_id != request.comparison_id
            or plan.challenge_id != request.challenge_id
            or plan.event_order != request.event_order
            or len({impact.node_id for impact in plan.impacts}) != len(plan.impacts)):
        raise ChallengePropagationError("invalid_result")
    impact_by_id = {impact.node_id: impact for impact in plan.impacts}
    target = impact_by_id.get(request.target_node_id)
    if (target is None or target.state is not ImpactState.DIRECTLY_CHALLENGED
            or target.paths != ((),)):
        raise ChallengePropagationError("invalid_result")
    for impact in plan.impacts:
        if (impact.node_id not in nodes or impact.node_type is not nodes[impact.node_id].node_type
                or impact.challenge_id != request.challenge_id or type(impact.paths) is not tuple):
            raise ChallengePropagationError("invalid_result")
        if impact.state is ImpactState.UNCHANGED:
            if impact.paths:
                raise ChallengePropagationError("invalid_result")
            continue
        if impact.node_id == request.target_node_id:
            continue
        if not impact.paths:
            raise ChallengePropagationError("invalid_result")
        for path in impact.paths:
            if not path or path[0].from_node_id != request.target_node_id or path[-1].to_node_id != impact.node_id:
                raise ChallengePropagationError("invalid_result")
            for index, step in enumerate(path):
                edge = edges.get(step.edge_id)
                if edge is None:
                    raise ChallengePropagationError("invalid_result")
                if step.direction is TraversalDirection.FORWARD:
                    valid = (edge.source_id == step.from_node_id and edge.target_id == step.to_node_id)
                else:
                    valid = (edge.target_id == step.from_node_id and edge.source_id == step.to_node_id)
                if not valid or edge.edge_type in (EdgeType.AFFECTS, EdgeType.CONTAINS, EdgeType.APPLIES_TO):
                    raise ChallengePropagationError("invalid_result")
                if index and path[index - 1].to_node_id != step.from_node_id:
                    raise ChallengePropagationError("invalid_result")
    if plan.traversal.complete and plan.traversal.unexplored_node_ids:
        raise ChallengePropagationError("invalid_result")
    if not plan.traversal.complete and any(item.state is ImpactState.UNCHANGED for item in plan.impacts):
        raise ChallengePropagationError("invalid_result")


def plan_challenge_impact(
    graph: EvidenceDependencyGraph,
    request: ChallengeRequest,
) -> ChallengeImpactPlan:
    """Return a deterministic, bounded impact plan over existing typed edges.

    Reverse traversal is explicit in each PathStep. DEPENDS_ON follows the
    graph's dependent-to-prerequisite direction; reverse traversal identifies
    dependents that may need reassessment. AFFECTS is annotation only and is
    never followed. UNCHANGED appears only when all permitted traversal work
    completed. On a bound, unexplored nodes are listed and no node is called
    unchanged. ``event_order`` describes the request only; no event store is
    read or reordered.
    """
    if type(request) is not ChallengeRequest:
        raise ChallengePropagationError("invalid_request")
    try:
        if type(graph) is not EvidenceDependencyGraph:
            raise DependencyGraphError("invalid_graph")
        graph_module._prevalidate_construction_inputs(
            graph.snapshot_identity, graph.nodes, graph.edges,
        )
        graph_module._validate_graph(graph)
    except DependencyGraphError as exc:
        raise ChallengePropagationError("invalid_graph") from exc

    nodes = {node.node_id: node for node in graph.nodes}
    edges = {edge.edge_id: edge for edge in graph.edges}
    target = nodes.get(request.target_node_id)
    if target is None:
        raise ChallengePropagationError("missing_target")
    if type(target) not in _TARGET_CLASSES or target.node_type is not request.target_node_type:
        raise ChallengePropagationError("target_type_mismatch")
    comparison_ids = {
        node.comparison_id for node in graph.nodes
        if type(node) in (Claim, ApplicabilityCondition, ComparisonRelation, Conclusion, ChallengeEvent)
    }
    if request.comparison_id not in comparison_ids or (
        _node_comparison_id(target) is not None
        and _node_comparison_id(target) != request.comparison_id
    ):
        raise ChallengePropagationError("comparison_mismatch")
    for ref in request.evidence_refs:
        evidence = nodes.get(ref)
        if type(evidence) is not SourcePassage:
            raise ChallengePropagationError("invalid_evidence_ref")

    incoming: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    preprocessed_edges = 0
    for edge in graph.edges:
        preprocessed_edges += 1
        # Structural containment, applicability assertion, and prior challenge
        # annotation are deliberately outside the propagation relation set.
        if edge.edge_type in (EdgeType.CONTAINS, EdgeType.APPLIES_TO, EdgeType.AFFECTS):
            continue
        incoming[edge.target_id].append(edge)
        outgoing[edge.source_id].append(edge)
    for adjacency in (*incoming.values(), *outgoing.values()):
        adjacency.sort(key=lambda edge: (edge.edge_type.value, edge.edge_id))

    impacts: dict[str, dict[str, object]] = {
        target.node_id: {
            "state": ImpactState.DIRECTLY_CHALLENGED,
            "paths": [()],
            "modes": {"root"},
        }
    }
    blockers: dict[tuple[str, str | None], PlanBlocker] = {}
    # Authoritative precedence table for outcome priority.
    # Lower number = higher priority. A node's state can only be overwritten
    # by a state with strictly lower priority number (i.e. higher priority).
    # This table is the single definition used in both the transition loop and
    # the post-traversal provenance check so they cannot conflict.
    _STATE_PRIORITIES: dict[ImpactState, int] = {
        ImpactState.DIRECTLY_CHALLENGED: 0,
        ImpactState.REASSESSMENT_REQUIRED: 1,
        ImpactState.BLOCKED_BY_MISSING_PROVENANCE: 2,
        ImpactState.POTENTIALLY_AFFECTED: 3,
        ImpactState.INCONCLUSIVE: 4,
        ImpactState.UNCHANGED: 5,
    }
    target_has_provenance = True
    if type(target) is Claim:
        target_has_provenance = any(
            edge.edge_type is EdgeType.DERIVED_FROM for edge in outgoing[target.node_id]
        )
    elif type(target) is ApplicabilityCondition and target.scope_state != "UNKNOWN":
        target_has_provenance = any(
            edge.edge_type is EdgeType.DERIVED_FROM for edge in outgoing[target.node_id]
        )
    if not target_has_provenance:
        blockers[("MISSING_PROVENANCE", target.node_id)] = PlanBlocker(
            "MISSING_PROVENANCE", target.node_id,
            "The target has no graph-validated DERIVED_FROM passage edge; request evidence references do not create provenance.",
        )

    queue = deque([(target.node_id, (), frozenset({target.node_id}), "root")])
    expanded: set[str] = set()
    examined: set[str] = set()
    total_path_entries = 0
    traversed_edges = 0
    limit: PlannerLimit | None = None

    while queue and limit is None:
        current_id, path, path_nodes, mode = queue.popleft()
        if current_id not in examined:
            if len(examined) >= MAX_VISITED_NODES:
                limit = PlannerLimit.VISITED_NODES
                break
            examined.add(current_id)
        expand_key = f"{current_id}\x00{mode}\x00{tuple(step.edge_id for step in path)}"
        if expand_key in expanded:
            continue
        expanded.add(expand_key)
        current = nodes[current_id]
        transitions = _make_transitions(current, mode, incoming, outgoing)
        for transition in transitions:
            if traversed_edges >= MAX_TRAVERSED_EDGES:
                limit = PlannerLimit.TRAVERSED_EDGES
                break
            traversed_edges += 1
            neighbor = nodes[transition.destination]
            source_candidate = _candidate_id(current)
            target_candidate = _candidate_id(neighbor)
            if (source_candidate is not None and target_candidate is not None
                    and source_candidate != target_candidate):
                blockers[("CROSS_CANDIDATE_BOUNDARY", transition.edge.edge_id)] = PlanBlocker(
                    "CROSS_CANDIDATE_BOUNDARY", current_id,
                    "A typed relationship crosses candidate ownership; propagation stopped at this boundary.",
                )
                continue
            if transition.destination in path_nodes:
                continue
            next_path = (*path, PathStep(
                transition.edge.edge_id, current_id, transition.destination, transition.direction,
            ))
            if len(next_path) > MAX_PATH_LENGTH:
                limit = PlannerLimit.PATH_LENGTH
                break
            prior = impacts.get(transition.destination)
            prior_paths = [] if prior is None else prior["paths"]
            assert isinstance(prior_paths, list)
            if next_path in prior_paths:
                continue
            if len(prior_paths) >= MAX_PATHS_PER_NODE:
                limit = PlannerLimit.PATHS_PER_NODE
                break
            if total_path_entries + len(next_path) > MAX_TOTAL_PATH_ENTRIES:
                limit = PlannerLimit.TOTAL_PATH_ENTRIES
                break
            total_path_entries += len(next_path)
            transition_state = transition.state
            if (type(neighbor) is ApplicabilityCondition
                    and _applicability_is_unresolved(neighbor)):
                transition_state = ImpactState.INCONCLUSIVE
            if prior is None:
                impacts[transition.destination] = {
                    "state": transition_state,
                    "paths": [next_path],
                    "modes": {transition.mode},
                }
            else:
                prior_paths.append(next_path)
                prior_modes = prior["modes"]
                assert isinstance(prior_modes, set)
                prior_modes.add(transition.mode)
                if _STATE_PRIORITIES[transition_state] < _STATE_PRIORITIES[prior["state"]]:  # type: ignore[index]
                    prior["state"] = transition_state
            queue.append((transition.destination, next_path,
                          path_nodes | {transition.destination}, transition.mode))

        # A reached claim or condition without source passages cannot be treated
        # as grounded. Mark the impact as blocked unless it is the direct target.
        # Uses the shared _STATE_PRIORITIES table to enforce the authoritative
        # precedence: BLOCKED_BY_MISSING_PROVENANCE (priority 2) must not
        # overwrite a state with higher priority (DIRECTLY_CHALLENGED=0 or
        # REASSESSMENT_REQUIRED=1).
        requires_provenance = (
            type(current) is Claim
            or (type(current) is ApplicabilityCondition and current.scope_state != "UNKNOWN")
        )
        if requires_provenance and current_id != request.target_node_id:
            has_provenance = any(edge.edge_type is EdgeType.DERIVED_FROM
                                 for edge in outgoing[current_id])
            if not has_provenance:
                blockers[("MISSING_PROVENANCE", current_id)] = PlanBlocker(
                    "MISSING_PROVENANCE", current_id,
                    "This reached claim or condition has no graph-validated source passage edge.",
                )
                if current_id in impacts:
                    current_state = impacts[current_id]["state"]
                    assert isinstance(current_state, ImpactState)
                    # Only overwrite if BLOCKED_BY_MISSING_PROVENANCE has strictly
                    # higher priority than the state already recorded.
                    if _STATE_PRIORITIES[ImpactState.BLOCKED_BY_MISSING_PROVENANCE] < _STATE_PRIORITIES[current_state]:
                        impacts[current_id]["state"] = ImpactState.BLOCKED_BY_MISSING_PROVENANCE

    complete = limit is None
    unexplored = () if complete else tuple(sorted(set(nodes) - examined))
    if complete:
        for node_id, node in nodes.items():
            if node_id not in impacts:
                impacts[node_id] = {
                    "state": ImpactState.UNCHANGED,
                    "paths": [],
                    "modes": set(),
                }

    ordered_impacts: list[NodeImpact] = []
    for node_id in sorted(impacts):
        value = impacts[node_id]
        state = value["state"]
        paths = value["paths"]
        assert isinstance(state, ImpactState) and isinstance(paths, list)
        ordered_paths = tuple(sorted(paths, key=lambda candidate: tuple(
            (step.edge_id, step.from_node_id, step.to_node_id, step.direction.value)
            for step in candidate
        )))
        reason = _reason(state)
        if (state is ImpactState.DIRECTLY_CHALLENGED
                and type(nodes[node_id]) is ApplicabilityCondition
                and _applicability_is_unresolved(nodes[node_id])):
            reason = (
                "This node is the direct target and its applicability scope or assessment "
                "is UNKNOWN; it remains unresolved and no applicability conclusion is inferred."
            )
        ordered_impacts.append(NodeImpact(
            node_id, nodes[node_id].node_type, state, reason, request.challenge_id,
            ordered_paths,
        ))
    scope_note = (
        "Completed means the permitted frontier was exhausted over this validated graph snapshot, "
        "using DERIVED_FROM, DEPENDS_ON, SUPPORTS, and CONTRADICTS paths only. UNCHANGED means "
        "no supported impact path was found within this bounded scope; it does not mean the node "
        "was individually visited or is globally independent of the challenge."
        if complete else
        "Incomplete means traversal stopped at the reported limit. Nodes outside examined_node_ids "
        "may remain unexplored and are not labeled UNCHANGED."
    )
    traversal = TraversalCompleteness(
        complete, limit, len(examined), traversed_edges,
        tuple(sorted(examined)), unexplored, preprocessed_edges, scope_note,
    )
    limitations = (
        "Source passage identity and exact quote provenance do not establish semantic support.",
        "SUPPORTS and CONTRADICTS remain proposal relationships and only request review.",
        "Prior AFFECTS annotations, CONTAINS structure, and APPLIES_TO assertions are not traversed.",
        "Caller evidence_refs are descriptive references and do not add graph edges or repair missing provenance.",
    )
    plan = ChallengeImpactPlan(
        request.comparison_id, request.challenge_id, request.event_order,
        "Descriptive request order only; no persisted event history was read or reordered.",
        request.evidence_refs, tuple(ordered_impacts),
        tuple(sorted(blockers.values(), key=lambda item: (item.code, item.node_id or "", item.detail))),
        traversal, limitations,
    )
    _validate_plan(plan, graph, request, nodes, edges)
    return plan

