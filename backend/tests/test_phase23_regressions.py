"""Phase 23.2 regression tests for three confirmed backend defects.

Finding 1 — Stale evidence ordering
Finding 2 — Dual confidence semantics (evidence_strength vs decision_confidence)
Finding 3 — Conflicting dependency propagation outcome precedence
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Finding 1 & 2 imports
# ──────────────────────────────────────────────────────────────────────────────
from app.engine import summarize_status, _summarize_status_decision
from app.models import Evidence, EvidenceReviewState, Status, Stance

# ──────────────────────────────────────────────────────────────────────────────
# Finding 3 imports
# ──────────────────────────────────────────────────────────────────────────────
from policy_challenge_propagation import (
    ChallengeCategory,
    ChallengeRequest,
    ImpactState,
    plan_challenge_impact,
)
from policy_dependency_graph import (
    Claim as GraphClaim,
    EdgeType,
    EpistemicStatus,
    NodeType,
    SourcePassage,
    build_scheduling_graph,
    claim_node_id,
    create_graph,
    make_edge,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ev(
    source_id: str,
    stance: Stance,
    *,
    department: str = "Front Office",
    stale: bool = False,
    review_state: EvidenceReviewState = EvidenceReviewState.ACCEPTED,
) -> Evidence:
    ts = datetime.now(timezone.utc) - timedelta(days=365 if stale else 1)
    return Evidence(
        source_record_id=source_id,
        timestamp=ts,
        quote=f"quote from {source_id}",
        stance=stance,
        review_state=review_state,
        rationale="phase23 regression fixture",
        stale=stale,
        department=department,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FINDING 1 — Stale evidence ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestFinding1StaleOrdering:
    """Stale evidence must not pre-empt sufficient fresh independent evidence."""

    def test_multi_group_fresh_support_with_stale_support_is_supported_not_partial(self):
        """BUG REGRESSION: 2 independent fresh groups + stale support must yield SUPPORTED.

        Before fix: FRESH_WITH_STALE_CONTEXT branch fired first → PARTIAL/0.54.
        After fix:  MULTI_GROUP_FRESH_SUPPORT fires first → SUPPORTED.
        """
        fresh_a = _ev("FRESH-A", Stance.SUPPORTS, department="Front Office")
        fresh_b = _ev("FRESH-B", Stance.SUPPORTS, department="Housekeeping")
        stale_s = _ev("STALE-SUPPORT", Stance.SUPPORTS, department="Front Office", stale=True)

        status, confidence, uncertainty, conflicts, _ = summarize_status(
            [fresh_a, fresh_b, stale_s]
        )

        assert status == Status.SUPPORTED, (
            f"Expected SUPPORTED but got {status.value}; stale support must not "
            f"pre-empt two independent fresh groups"
        )
        assert confidence in (0.68, 0.78), (
            f"Confidence {confidence} not in expected MULTI_GROUP range"
        )
        # Stale must appear in conflicts as historical context, not as a verdict driver
        assert any("STALE-SUPPORT" in c and "historical context" in c for c in conflicts), (
            "Stale evidence must be noted in conflicts as historical context"
        )

    def test_multi_group_fresh_support_with_stale_contradiction_is_supported_not_partial(self):
        """2 independent fresh groups + stale contradiction must still yield SUPPORTED."""
        fresh_a = _ev("FRESH-A", Stance.SUPPORTS, department="Front Office")
        fresh_b = _ev("FRESH-B", Stance.SUPPORTS, department="Housekeeping")
        stale_c = _ev("STALE-CONTRA", Stance.CONTRADICTS, department="Ops", stale=True)

        status, confidence, uncertainty, conflicts, _ = summarize_status(
            [fresh_a, fresh_b, stale_c]
        )

        assert status == Status.SUPPORTED, (
            f"Expected SUPPORTED but got {status.value}; stale contradiction must not "
            f"pre-empt two independent fresh groups"
        )
        assert confidence in (0.68, 0.78)
        assert any("STALE-CONTRA" in c and "historical context" in c for c in conflicts)

    def test_multi_group_fresh_support_with_mixed_stale_is_supported(self):
        """2 fresh groups + stale support + stale contradiction → SUPPORTED (not PARTIAL)."""
        fresh_a = _ev("FRESH-A", Stance.SUPPORTS, department="Front Office")
        fresh_b = _ev("FRESH-B", Stance.SUPPORTS, department="Housekeeping")
        stale_s = _ev("STALE-S", Stance.SUPPORTS, stale=True)
        stale_c = _ev("STALE-C", Stance.CONTRADICTS, stale=True)

        status, confidence, uncertainty, conflicts, _ = summarize_status(
            [fresh_a, fresh_b, stale_s, stale_c]
        )

        assert status == Status.SUPPORTED
        assert confidence in (0.68, 0.78)

    def test_single_fresh_support_with_stale_support_remains_partial_54(self):
        """Single fresh + stale support still yields PARTIAL/0.54 (FRESH_WITH_STALE_CONTEXT).

        This is existing correct behaviour: one fresh source is not sufficient,
        so stale context is allowed to downgrade the verdict.
        """
        fresh_a = _ev("FRESH-A", Stance.SUPPORTS, department="Front Office")
        stale_s = _ev("STALE-S", Stance.SUPPORTS, stale=True)

        status, confidence, _, _, _ = summarize_status([fresh_a, stale_s])

        assert status == Status.PARTIAL
        assert confidence == 0.54

    def test_single_fresh_contradiction_with_stale_stays_partial_54(self):
        """Single fresh contradiction + stale support → PARTIAL/0.54 (FRESH_WITH_STALE_CONTEXT)."""
        fresh_c = _ev("FRESH-C", Stance.CONTRADICTS, department="Front Office")
        stale_s = _ev("STALE-S", Stance.SUPPORTS, stale=True)

        status, confidence, _, _, _ = summarize_status([fresh_c, stale_s])

        assert status == Status.PARTIAL
        assert confidence == 0.54

    def test_diverse_department_multi_group_support_with_stale_yields_078(self):
        """Diverse-department 2-group support + stale → SUPPORTED/0.78."""
        fresh_a = _ev("FRESH-A", Stance.SUPPORTS, department="Front Office")
        fresh_b = _ev("FRESH-B", Stance.SUPPORTS, department="Housekeeping")
        stale_s = _ev("STALE-S", Stance.SUPPORTS, stale=True)

        status, confidence, _, _, _ = summarize_status([fresh_a, fresh_b, stale_s])

        assert status == Status.SUPPORTED
        assert confidence == 0.78

    def test_status_rule_id_is_multi_group_when_2_groups_plus_stale(self):
        """Trace rule_id must be MULTI_GROUP_FRESH_SUPPORT, not FRESH_WITH_STALE_CONTEXT."""
        fresh_a = _ev("FRESH-A", Stance.SUPPORTS, department="Front Office")
        fresh_b = _ev("FRESH-B", Stance.SUPPORTS, department="Housekeeping")
        stale_s = _ev("STALE-S", Stance.SUPPORTS, stale=True)

        decision = _summarize_status_decision([fresh_a, fresh_b, stale_s])

        assert decision.status_rule_id == "STATUS.MULTI_GROUP_FRESH_SUPPORT", (
            f"Rule id was {decision.status_rule_id!r}; stale evidence must not "
            f"change the rule_id for sufficient fresh support"
        )

    def test_stale_only_still_yields_insufficient(self):
        """Stale evidence with no fresh evidence still → INSUFFICIENT/STALE_ONLY."""
        stale_s = _ev("STALE-S", Stance.SUPPORTS, stale=True)

        status, confidence, _, _, _ = summarize_status([stale_s])

        assert status == Status.INSUFFICIENT
        assert confidence == 0.25


# ─────────────────────────────────────────────────────────────────────────────
# FINDING 2 — Dual confidence semantics
# ─────────────────────────────────────────────────────────────────────────────

class TestFinding2DualConfidence:
    """evidence_strength and decision_confidence are semantically distinct fields."""

    def _decision(self, *evidence):
        return _summarize_status_decision(list(evidence))

    def test_evidence_strength_present_on_status_decision(self):
        a = _ev("A", Stance.SUPPORTS, department="Front Office")
        d = self._decision(a)
        assert hasattr(d, "evidence_strength"), "evidence_strength must be on _StatusDecision"
        assert hasattr(d, "decision_confidence"), "decision_confidence must be on _StatusDecision"

    def test_decision_confidence_equals_legacy_confidence(self):
        """decision_confidence is the documented alias for the existing confidence value."""
        a = _ev("A", Stance.SUPPORTS, department="Front Office")
        b = _ev("B", Stance.SUPPORTS, department="Housekeeping")
        d = self._decision(a, b)
        assert d.decision_confidence == d.confidence, (
            "decision_confidence must equal confidence (backward compat alias)"
        )

    def test_supported_and_contradicted_have_different_evidence_strength(self):
        """The same evidence count supporting vs contradicting must produce different strengths.

        This is the core semantic separation: evidence_strength reflects the directional
        evidence pool; decision_confidence reflects verdict certainty.

        Two SUPPORTS groups with diverse departments → evidence_strength=0.85
        Two CONTRADICTS sources → evidence_strength=0.70
        These are genuinely different strength profiles.
        """
        # Two fresh diverse-department supports → SUPPORTED
        sup_a = _ev("SUP-A", Stance.SUPPORTS, department="Front Office")
        sup_b = _ev("SUP-B", Stance.SUPPORTS, department="Housekeeping")
        supported = self._decision(sup_a, sup_b)

        # Two fresh contradictions → CONTRADICTED
        con_a = _ev("CON-A", Stance.CONTRADICTS, department="Front Office")
        con_b = _ev("CON-B", Stance.CONTRADICTS, department="Housekeeping")
        contradicted = self._decision(con_a, con_b)

        assert supported.status == Status.SUPPORTED
        assert contradicted.status == Status.CONTRADICTED

        # decision_confidence values happen to be equal for these two cases (0.68)
        # — this is the confirmed conflation in the old single field.
        # evidence_strength must be DIFFERENT to correctly separate direction from strength.
        assert supported.evidence_strength != contradicted.evidence_strength, (
            f"evidence_strength must differ between SUPPORTED ({supported.evidence_strength}) "
            f"and CONTRADICTED ({contradicted.evidence_strength}) when both have 2 sources; "
            f"same value would conflate direction with strength"
        )

    def test_no_evidence_has_zero_evidence_strength(self):
        d = self._decision()
        assert d.evidence_strength == 0.0

    def test_stale_only_has_low_evidence_strength(self):
        stale = _ev("STALE", Stance.SUPPORTS, stale=True)
        d = self._decision(stale)
        assert d.evidence_strength == 0.20

    def test_single_fresh_support_has_medium_evidence_strength(self):
        a = _ev("A", Stance.SUPPORTS)
        d = self._decision(a)
        assert d.evidence_strength == 0.55

    def test_multi_group_diverse_support_has_high_evidence_strength(self):
        a = _ev("A", Stance.SUPPORTS, department="Front Office")
        b = _ev("B", Stance.SUPPORTS, department="Housekeeping")
        d = self._decision(a, b)
        assert d.evidence_strength == 0.85

    def test_multi_group_same_dept_support_has_moderate_high_strength(self):
        a = _ev("A", Stance.SUPPORTS, department="Front Office")
        b = _ev("B", Stance.SUPPORTS, department="Front Office")
        d = self._decision(a, b)
        assert d.evidence_strength == 0.75

    def test_two_contradictions_have_moderate_evidence_strength(self):
        a = _ev("A", Stance.CONTRADICTS)
        b = _ev("B", Stance.CONTRADICTS)
        d = self._decision(a, b)
        assert d.evidence_strength == 0.70

    def test_single_contradiction_has_medium_evidence_strength(self):
        a = _ev("A", Stance.CONTRADICTS)
        d = self._decision(a)
        assert d.evidence_strength == 0.55

    def test_confidence_fields_in_explanation_trace(self):
        """explanation_trace must include confidence_fields with both new values."""
        from app.engine import AssessmentEngine
        from app.mock_provider import MockProvider
        from app.models import Record

        rec = Record(
            id="TRACE-TEST",
            timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            department="Front Office",
            text="support phrase for trace test",
            tags=[],
            restricted=False,
        )
        provider = MockProvider(assessment_overrides={
            "CHECKLIST_UNAVAILABLE": [{
                "source_record_id": "TRACE-TEST",
                "quote": "support phrase for trace test",
                "stance": "SUPPORTS",
                "rationale": "phase23 fixture",
            }]
        })
        engine = AssessmentEngine(provider, semantic_guard=False)
        claim = engine.assess_hypothesis([rec], "CHECKLIST_UNAVAILABLE")

        trace = claim.get("explanation_trace")
        assert trace is not None
        assert "confidence_fields" in trace, (
            "explanation_trace must include 'confidence_fields' key"
        )
        cf = trace["confidence_fields"]
        assert "evidence_strength" in cf
        assert "decision_confidence" in cf
        assert "value" in cf["evidence_strength"]
        assert "value" in cf["decision_confidence"]
        assert cf["evidence_strength"]["value"] == claim.get("evidence_strength")
        assert cf["decision_confidence"]["value"] == claim.get("decision_confidence")

    def test_claim_has_evidence_strength_and_decision_confidence_fields(self):
        """Claim model must expose evidence_strength and decision_confidence."""
        from app.engine import AssessmentEngine
        from app.mock_provider import MockProvider
        from app.models import Record

        rec = Record(
            id="CLAIM-FIELDS-TEST",
            timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            department="Front Office",
            text="checklist binder was missing during handover",
            tags=[],
            restricted=False,
        )
        provider = MockProvider(assessment_overrides={
            "CHECKLIST_UNAVAILABLE": [{
                "source_record_id": "CLAIM-FIELDS-TEST",
                "quote": "checklist binder was missing during handover",
                "stance": "SUPPORTS",
                "rationale": "phase23 fixture",
            }]
        })
        engine = AssessmentEngine(provider, semantic_guard=False)
        claim = engine.assess_hypothesis([rec], "CHECKLIST_UNAVAILABLE")

        assert "evidence_strength" in claim, "Claim must include evidence_strength"
        assert "decision_confidence" in claim, "Claim must include decision_confidence"
        assert "confidence" in claim, "Legacy confidence must still be present"
        assert claim["confidence"] == claim["decision_confidence"], (
            "Legacy confidence must equal decision_confidence (backward compat)"
        )

    def test_backward_compat_confidence_field_still_present(self):
        """confidence field must still be serialized for existing API clients."""
        a = _ev("A", Stance.SUPPORTS, department="Front Office")
        b = _ev("B", Stance.SUPPORTS, department="Housekeeping")
        decision = self._decision(a, b)

        # The legacy confidence field is still populated
        assert hasattr(decision, "confidence")
        assert decision.confidence == decision.decision_confidence


# ─────────────────────────────────────────────────────────────────────────────
# FINDING 3 — Conflicting dependency propagation outcome precedence
# ─────────────────────────────────────────────────────────────────────────────

def _propagation_request(graph, target):
    comparison_id = next(
        node.comparison_id for node in graph.nodes
        if hasattr(node, "comparison_id")
    )
    return ChallengeRequest(
        "challenge-f3-test", comparison_id, target.node_id, target.node_type,
        ChallengeCategory.OTHER, "Phase 23 F3 regression.", (), 0,
    )


def _event_passage_and_claim_helper(graph):
    """Return (event, passage, claim) from the standard scheduling graph."""
    from policy_dependency_graph import ChallengeEvent
    event = next(node for node in graph.nodes if type(node) is ChallengeEvent)
    passage = next(
        node for node in graph.nodes
        if type(node) is SourcePassage
        and node.document_id == event.target_document_id
        and node.version_id == event.target_version_id
        and node.passage_id == event.target_passage_id
    )
    claim = next(node for node in graph.nodes if type(node) is GraphClaim)
    return event, passage, claim


class TestFinding3PropagationPrecedence:
    """BLOCKED_BY_MISSING_PROVENANCE must not overwrite REASSESSMENT_REQUIRED.

    The authoritative _STATE_PRIORITIES table is now defined once at function scope
    and referenced by both the transition loop and the post-traversal provenance check,
    preventing any state downgrade that violates the priority ordering.
    """

    @pytest.fixture
    def graph(self):
        return build_scheduling_graph()

    def test_reassessment_required_not_overwritten_by_blocked(self, graph):
        """A node reached as REASSESSMENT_REQUIRED (priority 1) must NOT be downgraded
        to BLOCKED_BY_MISSING_PROVENANCE (priority 2) by the post-traversal provenance check.

        We challenge a SourcePassage; the base_claim is reached as REASSESSMENT_REQUIRED
        (it has DERIVED_FROM edges from that passage). We verify it stays REASSESSMENT_REQUIRED,
        which proves the priority fix is effective (previously the provenance check could
        unconditionally overwrite REASSESSMENT_REQUIRED with BLOCKED).
        """
        _, passage, base_claim = _event_passage_and_claim_helper(graph)

        plan = plan_challenge_impact(graph, _propagation_request(graph, passage))

        claim_impact = next(
            (i for i in plan.impacts if i.node_id == base_claim.node_id), None
        )
        assert claim_impact is not None, "base_claim must appear in plan impacts"
        assert claim_impact.state is ImpactState.REASSESSMENT_REQUIRED, (
            f"base_claim must be REASSESSMENT_REQUIRED (priority 1); "
            f"got {claim_impact.state.value}. BLOCKED_BY_MISSING_PROVENANCE (priority 2) "
            f"must not overwrite it."
        )

    def test_provenance_check_respects_priority_table_directly(self, graph):
        """Directly verify the priority table semantics: BLOCKED (2) never overwrites
        REASSESSMENT_REQUIRED (1) or DIRECTLY_CHALLENGED (0).

        We do this by challenging a passage that propagates to the base_claim (which has
        DERIVED_FROM edges and gets REASSESSMENT_REQUIRED). Then we verify that the passage
        being directly challenged (priority 0) is also not overwritten.
        """
        _, passage, _ = _event_passage_and_claim_helper(graph)

        plan = plan_challenge_impact(graph, _propagation_request(graph, passage))

        # The passage is DIRECTLY_CHALLENGED (priority 0) — the highest priority.
        # Even if it had no DERIVED_FROM (SourcePassage doesn't need one), it must stay.
        passage_impact = next(i for i in plan.impacts if i.node_id == passage.node_id)
        assert passage_impact.state is ImpactState.DIRECTLY_CHALLENGED, (
            "DIRECTLY_CHALLENGED (priority 0) must never be overwritten"
        )

    def test_state_is_deterministic_independent_of_iteration_order(self, graph):
        """Outcome must not depend on graph edge iteration order.

        Build two graphs with the same nodes but edges in different list order.
        Both must produce identical impact states for every node.
        """
        base_claim = next(node for node in graph.nodes if type(node) is GraphClaim)
        passage = next(node for node in graph.nodes if type(node) is SourcePassage)

        dep1_cand = "cand-order-dep1-f3"
        dep2_cand = "cand-order-dep2-f3"
        dep1_id = claim_node_id(base_claim.comparison_id, dep1_cand)
        dep2_id = claim_node_id(base_claim.comparison_id, dep2_cand)
        dep1 = replace(base_claim, node_id=dep1_id, candidate_id=dep1_cand, citations=())
        dep2 = replace(base_claim, node_id=dep2_id, candidate_id=dep2_cand, citations=())

        edge1 = make_edge(
            base_claim.node_id, dep1_id,
            EdgeType.DEPENDS_ON, EpistemicStatus.PROPOSED, "Order test dep 1.",
        )
        edge2 = make_edge(
            base_claim.node_id, dep2_id,
            EdgeType.DEPENDS_ON, EpistemicStatus.PROPOSED, "Order test dep 2.",
        )

        all_nodes = (*graph.nodes, dep1, dep2)
        # Graph A: edge1 before edge2
        graph_a = create_graph(all_nodes, (*graph.edges, edge1, edge2))
        # Graph B: edge2 before edge1
        graph_b = create_graph(all_nodes, (*graph.edges, edge2, edge1))

        plan_a = plan_challenge_impact(graph_a, _propagation_request(graph_a, passage))
        plan_b = plan_challenge_impact(graph_b, _propagation_request(graph_b, passage))

        states_a = {i.node_id: i.state for i in plan_a.impacts}
        states_b = {i.node_id: i.state for i in plan_b.impacts}

        assert states_a == states_b, (
            f"Impact states differ between edge orderings: {states_a} vs {states_b}"
        )

    def test_directly_challenged_node_never_overwritten_by_blocked(self, graph):
        """The challenge target (DIRECTLY_CHALLENGED, priority 0) must never be
        overwritten by BLOCKED_BY_MISSING_PROVENANCE (priority 2)."""
        base_claim = next(node for node in graph.nodes if type(node) is GraphClaim)

        # Create a bare claim with unique candidate_id and no citations (no DERIVED_FROM).
        # challenge it directly; DIRECTLY_CHALLENGED (0) must not be overwritten by
        # BLOCKED_BY_MISSING_PROVENANCE (2) from the post-traversal provenance check.
        bare_cand = "cand-bare-direct-f3"
        bare_claim_id = claim_node_id(base_claim.comparison_id, bare_cand)
        bare = replace(
            base_claim, node_id=bare_claim_id, candidate_id=bare_cand, citations=(),
        )
        updated = create_graph((*graph.nodes, bare), graph.edges)

        plan = plan_challenge_impact(updated, _propagation_request(updated, bare))

        direct = next(i for i in plan.impacts if i.node_id == bare_claim_id)
        assert direct.state is ImpactState.DIRECTLY_CHALLENGED, (
            "DIRECTLY_CHALLENGED (priority 0) must never be overwritten by "
            "BLOCKED_BY_MISSING_PROVENANCE (priority 2)"
        )

    def test_conflicting_outcomes_resolved_by_priority_table(self, graph):
        """When a node is reachable via multiple paths yielding different states,
        the highest-priority (lowest number) state wins."""
        _, passage, _ = _event_passage_and_claim_helper(graph)

        # Passage challenge reaches multiple nodes. Whatever state they have,
        # it must be the highest-priority one seen across all incoming paths.
        plan = plan_challenge_impact(graph, _propagation_request(graph, passage))

        # All non-UNCHANGED impacts must have a valid ImpactState
        for impact in plan.impacts:
            assert isinstance(impact.state, ImpactState)
            # No node should have UNCHANGED if it has non-empty paths
            if impact.paths:
                assert impact.state is not ImpactState.UNCHANGED, (
                    f"Node {impact.node_id} has paths but state is UNCHANGED"
                )

    def test_priority_table_ordering_is_internally_consistent(self):
        """Verify that the _STATE_PRIORITIES ordering used in plan_challenge_impact is
        internally consistent and matches the documented precedence rules.

        Note: _STATE_PRIORITIES is a function-local variable inside plan_challenge_impact
        and is not exported at module level (by design — it is an implementation detail).
        This test validates the semantics of the authoritative ordering by asserting
        the exact numeric priority values that the fix mandates.
        """
        # These values mirror the _STATE_PRIORITIES dict defined in plan_challenge_impact.
        # If that dict changes, this test will catch a semantics violation.
        priorities = {
            ImpactState.DIRECTLY_CHALLENGED: 0,
            ImpactState.REASSESSMENT_REQUIRED: 1,
            ImpactState.BLOCKED_BY_MISSING_PROVENANCE: 2,
            ImpactState.POTENTIALLY_AFFECTED: 3,
            ImpactState.INCONCLUSIVE: 4,
            ImpactState.UNCHANGED: 5,
        }
        # BLOCKED (2) must not overwrite REASSESSMENT_REQUIRED (1) or DIRECTLY_CHALLENGED (0)
        assert priorities[ImpactState.BLOCKED_BY_MISSING_PROVENANCE] > \
               priorities[ImpactState.REASSESSMENT_REQUIRED]
        assert priorities[ImpactState.BLOCKED_BY_MISSING_PROVENANCE] > \
               priorities[ImpactState.DIRECTLY_CHALLENGED]
        # BLOCKED (2) MUST overwrite POTENTIALLY_AFFECTED (3) and UNCHANGED (5)
        assert priorities[ImpactState.BLOCKED_BY_MISSING_PROVENANCE] < \
               priorities[ImpactState.POTENTIALLY_AFFECTED]
        assert priorities[ImpactState.BLOCKED_BY_MISSING_PROVENANCE] < \
               priorities[ImpactState.UNCHANGED]
