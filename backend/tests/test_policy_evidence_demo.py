"""Focused offline tests for the Policy Investigator Evidence Demo.

Verifies:
1. Scenario initial proposal output (COMPATIBLE_CHANGE).
2. Local citation provenance derivation and boundary limits.
3. Reviewer challenge triggering dependency-aware recomputation.
4. Ungrounded department applicability remaining unresolved.
5. Invariant preservation (PROPOSAL_ONLY, NOT_VERIFIED, human_review_required).
6. Malformed inputs and contract tampering failing closed.
7. Total isolation from active API and remote network providers.
"""
from __future__ import annotations

import sys
from typing import Any

import pytest

from policy_candidate_adapter import MAX_REASONING, PolicyCandidateAdapterError
from policy_compare import (
    PolicyCompareError,
    PolicyPair,
    validate_policy_pair,
)
from policy_evidence_demo import (
    COMPARISON_ID,
    DOC_ID,
    HOTEL_NAME,
    V1_NOTICE_QUOTE,
    V1_TEXT,
    V2_NOTICE_QUOTE,
    V2_TEXT,
    UNIFORM_COMPARISON_ID,
    UNIFORM_DOC_ID,
    UNIFORM_V1_QUOTE,
    UNIFORM_V2_QUOTE,
    LOUNGE_COMPARISON_ID,
    LOUNGE_DOC_ID,
    LOUNGE_V1_QUOTE,
    LOUNGE_V2_QUOTE,
    SCENARIO_SCHEDULING,
    SCENARIO_UNIFORM,
    SCENARIO_LOUNGE,
    ALLOWED_SCENARIO_IDS,
    ReviewerChallenge,
    build_hotel_scheduling_policy_pair,
    build_hotel_uniform_policy_pair,
    build_hotel_lounge_policy_pair,
    get_scenario_pair,
    build_scenario_reviewer_challenge,
    build_initial_proposal_payload,
    evaluate_department_applicability,
    format_demo_summary,
    recompute_investigation_after_challenge,
    run_initial_evidence_investigation,
)
from policy_proposal_contract import (
    PolicyProposalContractError,
    build_proposal_request,
    normalize_proposal_response,
)


def test_demo_scenario_initial_output() -> None:
    """Verify expected initial proposal generation and local validation."""
    pair = build_hotel_scheduling_policy_pair()
    assert isinstance(pair, PolicyPair)
    assert pair.comparison_id == COMPARISON_ID
    assert pair.older.document_id == DOC_ID
    assert pair.newer.document_id == DOC_ID

    # Verify synthetic policy texts contain the intended clauses
    assert "48 hours before the affected shift" in pair.older.original_text
    assert "24 hours before the affected shift" in pair.newer.original_text
    assert len(pair.older.passages) == 3
    assert len(pair.newer.passages) == 3

    initial = run_initial_evidence_investigation(pair)

    # Initial proposed relation is COMPATIBLE_CHANGE (not naive CONTRADICTION)
    assert initial["proposed_relation"] == "COMPATIBLE_CHANGE"
    assert initial["status"] == "PROPOSAL_ONLY"
    assert initial["semantic_support"] == "NOT_VERIFIED"
    assert initial["human_review_required"] is True
    assert initial["official_policy_mutated"] is False

    # Core engine keeps classification INCONCLUSIVE pending human review
    assert initial["core_classification"] == "INCONCLUSIVE"
    assert initial["core_proposed_classification"] == "COMPATIBLE_CHANGE"
    assert "unknown_scope" in initial["uncertainty_reasons"]
    assert "insufficient_support" in initial["uncertainty_reasons"]
    assert initial["impact_status"] == "INCONCLUSIVE"


def test_citation_provenance_derived_locally() -> None:
    """Verify exact character spans are derived locally by substring matching."""
    pair = build_hotel_scheduling_policy_pair()
    initial = run_initial_evidence_investigation(pair)

    details = initial["provenance_details"]
    assert len(details) == 2

    older_cit = next(c for c in details if c["side"] == "OLDER")
    newer_cit = next(c for c in details if c["side"] == "NEWER")

    # Local derivation matches exact text slices in source documents
    assert older_cit["passage_id"] == pair.older.passages[1].passage_id
    assert pair.older.original_text[older_cit["start_cp"]:older_cit["end_cp"]] == V1_NOTICE_QUOTE
    assert older_cit["source_sha256"] == pair.older.source_sha256

    assert newer_cit["passage_id"] == pair.newer.passages[1].passage_id
    assert pair.newer.original_text[newer_cit["start_cp"]:newer_cit["end_cp"]] == V2_NOTICE_QUOTE
    assert newer_cit["source_sha256"] == pair.newer.source_sha256

    # Provenance limitation notice is explicitly communicated
    assert "does NOT establish semantic correctness" in initial["provenance_limitation_notice"]


def test_reviewer_challenge_triggers_dependency_aware_recomputation() -> None:
    """Verify challenge to older passage triggers arity check and honest uncertainty."""
    pair = build_hotel_scheduling_policy_pair()
    initial = run_initial_evidence_investigation(pair)

    challenge = ReviewerChallenge(
        challenge_id="chal-dept-housekeeping-001",
        target_side="OLDER",
        target_passage_id=pair.older.passages[1].passage_id,
        target_quote=V1_NOTICE_QUOTE,
        target_department="HOUSEKEEPING",
        challenge_description=(
            "Reviewer questions whether the v1 48-hour general scheduling rule was ever applicable to Housekeeping. "
            "Housekeeping operated under decentralized shift guidelines and has no departmental grounding in the policy text."
        ),
    )

    recomputed = recompute_investigation_after_challenge(pair, initial, challenge)

    # 1. Contract enforcement: Attempting one-sided COMPATIBLE_CHANGE is rejected
    assert recomputed["contract_enforcement"]["one_sided_change_rejected"] is True

    # 2. Recomputed proposal falls back to honest INCONCLUSIVE abstention
    proposal = recomputed["recomputed_proposal"]
    assert proposal["proposed_relation"] == "INCONCLUSIVE"
    assert proposal["abstain"] is True
    assert proposal["citations_count"] == 0
    assert "missing_evidence" in proposal["uncertainty_reasons"]
    assert "scope_or_time_unverified" in proposal["uncertainty_reasons"]

    # 3. Core policy result is also INCONCLUSIVE with human review required
    core_res = recomputed["recomputed_core_result"]
    assert core_res["classification"] == "INCONCLUSIVE"
    assert core_res["proposed_classification"] == "INCONCLUSIVE"
    assert core_res["human_review_required"] is True
    assert core_res["official_policy_mutated"] is False
    assert "unknown_scope" in core_res["uncertainty_reasons"]


def test_unsupported_department_applicability_remains_unresolved() -> None:
    """Verify ungrounded department scope is reported as UNGROUNDED without hallucinating."""
    pair = build_hotel_scheduling_policy_pair()

    audit_hk = evaluate_department_applicability(pair, "HOUSEKEEPING")
    assert audit_hk["department_id"] == "HOUSEKEEPING"
    assert audit_hk["applicability_status"] == "UNGROUNDED"
    assert audit_hk["older_scope_state"] == "UNKNOWN"
    assert audit_hk["newer_scope_state"] == "UNKNOWN"
    assert audit_hk["older_impact_dependencies_count"] == 0

    audit_spa = evaluate_department_applicability(pair, "SPA_WELLNESS")
    assert audit_spa["applicability_status"] == "UNGROUNDED"


def test_preservation_of_proposal_only_and_human_review_invariants() -> None:
    """Verify invariants hold across both initial and recomputed states."""
    pair = build_hotel_scheduling_policy_pair()
    initial = run_initial_evidence_investigation(pair)

    challenge = ReviewerChallenge(
        challenge_id="chal-002",
        target_side="OLDER",
        target_passage_id=pair.older.passages[1].passage_id,
        target_quote=V1_NOTICE_QUOTE,
        target_department="FRONT_OFFICE",
        challenge_description="Questioning baseline applicability.",
    )
    recomputed = recompute_investigation_after_challenge(pair, initial, challenge)

    # Invariants on initial
    assert initial["status"] == "PROPOSAL_ONLY"
    assert initial["semantic_support"] == "NOT_VERIFIED"
    assert initial["human_review_required"] is True
    assert initial["official_policy_mutated"] is False

    # Invariants on recomputed
    assert recomputed["recomputed_proposal"]["status"] == "PROPOSAL_ONLY"
    assert recomputed["recomputed_proposal"]["semantic_support"] == "NOT_VERIFIED"
    assert recomputed["recomputed_proposal"]["human_review_required"] is True
    assert recomputed["recomputed_core_result"]["human_review_required"] is True
    assert recomputed["recomputed_core_result"]["official_policy_mutated"] is False


def test_malformed_inputs_and_contract_tampering_fail_closed() -> None:
    """Verify malformed quotes, invalid pairs, and arity mismatches fail closed."""
    pair = build_hotel_scheduling_policy_pair()
    req = build_proposal_request(pair)

    # 1. Fabricated quote fails closed
    fake_quote_response = {
        "schema_version": 1,
        "request_id": req["request_id"],
        "candidates": [
            {
                "proposed_relation": "COMPATIBLE_CHANGE",
                "reasoning": "Fabricated quote test.",
                "citation_hints": [
                    {
                        "side": "OLDER",
                        "passage_id": pair.older.passages[1].passage_id,
                        "quote": "This sentence was never written in the policy.",
                    },
                    {
                        "side": "NEWER",
                        "passage_id": pair.newer.passages[1].passage_id,
                        "quote": V2_NOTICE_QUOTE,
                    },
                ],
                "uncertainty_reasons": ["semantic_support_unverified"],
                "abstain": False,
            }
        ],
    }
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, req, fake_quote_response)

    # 2. Invalid inputs to demo functions fail closed
    with pytest.raises(PolicyCompareError):
        run_initial_evidence_investigation("not-a-pair")  # type: ignore[arg-type]

    with pytest.raises(PolicyCompareError):
        evaluate_department_applicability(pair, "")

    with pytest.raises(PolicyCompareError):
        recompute_investigation_after_challenge("invalid-pair", {}, "invalid-challenge")  # type: ignore[arg-type]


def test_demo_isolation_from_active_api_and_runtime_network() -> None:
    """Verify demo module does not import or connect to active API or network."""
    import ast
    import policy_evidence_demo

    demo_module_source = open(policy_evidence_demo.__file__, "r", encoding="utf-8").read()
    tree = ast.parse(demo_module_source)

    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    # Must NOT import policy_api or network libraries
    assert "policy_api" not in imported_modules
    assert "requests" not in imported_modules
    assert "httpx" not in imported_modules
    assert "urllib" not in imported_modules
    assert "urllib.request" not in imported_modules
    assert "socket" not in imported_modules

    # Verify policy_api does NOT import demo module
    import policy_api
    api_module_source = open(policy_api.__file__, "r", encoding="utf-8").read()
    api_tree = ast.parse(api_module_source)
    api_imports: set[str] = set()
    for node in ast.walk(api_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                api_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            api_imports.add(node.module)

    assert "policy_evidence_demo" not in api_imports


def test_demo_summary_formatting() -> None:
    """Verify format_demo_summary produces complete, structured output."""
    pair = build_hotel_scheduling_policy_pair()
    initial = run_initial_evidence_investigation(pair)
    challenge = ReviewerChallenge(
        challenge_id="chal-dept-housekeeping-001",
        target_side="OLDER",
        target_passage_id=pair.older.passages[1].passage_id,
        target_quote=V1_NOTICE_QUOTE,
        target_department="HOUSEKEEPING",
        challenge_description="Questioning Housekeeping applicability.",
    )
    recomputed = recompute_investigation_after_challenge(pair, initial, challenge)
    summary = format_demo_summary(initial, recomputed)

    assert "STORY CONNECT AI POLICY INVESTIGATOR -- DEMO SCENARIO" in summary
    assert "STAGE 1: INITIAL INVESTIGATION & PROVENANCE DERIVATION" in summary
    assert "STAGE 2: REVIEWER EVIDENCE CHALLENGE" in summary
    assert "STAGE 3: DEPENDENCY AUDIT & CONTRACT REJECTION" in summary
    assert "STAGE 4: RECOMPUTED HONEST UNCERTAINTY OUTCOME" in summary
    assert "COMPATIBLE_CHANGE" in summary
    assert "INCONCLUSIVE" in summary
    assert "UNGROUNDED" in summary


def test_uniform_scenario_initial_output() -> None:
    """Verify uniform scenario proposal generates CONTRADICTION with honest core INCONCLUSIVE."""
    pair = build_hotel_uniform_policy_pair()
    assert isinstance(pair, PolicyPair)
    assert pair.comparison_id == UNIFORM_COMPARISON_ID
    assert pair.older.document_id == UNIFORM_DOC_ID

    res = run_initial_evidence_investigation(pair)
    assert res["proposed_relation"] == "CONTRADICTION"
    assert res["core_proposed_classification"] == "CONTRADICTION"
    assert res["core_classification"] == "INCONCLUSIVE"
    assert res["status"] == "PROPOSAL_ONLY"
    assert res["semantic_support"] == "NOT_VERIFIED"
    assert res["human_review_required"] is True
    assert len(res["provenance_details"]) == 2
    assert res["provenance_details"][0]["quote"] == UNIFORM_V1_QUOTE
    assert res["provenance_details"][1]["quote"] == UNIFORM_V2_QUOTE
    assert all(d["verified_locally"] for d in res["provenance_details"])


def test_lounge_scenario_initial_output() -> None:
    """Verify executive lounge scenario proposal generates SCOPE_OR_TIME_DIFFERENCE with time_disjoint."""
    pair = build_hotel_lounge_policy_pair()
    assert isinstance(pair, PolicyPair)
    assert pair.comparison_id == LOUNGE_COMPARISON_ID
    assert pair.older.document_id == LOUNGE_DOC_ID

    res = run_initial_evidence_investigation(pair)
    assert res["proposed_relation"] == "SCOPE_OR_TIME_DIFFERENCE"
    assert res["core_proposed_classification"] == "SCOPE_OR_TIME_DIFFERENCE"
    assert res["core_classification"] == "INCONCLUSIVE"
    assert "time_disjoint" in res["uncertainty_reasons"]
    assert len(res["provenance_details"]) == 2
    assert res["provenance_details"][0]["quote"] == LOUNGE_V1_QUOTE
    assert res["provenance_details"][1]["quote"] == LOUNGE_V2_QUOTE


def test_get_scenario_pair_allowlist() -> None:
    """Verify get_scenario_pair correctly resolves allowlist and rejects unknown IDs."""
    p1 = get_scenario_pair(SCENARIO_SCHEDULING)
    assert p1.comparison_id == COMPARISON_ID

    p2 = get_scenario_pair(SCENARIO_UNIFORM)
    assert p2.comparison_id == UNIFORM_COMPARISON_ID

    p3 = get_scenario_pair(SCENARIO_LOUNGE)
    assert p3.comparison_id == LOUNGE_COMPARISON_ID

    with pytest.raises(PolicyCompareError):
        get_scenario_pair("unknown_scenario_id")


def test_scenario_specific_challenges() -> None:
    """Verify challenge recomputations on Uniform and Lounge scenarios."""
    # Uniform challenge
    u_pair = build_hotel_uniform_policy_pair()
    u_initial = run_initial_evidence_investigation(u_pair)
    u_chal = build_scenario_reviewer_challenge(u_pair, u_initial, "CONCIERGE", SCENARIO_UNIFORM)
    assert u_chal.target_department == "CONCIERGE"
    assert "CONCIERGE" in u_chal.challenge_description

    u_recomp = recompute_investigation_after_challenge(u_pair, u_initial, u_chal)
    assert u_recomp["applicability_audit"]["applicability_status"] == "UNGROUNDED"
    assert u_recomp["contract_enforcement"]["one_sided_change_rejected"] is True
    assert u_recomp["recomputed_proposal"]["proposed_relation"] == "INCONCLUSIVE"
    assert u_recomp["recomputed_core_result"]["classification"] == "INCONCLUSIVE"

    # Lounge challenge
    l_pair = build_hotel_lounge_policy_pair()
    l_initial = run_initial_evidence_investigation(l_pair)
    l_chal = build_scenario_reviewer_challenge(l_pair, l_initial, "VALET", SCENARIO_LOUNGE)
    assert l_chal.target_department == "VALET"

    l_recomp = recompute_investigation_after_challenge(l_pair, l_initial, l_chal)
    assert l_recomp["applicability_audit"]["applicability_status"] == "UNGROUNDED"
    assert l_recomp["contract_enforcement"]["one_sided_change_rejected"] is True
    assert l_recomp["recomputed_proposal"]["proposed_relation"] == "INCONCLUSIVE"

