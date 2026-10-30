"""Synthetic offline tests for bounded challenge impact planning."""
from copy import deepcopy
from dataclasses import replace

import pytest

import policy_challenge_propagation as propagation
from policy_challenge_propagation import (
    ChallengeCategory,
    ChallengeImpactPlan,
    ChallengePropagationError,
    ChallengeRequest,
    ImpactState,
    NodeImpact,
    PathStep,
    PlanBlocker,
    PlannerLimit,
    TraversalCompleteness,
    TraversalDirection,
    plan_challenge_impact,
)
from policy_dependency_graph import (
    ApplicabilityCondition,
    ChallengeEvent,
    Claim,
    DependencyGraphError,
    EdgeType,
    EpistemicStatus,
    EvidenceDependencyGraph,
    NodeType,
    PolicyVersion,
    SourcePassage,
    build_scheduling_graph,
    claim_node_id,
    create_graph,
    make_edge,
)


@pytest.fixture
def graph():
    return build_scheduling_graph()


def _request(graph, target, *, category=ChallengeCategory.OTHER, evidence_refs=(), order=7):
    comparison_id = next(
        node.comparison_id for node in graph.nodes
        if hasattr(node, "comparison_id")
    )
    return ChallengeRequest(
        "challenge-synthetic-1", comparison_id, target.node_id, target.node_type,
        category, "Synthetic review request.", tuple(evidence_refs), order,
    )


def _impact(plan, node):
    return next(item for item in plan.impacts if item.node_id == node.node_id)


def _event_passage_and_claim(graph):
    event = next(node for node in graph.nodes if type(node) is ChallengeEvent)
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage
                   and node.document_id == event.target_document_id
                   and node.version_id == event.target_version_id
                   and node.passage_id == event.target_passage_id)
    claim = next(node for node in graph.nodes if type(node) is Claim)
    return event, passage, claim


def test_source_challenge_reaches_claim_relation_and_conclusion_by_typed_paths(graph):
    _, passage, claim = _event_passage_and_claim(graph)
    relation = next(node for node in graph.nodes if node.node_type.value == "ComparisonRelation")
    conclusion = next(node for node in graph.nodes if node.node_type.value == "Conclusion")

    plan = plan_challenge_impact(graph, _request(graph, passage))

    assert _impact(plan, passage).state is ImpactState.DIRECTLY_CHALLENGED
    assert _impact(plan, claim).state is ImpactState.REASSESSMENT_REQUIRED
    assert _impact(plan, relation).state is ImpactState.REASSESSMENT_REQUIRED
    assert _impact(plan, conclusion).state is ImpactState.REASSESSMENT_REQUIRED
    for node in (claim, relation, conclusion):
        for path in _impact(plan, node).paths:
            assert path[0].from_node_id == passage.node_id
            assert path[-1].to_node_id == node.node_id
    assert plan.traversal.complete


def test_comparison_relation_can_be_directly_challenged(graph):
    relation = next(node for node in graph.nodes if node.node_type is NodeType.COMPARISON_RELATION)
    conclusion = next(node for node in graph.nodes if node.node_type is NodeType.CONCLUSION)

    plan = plan_challenge_impact(graph, _request(graph, relation))

    assert _impact(plan, relation).state is ImpactState.DIRECTLY_CHALLENGED
    assert _impact(plan, relation).paths == ((),)
    assert _impact(plan, conclusion).state is ImpactState.REASSESSMENT_REQUIRED


def test_conclusion_can_be_directly_challenged(graph):
    conclusion = next(node for node in graph.nodes if node.node_type is NodeType.CONCLUSION)
    relation = next(node for node in graph.nodes if node.node_type is NodeType.COMPARISON_RELATION)

    plan = plan_challenge_impact(graph, _request(graph, conclusion))

    assert _impact(plan, conclusion).state is ImpactState.DIRECTLY_CHALLENGED
    assert _impact(plan, conclusion).paths == ((),)
    assert _impact(plan, relation).state is ImpactState.POTENTIALLY_AFFECTED


def test_reverse_traversal_is_explicit_and_uses_existing_edge_direction(graph):
    _, passage, claim = _event_passage_and_claim(graph)
    plan = plan_challenge_impact(graph, _request(graph, passage))
    path = _impact(plan, claim).paths[0]
    assert path[0].direction is TraversalDirection.REVERSE


def test_prior_affects_annotations_are_not_followed_or_recursively_propagated(graph):
    event, passage, _ = _event_passage_and_claim(graph)
    plan = plan_challenge_impact(graph, _request(graph, passage))
    assert _impact(plan, event).state is ImpactState.UNCHANGED
    assert all(step.edge_id not in {
        edge.edge_id for edge in graph.edges if edge.edge_type is EdgeType.AFFECTS
    } for impact in plan.impacts for path in impact.paths for step in path)


def test_contains_structure_does_not_fan_out_to_unrelated_passages(graph):
    _, challenged, _ = _event_passage_and_claim(graph)
    unrelated = next(node for node in graph.nodes
                     if type(node) is SourcePassage and node.node_id != challenged.node_id
                     and not any(edge.edge_type is EdgeType.DERIVED_FROM
                                 and edge.target_id == node.node_id
                                 for edge in graph.edges))
    plan = plan_challenge_impact(graph, _request(graph, challenged))
    assert _impact(plan, unrelated).state is ImpactState.UNCHANGED
    assert all(step.edge_id not in {
        edge.edge_id for edge in graph.edges if edge.edge_type is EdgeType.CONTAINS
    } for impact in plan.impacts for path in impact.paths for step in path)


def test_applicability_challenge_does_not_invalidate_or_reach_policy_version(graph):
    condition = next(node for node in graph.nodes if type(node) is ApplicabilityCondition)
    plan = plan_challenge_impact(graph, _request(graph, condition,
                                                category=ChallengeCategory.APPLICABILITY))
    version_ids = {node.node_id for node in graph.nodes if node.node_type.value == "PolicyVersion"}
    assert version_ids.isdisjoint({item.node_id for item in plan.impacts
                                   if item.state is ImpactState.REASSESSMENT_REQUIRED})
    assert not any(step.edge_id in {
        edge.edge_id for edge in graph.edges if edge.edge_type is EdgeType.APPLIES_TO
    } for impact in plan.impacts for path in impact.paths for step in path)


def test_unknown_applicability_remains_unknown_after_planning(graph):
    condition = next(node for node in graph.nodes
                     if type(node) is ApplicabilityCondition and node.scope_state == "UNKNOWN")
    before = condition
    plan_challenge_impact(graph, _request(graph, condition,
                                          category=ChallengeCategory.APPLICABILITY))
    after = next(node for node in graph.nodes if node.node_id == condition.node_id)
    assert after is before
    assert after.scope_state == "UNKNOWN"


def _unknown_condition_without_evidence(graph):
    condition = next(node for node in graph.nodes
                     if type(node) is ApplicabilityCondition and node.scope_state == "UNKNOWN")
    updated_condition = replace(condition, evidence_passage_ids=())
    edges = tuple(edge for edge in graph.edges
                  if not (edge.source_id == condition.node_id
                          and edge.edge_type is EdgeType.DERIVED_FROM))
    nodes = tuple(updated_condition if node.node_id == condition.node_id else node
                  for node in graph.nodes)
    return create_graph(nodes, edges), updated_condition


def test_direct_unknown_condition_without_evidence_stays_unresolved_not_blocked(graph):
    updated, condition = _unknown_condition_without_evidence(graph)
    before_edges = updated.edges

    plan = plan_challenge_impact(updated, _request(
        updated, condition, category=ChallengeCategory.APPLICABILITY,
    ))

    impact = _impact(plan, condition)
    assert impact.state is ImpactState.DIRECTLY_CHALLENGED
    assert "UNKNOWN" in impact.reason
    assert not any(blocker.code == "MISSING_PROVENANCE" for blocker in plan.blockers)
    assert condition.scope_state == "UNKNOWN"
    assert updated.edges == before_edges
    assert not any(step.edge_id in {
        edge.edge_id for edge in updated.edges
        if edge.edge_type in (EdgeType.APPLIES_TO, EdgeType.SUPPORTS, EdgeType.CONTRADICTS)
    } for path in impact.paths for step in path)


def test_dependency_path_to_unknown_condition_is_inconclusive_not_missing(graph):
    updated, condition = _unknown_condition_without_evidence(graph)
    relation = next(node for node in updated.nodes if node.node_type is NodeType.COMPARISON_RELATION)
    dependency = make_edge(
        relation.node_id, condition.node_id, EdgeType.DEPENDS_ON,
        EpistemicStatus.PROPOSED, "Synthetic unresolved applicability dependency.",
    )
    updated = create_graph(updated.nodes, (*updated.edges, dependency))

    plan = plan_challenge_impact(updated, _request(updated, relation))

    impact = _impact(plan, condition)
    assert impact.state is ImpactState.INCONCLUSIVE
    assert impact.paths[0][0].direction is TraversalDirection.FORWARD
    assert not any(blocker.code == "MISSING_PROVENANCE" and blocker.node_id == condition.node_id
                   for blocker in plan.blockers)
    assert condition.scope_state == "UNKNOWN"
    assert "applicability remains unresolved" in impact.reason


def test_unknown_condition_with_valid_passage_provenance_is_not_blocked(graph):
    updated, condition = _unknown_condition_without_evidence(graph)
    passage = next(node for node in updated.nodes
                   if type(node) is SourcePassage
                   and node.document_id == condition.document_id
                   and node.version_id == condition.version_id
                   and node.source_sha256 == condition.source_sha256)
    condition = replace(condition, evidence_passage_ids=(passage.passage_id,))
    nodes = tuple(condition if node.node_id == condition.node_id else node for node in updated.nodes)
    edge = make_edge(condition.node_id, passage.node_id, EdgeType.DERIVED_FROM,
                     EpistemicStatus.SOURCE_VALIDATED,
                     "Synthetic passage provenance; applicability remains unknown.")
    updated = create_graph(nodes, (*updated.edges, edge))

    plan = plan_challenge_impact(updated, _request(updated, condition))

    assert _impact(plan, condition).state is ImpactState.DIRECTLY_CHALLENGED
    assert not any(blocker.code == "MISSING_PROVENANCE" and blocker.node_id == condition.node_id
                   for blocker in plan.blockers)
    assert condition.scope_state == "UNKNOWN"
    assert not any(item.state is ImpactState.REASSESSMENT_REQUIRED
                   and item.node_type is NodeType.POLICY_VERSION for item in plan.impacts)


def test_unknown_applicability_assessment_with_grounded_scope_remains_inconclusive(graph):
    updated, condition = _unknown_condition_without_evidence(graph)
    version = next(node for node in updated.nodes
                   if type(node) is PolicyVersion and node.document_id == condition.document_id
                   and node.version_id == condition.version_id)
    passage = next(node for node in updated.nodes
                   if type(node) is SourcePassage and node.document_id == condition.document_id
                   and node.version_id == condition.version_id)
    all_version = replace(version, department_scope_state="ALL", department_scope_ids=())
    unresolved = replace(condition, scope_state="ALL", scope_ids=(),
                         evidence_passage_ids=(passage.passage_id,),
                         applicability_status="UNKNOWN")
    nodes = tuple(
        all_version if node.node_id == version.node_id else
        unresolved if node.node_id == condition.node_id else node
        for node in updated.nodes
    )
    provenance = make_edge(unresolved.node_id, passage.node_id, EdgeType.DERIVED_FROM,
                           EpistemicStatus.SOURCE_VALIDATED,
                           "Synthetic provenance does not resolve applicability.")
    relation = next(node for node in nodes if node.node_type is NodeType.COMPARISON_RELATION)
    dependency = make_edge(relation.node_id, unresolved.node_id, EdgeType.DEPENDS_ON,
                           EpistemicStatus.PROPOSED,
                           "Synthetic dependency on unresolved applicability.")
    updated = create_graph(nodes, (*updated.edges, provenance, dependency))

    plan = plan_challenge_impact(updated, _request(updated, relation))

    impact = _impact(plan, unresolved)
    assert impact.state is ImpactState.INCONCLUSIVE
    assert unresolved.scope_state == "ALL"
    assert unresolved.applicability_status == "UNKNOWN"
    assert not any(blocker.code == "MISSING_PROVENANCE" and blocker.node_id == unresolved.node_id
                   for blocker in plan.blockers)
    assert not any(step.edge_id in {
        edge.edge_id for edge in updated.edges if edge.edge_type is EdgeType.APPLIES_TO
    } for path in impact.paths for step in path)


def test_non_unknown_condition_without_required_evidence_is_rejected_by_graph(graph):
    unknown = next(node for node in graph.nodes
                   if type(node) is ApplicabilityCondition and node.scope_state == "UNKNOWN")
    version = next(node for node in graph.nodes
                   if type(node) is PolicyVersion and node.document_id == unknown.document_id
                   and node.version_id == unknown.version_id)
    passage = next(node for node in graph.nodes
                   if type(node) is SourcePassage and node.document_id == unknown.document_id
                   and node.version_id == unknown.version_id)
    all_version = replace(version, department_scope_state="ALL", department_scope_ids=())
    all_condition = replace(unknown, scope_state="ALL", scope_ids=(),
                            evidence_passage_ids=(passage.passage_id,))
    valid_nodes = tuple(
        all_version if node.node_id == version.node_id else
        all_condition if node.node_id == unknown.node_id else node
        for node in graph.nodes
    )
    provenance = make_edge(all_condition.node_id, passage.node_id, EdgeType.DERIVED_FROM,
                           EpistemicStatus.SOURCE_VALIDATED, "Synthetic source reference.")
    valid_graph = create_graph(valid_nodes, (*graph.edges, provenance))
    invalid = replace(all_condition, evidence_passage_ids=())
    nodes = tuple(invalid if node.node_id == invalid.node_id else node for node in valid_graph.nodes)
    edges = tuple(edge for edge in valid_graph.edges
                  if not (edge.source_id == invalid.node_id
                          and edge.edge_type is EdgeType.DERIVED_FROM))
    with pytest.raises(DependencyGraphError) as error:
        create_graph(nodes, edges)
    assert error.value.code == "invalid_node"


@pytest.mark.parametrize("proposal_type", [EdgeType.SUPPORTS, EdgeType.CONTRADICTS])
def test_proposed_relationship_requests_review_without_becoming_fact(graph, proposal_type):
    _, passage, claim = _event_passage_and_claim(graph)
    proposal = make_edge(passage.node_id, claim.node_id, proposal_type,
                         EpistemicStatus.PROPOSED, "Synthetic proposal only.")
    updated = create_graph(graph.nodes, (*graph.edges, proposal))
    plan = plan_challenge_impact(updated, _request(updated, passage))
    assert _impact(plan, claim).state is ImpactState.REASSESSMENT_REQUIRED
    assert proposal in updated.edges
    assert proposal.epistemic_status is EpistemicStatus.PROPOSED
    assert "semantic support" in plan.limitations[0]


def test_missing_target_provenance_is_blocked_even_when_request_lists_evidence(graph):
    base = next(node for node in graph.nodes if type(node) is Claim)
    claim = replace(base, node_id=claim_node_id(base.comparison_id, "cand-unverified"),
                    candidate_id="cand-unverified", citations=())
    updated = create_graph((*graph.nodes, claim), graph.edges)
    passage = next(node for node in updated.nodes if type(node) is SourcePassage)
    request = _request(updated, claim, evidence_refs=(passage.node_id,))
    plan = plan_challenge_impact(updated, request)
    assert _impact(plan, claim).state is ImpactState.DIRECTLY_CHALLENGED
    assert any(blocker.code == "MISSING_PROVENANCE" and blocker.node_id == claim.node_id
               for blocker in plan.blockers)


def test_cross_candidate_dependency_is_not_propagated(graph):
    base = next(node for node in graph.nodes if type(node) is Claim)
    left_id = "cand-boundary-left"
    right_id = "cand-boundary-right"
    left = replace(base, node_id=claim_node_id(base.comparison_id, left_id),
                   candidate_id=left_id, citations=())
    right = replace(base, node_id=claim_node_id(base.comparison_id, right_id),
                    candidate_id=right_id, citations=())
    edge = make_edge(left.node_id, right.node_id, EdgeType.DEPENDS_ON,
                     EpistemicStatus.PROPOSED, "Synthetic typed dependency.")
    updated = create_graph((*graph.nodes, left, right), (*graph.edges, edge))

    plan = plan_challenge_impact(updated, _request(updated, right))

    assert _impact(plan, left).state is ImpactState.UNCHANGED
    assert any(blocker.code == "CROSS_CANDIDATE_BOUNDARY" for blocker in plan.blockers)


def test_isolated_target_completes_and_marks_only_scoped_nonimpacts_unchanged(graph):
    base = next(node for node in graph.nodes if type(node) is Claim)
    isolated = replace(base, node_id=claim_node_id(base.comparison_id, "cand-isolated"),
                       candidate_id="cand-isolated", citations=())
    updated = create_graph((*graph.nodes, isolated), graph.edges)
    plan = plan_challenge_impact(updated, _request(updated, isolated))
    assert plan.traversal.complete
    assert _impact(plan, isolated).state is ImpactState.DIRECTLY_CHALLENGED
    assert all(item.state is ImpactState.UNCHANGED for item in plan.impacts
               if item.node_id != isolated.node_id)


def test_request_order_is_descriptive_and_plan_is_deterministic(graph):
    _, passage, _ = _event_passage_and_claim(graph)
    request = _request(graph, passage, order=42)
    first = plan_challenge_impact(graph, request)
    second = plan_challenge_impact(graph, request)
    assert first == second
    assert first.event_order == 42
    assert "no persisted event history" in first.event_order_note


def test_multiple_paths_are_stably_ordered_across_repeated_and_reordered_graphs(graph):
    _, passage, claim = _event_passage_and_claim(graph)
    extra_edges = tuple(make_edge(
        passage.node_id, claim.node_id, edge_type, EpistemicStatus.PROPOSED,
        "Synthetic proposal path only.",
    ) for edge_type in (EdgeType.SUPPORTS, EdgeType.CONTRADICTS))
    multi_path_graph = create_graph(graph.nodes, (*graph.edges, *extra_edges))
    request = _request(multi_path_graph, passage)

    first = plan_challenge_impact(multi_path_graph, request)
    repeated = plan_challenge_impact(multi_path_graph, request)
    reordered_graph = create_graph(tuple(reversed(multi_path_graph.nodes)),
                                   tuple(reversed(multi_path_graph.edges)))
    reordered = plan_challenge_impact(reordered_graph, request)

    paths = _impact(first, claim).paths
    assert len(paths) == 3
    assert paths == tuple(sorted(paths, key=lambda path: tuple(
        (step.edge_id, step.from_node_id, step.to_node_id, step.direction.value)
        for step in path
    )))
    assert first == repeated == reordered


def test_unchanged_scope_and_edge_accounting_are_explicit_for_isolated_target(graph):
    base = next(node for node in graph.nodes if type(node) is Claim)
    isolated = replace(base, node_id=claim_node_id(base.comparison_id, "cand-scope-isolated"),
                       candidate_id="cand-scope-isolated", citations=())
    updated = create_graph((*graph.nodes, isolated), graph.edges)
    plan = plan_challenge_impact(updated, _request(updated, isolated))

    assert plan.traversal.complete
    assert _impact(plan, next(node for node in updated.nodes if node.node_type is NodeType.SOURCE_DOCUMENT)).state is ImpactState.UNCHANGED
    assert plan.traversal.examined_node_ids == (isolated.node_id,)
    assert plan.traversal.preprocessed_edges == len(updated.edges)
    assert plan.traversal.traversed_edges == 0
    assert "does not mean the node was individually visited" in plan.traversal.scope_note
    unchanged = next(item for item in plan.impacts if item.state is ImpactState.UNCHANGED)
    assert "does not establish" in unchanged.reason


def test_incomplete_plan_scope_note_does_not_claim_unexplored_nodes_unchanged(graph, monkeypatch):
    _, passage, claim_template = _event_passage_and_claim(graph)
    extra_claims = []
    proposals = []
    for index in range(6):
        candidate_id = f"cand-incomplete-{index:02d}"
        claim = replace(claim_template,
                        node_id=claim_node_id(claim_template.comparison_id, candidate_id),
                        candidate_id=candidate_id, citations=())
        extra_claims.append(claim)
        proposals.append(make_edge(passage.node_id, claim.node_id, EdgeType.SUPPORTS,
                                   EpistemicStatus.PROPOSED, "Synthetic proposal only."))
    updated = create_graph((*graph.nodes, *extra_claims), (*graph.edges, *proposals))
    monkeypatch.setattr(propagation, "MAX_VISITED_NODES", 3)

    plan = plan_challenge_impact(updated, _request(updated, passage))

    assert not plan.traversal.complete
    assert plan.traversal.limit_reached is PlannerLimit.VISITED_NODES
    assert "not labeled UNCHANGED" in plan.traversal.scope_note
    assert plan.traversal.unexplored_node_ids
    assert all(item.state is not ImpactState.UNCHANGED for item in plan.impacts)


def test_planning_does_not_mutate_graph_or_request(graph):
    _, passage, _ = _event_passage_and_claim(graph)
    request = _request(graph, passage)
    before = deepcopy((graph.snapshot_identity, graph.nodes, graph.edges, request))
    plan_challenge_impact(graph, request)
    assert (graph.snapshot_identity, graph.nodes, graph.edges, request) == before
    with pytest.raises((AttributeError, TypeError)):
        graph.edges = ()


def test_public_result_models_reject_mutable_constructor_collections():
    challenge_id = "challenge-immutable"
    direct = NodeImpact("target", NodeType.CLAIM, ImpactState.DIRECTLY_CHALLENGED,
                        "Direct target.", challenge_id, ((),))
    step = PathStep("edge:synthetic", "target", "dependent", TraversalDirection.FORWARD)
    traversal = TraversalCompleteness(
        True, None, 1, 0, ("target",), (), 0, "Completed bounded scope.",
    )
    original_path = [step]
    with pytest.raises(ChallengePropagationError) as path_step_error:
        PathStep([], "target", "dependent", TraversalDirection.FORWARD)  # type: ignore[arg-type]
    original_path.append(step)
    assert path_step_error.value.code == "invalid_result"

    with pytest.raises(ChallengePropagationError) as impact_error:
        NodeImpact("dependent", NodeType.CLAIM, ImpactState.REASSESSMENT_REQUIRED,
                   "Review dependency.", challenge_id, [original_path])  # type: ignore[arg-type]
    assert impact_error.value.code == "invalid_result"

    mutable_code = ["MISSING_PROVENANCE"]
    with pytest.raises(ChallengePropagationError) as blocker_error:
        PlanBlocker(mutable_code, "target", "Missing source.")  # type: ignore[arg-type]
    mutable_code.append("CROSS_CANDIDATE_BOUNDARY")
    assert blocker_error.value.code == "invalid_result"

    mutable_examined = ["target"]
    with pytest.raises(ChallengePropagationError) as traversal_error:
        TraversalCompleteness(True, None, 1, 0, mutable_examined, (), 0,
                             "Completed bounded scope.")  # type: ignore[arg-type]
    mutable_examined.append("dependent")
    assert traversal_error.value.code == "invalid_result"

    mutable_impacts = [direct]
    with pytest.raises(ChallengePropagationError) as plan_error:
        ChallengeImpactPlan(
            "cmp-syn-immutable", challenge_id, 0, "Descriptive only.", (),
            mutable_impacts, (), traversal, (),  # type: ignore[arg-type]
        )
    mutable_impacts.clear()
    assert plan_error.value.code == "invalid_result"


def test_public_result_models_accept_only_deeply_immutable_tuple_graph():
    challenge_id = "challenge-immutable"
    step = PathStep("edge:synthetic", "target", "dependent", TraversalDirection.FORWARD)
    direct = NodeImpact("target", NodeType.CLAIM, ImpactState.DIRECTLY_CHALLENGED,
                        "Direct target.", challenge_id, ((),))
    dependent = NodeImpact("dependent", NodeType.CLAIM, ImpactState.REASSESSMENT_REQUIRED,
                           "Review dependency.", challenge_id, ((step,),))
    traversal = TraversalCompleteness(
        True, None, 2, 1, ("dependent", "target"), (), 1,
        "Completed bounded scope.",
    )
    result = ChallengeImpactPlan(
        "cmp-syn-immutable", challenge_id, 0, "Descriptive only.", (),
        (dependent, direct), (), traversal, ("Review only.",),
    )
    assert type(result.impacts) is tuple
    assert type(result.impacts[0].paths) is tuple
    assert type(result.impacts[0].paths[0]) is tuple
    with pytest.raises((AttributeError, TypeError)):
        result.impacts[0].paths = ()  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        result.traversal.examined_node_ids += ("extra",)  # type: ignore[misc]


@pytest.mark.parametrize("field,value", [
    ("challenge_id", ""),
    ("comparison_id", ""),
    ("target_node_id", ""),
    ("target_node_type", "SourcePassage"),
    ("category", "OTHER"),
    ("explanation", "  "),
    ("evidence_refs", ["passage"]),
    ("event_order", True),
])
def test_request_rejects_malformed_exact_types(field, value):
    values = {
        "challenge_id": "challenge-1", "comparison_id": "cmp-syn-demo",
        "target_node_id": "source-passage:synthetic", "target_node_type": SourcePassage.node_type,
        "category": ChallengeCategory.OTHER, "explanation": "Review this synthetic target.",
        "evidence_refs": (), "event_order": 0,
    }
    values[field] = value
    with pytest.raises(ChallengePropagationError) as error:
        ChallengeRequest(**values)
    assert error.value.code == "invalid_request"
    assert "synthetic" not in str(error.value)


def test_wrong_target_type_and_missing_target_fail_closed(graph):
    _, passage, _ = _event_passage_and_claim(graph)
    request = replace(_request(graph, passage), target_node_type=next(
        node.node_type for node in graph.nodes if type(node) is Claim
    ))
    with pytest.raises(ChallengePropagationError) as mismatch:
        plan_challenge_impact(graph, request)
    assert mismatch.value.code == "target_type_mismatch"
    missing = replace(_request(graph, passage), target_node_id="absent-node")
    with pytest.raises(ChallengePropagationError) as absent:
        plan_challenge_impact(graph, missing)
    assert absent.value.code == "missing_target"


def test_evidence_reference_must_name_existing_source_passage(graph):
    _, passage, _ = _event_passage_and_claim(graph)
    request = _request(graph, passage, evidence_refs=("missing-passage",))
    with pytest.raises(ChallengePropagationError) as error:
        plan_challenge_impact(graph, request)
    assert error.value.code == "invalid_evidence_ref"


def test_incomplete_visited_node_limit_never_labels_nodes_unchanged(graph, monkeypatch):
    _, passage, claim_template = _event_passage_and_claim(graph)
    extra_claims = []
    support_edges = []
    for index in range(8):
        candidate_id = f"cand-wide-{index:02d}"
        claim = replace(claim_template,
                        node_id=claim_node_id(claim_template.comparison_id, candidate_id),
                        candidate_id=candidate_id, citations=())
        extra_claims.append(claim)
        support_edges.append(make_edge(
            passage.node_id, claim.node_id, EdgeType.SUPPORTS,
            EpistemicStatus.PROPOSED, "Synthetic proposal only.",
        ))
    updated = create_graph((*graph.nodes, *extra_claims), (*graph.edges, *support_edges))
    monkeypatch.setattr(propagation, "MAX_VISITED_NODES", 4)

    plan = plan_challenge_impact(updated, _request(updated, passage))

    assert not plan.traversal.complete
    assert plan.traversal.limit_reached is PlannerLimit.VISITED_NODES
    assert plan.traversal.unexplored_node_ids
    assert all(item.state is not ImpactState.UNCHANGED for item in plan.impacts)


def test_path_length_limit_is_reported_without_recursion(graph, monkeypatch):
    _, passage, _ = _event_passage_and_claim(graph)
    monkeypatch.setattr(propagation, "MAX_PATH_LENGTH", 1)
    plan = plan_challenge_impact(graph, _request(graph, passage))
    assert not plan.traversal.complete
    assert plan.traversal.limit_reached is PlannerLimit.PATH_LENGTH
    assert all(item.state is not ImpactState.UNCHANGED for item in plan.impacts)


@pytest.mark.parametrize("limit_name,limit_value,expected", [
    ("MAX_TRAVERSED_EDGES", 1, PlannerLimit.TRAVERSED_EDGES),
    ("MAX_PATHS_PER_NODE", 1, PlannerLimit.PATHS_PER_NODE),
    ("MAX_TOTAL_PATH_ENTRIES", 1, PlannerLimit.TOTAL_PATH_ENTRIES),
])
def test_each_remaining_traversal_budget_reports_incomplete(
        graph, monkeypatch, limit_name, limit_value, expected):
    _, passage, claim = _event_passage_and_claim(graph)
    proposal = make_edge(passage.node_id, claim.node_id, EdgeType.SUPPORTS,
                         EpistemicStatus.PROPOSED, "Synthetic proposal only.")
    updated = create_graph(graph.nodes, (*graph.edges, proposal))
    monkeypatch.setattr(propagation, limit_name, limit_value)

    plan = plan_challenge_impact(updated, _request(updated, passage))

    assert not plan.traversal.complete
    assert plan.traversal.limit_reached is expected
    assert plan.traversal.unexplored_node_ids
    assert all(item.state is not ImpactState.UNCHANGED for item in plan.impacts)
    if expected is PlannerLimit.TRAVERSED_EDGES:
        assert plan.traversal.traversed_edges == limit_value


def test_graph_validation_errors_are_sanitized_at_planner_boundary(graph):
    malformed = object.__new__(EvidenceDependencyGraph)
    object.__setattr__(malformed, "snapshot_identity", "forged")
    object.__setattr__(malformed, "nodes", graph.nodes)
    object.__setattr__(malformed, "edges", graph.edges)
    _, passage, _ = _event_passage_and_claim(graph)
    with pytest.raises(ChallengePropagationError) as error:
        plan_challenge_impact(malformed, _request(graph, passage))
    assert error.value.code == "invalid_graph"
    assert "forged" not in str(error.value)


def test_graph_failure_path_does_not_expose_dependency_graph_exception(graph):
    _, passage, _ = _event_passage_and_claim(graph)
    request = _request(graph, passage)
    with pytest.raises(ChallengePropagationError) as error:
        plan_challenge_impact(None, request)  # type: ignore[arg-type]
    assert error.value.code == "invalid_graph"
    assert not isinstance(error.value, DependencyGraphError)

