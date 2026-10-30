"""Offline integrity tests for the synthetic policy dependency graph."""
from copy import deepcopy
from dataclasses import fields, replace
from enum import Enum

import pytest
import policy_dependency_graph as dependency_graph_module

from policy_compare import validate_policy_pair
from policy_dependency_graph import (
    ApplicabilityCondition,
    ChallengeEvent,
    Claim,
    ComparisonRelation,
    Conclusion,
    DependencyGraphError,
    EvidenceDependencyGraph,
    EdgeType,
    EpistemicStatus,
    MAX_AGGREGATE_NESTED_ENTRIES,
    MAX_AGGREGATE_REFERENCES,
    MAX_AGGREGATE_TEXT_BYTES,
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    MAX_SNAPSHOT_IDENTITY_BYTES,
    PolicyVersion,
    SourceDocument,
    SourcePassage,
    build_scheduling_graph,
    claim_node_id,
    applicability_node_id,
    challenge_event_node_id,
    create_graph,
    make_edge,
    _validate_edge,
    policy_version_id,
    project_policy_graph,
    source_passage_id,
    _prevalidate_construction_inputs,
    _snapshot_identity,
)
from policy_evidence_demo import (
    SCENARIO_SCHEDULING,
    build_hotel_scheduling_policy_pair,
    build_scenario_reviewer_challenge,
    run_initial_evidence_investigation,
)


@pytest.fixture
def graph():
    return build_scheduling_graph()


def _all_versions(pair, older_text=None):
    def version_data(version, text):
        return {
            "document_id": version.document_id,
            "version_id": version.version_id,
            "original_text": text,
            "effective_from": version.effective_from.isoformat() if version.effective_from else None,
            "effective_to_exclusive": version.effective_to_exclusive.isoformat() if version.effective_to_exclusive else None,
            "scope": {
                "departments": {"state": version.scope.departments.state,
                                "ids": list(version.scope.departments.ids)},
                "procedures": {"state": version.scope.procedures.state,
                               "ids": list(version.scope.procedures.ids)},
                "property_id": version.scope.property_id,
                "evidence_passage_ids": list(version.scope.evidence_passage_ids),
            },
            "text_coverage": version.text_coverage,
            "impact_dependencies": [{
                "department_id": item.department_id,
                "procedure_id": item.procedure_id,
                "passage_ids": list(item.passage_ids),
            } for item in version.impact_dependencies],
        }

    return validate_policy_pair({
        "schema_version": pair.schema_version,
        "comparison_id": pair.comparison_id,
        "older": version_data(pair.older, older_text if older_text is not None else pair.older.original_text),
        "newer": version_data(pair.newer, pair.newer.original_text),
    })


def _project(pair=None):
    pair = pair or build_hotel_scheduling_policy_pair()
    initial = run_initial_evidence_investigation(pair)
    challenge = build_scenario_reviewer_challenge(
        pair, initial, "HOUSEKEEPING", scenario_id=SCENARIO_SCHEDULING,
    )
    return project_policy_graph(pair, initial, challenge)


def _replace_graph(graph, *, nodes=None, edges=None):
    return create_graph(graph.nodes if nodes is None else tuple(nodes),
                        graph.edges if edges is None else tuple(edges))


def _payload_totals(snapshot_identity, nodes, edges):
    """Independent test accounting for the documented logical payload budget."""
    totals = {"bytes": MAX_SNAPSHOT_IDENTITY_BYTES, "references": 0, "nested": 0}

    def visit(value, field_name=""):
        if type(value) is str:
            totals["bytes"] += len(value.encode("utf-8", "strict"))
        elif isinstance(value, Enum):
            totals["bytes"] += len(value.value.encode("utf-8", "strict"))
        elif type(value) is tuple:
            totals["nested"] += len(value)
            if field_name in {"citations", "evidence_passage_ids"}:
                totals["references"] += len(value)
            for item in value:
                visit(item)
        elif hasattr(type(value), "__dataclass_fields__"):
            for item in fields(value):
                visit(getattr(value, item.name), item.name)

    for node in nodes:
        visit(node)
    for edge in edges:
        visit(edge)
    return totals


def _graph_for_payload_bytes(graph, target):
    base = next(node for node in graph.nodes if type(node) is Claim)
    nodes = list(graph.nodes)
    current = _payload_totals(graph.snapshot_identity, tuple(nodes), graph.edges)["bytes"]
    candidate_id = "cand-bytebudget-00000"
    blank = replace(base, node_id=claim_node_id(base.comparison_id, candidate_id),
                    candidate_id=candidate_id, summary="", citations=())
    overhead = (_payload_totals(graph.snapshot_identity, (*nodes, blank), graph.edges)["bytes"]
                - current)
    step = overhead + 1_000
    full_count, remainder = divmod(target - current, step)
    partial_size = 0
    grow_existing = remainder if remainder and remainder <= overhead else 0
    if remainder and not grow_existing:
        partial_size = remainder - overhead
        assert 1 <= partial_size <= 1_000
    for index in range(full_count):
        candidate_id = f"cand-bytebudget-{index:05d}"
        nodes.append(replace(base, node_id=claim_node_id(base.comparison_id, candidate_id),
                             candidate_id=candidate_id, summary="x" * 1_000, citations=()))
    if partial_size:
        index = full_count
        candidate_id = f"cand-bytebudget-{index:05d}"
        nodes.append(replace(base, node_id=claim_node_id(base.comparison_id, candidate_id),
                             candidate_id=candidate_id, summary="x" * partial_size, citations=()))
    growth_left = grow_existing
    for index, node in enumerate(nodes):
        if growth_left == 0:
            break
        if type(node) is Claim and len(node.summary) < 1_000:
            increase = min(growth_left, 1_000 - len(node.summary))
            nodes[index] = replace(node, summary=node.summary + "x" * increase)
            growth_left -= increase
    assert growth_left == 0
    assert _payload_totals(graph.snapshot_identity, tuple(nodes), graph.edges)["bytes"] == target
    return tuple(nodes)


def _pad_nodes_to_payload_bytes(graph, nodes, edges, target):
    """Add valid empty proposal nodes and bounded summaries to reach a byte total."""
    nodes = list(nodes)
    base = next(node for node in nodes if type(node) is Claim)
    current = _payload_totals(graph.snapshot_identity, tuple(nodes), edges)["bytes"]
    assert current <= target
    candidate_id = "cand-combined-budget-00000"
    blank = replace(base, node_id=claim_node_id(base.comparison_id, candidate_id),
                    candidate_id=candidate_id, summary="", citations=())
    overhead = (_payload_totals(graph.snapshot_identity, (*nodes, blank), edges)["bytes"]
                - current)
    step = overhead + 1_000
    full_count, remainder = divmod(target - current, step)
    grow_existing = remainder if remainder and remainder <= overhead else 0
    partial_size = 0
    if remainder and not grow_existing:
        partial_size = remainder - overhead
        assert 1 <= partial_size <= 1_000
    for index in range(full_count):
        candidate_id = f"cand-combined-budget-{index:05d}"
        nodes.append(replace(
            base, node_id=claim_node_id(base.comparison_id, candidate_id),
            candidate_id=candidate_id, summary="x" * 1_000, citations=(),
        ))
    if partial_size:
        index = full_count
        candidate_id = f"cand-combined-budget-{index:05d}"
        nodes.append(replace(
            base, node_id=claim_node_id(base.comparison_id, candidate_id),
            candidate_id=candidate_id, summary="x" * partial_size, citations=(),
        ))
    growth_left = grow_existing
    for index, node in enumerate(nodes):
        if growth_left == 0:
            break
        if type(node) is Claim and len(node.summary) < 1_000:
            increase = min(growth_left, 1_000 - len(node.summary))
            nodes[index] = replace(node, summary=node.summary + "x" * increase)
            growth_left -= increase
    assert growth_left == 0
    assert _payload_totals(graph.snapshot_identity, tuple(nodes), edges)["bytes"] == target
    return tuple(nodes)


def _construct(nodes, edges, path, identity):
    if path == "factory":
        return create_graph(nodes, edges)
    return EvidenceDependencyGraph(identity, nodes, edges)


def test_valid_typed_graph_construction_and_epistemic_statuses(graph):
    by_type = {type(node) for node in graph.nodes}
    assert {SourceDocument, PolicyVersion, SourcePassage, Claim,
            ApplicabilityCondition, ComparisonRelation, Conclusion} <= by_type
    assert any(node.epistemic_status is EpistemicStatus.CHALLENGED
               for node in graph.nodes if type(node) is ApplicabilityCondition)
    assert graph.snapshot_identity.startswith("provisional-graph-v1|")


def test_ids_are_stable_across_identical_construction():
    first = build_scheduling_graph()
    second = build_scheduling_graph()
    assert first.snapshot_identity == second.snapshot_identity
    assert [node.node_id for node in first.nodes] == [node.node_id for node in second.nodes]
    assert [edge.edge_id for edge in first.edges] == [edge.edge_id for edge in second.edges]


def test_full_source_hash_changes_passage_identity():
    pair = build_hotel_scheduling_policy_pair()
    changed = _all_versions(pair, pair.older.original_text + "\n\nSynthetic appendix.")
    graph_one, graph_two = _project(pair), _project(changed)
    old_one = next(node for node in graph_one.nodes
                   if type(node) is SourcePassage and node.version_id == "v1" and node.ordinal == 2)
    old_two = next(node for node in graph_two.nodes
                   if type(node) is SourcePassage and node.version_id == "v1" and node.ordinal == 2)
    assert old_one.passage_id == old_two.passage_id
    assert old_one.source_sha256 != old_two.source_sha256
    assert old_one.node_id != old_two.node_id


def test_duplicate_node_rejected(graph):
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=(*graph.nodes, graph.nodes[0]))
    assert error.value.code == "duplicate_node"


def test_duplicate_typed_edge_rejected(graph):
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, edges=(*graph.edges, graph.edges[0]))
    assert error.value.code == "duplicate_edge"


def test_missing_node_reference_rejected(graph):
    relation = next(node for node in graph.nodes if type(node) is ComparisonRelation)
    missing = make_edge(relation.node_id, "claim:missing", EdgeType.DEPENDS_ON,
                        EpistemicStatus.LOCALLY_DERIVED, "Synthetic missing reference.")
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, edges=(*graph.edges, missing))
    assert error.value.code == "missing_reference"


def test_invalid_edge_direction_rejected(graph):
    document = next(node for node in graph.nodes if type(node) is SourceDocument)
    passage = next(node for node in graph.nodes if type(node) is SourcePassage)
    invalid = make_edge(document.node_id, passage.node_id, EdgeType.CONTAINS,
                        EpistemicStatus.SOURCE_VALIDATED, "Invalid source/target types.")
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, edges=(*graph.edges, invalid))
    assert error.value.code == "invalid_edge"


def test_cross_version_citation_reference_rejected(graph):
    citation_edge = next(edge for edge in graph.edges
                         if edge.edge_type is EdgeType.DERIVED_FROM
                         and next(node for node in graph.nodes if node.node_id == edge.source_id).__class__ is Claim
                         and next(node for node in graph.nodes if node.node_id == edge.target_id).version_id == "v1")
    target = next(node for node in graph.nodes
                  if type(node) is SourcePassage and node.version_id == "v2" and node.ordinal == 3)
    wrong = make_edge(citation_edge.source_id, target.node_id, EdgeType.DERIVED_FROM,
                      EpistemicStatus.SOURCE_VALIDATED, citation_edge.provenance)
    edges = tuple(edge for edge in graph.edges if edge.edge_id != citation_edge.edge_id) + (wrong,)
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, edges=edges)
    assert error.value.code in {"invalid_citation", "invalid_offsets"}


def test_invalid_passage_ownership_rejected(graph):
    passage = next(node for node in graph.nodes if type(node) is SourcePassage)
    incorrect_owner = replace(passage, document_id="syn-policy-other")
    nodes = tuple(incorrect_owner if item.node_id == passage.node_id else item for item in graph.nodes)
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=nodes)
    assert error.value.code in {"invalid_node", "invalid_ownership"}


def test_invalid_source_offsets_rejected(graph):
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.version_id == "v1" and node.ordinal == 2)
    shifted = replace(passage, start_cp=passage.start_cp + 1)
    nodes = tuple(shifted if item.node_id == passage.node_id else item for item in graph.nodes)
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=nodes)
    assert error.value.code in {"invalid_offsets", "invalid_citation"}


def test_unknown_applicability_has_no_applies_to_edge(graph):
    conditions = [node for node in graph.nodes if type(node) is ApplicabilityCondition]
    assert len(conditions) == 2
    assert all(node.scope_state == "UNKNOWN" for node in conditions)
    assert all(node.applicability_status == "UNGROUNDED" for node in conditions)
    assert not any(edge.edge_type is EdgeType.APPLIES_TO for edge in graph.edges)


def test_semantic_support_edges_cannot_be_marked_verified(graph):
    passage = next(node for node in graph.nodes if type(node) is SourcePassage)
    claim = next(node for node in graph.nodes if type(node) is Claim)
    assert not any(edge.edge_type in {EdgeType.SUPPORTS, EdgeType.CONTRADICTS}
                   for edge in graph.edges)
    unsupported = make_edge(passage.node_id, claim.node_id, EdgeType.SUPPORTS,
                            EpistemicStatus.SOURCE_VALIDATED,
                            "An exact quote is not semantic support.")
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, edges=(*graph.edges, unsupported))
    assert error.value.code == "invalid_edge"


def test_dependency_cycle_is_rejected(graph):
    base_claim = next(node for node in graph.nodes if type(node) is Claim)
    claim_a = replace(base_claim, node_id=claim_node_id(base_claim.comparison_id, "cand-cycle-a"),
                      candidate_id="cand-cycle-a", citations=())
    claim_b = replace(base_claim, node_id=claim_node_id(base_claim.comparison_id, "cand-cycle-b"),
                      candidate_id="cand-cycle-b", citations=())
    cycle_edges = (
        make_edge(claim_a.node_id, claim_b.node_id, EdgeType.DEPENDS_ON,
                  EpistemicStatus.PROPOSED, "Synthetic dependency A to B."),
        make_edge(claim_b.node_id, claim_a.node_id, EdgeType.DEPENDS_ON,
                  EpistemicStatus.PROPOSED, "Synthetic dependency B to A."),
    )
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=(*graph.nodes, claim_a, claim_b),
                       edges=(*graph.edges, *cycle_edges))
    assert error.value.code == "dependency_cycle"


def test_graph_order_is_deterministic_for_shuffled_input(graph):
    shuffled = create_graph(tuple(reversed(graph.nodes)), tuple(reversed(graph.edges)))
    assert shuffled.snapshot_identity == graph.snapshot_identity
    assert shuffled.nodes == graph.nodes
    assert shuffled.edges == graph.edges


def test_scheduling_projection_contains_both_versions_citations_and_challenge(graph):
    versions = [node for node in graph.nodes if type(node) is PolicyVersion]
    passages = [node for node in graph.nodes if type(node) is SourcePassage]
    claim = next(node for node in graph.nodes if type(node) is Claim)
    event = next(node for node in graph.nodes if node.node_type.value == "ChallengeEvent")
    assert {node.version_id for node in versions} == {"v1", "v2"}
    assert len(passages) >= 6
    assert len(claim.citations) == 2
    assert all(any(edge.edge_type is EdgeType.DERIVED_FROM
                   and edge.source_id == claim.node_id
                   and edge.target_id == source_passage_id(ref.document_id, ref.version_id,
                                                          ref.source_sha256, ref.passage_id)
                   for edge in graph.edges) for ref in claim.citations)
    assert any(edge.edge_type is EdgeType.AFFECTS and edge.source_id == event.node_id
               for edge in graph.edges)


def test_validated_conclusion_remains_inconclusive(graph):
    conclusion = next(node for node in graph.nodes if type(node) is Conclusion)
    relation = next(node for node in graph.nodes if type(node) is ComparisonRelation)
    assert relation.relation == "COMPATIBLE_CHANGE"
    assert conclusion.classification == "INCONCLUSIVE"
    assert conclusion.proposed_classification == "COMPATIBLE_CHANGE"


def test_review_and_policy_mutation_flags_are_preserved(graph):
    conclusion = next(node for node in graph.nodes if type(node) is Conclusion)
    assert conclusion.human_review_required is True
    assert conclusion.official_policy_mutated is False


def test_invalid_epistemic_status_is_rejected(graph):
    document = next(node for node in graph.nodes if type(node) is SourceDocument)
    invalid = replace(document, epistemic_status="SOURCE_VALIDATED")
    nodes = tuple(invalid if item.node_id == document.node_id else item for item in graph.nodes)
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=nodes)
    assert error.value.code == "invalid_node"


def test_node_types_have_no_unrecognized_mutable_attributes(graph):
    document = next(node for node in graph.nodes if type(node) is SourceDocument)
    with pytest.raises((AttributeError, TypeError)):
        document.unrecognized = "value"  # type: ignore[attr-defined]


def _claim_cycle_nodes(graph, count, prefix):
    base = next(node for node in graph.nodes if type(node) is Claim)
    return tuple(
        replace(base, node_id=claim_node_id(base.comparison_id, f"cand-{prefix}-{index:04d}"),
                candidate_id=f"cand-{prefix}-{index:04d}", citations=())
        for index in range(count)
    )


def _cycle_edges(nodes):
    return tuple(make_edge(node.node_id, nodes[(index + 1) % len(nodes)].node_id,
                           EdgeType.DEPENDS_ON, EpistemicStatus.PROPOSED,
                           "Synthetic cycle edge.")
                 for index, node in enumerate(nodes))


@pytest.mark.parametrize("scope_state,scope_ids,evidence,accepted", [
    ("KNOWN", ("HOUSEKEEPING",), (), True),
    ("KNOWN", ("HOUSEKEEPING",), ("p000001-0000000000000000",), True),
    ("KNOWN", ("FRONT_DESK",), (), False),
    ("KNOWN", ("FRONT_DESK",), ("p000001-0000000000000000",), False),
    ("UNKNOWN", (), (), False),
    ("UNKNOWN", (), ("p000001-0000000000000000",), False),
    ("ALL", (), ("p000001-0000000000000000",), True),
])
def test_applies_to_uses_explicit_department_scope_not_evidence_alone(
        graph, scope_state, scope_ids, evidence, accepted):
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    version = next(node for node in graph.nodes
                   if type(node) is PolicyVersion and node.version_id == condition.version_id)
    version = replace(version, department_scope_state=scope_state,
                      department_scope_ids=scope_ids)
    condition = replace(condition, scope_state=scope_state, scope_ids=scope_ids,
                         evidence_passage_ids=evidence)
    edge = make_edge(version.node_id, condition.node_id, EdgeType.APPLIES_TO,
                     EpistemicStatus.SOURCE_VALIDATED, "Synthetic applicability check.")
    node_map = {version.node_id: version, condition.node_id: condition}
    if accepted:
        _validate_edge(edge, node_map)
    else:
        with pytest.raises(DependencyGraphError):
            _validate_edge(edge, node_map)


@pytest.mark.parametrize("target_type", [Claim, ComparisonRelation, Conclusion])
def test_challenge_affects_related_candidate_target(graph, target_type):
    event = next(node for node in graph.nodes if type(node) is ChallengeEvent)
    target = next(node for node in graph.nodes if type(node) is target_type)
    edge = make_edge(event.node_id, target.node_id, EdgeType.AFFECTS,
                     EpistemicStatus.CHALLENGED, "Challenge targets its cited candidate context.")
    updated = _replace_graph(graph, edges=(*graph.edges, edge))
    assert edge in updated.edges


@pytest.mark.parametrize("target_type", [Claim, ComparisonRelation, Conclusion])
def test_challenge_rejects_unrelated_candidate_target(graph, target_type):
    event = next(node for node in graph.nodes if type(node) is ChallengeEvent)
    claim = next(node for node in graph.nodes if type(node) is Claim)
    if target_type is Claim:
        target = replace(claim, node_id=claim_node_id(claim.comparison_id, "cand-unrelated"),
                         candidate_id="cand-unrelated", citations=())
    elif target_type is ComparisonRelation:
        base = next(node for node in graph.nodes if type(node) is ComparisonRelation)
        target = replace(base, node_id=f"comparison-relation:{base.comparison_id}:cand-unrelated",
                         candidate_id="cand-unrelated", claim_node_id=claim.node_id)
    else:
        base = next(node for node in graph.nodes if type(node) is Conclusion)
        target = replace(base, node_id=f"conclusion:{base.comparison_id}:cand-unrelated:validated",
                         candidate_id="cand-unrelated")
    edge = make_edge(event.node_id, target.node_id, EdgeType.AFFECTS,
                     EpistemicStatus.CHALLENGED, "Status alone does not establish ownership.")
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=(*graph.nodes, target), edges=(*graph.edges, edge))
    assert error.value.code == "invalid_ownership"


def test_dependency_self_cycle_is_rejected(graph):
    claim = _claim_cycle_nodes(graph, 1, "self")[0]
    edge = make_edge(claim.node_id, claim.node_id, EdgeType.DEPENDS_ON,
                     EpistemicStatus.PROPOSED, "Synthetic self cycle.")
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=(*graph.nodes, claim), edges=(*graph.edges, edge))
    assert error.value.code == "dependency_cycle"


def test_larger_disconnected_dependency_cycle_is_rejected(graph):
    cycle = _claim_cycle_nodes(graph, 4, "disconnected")
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, nodes=(*graph.nodes, *cycle),
                       edges=(*graph.edges, *_cycle_edges(cycle)))
    assert error.value.code == "dependency_cycle"


def test_long_acyclic_dependency_chain_at_node_limit_is_accepted(graph):
    from policy_dependency_graph import MAX_GRAPH_NODES
    count = MAX_GRAPH_NODES - len(graph.nodes)
    chain = _claim_cycle_nodes(graph, count, "longchain")
    edges = tuple(make_edge(left.node_id, right.node_id, EdgeType.DEPENDS_ON,
                            EpistemicStatus.PROPOSED, "Synthetic acyclic chain.")
                  for left, right in zip(chain, chain[1:]))
    result = _replace_graph(graph, nodes=(*graph.nodes, *chain), edges=(*graph.edges, *edges))
    assert len(result.nodes) == MAX_GRAPH_NODES


def test_non_dependency_challenge_edges_are_not_counted_as_cycles(graph):
    event = next(node for node in graph.nodes if type(node) is ChallengeEvent)
    claim = next(node for node in graph.nodes if type(node) is Claim)
    edge = make_edge(event.node_id, claim.node_id, EdgeType.AFFECTS,
                     EpistemicStatus.CHALLENGED, "Non-dependency relationship.")
    result = _replace_graph(graph, edges=(*graph.edges, edge))
    assert edge in result.edges


@pytest.mark.parametrize("mutate", [
    lambda node: replace(node, comparison_id=[]),
    lambda node: replace(node, comparison_id=""),
    lambda node: replace(node, candidate_id=[]),
])
def test_malformed_unhashable_or_missing_identity_fields_use_controlled_error(graph, mutate):
    claim = next(node for node in graph.nodes if type(node) is Claim)
    invalid = mutate(claim)
    nodes = tuple(invalid if item.node_id == claim.node_id else item for item in graph.nodes)
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, graph.edges)


def test_unexpected_node_type_uses_controlled_error(graph):
    with pytest.raises(DependencyGraphError):
        create_graph((*graph.nodes, object()), graph.edges)


def test_projection_preserves_notice_text_and_does_not_mutate_inputs():
    pair = build_hotel_scheduling_policy_pair()
    initial = run_initial_evidence_investigation(pair)
    pair_before, initial_before = deepcopy(pair), deepcopy(initial)
    challenge = build_scenario_reviewer_challenge(
        pair, initial, "HOUSEKEEPING", scenario_id=SCENARIO_SCHEDULING,
    )
    graph = project_policy_graph(pair, initial, challenge)
    versions = {node.version_id: node for node in graph.nodes if type(node) is PolicyVersion}
    assert "48 hours" in versions["v1"].original_text
    assert "24 hours" in versions["v2"].original_text
    assert all(condition.scope_state == "UNKNOWN"
               for condition in graph.nodes if type(condition) is ApplicabilityCondition)
    assert not any(edge.edge_type in {EdgeType.APPLIES_TO, EdgeType.SUPPORTS, EdgeType.CONTRADICTS}
                   for edge in graph.edges)
    assert pair == pair_before
    assert initial == initial_before
    conclusion = next(node for node in graph.nodes if type(node) is Conclusion)
    assert conclusion.classification == "INCONCLUSIVE"
    assert conclusion.human_review_required is True


def _condition_evidence_graph(graph, condition, passage, *, include_edge=True):
    updated_condition = replace(condition, evidence_passage_ids=(passage.passage_id,))
    nodes = tuple(updated_condition if node.node_id == condition.node_id else node
                  for node in graph.nodes)
    edges = graph.edges
    if include_edge:
        edges = (*edges, make_edge(updated_condition.node_id, passage.node_id,
                                   EdgeType.DERIVED_FROM, EpistemicStatus.SOURCE_VALIDATED,
                                   "Scope metadata references this exact version passage."))
    return _replace_graph(graph, nodes=nodes, edges=edges)


def test_public_graph_accepts_same_version_applicability_evidence(graph):
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.version_id == condition.version_id)
    version = next(node for node in graph.nodes
                   if type(node) is PolicyVersion and node.version_id == condition.version_id)
    updated_version = replace(version, department_scope_state="KNOWN",
                              department_scope_ids=("HOUSEKEEPING",))
    updated_condition = replace(condition, scope_state="KNOWN", scope_ids=("HOUSEKEEPING",),
                                evidence_passage_ids=(passage.passage_id,))
    nodes = tuple(updated_version if node.node_id == version.node_id else
                  updated_condition if node.node_id == condition.node_id else node
                  for node in graph.nodes)
    evidence_edge = make_edge(updated_condition.node_id, passage.node_id,
                              EdgeType.DERIVED_FROM, EpistemicStatus.SOURCE_VALIDATED,
                              "Scope metadata references this exact version passage.")
    applies_edge = make_edge(updated_version.node_id, updated_condition.node_id,
                             EdgeType.APPLIES_TO, EpistemicStatus.SOURCE_VALIDATED,
                             "Explicit known scope includes the department.")
    result = create_graph(nodes, (*graph.edges, evidence_edge, applies_edge))
    assert any(edge.edge_type is EdgeType.DERIVED_FROM
               and edge.source_id == updated_condition.node_id and edge.target_id == passage.node_id
               for edge in result.edges)
    assert applies_edge in result.edges


def test_public_graph_rejects_nonexistent_applicability_passage(graph):
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    fabricated = replace(condition, evidence_passage_ids=("p999999-0000000000000000",))
    nodes = tuple(fabricated if node.node_id == condition.node_id else node for node in graph.nodes)
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, graph.edges)


def test_public_graph_rejects_cross_version_applicability_evidence(graph):
    condition = next(node for node in graph.nodes
                     if type(node) is ApplicabilityCondition and node.version_id == "v1")
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.version_id == "v2")
    updated = replace(condition, evidence_passage_ids=(passage.passage_id,))
    nodes = tuple(updated if node.node_id == condition.node_id else node for node in graph.nodes)
    edge = make_edge(updated.node_id, passage.node_id, EdgeType.DERIVED_FROM,
                     EpistemicStatus.SOURCE_VALIDATED, "Wrong-version evidence reference.")
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, (*graph.edges, edge))


def test_public_graph_rejects_wrong_document_applicability_evidence(graph):
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.version_id == condition.version_id)
    updated = replace(
        condition, document_id="syn-policy-other",
        node_id=applicability_node_id(condition.comparison_id, "syn-policy-other",
                                      condition.version_id, condition.source_sha256,
                                      condition.dimension, condition.target_id),
        evidence_passage_ids=(passage.passage_id,),
    )
    nodes = tuple(updated if node.node_id == condition.node_id else node for node in graph.nodes)
    edge = make_edge(updated.node_id, passage.node_id, EdgeType.DERIVED_FROM,
                     EpistemicStatus.SOURCE_VALIDATED, "Wrong-document evidence reference.")
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, (*graph.edges, edge))


def test_public_graph_rejects_applicability_evidence_without_provenance_edge(graph):
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.version_id == condition.version_id)
    updated = replace(condition, evidence_passage_ids=(passage.passage_id,))
    nodes = tuple(updated if node.node_id == condition.node_id else node for node in graph.nodes)
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, graph.edges)


def test_public_graph_preserves_unknown_scope_with_valid_evidence_but_no_applies_to(graph):
    condition = next(node for node in graph.nodes
                     if type(node) is ApplicabilityCondition and node.scope_state == "UNKNOWN")
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.version_id == condition.version_id)
    result = _condition_evidence_graph(graph, condition, passage)
    assert not any(edge.edge_type is EdgeType.APPLIES_TO
                   and edge.target_id == condition.node_id for edge in result.edges)


def test_public_graph_rejects_known_scope_exclusion_even_with_valid_evidence(graph):
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    version = next(node for node in graph.nodes
                   if type(node) is PolicyVersion and node.version_id == condition.version_id)
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.version_id == condition.version_id)
    updated_version = replace(version, department_scope_state="KNOWN",
                              department_scope_ids=("FRONT_DESK",))
    updated_condition = replace(condition, scope_state="KNOWN", scope_ids=("FRONT_DESK",),
                                evidence_passage_ids=(passage.passage_id,))
    nodes = tuple(updated_version if node.node_id == version.node_id else
                  updated_condition if node.node_id == condition.node_id else node
                  for node in graph.nodes)
    evidence_edge = make_edge(updated_condition.node_id, passage.node_id,
                              EdgeType.DERIVED_FROM, EpistemicStatus.SOURCE_VALIDATED,
                              "Known scope metadata provenance.")
    applies_edge = make_edge(updated_version.node_id, updated_condition.node_id,
                             EdgeType.APPLIES_TO, EpistemicStatus.SOURCE_VALIDATED,
                             "Must reject excluded department.")
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, (*graph.edges, evidence_edge, applies_edge))


@pytest.mark.parametrize("target_type", [SourcePassage, ApplicabilityCondition])
def test_public_graph_rejects_cross_comparison_challenge_targets(graph, target_type):
    event = next(node for node in graph.nodes if type(node) is ChallengeEvent)
    target = next(node for node in graph.nodes if type(node) is target_type)
    other_comparison = "cmp-syn-unrelated-002"
    unrelated_event = replace(
        event, comparison_id=other_comparison,
        node_id=challenge_event_node_id(other_comparison, event.challenge_id),
    )
    nodes = tuple(unrelated_event if node.node_id == event.node_id else node
                  for node in graph.nodes)
    retained_edges = tuple(edge for edge in graph.edges if edge.source_id != event.node_id)
    edge = make_edge(unrelated_event.node_id, target.node_id, EdgeType.AFFECTS,
                     EpistemicStatus.CHALLENGED, "Cross-comparison target must fail.")
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, (*retained_edges, edge))


class _ExplodingFormat:
    def __format__(self, _format_spec):
        raise RuntimeError("caller formatting should not run")


def test_public_graph_rejects_exploding_identity_before_formatting(graph):
    claim = next(node for node in graph.nodes if type(node) is Claim)
    malformed = replace(claim, comparison_id=_ExplodingFormat())
    nodes = tuple(malformed if node.node_id == claim.node_id else node for node in graph.nodes)
    with pytest.raises(DependencyGraphError):
        create_graph(nodes, graph.edges)


def test_public_graph_accepts_exactly_5000_nodes(graph):
    from policy_dependency_graph import MAX_GRAPH_NODES
    extra = _claim_cycle_nodes(graph, MAX_GRAPH_NODES - len(graph.nodes), "nodebound")
    result = create_graph((*graph.nodes, *extra), graph.edges)
    assert len(result.nodes) == MAX_GRAPH_NODES
    assert len(EvidenceDependencyGraph(
        result.snapshot_identity, (*graph.nodes, *extra), graph.edges,
    ).nodes) == MAX_GRAPH_NODES


def test_public_graph_rejects_5001_nodes_before_validation(graph):
    from policy_dependency_graph import MAX_GRAPH_NODES
    extra = _claim_cycle_nodes(graph, MAX_GRAPH_NODES + 1 - len(graph.nodes), "overnodebound")
    with pytest.raises(DependencyGraphError) as error:
        create_graph((*graph.nodes, *extra), graph.edges)
    assert error.value.code == "invalid_graph"


def _dependency_edges_for_total(graph, claims, total):
    needed = total - len(graph.edges)
    edges = []
    for left_index, left in enumerate(claims):
        for right in claims[left_index + 1:]:
            edges.append(make_edge(left.node_id, right.node_id, EdgeType.DEPENDS_ON,
                                   EpistemicStatus.PROPOSED, "Synthetic proposal dependency."))
            if len(edges) == needed:
                return tuple(edges)
    raise AssertionError("test graph did not provide enough unique dependency edges")


def test_public_graph_accepts_exactly_10000_edges(graph):
    claims = _claim_cycle_nodes(graph, 150, "edgebound")
    edges = _dependency_edges_for_total(graph, claims, 10_000)
    result = create_graph((*graph.nodes, *claims), (*graph.edges, *edges))
    assert len(result.edges) == 10_000
    assert len(EvidenceDependencyGraph(
        result.snapshot_identity, (*graph.nodes, *claims), (*graph.edges, *edges),
    ).edges) == 10_000


def test_public_graph_rejects_10001_edges_before_edge_validation(graph):
    claims = _claim_cycle_nodes(graph, 150, "overedgebound")
    edges = _dependency_edges_for_total(graph, claims, 10_001)
    with pytest.raises(DependencyGraphError) as error:
        create_graph((*graph.nodes, *claims), (*graph.edges, *edges))
    assert error.value.code == "invalid_graph"


def test_direct_graph_constructor_rejects_oversized_nodes_and_edges_before_sorting(graph):
    from policy_dependency_graph import MAX_GRAPH_EDGES, MAX_GRAPH_NODES
    extra_nodes = _claim_cycle_nodes(
        graph, MAX_GRAPH_NODES + 1 - len(graph.nodes), "directovernodebound",
    )
    with pytest.raises(DependencyGraphError) as node_error:
        EvidenceDependencyGraph(graph.snapshot_identity, (*graph.nodes, *extra_nodes), graph.edges)
    assert node_error.value.code == "invalid_graph"

    repeated = graph.edges[0]
    oversized_edges = (*graph.edges, *((repeated,) * (MAX_GRAPH_EDGES + 1 - len(graph.edges))))
    with pytest.raises(DependencyGraphError) as edge_error:
        EvidenceDependencyGraph(graph.snapshot_identity, graph.nodes, oversized_edges)
    assert edge_error.value.code == "invalid_graph"


def test_dependency_edges_cannot_launder_proposed_nodes_as_source_validated(graph):
    edge = next(edge for edge in graph.edges
                if edge.edge_type is EdgeType.DEPENDS_ON
                and next(node for node in graph.nodes if node.node_id == edge.source_id).__class__
                is ComparisonRelation)
    assert edge.epistemic_status is EpistemicStatus.LOCALLY_DERIVED
    validated = replace(edge, epistemic_status=EpistemicStatus.SOURCE_VALIDATED)
    edges = tuple(validated if item.edge_id == edge.edge_id else item for item in graph.edges)
    with pytest.raises(DependencyGraphError) as error:
        _replace_graph(graph, edges=edges)
    assert error.value.code == "invalid_edge"


@pytest.mark.parametrize("path", ["factory", "direct"])
def test_direct_and_factory_construction_reject_malformed_objects_before_sorting(graph, path):
    class ExplodingOrder:
        comparisons = 0

        def __lt__(self, _other):
            type(self).comparisons += 1
            raise AssertionError("sorting malformed caller value must not run")

    claim = next(node for node in graph.nodes if type(node) is Claim)
    malformed = replace(claim, node_id=ExplodingOrder())
    nodes = tuple(malformed if item.node_id == claim.node_id else item for item in graph.nodes)
    with pytest.raises(DependencyGraphError) as error:
        _construct(nodes, graph.edges, path, graph.snapshot_identity)
    assert error.value.code == "invalid_node"
    assert ExplodingOrder.comparisons == 0
    assert nodes[graph.nodes.index(claim)] is malformed

    edge = graph.edges[0]
    malformed_edge = replace(edge, edge_id=ExplodingOrder())
    edges = tuple(malformed_edge if item.edge_id == edge.edge_id else item for item in graph.edges)
    with pytest.raises(DependencyGraphError) as edge_error:
        _construct(graph.nodes, edges, path, graph.snapshot_identity)
    assert edge_error.value.code == "invalid_edge"
    assert ExplodingOrder.comparisons == 0
    assert edges[0] is malformed_edge


@pytest.mark.parametrize("path", ["factory", "direct"])
def test_direct_and_factory_construction_reject_invalid_edge_and_nested_types(graph, path):
    edge = graph.edges[0]
    bad_edge = replace(edge, edge_id=object())
    edges = tuple(bad_edge if item.edge_id == edge.edge_id else item for item in graph.edges)
    with pytest.raises(DependencyGraphError) as error:
        _construct(graph.nodes, edges, path, graph.snapshot_identity)
    assert error.value.code == "invalid_edge"
    assert edges[0] is bad_edge

    claim = next(node for node in graph.nodes if type(node) is Claim)
    bad_claim = replace(claim, citations=[])
    nodes = tuple(bad_claim if item.node_id == claim.node_id else item for item in graph.nodes)
    with pytest.raises(DependencyGraphError) as nested_error:
        _construct(nodes, graph.edges, path, graph.snapshot_identity)
    assert nested_error.value.code == "invalid_node"
    assert nodes[graph.nodes.index(claim)] is bad_claim


def test_direct_graph_construction_accepts_a_valid_graph(graph):
    assert EvidenceDependencyGraph(graph.snapshot_identity, graph.nodes, graph.edges) == graph


def test_aggregate_utf8_byte_budget_accepts_below_and_at_limit_and_rejects_above(graph):
    below = _graph_for_payload_bytes(graph, MAX_AGGREGATE_TEXT_BYTES - 1)
    exact = _graph_for_payload_bytes(graph, MAX_AGGREGATE_TEXT_BYTES)
    above = _graph_for_payload_bytes(graph, MAX_AGGREGATE_TEXT_BYTES + 1)
    for nodes in (below, exact):
        assert _payload_totals(graph.snapshot_identity, nodes, graph.edges)["bytes"] <= MAX_AGGREGATE_TEXT_BYTES
        assert create_graph(nodes, graph.edges).nodes == tuple(sorted(nodes, key=lambda node: node.node_id))
        assert EvidenceDependencyGraph(graph.snapshot_identity, nodes, graph.edges).nodes == tuple(
            sorted(nodes, key=lambda node: node.node_id)
        )
    original_nodes, original_edges = deepcopy(above), deepcopy(graph.edges)
    for path in ("factory", "direct"):
        with pytest.raises(DependencyGraphError) as error:
            _construct(above, graph.edges, path, graph.snapshot_identity)
        assert error.value.code == "graph_budget_exceeded"
    assert above == original_nodes and graph.edges == original_edges


def test_aggregate_byte_accounting_counts_utf8_multibyte_text(graph):
    claim = next(node for node in graph.nodes if type(node) is Claim)
    multibyte = replace(claim, summary="é" * 1_000)
    nodes = tuple(multibyte if node.node_id == claim.node_id else node for node in graph.nodes)
    totals = _payload_totals(graph.snapshot_identity, nodes, graph.edges)
    assert len(multibyte.summary) == 1_000
    assert totals["bytes"] >= MAX_SNAPSHOT_IDENTITY_BYTES + 2_000
    assert create_graph(nodes, graph.edges)


def test_utf8_multibyte_growth_crosses_exact_aggregate_byte_boundary(graph):
    exact_nodes = _graph_for_payload_bytes(graph, MAX_AGGREGATE_TEXT_BYTES)
    claim = next(node for node in exact_nodes if type(node) is Claim and node.summary)
    changed_claim = replace(claim, summary="é" + claim.summary[1:])
    over_nodes = tuple(changed_claim if node.node_id == claim.node_id else node
                       for node in exact_nodes)
    assert len(changed_claim.summary) == len(claim.summary)
    assert (_payload_totals(graph.snapshot_identity, over_nodes, graph.edges)["bytes"]
            == MAX_AGGREGATE_TEXT_BYTES + 1)
    original = deepcopy(over_nodes)
    for path in ("factory", "direct"):
        with pytest.raises(DependencyGraphError) as error:
            _construct(over_nodes, graph.edges, path, graph.snapshot_identity)
        assert error.value.code == "graph_budget_exceeded"
    assert over_nodes == original


def test_combined_aggregate_budgets_accept_boundary_and_reject_overflow(graph):
    claim = next(node for node in graph.nodes if type(node) is Claim)
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    matching_passage = next(
        node for node in graph.nodes
        if type(node) is SourcePassage
        and (node.document_id, node.version_id, node.source_sha256)
        == (condition.document_id, condition.version_id, condition.source_sha256)
    )
    baseline_refs = _payload_totals(graph.snapshot_identity, graph.nodes, graph.edges)["references"]
    other_refs = (baseline_refs - len(claim.citations)
                  - len(condition.evidence_passage_ids))
    claim_reference_count = MAX_AGGREGATE_REFERENCES - other_refs - 1
    assert claim_reference_count > 0
    updated_claim = replace(claim, citations=(claim.citations[0],) * claim_reference_count)
    updated_condition = replace(condition, evidence_passage_ids=(matching_passage.passage_id,))
    nodes = tuple(
        updated_claim if node.node_id == claim.node_id else
        updated_condition if node.node_id == condition.node_id else node
        for node in graph.nodes
    )
    passage_target = matching_passage.node_id
    edges = tuple(
        edge for edge in graph.edges
        if not (edge.edge_type is EdgeType.DERIVED_FROM
                and ((edge.source_id == claim.node_id and edge.target_id !=
                      source_passage_id(claim.citations[0].document_id,
                                        claim.citations[0].version_id,
                                        claim.citations[0].source_sha256,
                                        claim.citations[0].passage_id))
                     or (edge.source_id == condition.node_id and edge.target_id != passage_target)))
    )
    if not any(edge.source_id == condition.node_id and edge.target_id == passage_target
               and edge.edge_type is EdgeType.DERIVED_FROM for edge in edges):
        edges += (make_edge(condition.node_id, passage_target, EdgeType.DERIVED_FROM,
                            EpistemicStatus.SOURCE_VALIDATED,
                            "Synthetic applicability passage provenance."),)

    conclusion = next(node for node in nodes if type(node) is Conclusion)
    before_nested = _payload_totals(graph.snapshot_identity, nodes, edges)["nested"]
    reason_count = (MAX_AGGREGATE_NESTED_ENTRIES - before_nested
                    + len(conclusion.uncertainty_reasons))
    updated_conclusion = replace(
        conclusion, uncertainty_reasons=("combined budget reason",) * reason_count,
    )
    nodes = tuple(updated_conclusion if node.node_id == conclusion.node_id else node
                  for node in nodes)
    nodes = _pad_nodes_to_payload_bytes(
        graph, nodes, edges, MAX_AGGREGATE_TEXT_BYTES,
    )
    totals = _payload_totals(graph.snapshot_identity, nodes, edges)
    assert totals["bytes"] == MAX_AGGREGATE_TEXT_BYTES
    assert totals["nested"] == MAX_AGGREGATE_NESTED_ENTRIES
    assert totals["references"] == MAX_AGGREGATE_REFERENCES
    assert len(nodes) <= MAX_GRAPH_NODES and len(edges) <= MAX_GRAPH_EDGES
    assert create_graph(nodes, edges)
    assert EvidenceDependencyGraph(graph.snapshot_identity, nodes, edges)

    summary_claim = next(node for node in nodes if type(node) is Claim and node.summary)
    changed = replace(summary_claim, summary="é" + summary_claim.summary[1:])
    over_nodes = tuple(changed if node.node_id == summary_claim.node_id else node for node in nodes)
    assert _payload_totals(graph.snapshot_identity, over_nodes, edges)["bytes"] == (
        MAX_AGGREGATE_TEXT_BYTES + 1
    )
    for path in ("factory", "direct"):
        with pytest.raises(DependencyGraphError) as error:
            _construct(over_nodes, edges, path, graph.snapshot_identity)
        assert error.value.code == "graph_budget_exceeded"
        assert over_nodes[over_nodes.index(changed)] is changed
        assert changed.summary.startswith("é")


@pytest.mark.parametrize("path", ["factory", "direct"])
def test_deeply_nested_node_tuple_is_rejected_without_recursion_or_mutation(graph, path):
    claim = next(node for node in graph.nodes if type(node) is Claim)
    nested = "malformed leaf"
    for _ in range(3_000):
        nested = (nested,)
    malformed = replace(claim, citations=nested)
    nodes = tuple(malformed if item.node_id == claim.node_id else item for item in graph.nodes)

    with pytest.raises(DependencyGraphError) as error:
        _construct(nodes, graph.edges, path, graph.snapshot_identity)

    assert error.value.code == "invalid_node"
    assert str(error.value) == "Evidence dependency graph contains an invalid node."
    assert nodes[graph.nodes.index(claim)] is malformed
    assert malformed.citations is nested


def test_snapshot_identity_utf8_boundary_is_checked_before_construction(graph):
    exact = "é" * (MAX_SNAPSHOT_IDENTITY_BYTES // 2)
    assert len(exact) < MAX_SNAPSHOT_IDENTITY_BYTES
    assert _prevalidate_construction_inputs(exact, graph.nodes, graph.edges)
    with pytest.raises(DependencyGraphError) as direct_error:
        EvidenceDependencyGraph(exact, graph.nodes, graph.edges)
    assert direct_error.value.code == "invalid_graph"

    oversized = exact + "a"
    with pytest.raises(DependencyGraphError) as error:
        EvidenceDependencyGraph(oversized, graph.nodes, graph.edges)
    assert error.value.code == "invalid_graph"
    with pytest.raises(DependencyGraphError) as preflight_error:
        _prevalidate_construction_inputs(oversized, graph.nodes, graph.edges)
    assert preflight_error.value.code == "invalid_graph"


def test_factory_rejects_generated_snapshot_identity_over_limit_before_join(graph):
    versions = []
    for index in range(130):
        document_id = "syn-policy-boundary"
        version_id = f"v{index:03d}"
        digest = "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
        versions.append(PolicyVersion(
            policy_version_id(document_id, version_id, digest),
            EpistemicStatus.SOURCE_VALIDATED, document_id, version_id, digest,
            "x", None, None, "UNKNOWN", (), "UNKNOWN", (), None, "FULL_DOCUMENT",
        ))
    with pytest.raises(DependencyGraphError) as error:
        create_graph(graph.nodes + tuple(versions), graph.edges)
    assert error.value.code == "invalid_graph"


def test_factory_accepts_exact_10000_byte_multibyte_snapshot_identity_and_rejects_next_byte(
        graph, monkeypatch):
    template = next(node for node in graph.nodes if type(node) is ChallengeEvent)
    nodes = graph.nodes
    events = []
    remaining = MAX_SNAPSHOT_IDENTITY_BYTES
    for index in range(100):
        challenge_id = f"phase18m-{index:03d}-"
        event = replace(
            template,
            node_id=challenge_event_node_id(template.comparison_id, challenge_id),
            challenge_id=challenge_id,
        )
        events.append(event)
    nodes += tuple(events)
    initial_identity = _snapshot_identity(nodes)
    remaining -= len(initial_identity.encode("utf-8"))
    assert remaining > 0

    padded_events = []
    for event in events:
        capacity = 120 - len(event.challenge_id)
        two_byte_chars = min(remaining // 2, capacity)
        suffix = "é" * two_byte_chars
        remaining -= 2 * two_byte_chars
        if remaining and two_byte_chars < capacity:
            suffix += "a"
            remaining -= 1
        challenge_id = event.challenge_id + suffix
        padded_events.append(replace(
            event,
            node_id=challenge_event_node_id(event.comparison_id, challenge_id),
            challenge_id=challenge_id,
        ))
    assert remaining == 0
    nodes = graph.nodes + tuple(padded_events)
    exact_identity = _snapshot_identity(nodes)
    assert len(exact_identity.encode("utf-8")) == MAX_SNAPSHOT_IDENTITY_BYTES
    assert "é" in exact_identity

    result = create_graph(nodes, graph.edges)
    assert result.snapshot_identity == exact_identity
    assert len(result.snapshot_identity.encode("utf-8")) == MAX_SNAPSHOT_IDENTITY_BYTES
    assert result.snapshot_identity.startswith("provisional-graph-v1|")

    last_event = next(event for event in padded_events if len(event.challenge_id) < 120)
    larger_id = last_event.challenge_id + "a"
    oversized_event = replace(
        last_event,
        node_id=challenge_event_node_id(last_event.comparison_id, larger_id),
        challenge_id=larger_id,
    )
    oversized_nodes = tuple(
        oversized_event if node.node_id == last_event.node_id else node for node in nodes
    )
    materialized_identities = []
    original_size = dependency_graph_module._strict_utf8_size

    def track_complete_identity(value):
        if value.startswith("provisional-graph-v1|"):
            materialized_identities.append(value)
        return original_size(value)

    monkeypatch.setattr(dependency_graph_module, "_strict_utf8_size", track_complete_identity)
    with pytest.raises(DependencyGraphError) as error:
        create_graph(oversized_nodes, graph.edges)
    assert error.value.code == "invalid_graph"
    assert str(error.value) == "Evidence dependency graph is invalid."
    assert not materialized_identities


@pytest.mark.parametrize("count,accepted", [
    (MAX_AGGREGATE_REFERENCES - 1, True),
    (MAX_AGGREGATE_REFERENCES, True),
    (MAX_AGGREGATE_REFERENCES + 1, False),
])
@pytest.mark.parametrize("path", ["factory", "direct"])
def test_aggregate_reference_budget_is_consistent_across_construction_paths(
        graph, count, accepted, path):
    claim = next(node for node in graph.nodes if type(node) is Claim)
    reference = claim.citations[0]
    updated = replace(claim, citations=(reference,) * count)
    nodes = tuple(updated if node.node_id == claim.node_id else node for node in graph.nodes)
    referenced_passage = source_passage_id(
        reference.document_id, reference.version_id, reference.source_sha256, reference.passage_id,
    )
    edges = tuple(edge for edge in graph.edges
                  if not (edge.edge_type is EdgeType.DERIVED_FROM
                          and edge.source_id == claim.node_id
                          and edge.target_id != referenced_passage))
    original_nodes, original_edges = deepcopy(nodes), deepcopy(edges)
    if accepted:
        assert _payload_totals(graph.snapshot_identity, nodes, edges)["references"] == count
        _construct(nodes, edges, path, graph.snapshot_identity)
    else:
        with pytest.raises(DependencyGraphError) as error:
            _construct(nodes, edges, path, graph.snapshot_identity)
        assert error.value.code == "graph_budget_exceeded"
        assert nodes == original_nodes and edges == original_edges


@pytest.mark.parametrize("count,accepted", [
    (MAX_AGGREGATE_NESTED_ENTRIES - 1, True),
    (MAX_AGGREGATE_NESTED_ENTRIES, True),
    (MAX_AGGREGATE_NESTED_ENTRIES + 1, False),
])
@pytest.mark.parametrize("path", ["factory", "direct"])
def test_aggregate_nested_entry_budget_is_consistent_across_construction_paths(
        graph, count, accepted, path):
    conclusion = next(node for node in graph.nodes if type(node) is Conclusion)
    baseline = _payload_totals(graph.snapshot_identity, graph.nodes, graph.edges)["nested"]
    adjusted_count = len(conclusion.uncertainty_reasons) + count - baseline
    updated = replace(conclusion, uncertainty_reasons=("bounded synthetic reason",) * adjusted_count)
    nodes = tuple(updated if node.node_id == conclusion.node_id else node for node in graph.nodes)
    assert _payload_totals(graph.snapshot_identity, nodes, graph.edges)["nested"] == count
    original_nodes, original_edges = deepcopy(nodes), deepcopy(graph.edges)
    if accepted:
        _construct(nodes, graph.edges, path, graph.snapshot_identity)
    else:
        with pytest.raises(DependencyGraphError) as error:
            _construct(nodes, graph.edges, path, graph.snapshot_identity)
        assert error.value.code == "graph_budget_exceeded"
        assert nodes == original_nodes and graph.edges == original_edges
