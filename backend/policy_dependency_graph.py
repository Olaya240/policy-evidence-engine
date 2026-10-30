"""Typed, in-memory dependency graph for the synthetic policy demo.

This is a read-only projection over already validated policy structures. It
does not change proposal generation, recomputation, session history, or policy
state. ``SOURCE_VALIDATED`` means that source structure and citation spans were
validated locally; it does not establish source authenticity, semantic support,
or policy applicability. Snapshot identity is a provisional composite label,
not a canonical graph hash.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
import re
import heapq
from typing import ClassVar, TypeAlias

from policy_compare import PolicyCompareError, PolicyPair, validate_citation
from policy_evidence_demo import (
    SCENARIO_SCHEDULING,
    ReviewerChallenge,
    build_hotel_scheduling_policy_pair,
    build_scenario_reviewer_challenge,
    evaluate_department_applicability,
    run_initial_evidence_investigation,
)


MAX_GRAPH_NODES = 5_000
MAX_GRAPH_EDGES = 10_000
# These budgets bound the accepted logical payload, not Python's exact heap use.
# UTF-8 bytes include every scalar string and enum value in nodes, edges, and the
# provisional identity. Nested entries count tuple members inside graph objects;
# references count citation records and applicability passage IDs.
MAX_AGGREGATE_TEXT_BYTES = 4 * 1024 * 1024
MAX_AGGREGATE_REFERENCES = 256
MAX_AGGREGATE_NESTED_ENTRIES = 25_000
MAX_SNAPSHOT_IDENTITY_BYTES = 10_000
MAX_PROVENANCE_CHARS = 500
MAX_DESCRIPTION_CHARS = 500
MAX_CITATION_CHARS = 4_000
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DOC_ID = re.compile(r"syn-policy-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION_ID = re.compile(r"v[A-Za-z0-9][A-Za-z0-9.-]{0,23}\Z")
_COMPARISON_ID = re.compile(r"cmp-syn-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_CANDIDATE_ID = re.compile(r"cand-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_PASSAGE_ID = re.compile(r"p[0-9]{6}-[0-9a-f]{16}\Z")
_SCOPE_ID = re.compile(r"(?:ALL|[A-Z][A-Z0-9_]{1,63})\Z")


class DependencyGraphError(ValueError):
    """Controlled graph validation error that never includes input contents."""

    _MESSAGES = {
        "invalid_graph": "Evidence dependency graph is invalid.",
        "invalid_node": "Evidence dependency graph contains an invalid node.",
        "duplicate_node": "Evidence dependency graph contains a duplicate node.",
        "duplicate_edge": "Evidence dependency graph contains a duplicate edge.",
        "missing_reference": "Evidence dependency graph contains a missing reference.",
        "invalid_edge": "Evidence dependency graph contains an invalid edge.",
        "invalid_citation": "Evidence dependency graph contains invalid citation provenance.",
        "invalid_ownership": "Evidence dependency graph contains invalid source ownership.",
        "invalid_offsets": "Evidence dependency graph contains invalid source offsets.",
        "unknown_applicability": "Unknown applicability cannot be asserted as an edge.",
        "dependency_cycle": "Evidence dependency graph contains a dependency cycle.",
        "graph_budget_exceeded": "Evidence dependency graph exceeds its aggregate budget.",
    }

    def __init__(self, code: str) -> None:
        if code not in self._MESSAGES:
            code = "invalid_graph"
        self.code = code
        super().__init__(self._MESSAGES[code])


class NodeType(str, Enum):
    SOURCE_DOCUMENT = "SourceDocument"
    POLICY_VERSION = "PolicyVersion"
    SOURCE_PASSAGE = "SourcePassage"
    CLAIM = "Claim"
    APPLICABILITY_CONDITION = "ApplicabilityCondition"
    COMPARISON_RELATION = "ComparisonRelation"
    CONCLUSION = "Conclusion"
    CHALLENGE_EVENT = "ChallengeEvent"


class EpistemicStatus(str, Enum):
    SOURCE_VALIDATED = "SOURCE_VALIDATED"
    LOCALLY_DERIVED = "LOCALLY_DERIVED"
    PROPOSED = "PROPOSED"
    CHALLENGED = "CHALLENGED"
    UNVERIFIED = "UNVERIFIED"


class EdgeType(str, Enum):
    CONTAINS = "CONTAINS"
    DERIVED_FROM = "DERIVED_FROM"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    APPLIES_TO = "APPLIES_TO"
    DEPENDS_ON = "DEPENDS_ON"
    AFFECTS = "AFFECTS"


@dataclass(frozen=True, slots=True)
class SourceDocument:
    node_id: str
    epistemic_status: EpistemicStatus
    document_id: str
    node_type: ClassVar[NodeType] = NodeType.SOURCE_DOCUMENT


@dataclass(frozen=True, slots=True)
class PolicyVersion:
    """Version data projection; named separately to avoid shadowing core type."""

    node_id: str
    epistemic_status: EpistemicStatus
    document_id: str
    version_id: str
    source_sha256: str
    original_text: str
    effective_from: date | None
    effective_to_exclusive: date | None
    department_scope_state: str
    department_scope_ids: tuple[str, ...]
    procedure_scope_state: str
    procedure_scope_ids: tuple[str, ...]
    property_id: str | None
    text_coverage: str
    node_type: ClassVar[NodeType] = NodeType.POLICY_VERSION


@dataclass(frozen=True, slots=True)
class SourcePassage:
    node_id: str
    epistemic_status: EpistemicStatus
    document_id: str
    version_id: str
    source_sha256: str
    passage_id: str
    ordinal: int
    start_cp: int
    end_cp: int
    text: str
    text_sha256: str
    node_type: ClassVar[NodeType] = NodeType.SOURCE_PASSAGE


@dataclass(frozen=True, slots=True)
class CitationReference:
    """Validated source span attached to a proposal claim."""

    side: str
    document_id: str
    version_id: str
    source_sha256: str
    passage_id: str
    start_cp: int
    end_cp: int
    quote: str


@dataclass(frozen=True, slots=True)
class Claim:
    node_id: str
    epistemic_status: EpistemicStatus
    comparison_id: str
    candidate_id: str
    summary: str
    proposed_classification: str
    citations: tuple[CitationReference, ...]
    node_type: ClassVar[NodeType] = NodeType.CLAIM


@dataclass(frozen=True, slots=True)
class ApplicabilityCondition:
    node_id: str
    epistemic_status: EpistemicStatus
    comparison_id: str
    document_id: str
    version_id: str
    source_sha256: str
    dimension: str
    target_id: str
    scope_state: str
    scope_ids: tuple[str, ...]
    evidence_passage_ids: tuple[str, ...]
    applicability_status: str
    node_type: ClassVar[NodeType] = NodeType.APPLICABILITY_CONDITION


@dataclass(frozen=True, slots=True)
class ComparisonRelation:
    node_id: str
    epistemic_status: EpistemicStatus
    comparison_id: str
    candidate_id: str
    relation: str
    claim_node_id: str
    node_type: ClassVar[NodeType] = NodeType.COMPARISON_RELATION


@dataclass(frozen=True, slots=True)
class Conclusion:
    node_id: str
    epistemic_status: EpistemicStatus
    comparison_id: str
    candidate_id: str
    classification: str
    proposed_classification: str
    uncertainty_reasons: tuple[str, ...]
    human_review_required: bool
    official_policy_mutated: bool
    node_type: ClassVar[NodeType] = NodeType.CONCLUSION


@dataclass(frozen=True, slots=True)
class ChallengeEvent:
    node_id: str
    epistemic_status: EpistemicStatus
    comparison_id: str
    challenge_id: str
    scenario_id: str
    target_department: str
    target_side: str
    target_document_id: str
    target_version_id: str
    target_source_sha256: str
    target_passage_id: str
    target_quote: str
    description: str
    node_type: ClassVar[NodeType] = NodeType.CHALLENGE_EVENT


GraphNode: TypeAlias = (
    SourceDocument | PolicyVersion | SourcePassage | Claim |
    ApplicabilityCondition | ComparisonRelation | Conclusion | ChallengeEvent
)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    epistemic_status: EpistemicStatus
    provenance: str


@dataclass(frozen=True, slots=True)
class EvidenceDependencyGraph:
    """Immutable, sorted graph snapshot; identity is a provisional composite."""

    snapshot_identity: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def __post_init__(self) -> None:
        _prevalidate_construction_inputs(self.snapshot_identity, self.nodes, self.edges)
        sorted_nodes = tuple(sorted(self.nodes, key=lambda node: node.node_id))
        sorted_edges = tuple(sorted(self.edges, key=lambda edge: edge.edge_id))
        object.__setattr__(self, "nodes", sorted_nodes)
        object.__setattr__(self, "edges", sorted_edges)
        _validate_graph(self)


def _fail(code: str) -> None:
    raise DependencyGraphError(code)


def source_document_id(document_id: str) -> str:
    return f"source-document:{document_id}"


def policy_version_id(document_id: str, version_id: str, source_sha256: str) -> str:
    return f"policy-version:{document_id}:{version_id}:{source_sha256}"


def source_passage_id(
    document_id: str, version_id: str, source_sha256: str, passage_id: str,
) -> str:
    """Version-aware identity uses the full source digest, never its prefix alone."""
    return f"source-passage:{document_id}:{version_id}:{source_sha256}:{passage_id}"


def claim_node_id(comparison_id: str, candidate_id: str) -> str:
    return f"claim:{comparison_id}:{candidate_id}"


def applicability_node_id(
    comparison_id: str, document_id: str, version_id: str,
    source_sha256: str, dimension: str, target_id: str,
) -> str:
    return (f"applicability:{comparison_id}:{document_id}:{version_id}:"
            f"{source_sha256}:{dimension}:{target_id}")


def comparison_relation_node_id(comparison_id: str, candidate_id: str) -> str:
    return f"comparison-relation:{comparison_id}:{candidate_id}"


def conclusion_node_id(comparison_id: str, candidate_id: str) -> str:
    return f"conclusion:{comparison_id}:{candidate_id}:validated"


def challenge_event_node_id(comparison_id: str, challenge_id: str) -> str:
    return f"challenge-event:{comparison_id}:{challenge_id}"


def edge_id(source_id: str, edge_type: EdgeType, target_id: str) -> str:
    return f"edge:{edge_type.value}:{source_id}->{target_id}"


def make_edge(
    source_id: str,
    target_id: str,
    edge_type: EdgeType,
    epistemic_status: EpistemicStatus,
    provenance: str,
) -> GraphEdge:
    return GraphEdge(edge_id(source_id, edge_type, target_id), source_id, target_id,
                     edge_type, epistemic_status, provenance)


def _snapshot_identity(nodes: tuple[GraphNode, ...]) -> str:
    if type(nodes) is not tuple:
        _fail("invalid_graph")
    allowed_types = (SourceDocument, PolicyVersion, SourcePassage, Claim,
                     ApplicabilityCondition, ComparisonRelation, Conclusion, ChallengeEvent)
    for node in nodes:
        if type(node) not in allowed_types or type(node.node_id) is not str:
            _fail("invalid_node")
        if type(node) is PolicyVersion:
            values = (node.document_id, node.version_id, node.source_sha256)
        elif type(node) in (Claim, ApplicabilityCondition, ComparisonRelation, Conclusion, ChallengeEvent):
            values = (node.comparison_id,)
            if type(node) is ChallengeEvent:
                values = (node.comparison_id, node.challenge_id)
        else:
            values = ()
        if any(type(value) is not str or not value for value in values):
            _fail("invalid_node")
    versions = sorted(
        (node for node in nodes if type(node) is PolicyVersion),
        key=lambda node: (node.document_id, node.version_id, node.source_sha256),
    )
    if not versions:
        _fail("invalid_graph")
    comparison_ids = sorted({
        node.comparison_id for node in nodes
        if type(node) in (Claim, ApplicabilityCondition, ComparisonRelation, Conclusion, ChallengeEvent)
    })
    if len(comparison_ids) != 1:
        _fail("invalid_graph")
    challenges = sorted(node.challenge_id for node in nodes if type(node) is ChallengeEvent)
    prefix = "provisional-graph-v1|"
    separator = "|"
    challenge_prefix = "|challenges="
    comparison_id = comparison_ids[0]
    version_components = []
    for node in versions:
        components = (node.document_id, node.version_id, node.source_sha256)
        component_sizes = tuple(_strict_utf8_size(value) for value in components)
        if any(size is None for size in component_sizes):
            _fail("invalid_node")
        part_size = sum(component_sizes) + 2  # two slashes
        version_components.append((node, part_size))
    challenge_sizes = tuple(_strict_utf8_size(value) for value in challenges)
    if any(size is None for size in challenge_sizes):
        _fail("invalid_node")
    identity_size = (
        len(prefix.encode("ascii")) + _strict_utf8_size(comparison_id)
        + len(separator.encode("ascii")) + len(challenge_prefix.encode("ascii"))
        + (sum(size for _, size in version_components) + max(0, len(versions) - 1))
        + (sum(challenge_sizes) + max(0, len(challenges) - 1) if challenges
           else len("none"))
    )
    if identity_size > MAX_SNAPSHOT_IDENTITY_BYTES:
        _fail("invalid_graph")
    version_parts = ";".join(
        f"{node.document_id}/{node.version_id}/{node.source_sha256}"
        for node, _ in version_components
    )
    challenge_part = ";".join(challenges) if challenges else "none"
    identity = (f"{prefix}{comparison_id}|{version_parts}"
                f"{challenge_prefix}{challenge_part}")
    if _strict_utf8_size(identity) != identity_size:
        _fail("invalid_graph")
    return identity


def _valid_string(value: object, *, maximum: int, nonblank: bool = True) -> bool:
    return (type(value) is str and len(value) <= maximum
            and (not nonblank or bool(value.strip()))
            and "\x00" not in value)


def _strict_utf8_size(value: str) -> int | None:
    try:
        return len(value.encode("utf-8", "strict"))
    except UnicodeError:
        return None


_GRAPH_NODE_TYPES = (SourceDocument, PolicyVersion, SourcePassage, Claim,
                     ApplicabilityCondition, ComparisonRelation, Conclusion, ChallengeEvent)


def _prevalidate_construction_inputs(
    snapshot_identity: object, nodes: object, edges: object,
) -> tuple[int, int, int]:
    """Bound and shape-check raw inputs before sorting or semantic validation.

    The iterative walk accepts only exact immutable graph value types and
    built-in scalar/container types, avoiding caller-defined behavior and
    Python recursion limits.
    """
    if (type(nodes) is not tuple or type(edges) is not tuple
            or len(nodes) > MAX_GRAPH_NODES or len(edges) > MAX_GRAPH_EDGES
            or not _valid_string(snapshot_identity, maximum=10_000)):
        _fail("invalid_graph")
    identity_bytes = _strict_utf8_size(snapshot_identity)
    if identity_bytes is None:
        _fail("invalid_graph")
    if identity_bytes > MAX_SNAPSHOT_IDENTITY_BYTES:
        _fail("invalid_graph")

    totals = {"bytes": 0, "references": 0, "nested": 0}

    stack = []

    def push(value: object, owner: str, field_name: str = "") -> None:
        stack.append((value, owner, field_name))

    def visit_all() -> None:
        while stack:
            value, owner, field_name = stack.pop()
            if type(value) is str:
                if len(value) > MAX_AGGREGATE_TEXT_BYTES:
                    _fail("graph_budget_exceeded")
                encoded_size = _strict_utf8_size(value)
                if encoded_size is None:
                    _fail("invalid_node" if owner == "node" else "invalid_edge")
                totals["bytes"] += encoded_size
                if totals["bytes"] > MAX_AGGREGATE_TEXT_BYTES:
                    _fail("graph_budget_exceeded")
                continue
            if type(value) in (EpistemicStatus, EdgeType, NodeType):
                push(value.value, owner)
                continue
            if type(value) is tuple:
                totals["nested"] += len(value)
                if totals["nested"] > MAX_AGGREGATE_NESTED_ENTRIES:
                    _fail("graph_budget_exceeded")
                if field_name in {"citations", "evidence_passage_ids"}:
                    totals["references"] += len(value)
                    if totals["references"] > MAX_AGGREGATE_REFERENCES:
                        _fail("graph_budget_exceeded")
                for item in reversed(value):
                    push(item, owner)
                continue
            if type(value) in _GRAPH_NODE_TYPES or type(value) in (GraphEdge, CitationReference):
                for item in reversed(fields(value)):
                    push(getattr(value, item.name), owner, item.name)
                continue
            if type(value) in (int, bool, date, type(None)):
                continue
            _fail("invalid_node" if owner == "node" else "invalid_edge")

    for node in nodes:
        if type(node) not in _GRAPH_NODE_TYPES:
            _fail("invalid_node")
        push(node, "node")
    for edge in edges:
        if type(edge) is not GraphEdge:
            _fail("invalid_edge")
        push(edge, "edge")
    visit_all()

    # Reserve the full allowed identity size so factory and direct construction
    # apply one budget before identity formatting/sorting.
    totals["bytes"] += MAX_SNAPSHOT_IDENTITY_BYTES
    if totals["bytes"] > MAX_AGGREGATE_TEXT_BYTES:
        _fail("graph_budget_exceeded")

    # Shape validation now runs only over bounded, exact built-in values. It
    # also verifies every identity field before the caller's tuples are sorted.
    for node in nodes:
        _validate_node_shape(node)
    for edge in edges:
        _validate_edge_shape(edge)
    return totals["bytes"], totals["references"], totals["nested"]


def _expected_node_id(node: GraphNode) -> str:
    if type(node) is SourceDocument:
        return source_document_id(node.document_id)
    if type(node) is PolicyVersion:
        return policy_version_id(node.document_id, node.version_id, node.source_sha256)
    if type(node) is SourcePassage:
        return source_passage_id(node.document_id, node.version_id,
                                 node.source_sha256, node.passage_id)
    if type(node) is Claim:
        return claim_node_id(node.comparison_id, node.candidate_id)
    if type(node) is ApplicabilityCondition:
        return applicability_node_id(node.comparison_id, node.document_id,
                                     node.version_id, node.source_sha256,
                                     node.dimension, node.target_id)
    if type(node) is ComparisonRelation:
        return comparison_relation_node_id(node.comparison_id, node.candidate_id)
    if type(node) is Conclusion:
        return conclusion_node_id(node.comparison_id, node.candidate_id)
    if type(node) is ChallengeEvent:
        return challenge_event_node_id(node.comparison_id, node.challenge_id)
    _fail("invalid_node")


def _validate_node_shape(node: GraphNode) -> None:
    if type(node) not in (SourceDocument, PolicyVersion, SourcePassage, Claim,
                          ApplicabilityCondition, ComparisonRelation, Conclusion,
                          ChallengeEvent):
        _fail("invalid_node")
    if type(node.epistemic_status) is not EpistemicStatus:
        _fail("invalid_node")
    if not _valid_string(node.node_id, maximum=2_000):
        _fail("invalid_node")
    identity_fields = {
        SourceDocument: ("document_id",),
        PolicyVersion: ("document_id", "version_id", "source_sha256"),
        SourcePassage: ("document_id", "version_id", "source_sha256", "passage_id"),
        Claim: ("comparison_id", "candidate_id"),
        ApplicabilityCondition: ("comparison_id", "document_id", "version_id",
                                 "source_sha256", "dimension", "target_id"),
        ComparisonRelation: ("comparison_id", "candidate_id"),
        Conclusion: ("comparison_id", "candidate_id"),
        ChallengeEvent: ("comparison_id", "challenge_id"),
    }[type(node)]
    if any(type(getattr(node, field)) is not str for field in identity_fields):
        _fail("invalid_node")
    if node.node_id != _expected_node_id(node):
        _fail("invalid_node")

    if type(node) is SourceDocument:
        valid = (type(node.document_id) is str and _DOC_ID.fullmatch(node.document_id) is not None
                 and node.epistemic_status is EpistemicStatus.SOURCE_VALIDATED)
    elif type(node) is PolicyVersion:
        valid = (
            type(node.document_id) is str and _DOC_ID.fullmatch(node.document_id) is not None
            and type(node.version_id) is str and _VERSION_ID.fullmatch(node.version_id) is not None
            and type(node.source_sha256) is str and _SHA256.fullmatch(node.source_sha256) is not None
            and _valid_string(node.original_text, maximum=100_000)
            and (node.effective_from is None or type(node.effective_from) is date)
            and (node.effective_to_exclusive is None or type(node.effective_to_exclusive) is date)
            and (node.effective_from is None or node.effective_to_exclusive is None
                 or node.effective_from < node.effective_to_exclusive)
            and type(node.department_scope_state) is str
            and node.department_scope_state in {"KNOWN", "UNKNOWN", "ALL"}
            and type(node.department_scope_ids) is tuple
            and len(node.department_scope_ids) <= MAX_GRAPH_NODES
            and all(type(value) is str and _SCOPE_ID.fullmatch(value) for value in node.department_scope_ids)
            and len(set(node.department_scope_ids)) == len(node.department_scope_ids)
            and ((node.department_scope_state == "KNOWN" and bool(node.department_scope_ids))
                 or (node.department_scope_state != "KNOWN" and not node.department_scope_ids))
            and type(node.procedure_scope_state) is str
            and node.procedure_scope_state in {"KNOWN", "UNKNOWN", "ALL"}
            and type(node.procedure_scope_ids) is tuple
            and len(node.procedure_scope_ids) <= MAX_GRAPH_NODES
            and all(type(value) is str and _SCOPE_ID.fullmatch(value) for value in node.procedure_scope_ids)
            and len(set(node.procedure_scope_ids)) == len(node.procedure_scope_ids)
            and ((node.procedure_scope_state == "KNOWN" and bool(node.procedure_scope_ids))
                 or (node.procedure_scope_state != "KNOWN" and not node.procedure_scope_ids))
            and (node.property_id is None or (type(node.property_id) is str and _SCOPE_ID.fullmatch(node.property_id)))
            and type(node.text_coverage) is str
            and node.text_coverage in {"FULL_DOCUMENT", "EXCERPT"}
            and node.epistemic_status is EpistemicStatus.SOURCE_VALIDATED
        )
        if valid:
            from hashlib import sha256
            try:
                valid = sha256(node.original_text.encode("utf-8", "strict")).hexdigest() == node.source_sha256
            except UnicodeError:
                valid = False
    elif type(node) is SourcePassage:
        valid = (
            type(node.document_id) is str and _DOC_ID.fullmatch(node.document_id) is not None
            and type(node.version_id) is str and _VERSION_ID.fullmatch(node.version_id) is not None
            and type(node.source_sha256) is str and _SHA256.fullmatch(node.source_sha256) is not None
            and type(node.passage_id) is str and _PASSAGE_ID.fullmatch(node.passage_id) is not None
            and type(node.ordinal) is int and node.ordinal > 0
            and type(node.start_cp) is int and type(node.end_cp) is int
            and 0 <= node.start_cp < node.end_cp
            and _valid_string(node.text, maximum=100_000)
            and type(node.text_sha256) is str and _SHA256.fullmatch(node.text_sha256) is not None
            and node.epistemic_status is EpistemicStatus.SOURCE_VALIDATED
        )
        if valid:
            from hashlib import sha256
            try:
                valid = (sha256(node.text.encode("utf-8", "strict")).hexdigest() == node.text_sha256
                         and node.passage_id == f"p{node.ordinal:06d}-{node.text_sha256[:16]}")
            except UnicodeError:
                valid = False
    elif type(node) is Claim:
        valid = (
            type(node.comparison_id) is str and _COMPARISON_ID.fullmatch(node.comparison_id) is not None
            and type(node.candidate_id) is str and _CANDIDATE_ID.fullmatch(node.candidate_id) is not None
            and _valid_string(node.summary, maximum=1_000)
            and type(node.proposed_classification) is str
            and node.proposed_classification in {"CONTRADICTION", "COMPATIBLE_CHANGE", "NEW_RULE",
                                                 "SCOPE_OR_TIME_DIFFERENCE", "INCONCLUSIVE"}
            and type(node.citations) is tuple
            and len(node.citations) <= MAX_GRAPH_EDGES
            and all(type(item) is CitationReference for item in node.citations)
            and node.epistemic_status is EpistemicStatus.PROPOSED
        )
        if valid:
            valid = all(_valid_citation_shape(item) for item in node.citations)
    elif type(node) is ApplicabilityCondition:
        valid = (
            type(node.comparison_id) is str and _COMPARISON_ID.fullmatch(node.comparison_id) is not None
            and type(node.document_id) is str and _DOC_ID.fullmatch(node.document_id) is not None
            and type(node.version_id) is str and _VERSION_ID.fullmatch(node.version_id) is not None
            and type(node.source_sha256) is str and _SHA256.fullmatch(node.source_sha256) is not None
            and type(node.dimension) is str
            and node.dimension in {"DEPARTMENT", "PROCEDURE"}
            and type(node.target_id) is str and _SCOPE_ID.fullmatch(node.target_id) is not None
            and type(node.scope_state) is str
            and node.scope_state in {"KNOWN", "UNKNOWN", "ALL"}
            and type(node.scope_ids) is tuple
            and len(node.scope_ids) <= MAX_GRAPH_NODES
            and all(type(value) is str and _SCOPE_ID.fullmatch(value) for value in node.scope_ids)
            and len(set(node.scope_ids)) == len(node.scope_ids)
            and ((node.scope_state == "KNOWN" and bool(node.scope_ids))
                 or (node.scope_state != "KNOWN" and not node.scope_ids))
            and type(node.evidence_passage_ids) is tuple
            and len(node.evidence_passage_ids) <= MAX_GRAPH_EDGES
            and all(type(value) is str and _PASSAGE_ID.fullmatch(value) for value in node.evidence_passage_ids)
            and len(set(node.evidence_passage_ids)) == len(node.evidence_passage_ids)
            and (node.scope_state == "UNKNOWN" or bool(node.evidence_passage_ids))
            and type(node.applicability_status) is str
            and node.applicability_status in {"GROUNDED", "UNGROUNDED", "UNKNOWN"}
            and node.epistemic_status in {EpistemicStatus.CHALLENGED, EpistemicStatus.UNVERIFIED,
                                          EpistemicStatus.SOURCE_VALIDATED}
        )
        if valid and node.scope_state == "UNKNOWN":
            valid = (node.applicability_status != "GROUNDED"
                     and node.epistemic_status is not EpistemicStatus.SOURCE_VALIDATED)
    elif type(node) is ComparisonRelation:
        valid = (
            type(node.comparison_id) is str and _COMPARISON_ID.fullmatch(node.comparison_id) is not None
            and type(node.candidate_id) is str and _CANDIDATE_ID.fullmatch(node.candidate_id) is not None
            and type(node.relation) is str
            and node.relation in {"CONTRADICTION", "COMPATIBLE_CHANGE", "NEW_RULE",
                                  "SCOPE_OR_TIME_DIFFERENCE", "INCONCLUSIVE"}
            and type(node.claim_node_id) is str
            and node.epistemic_status is EpistemicStatus.PROPOSED
        )
    elif type(node) is Conclusion:
        valid = (
            type(node.comparison_id) is str and _COMPARISON_ID.fullmatch(node.comparison_id) is not None
            and type(node.candidate_id) is str and _CANDIDATE_ID.fullmatch(node.candidate_id) is not None
            and type(node.classification) is str and node.classification == "INCONCLUSIVE"
            and type(node.proposed_classification) is str
            and node.proposed_classification in {"CONTRADICTION", "COMPATIBLE_CHANGE", "NEW_RULE",
                                                 "SCOPE_OR_TIME_DIFFERENCE", "INCONCLUSIVE"}
            and type(node.uncertainty_reasons) is tuple
            and all(_valid_string(reason, maximum=100) for reason in node.uncertainty_reasons)
            and type(node.human_review_required) is bool and node.human_review_required is True
            and type(node.official_policy_mutated) is bool and node.official_policy_mutated is False
            and node.epistemic_status is EpistemicStatus.LOCALLY_DERIVED
        )
    else:
        valid = (
            type(node.comparison_id) is str and _COMPARISON_ID.fullmatch(node.comparison_id) is not None
            and _valid_string(node.challenge_id, maximum=120)
            and node.scenario_id == SCENARIO_SCHEDULING
            and type(node.target_department) is str and _SCOPE_ID.fullmatch(node.target_department) is not None
            and type(node.target_side) is str and node.target_side in {"OLDER", "NEWER"}
            and type(node.target_document_id) is str and _DOC_ID.fullmatch(node.target_document_id) is not None
            and type(node.target_version_id) is str and _VERSION_ID.fullmatch(node.target_version_id) is not None
            and type(node.target_source_sha256) is str and _SHA256.fullmatch(node.target_source_sha256) is not None
            and type(node.target_passage_id) is str and _PASSAGE_ID.fullmatch(node.target_passage_id) is not None
            and _valid_string(node.target_quote, maximum=MAX_CITATION_CHARS)
            and _valid_string(node.description, maximum=MAX_DESCRIPTION_CHARS)
            and node.epistemic_status is EpistemicStatus.CHALLENGED
        )
    if not valid:
        _fail("invalid_node")


def _valid_citation_shape(citation: CitationReference) -> bool:
    return (
        type(citation.side) is str and citation.side in {"OLDER", "NEWER", "PRECEDENCE"}
        and type(citation.document_id) is str and _DOC_ID.fullmatch(citation.document_id) is not None
        and type(citation.version_id) is str and _VERSION_ID.fullmatch(citation.version_id) is not None
        and type(citation.source_sha256) is str and _SHA256.fullmatch(citation.source_sha256) is not None
        and type(citation.passage_id) is str and _PASSAGE_ID.fullmatch(citation.passage_id) is not None
        and type(citation.start_cp) is int and type(citation.end_cp) is int
        and 0 <= citation.start_cp < citation.end_cp
        and _valid_string(citation.quote, maximum=MAX_CITATION_CHARS)
    )


def _valid_edge_types(edge_type: EdgeType, source: GraphNode, target: GraphNode) -> bool:
    pair = (type(source), type(target))
    if edge_type is EdgeType.CONTAINS:
        return pair in {(SourceDocument, PolicyVersion), (PolicyVersion, SourcePassage)}
    if edge_type is EdgeType.DERIVED_FROM:
        return pair in {(Claim, SourcePassage), (ApplicabilityCondition, SourcePassage)}
    if edge_type in {EdgeType.SUPPORTS, EdgeType.CONTRADICTS}:
        return type(source) is SourcePassage and type(target) in {Claim, ComparisonRelation}
    if edge_type is EdgeType.APPLIES_TO:
        return pair == (PolicyVersion, ApplicabilityCondition)
    if edge_type is EdgeType.DEPENDS_ON:
        return (
            (type(source) is Claim and type(target) in {Claim, ApplicabilityCondition})
            or (type(source) is ComparisonRelation and type(target) in {Claim, ApplicabilityCondition})
            or (type(source) is Conclusion and type(target) in {Claim, ComparisonRelation})
        )
    if edge_type is EdgeType.AFFECTS:
        return type(source) is ChallengeEvent and type(target) in {
            SourcePassage, ApplicabilityCondition, Claim, ComparisonRelation, Conclusion
        }
    return False


def _validate_edge_shape(edge: object) -> None:
    if type(edge) is not GraphEdge or type(edge.edge_type) is not EdgeType:
        _fail("invalid_edge")
    if type(edge.epistemic_status) is not EpistemicStatus:
        _fail("invalid_edge")
    if (not _valid_string(edge.edge_id, maximum=4_500)
            or not _valid_string(edge.source_id, maximum=2_000)
            or not _valid_string(edge.target_id, maximum=2_000)
            or not _valid_string(edge.provenance, maximum=MAX_PROVENANCE_CHARS)
            or edge.edge_id != edge_id(edge.source_id, edge.edge_type, edge.target_id)):
        _fail("invalid_edge")


def _validate_edge(edge: GraphEdge, nodes: dict[str, GraphNode]) -> None:
    _validate_edge_shape(edge)
    source, target = nodes.get(edge.source_id), nodes.get(edge.target_id)
    if source is None or target is None:
        _fail("missing_reference")
    if not _valid_edge_types(edge.edge_type, source, target):
        _fail("invalid_edge")

    if edge.edge_type is EdgeType.CONTAINS:
        if type(source) is SourceDocument:
            valid = source.document_id == target.document_id
        else:
            valid = (source.document_id == target.document_id
                     and source.version_id == target.version_id
                     and source.source_sha256 == target.source_sha256)
        if not valid or edge.epistemic_status is not EpistemicStatus.SOURCE_VALIDATED:
            _fail("invalid_ownership")
    elif edge.edge_type is EdgeType.DERIVED_FROM:
        if type(source) is Claim:
            refs = [ref for ref in source.citations
                    if ref.document_id == target.document_id
                    and ref.version_id == target.version_id
                    and ref.source_sha256 == target.source_sha256
                    and ref.passage_id == target.passage_id]
            if not refs:
                _fail("invalid_citation")
            if any(ref.start_cp < target.start_cp or ref.end_cp > target.end_cp
                   or target.text[ref.start_cp - target.start_cp:ref.end_cp - target.start_cp] != ref.quote
                   for ref in refs):
                _fail("invalid_offsets")
        elif (source.document_id != target.document_id
              or source.version_id != target.version_id
              or source.source_sha256 != target.source_sha256
              or target.passage_id not in source.evidence_passage_ids):
            _fail("invalid_citation")
        if edge.epistemic_status is not EpistemicStatus.SOURCE_VALIDATED:
            _fail("invalid_edge")
    elif edge.edge_type in {EdgeType.SUPPORTS, EdgeType.CONTRADICTS}:
        if edge.epistemic_status not in {EpistemicStatus.PROPOSED, EpistemicStatus.UNVERIFIED}:
            _fail("invalid_edge")
    elif edge.edge_type is EdgeType.APPLIES_TO:
        assert type(source) is PolicyVersion and type(target) is ApplicabilityCondition
        if (source.document_id != target.document_id or source.version_id != target.version_id
                or source.source_sha256 != target.source_sha256):
            _fail("invalid_ownership")
        if target.scope_state == "UNKNOWN":
            _fail("unknown_applicability")
        # Citation provenance cannot override an explicit scope exclusion.
        grounded = (target.scope_state == "ALL"
                    or (target.scope_state == "KNOWN" and target.target_id in target.scope_ids))
        if not grounded:
            _fail("unknown_applicability")
        if (target.dimension != "DEPARTMENT"
                or source.department_scope_state != target.scope_state
                or source.department_scope_ids != target.scope_ids):
            _fail("invalid_ownership")
        if edge.epistemic_status is not EpistemicStatus.SOURCE_VALIDATED:
            _fail("invalid_edge")
    elif edge.edge_type is EdgeType.DEPENDS_ON:
        allowed_statuses = {
            (Claim, Claim): {EpistemicStatus.PROPOSED, EpistemicStatus.UNVERIFIED},
            (Claim, ApplicabilityCondition): {EpistemicStatus.PROPOSED, EpistemicStatus.UNVERIFIED},
            (ComparisonRelation, Claim): {EpistemicStatus.LOCALLY_DERIVED},
            (ComparisonRelation, ApplicabilityCondition): {
                EpistemicStatus.PROPOSED, EpistemicStatus.UNVERIFIED,
            },
            (Conclusion, Claim): {EpistemicStatus.LOCALLY_DERIVED},
            (Conclusion, ComparisonRelation): {EpistemicStatus.LOCALLY_DERIVED},
        }
        if edge.epistemic_status not in allowed_statuses[(type(source), type(target))]:
            _fail("invalid_edge")
        if type(source) is ComparisonRelation and type(target) is Claim:
            if (source.claim_node_id != target.node_id
                    or source.comparison_id != target.comparison_id
                    or source.candidate_id != target.candidate_id):
                _fail("invalid_edge")
        if type(source) is Conclusion and type(target) is ComparisonRelation:
            if (source.comparison_id != target.comparison_id
                    or source.candidate_id != target.candidate_id):
                _fail("invalid_edge")
        if type(target) is ApplicabilityCondition:
            if source.comparison_id != target.comparison_id:
                _fail("invalid_edge")
        if type(source) is Claim and type(target) is Claim:
            if source.comparison_id != target.comparison_id:
                _fail("invalid_edge")
        if type(source) is Conclusion and type(target) is Claim:
            if (source.comparison_id != target.comparison_id
                    or source.candidate_id != target.candidate_id):
                _fail("invalid_edge")
    elif edge.edge_type is EdgeType.AFFECTS:
        if edge.epistemic_status is not EpistemicStatus.CHALLENGED:
            _fail("invalid_edge")
        if type(target) is SourcePassage:
            if (source.target_document_id != target.document_id
                    or source.target_version_id != target.version_id
                    or source.target_source_sha256 != target.source_sha256
                    or source.target_passage_id != target.passage_id
                    or source.target_quote not in target.text):
                _fail("invalid_ownership")
        elif type(target) is ApplicabilityCondition:
            if (source.comparison_id != target.comparison_id
                    or source.target_department != target.target_id
                    or source.target_document_id != target.document_id
                    or source.target_version_id != target.version_id
                    or source.target_source_sha256 != target.source_sha256):
                _fail("invalid_ownership")
        else:
            passage_id = source_passage_id(
                source.target_document_id, source.target_version_id,
                source.target_source_sha256, source.target_passage_id,
            )
            if type(target) is Claim:
                claim = target
            elif type(target) is ComparisonRelation:
                claim = nodes.get(target.claim_node_id)
                if (type(claim) is not Claim or claim.comparison_id != target.comparison_id
                        or claim.candidate_id != target.candidate_id):
                    _fail("invalid_ownership")
            else:
                relation = nodes.get(comparison_relation_node_id(
                    target.comparison_id, target.candidate_id,
                ))
                if (type(relation) is not ComparisonRelation
                        or relation.comparison_id != target.comparison_id
                        or relation.candidate_id != target.candidate_id):
                    _fail("invalid_ownership")
                claim = nodes.get(relation.claim_node_id)
                if (type(claim) is not Claim or claim.comparison_id != target.comparison_id
                        or claim.candidate_id != target.candidate_id):
                    _fail("invalid_ownership")
            if (claim.comparison_id != source.comparison_id
                    or not any(ref.document_id == source.target_document_id
                               and ref.version_id == source.target_version_id
                               and ref.source_sha256 == source.target_source_sha256
                               and source_passage_id(ref.document_id, ref.version_id,
                                                     ref.source_sha256, ref.passage_id) == passage_id
                               for ref in claim.citations)):
                _fail("invalid_ownership")


def _validate_citations(nodes: dict[str, GraphNode]) -> None:
    versions = {
        (node.document_id, node.version_id, node.source_sha256): node
        for node in nodes.values() if type(node) is PolicyVersion
    }
    passages = {
        (node.document_id, node.version_id, node.source_sha256, node.passage_id): node
        for node in nodes.values() if type(node) is SourcePassage
    }
    pairs: dict[str, PolicyPair] = {}
    for version in versions.values():
        if source_document_id(version.document_id) not in nodes:
            _fail("invalid_ownership")
    for passage in passages.values():
        version = versions.get((passage.document_id, passage.version_id, passage.source_sha256))
        if version is None:
            _fail("invalid_ownership")
        if (passage.end_cp > len(version.original_text)
                or version.original_text[passage.start_cp:passage.end_cp] != passage.text):
            _fail("invalid_offsets")
    for node in nodes.values():
        if type(node) is not Claim:
            continue
        pair = pairs.get(node.comparison_id)
        if pair is None:
            pair = _pair_from_version_nodes(nodes, node.comparison_id)
            pairs[node.comparison_id] = pair
        for citation in node.citations:
            passage = passages.get((citation.document_id, citation.version_id,
                                    citation.source_sha256, citation.passage_id))
            if passage is None:
                _fail("invalid_citation")
            version = versions.get((citation.document_id, citation.version_id,
                                    citation.source_sha256))
            if version is None:
                _fail("invalid_citation")
            try:
                checked = validate_citation(pair=pair, value={
                    "document_id": citation.document_id,
                    "version_id": citation.version_id,
                    "source_sha256": citation.source_sha256,
                    "passage_id": citation.passage_id,
                    "start_cp": citation.start_cp,
                    "end_cp": citation.end_cp,
                    "quote": citation.quote,
                }, expected_side=citation.side if citation.side in {"OLDER", "NEWER"} else None)
            except PolicyCompareError:
                _fail("invalid_citation")
            if checked["source_sha256"] != passage.source_sha256:
                _fail("invalid_citation")


def _validate_applicability_provenance(
    nodes: dict[str, GraphNode], edges: dict[str, GraphEdge],
) -> None:
    """Bind every listed scope passage to its version and a typed graph edge.

    This validates provenance only; it does not establish that a passage
    semantically supports the department or procedure scope.
    """
    passages = {
        (node.document_id, node.version_id, node.source_sha256, node.passage_id): node
        for node in nodes.values() if type(node) is SourcePassage
    }
    derived_pairs = {
        (edge.source_id, edge.target_id) for edge in edges.values()
        if edge.edge_type is EdgeType.DERIVED_FROM
    }
    for condition in (node for node in nodes.values()
                      if type(node) is ApplicabilityCondition):
        version = nodes.get(policy_version_id(
            condition.document_id, condition.version_id, condition.source_sha256,
        ))
        if (type(version) is not PolicyVersion
                or version.document_id != condition.document_id
                or version.version_id != condition.version_id
                or version.source_sha256 != condition.source_sha256):
            _fail("invalid_ownership")
        if condition.dimension == "DEPARTMENT":
            scope_state, scope_ids = version.department_scope_state, version.department_scope_ids
        else:
            scope_state, scope_ids = version.procedure_scope_state, version.procedure_scope_ids
        if condition.scope_state != scope_state or condition.scope_ids != scope_ids:
            _fail("invalid_ownership")
        for passage_id in condition.evidence_passage_ids:
            passage = passages.get((condition.document_id, condition.version_id,
                                    condition.source_sha256, passage_id))
            if passage is None:
                _fail("invalid_citation")
            if (condition.node_id, passage.node_id) not in derived_pairs:
                _fail("invalid_citation")


def _pair_from_version_nodes(nodes: dict[str, GraphNode], comparison_id: str) -> PolicyPair:
    """Only used to reapply the existing exact citation validator."""
    from policy_compare import ImpactDependency, PolicyVersion as CorePolicyVersion
    from policy_compare import Scope, ScopeSet
    versions = sorted(
        (node for node in nodes.values() if type(node) is PolicyVersion),
        key=lambda node: (node.effective_from or date.min, node.version_id),
    )
    if len(versions) != 2:
        _fail("invalid_graph")
    converted = []
    for item in versions:
        passage_nodes = sorted(
            (node for node in nodes.values() if type(node) is SourcePassage
             and node.document_id == item.document_id and node.version_id == item.version_id
             and node.source_sha256 == item.source_sha256), key=lambda node: node.ordinal,
        )
        from policy_compare import Passage
        passages = tuple(Passage(p.passage_id, p.ordinal, p.start_cp, p.end_cp,
                                 p.text, p.text_sha256) for p in passage_nodes)
        converted.append(CorePolicyVersion(
            item.document_id, item.version_id, item.original_text, item.source_sha256,
            item.effective_from, item.effective_to_exclusive,
            Scope(ScopeSet(item.department_scope_state, item.department_scope_ids),
                  ScopeSet(item.procedure_scope_state, item.procedure_scope_ids),
                  item.property_id, tuple()),
            item.text_coverage, passages, tuple(),
        ))
    return PolicyPair(1, comparison_id, converted[0], converted[1])


def _validate_graph(graph: EvidenceDependencyGraph) -> None:
    _validate_graph_contents(graph)


def _validate_graph_contents(graph: EvidenceDependencyGraph) -> None:
    if type(graph) is not EvidenceDependencyGraph or not _valid_string(graph.snapshot_identity, maximum=10_000):
        _fail("invalid_graph")
    if len(graph.nodes) > MAX_GRAPH_NODES or len(graph.edges) > MAX_GRAPH_EDGES:
        _fail("invalid_graph")
    nodes: dict[str, GraphNode] = {}
    for node in graph.nodes:
        _validate_node_shape(node)
        if node.node_id in nodes:
            _fail("duplicate_node")
        nodes[node.node_id] = node
    comparison_ids = {
        node.comparison_id for node in nodes.values()
        if type(node) in (Claim, ApplicabilityCondition, ComparisonRelation,
                          Conclusion, ChallengeEvent)
    }
    if len(comparison_ids) != 1:
        _fail("invalid_graph")
    graph_comparison_id = next(iter(comparison_ids))
    if any(node.comparison_id != graph_comparison_id
           for node in nodes.values() if type(node) is ChallengeEvent):
        _fail("invalid_ownership")
    edges: dict[str, GraphEdge] = {}
    typed_edges: set[tuple[str, EdgeType, str]] = set()
    for edge in graph.edges:
        _validate_edge(edge, nodes)
        if edge.edge_id in edges or (edge.source_id, edge.edge_type, edge.target_id) in typed_edges:
            _fail("duplicate_edge")
        edges[edge.edge_id] = edge
        typed_edges.add((edge.source_id, edge.edge_type, edge.target_id))

    # Every proposal citation must have exactly one matching provenance edge.
    derived_pairs = {
        (edge.source_id, edge.target_id) for edge in edges.values()
        if edge.edge_type is EdgeType.DERIVED_FROM
    }
    for node in nodes.values():
        if type(node) is not Claim:
            continue
        passage_ids = {source_passage_id(citation.document_id, citation.version_id,
                                         citation.source_sha256, citation.passage_id)
                       for citation in node.citations}
        for passage_id in passage_ids:
            if (node.node_id, passage_id) not in derived_pairs:
                _fail("invalid_citation")
    _validate_citations(nodes)
    _validate_applicability_provenance(nodes, edges)

    if graph.snapshot_identity != _snapshot_identity(graph.nodes):
        _fail("invalid_graph")

    # Kahn's algorithm covers every dependency edge without recursion. Sorting
    # the ready queue and adjacency lists keeps traversal deterministic.
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in nodes}
    for edge in edges.values():
        if edge.edge_type is EdgeType.DEPENDS_ON:
            adjacency[edge.source_id].append(edge.target_id)
            indegree[edge.target_id] += 1
    for targets in adjacency.values():
        targets.sort()
    ready = [node_id for node_id in sorted(indegree) if indegree[node_id] == 0]
    heapq.heapify(ready)
    visited_count = 0
    while ready:
        node_id = heapq.heappop(ready)
        visited_count += 1
        for target_id in adjacency[node_id]:
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                heapq.heappush(ready, target_id)
    if visited_count != len(nodes):
        _fail("dependency_cycle")


def create_graph(
    nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...],
) -> EvidenceDependencyGraph:
    """Construct, sort, and validate a graph with a provisional identity."""
    _prevalidate_construction_inputs("provisional-pending", nodes, edges)
    ordered_nodes = tuple(sorted(nodes, key=lambda node: node.node_id))
    identity = _snapshot_identity(ordered_nodes)
    return EvidenceDependencyGraph(identity, ordered_nodes, edges)


def _version_nodes(pair: PolicyPair) -> tuple[list[GraphNode], dict[tuple[str, str], PolicyVersion]]:
    nodes: list[GraphNode] = []
    versions: dict[tuple[str, str], PolicyVersion] = {}
    nodes.append(SourceDocument(source_document_id(pair.older.document_id),
                                EpistemicStatus.SOURCE_VALIDATED, pair.older.document_id))
    for version in (pair.older, pair.newer):
        node = PolicyVersion(
            policy_version_id(version.document_id, version.version_id, version.source_sha256),
            EpistemicStatus.SOURCE_VALIDATED, version.document_id, version.version_id,
            version.source_sha256, version.original_text, version.effective_from,
            version.effective_to_exclusive, version.scope.departments.state,
            version.scope.departments.ids, version.scope.procedures.state,
            version.scope.procedures.ids, version.scope.property_id, version.text_coverage,
        )
        nodes.append(node)
        versions[(version.document_id, version.version_id)] = node
        for passage in version.passages:
            nodes.append(SourcePassage(
                source_passage_id(version.document_id, version.version_id,
                                  version.source_sha256, passage.passage_id),
                EpistemicStatus.SOURCE_VALIDATED, version.document_id,
                version.version_id, version.source_sha256, passage.passage_id,
                passage.ordinal, passage.start_cp, passage.end_cp, passage.text,
                passage.text_sha256,
            ))
    return nodes, versions


def project_policy_graph(
    pair: PolicyPair,
    initial_investigation: dict[str, object],
    challenge: ReviewerChallenge,
) -> EvidenceDependencyGraph:
    """Project validated policy-demo data without changing its API behavior."""
    if type(pair) is not PolicyPair or type(challenge) is not ReviewerChallenge:
        _fail("invalid_graph")
    if (type(initial_investigation) is not dict
            or initial_investigation.get("comparison_id") != pair.comparison_id
            or pair.comparison_id != "cmp-syn-hotel-luminary-001"
            or challenge.target_department != "HOUSEKEEPING"):
        _fail("invalid_graph")

    nodes, version_nodes = _version_nodes(pair)
    edges: list[GraphEdge] = []
    document_node = source_document_id(pair.older.document_id)
    for version in (pair.older, pair.newer):
        version_node_id = policy_version_id(version.document_id, version.version_id,
                                            version.source_sha256)
        edges.append(make_edge(document_node, version_node_id, EdgeType.CONTAINS,
                               EpistemicStatus.SOURCE_VALIDATED,
                               "Validated document identifier contains this policy version."))
        for passage in version.passages:
            passage_node_id = source_passage_id(version.document_id, version.version_id,
                                                version.source_sha256, passage.passage_id)
            edges.append(make_edge(version_node_id, passage_node_id, EdgeType.CONTAINS,
                                   EpistemicStatus.SOURCE_VALIDATED,
                                   "Passage span and digest derive from this validated version."))

    applicability = evaluate_department_applicability(pair, challenge.target_department)
    condition_ids: dict[tuple[str, str], str] = {}
    for core_version in (pair.older, pair.newer):
        node_version = version_nodes[(core_version.document_id, core_version.version_id)]
        explicit_passages = set(core_version.scope.evidence_passage_ids)
        for dependency in core_version.impact_dependencies:
            if dependency.department_id == challenge.target_department:
                explicit_passages.update(dependency.passage_ids)
        challenged = (core_version.version_id == pair.older.version_id
                      and challenge.target_side == "OLDER")
        condition_status = EpistemicStatus.CHALLENGED if challenged else EpistemicStatus.UNVERIFIED
        applicability_status = ("UNGROUNDED" if applicability["applicability_status"] == "UNGROUNDED"
                                 else "GROUNDED")
        condition = ApplicabilityCondition(
            applicability_node_id(pair.comparison_id, core_version.document_id,
                                   core_version.version_id, core_version.source_sha256,
                                   "DEPARTMENT", challenge.target_department),
            condition_status, pair.comparison_id, core_version.document_id,
            core_version.version_id, core_version.source_sha256, "DEPARTMENT",
            challenge.target_department, core_version.scope.departments.state,
            core_version.scope.departments.ids, tuple(sorted(explicit_passages)),
            applicability_status,
        )
        nodes.append(condition)
        condition_ids[(core_version.document_id, core_version.version_id)] = condition.node_id
        for passage_id in sorted(explicit_passages):
            passage_node_id = source_passage_id(core_version.document_id, core_version.version_id,
                                                core_version.source_sha256, passage_id)
            edges.append(make_edge(condition.node_id, passage_node_id, EdgeType.DERIVED_FROM,
                                   EpistemicStatus.SOURCE_VALIDATED,
                                   "Applicability metadata references this source passage; semantic interpretation remains unverified."))
        known_applies = (
            core_version.scope.departments.state == "ALL"
            or (core_version.scope.departments.state == "KNOWN"
                and challenge.target_department in core_version.scope.departments.ids)
        )
        if known_applies:
            edges.append(make_edge(node_version.node_id, condition.node_id, EdgeType.APPLIES_TO,
                                   EpistemicStatus.SOURCE_VALIDATED,
                                   "Structured department scope or impact metadata names this target."))

    candidate_id = initial_investigation.get("candidate_id")
    proposed_relation = initial_investigation.get("proposed_relation")
    summary = initial_investigation.get("reasoning")
    details = initial_investigation.get("provenance_details")
    if (type(candidate_id) is not str or _CANDIDATE_ID.fullmatch(candidate_id) is None
            or type(proposed_relation) is not str
            or type(summary) is not str or type(details) is not list):
        _fail("invalid_graph")

    citation_refs: list[CitationReference] = []
    for detail in details:
        if type(detail) is not dict:
            _fail("invalid_citation")
        side = detail.get("side")
        version = pair.older if side == "OLDER" else pair.newer if side == "NEWER" else None
        if version is None:
            _fail("invalid_citation")
        try:
            citation = validate_citation(pair, {
                "document_id": version.document_id,
                "version_id": version.version_id,
                "source_sha256": detail.get("source_sha256"),
                "passage_id": detail.get("passage_id"),
                "start_cp": detail.get("start_cp"),
                "end_cp": detail.get("end_cp"),
                "quote": detail.get("quote"),
            }, expected_side=side)
        except PolicyCompareError:
            _fail("invalid_citation")
        citation_refs.append(CitationReference(
            side, citation["document_id"], citation["version_id"],
            citation["source_sha256"], citation["passage_id"],
            citation["start_cp"], citation["end_cp"], citation["quote"],
        ))

    claim = Claim(claim_node_id(pair.comparison_id, candidate_id),
                  EpistemicStatus.PROPOSED, pair.comparison_id, candidate_id,
                  summary[:1_000], proposed_relation, tuple(citation_refs))
    relation = ComparisonRelation(
        comparison_relation_node_id(pair.comparison_id, candidate_id),
        EpistemicStatus.PROPOSED, pair.comparison_id, candidate_id,
        proposed_relation, claim.node_id,
    )
    classification = initial_investigation.get("core_classification")
    proposed_classification = initial_investigation.get("core_proposed_classification")
    uncertainty = initial_investigation.get("uncertainty_reasons")
    human_review = initial_investigation.get("human_review_required")
    policy_mutated = initial_investigation.get("official_policy_mutated")
    if (type(classification) is not str or type(proposed_classification) is not str
            or type(uncertainty) is not list or any(type(item) is not str for item in uncertainty)
            or type(human_review) is not bool or type(policy_mutated) is not bool):
        _fail("invalid_graph")
    conclusion = Conclusion(
        conclusion_node_id(pair.comparison_id, candidate_id),
        EpistemicStatus.LOCALLY_DERIVED, pair.comparison_id, candidate_id,
        classification, proposed_classification, tuple(sorted(set(uncertainty))),
        human_review, policy_mutated,
    )

    target_version = pair.older if challenge.target_side == "OLDER" else pair.newer
    target_passage = target_version.passage(challenge.target_passage_id)
    if (target_passage is None or challenge.target_quote not in target_passage.text
            or challenge.target_department != "HOUSEKEEPING"):
        _fail("invalid_citation")
    challenge_node = ChallengeEvent(
        challenge_event_node_id(pair.comparison_id, challenge.challenge_id),
        EpistemicStatus.CHALLENGED, pair.comparison_id, challenge.challenge_id,
        SCENARIO_SCHEDULING, challenge.target_department, challenge.target_side,
        target_version.document_id, target_version.version_id, target_version.source_sha256,
        challenge.target_passage_id, challenge.target_quote,
        challenge.challenge_description[:MAX_DESCRIPTION_CHARS],
    )

    nodes.extend((claim, relation, conclusion, challenge_node))
    cited_passages = {
        source_passage_id(citation.document_id, citation.version_id,
                          citation.source_sha256, citation.passage_id)
        for citation in citation_refs
    }
    for passage_node in sorted(cited_passages):
        edges.append(make_edge(claim.node_id, passage_node, EdgeType.DERIVED_FROM,
                               EpistemicStatus.SOURCE_VALIDATED,
                               "Exact citation source/version/span validated; this does not establish semantic support."))
    edges.extend((
        make_edge(relation.node_id, claim.node_id, EdgeType.DEPENDS_ON,
                  EpistemicStatus.LOCALLY_DERIVED,
                  "The proposed comparison relation is the candidate claim's recorded relation."),
        make_edge(conclusion.node_id, relation.node_id, EdgeType.DEPENDS_ON,
                  EpistemicStatus.LOCALLY_DERIVED,
                  "The validated conclusion retains the candidate relation as a proposal."),
    ))
    target_passage_node = source_passage_id(target_version.document_id, target_version.version_id,
                                           target_version.source_sha256, target_passage.passage_id)
    edges.extend((
        make_edge(challenge_node.node_id, target_passage_node, EdgeType.AFFECTS,
                  EpistemicStatus.CHALLENGED,
                  "The challenge requests reassessment of this cited rule; it does not refute the text."),
        make_edge(challenge_node.node_id,
                  condition_ids[(target_version.document_id, target_version.version_id)],
                  EdgeType.AFFECTS, EpistemicStatus.CHALLENGED,
                  "The challenge questions department applicability; it does not establish non-applicability."),
    ))
    return create_graph(tuple(nodes), tuple(edges))


def build_scheduling_graph() -> EvidenceDependencyGraph:
    """Build the existing fictional 48-hour/24-hour Housekeeping projection."""
    pair = build_hotel_scheduling_policy_pair()
    initial = run_initial_evidence_investigation(pair)
    challenge = build_scenario_reviewer_challenge(
        pair, initial, "HOUSEKEEPING", scenario_id=SCENARIO_SCHEDULING,
    )
    return project_policy_graph(pair, initial, challenge)
