"""Offline regression tests for the isolated mock-only provider boundary prototype."""
from __future__ import annotations

import json
from typing import Any

import pytest

from policy_mock_provider_runner import (
    DeterministicMockProposalAdapter,
    PolicyMockRunnerError,
    make_synthetic_policy_pair,
    run_mock_policy_proposal_pipeline,
)
from policy_proposal_contract import build_proposal_request


def _candidate(
    proposed_relation: str = "CONTRADICTION",
    *,
    reasoning: str = "Candidate diff identified for human review.",
    older_quote: str = "before shift end.",
    newer_quote: str = "at shift start.",
    older_passage_id: str | None = None,
    newer_passage_id: str | None = None,
    uncertainty_reasons: list[str] | None = None,
    abstain: bool = False,
    hints: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Helper to construct a valid untrusted candidate proposal."""
    if hints is not None:
        citation_hints = hints
    elif abstain:
        citation_hints = []
    elif proposed_relation == "NEW_RULE":
        citation_hints = [{
            "side": "NEWER",
            "passage_id": newer_passage_id or "p000001",
            "quote": newer_quote,
        }]
    else:
        citation_hints = [
            {
                "side": "OLDER",
                "passage_id": older_passage_id or "p000001",
                "quote": older_quote,
            },
            {
                "side": "NEWER",
                "passage_id": newer_passage_id or "p000001",
                "quote": newer_quote,
            },
        ]

    reasons = uncertainty_reasons or ["semantic_support_unverified"]
    if proposed_relation == "INCONCLUSIVE" and not reasons:
        reasons = ["missing_evidence"]

    return {
        "proposed_relation": proposed_relation,
        "reasoning": reasoning,
        "citation_hints": citation_hints,
        "uncertainty_reasons": reasons,
        "abstain": abstain,
    }


def _response(request_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": request_id,
        "candidates": candidates,
    }


def test_valid_mock_response_contradiction() -> None:
    """Exercise a valid deterministic mock proposal through the end-to-end seam."""
    pair = make_synthetic_policy_pair()
    req = build_proposal_request(pair)
    old_p = pair.older.passages[0].passage_id
    new_p = pair.newer.passages[0].passage_id

    cand = _candidate(
        "CONTRADICTION",
        older_quote="before shift end.",
        newer_quote="at shift start.",
        older_passage_id=old_p,
        newer_passage_id=new_p,
    )
    payload = _response(req["request_id"], [cand])
    adapter = DeterministicMockProposalAdapter(response_payload=payload)

    output = run_mock_policy_proposal_pipeline(pair, adapter)

    assert output["schema_version"] == 1
    assert output["comparison_id"] == pair.comparison_id
    assert len(output["results"]) == 1

    res = output["results"][0]
    # Mandatory invariant checks
    assert res["proposed_classification"] == "CONTRADICTION"
    assert res["classification"] == "INCONCLUSIVE"
    assert res["assessment_status"] == "INCONCLUSIVE"
    assert res["proposal_status"] == "PROPOSAL_ONLY"
    assert res["proposal_semantic_support"] == "NOT_VERIFIED"
    assert res["human_review_required"] is True
    assert res["official_policy_mutated"] is False
    assert res["impact"]["status"] == "INCONCLUSIVE"
    assert res["impact"]["coverage_assertion"] == "INCOMPLETE"
    assert res["impact"]["proposed_targets"] == []


def test_valid_mock_response_all_five_relations() -> None:
    """Verify that all five canonical relation labels are supported."""
    pair = make_synthetic_policy_pair()
    req = build_proposal_request(pair)
    old_p = pair.older.passages[0].passage_id
    new_p = pair.newer.passages[0].passage_id

    # 1. CONTRADICTION (two-sided)
    c1 = _candidate("CONTRADICTION", older_passage_id=old_p, newer_passage_id=new_p)
    out1 = run_mock_policy_proposal_pipeline(
        pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c1]))
    )
    assert out1["results"][0]["proposed_classification"] == "CONTRADICTION"

    # 2. COMPATIBLE_CHANGE (two-sided)
    c2 = _candidate("COMPATIBLE_CHANGE", older_passage_id=old_p, newer_passage_id=new_p)
    out2 = run_mock_policy_proposal_pipeline(
        pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c2]))
    )
    assert out2["results"][0]["proposed_classification"] == "COMPATIBLE_CHANGE"

    # 3. NEW_RULE (newer-side only)
    c3 = _candidate("NEW_RULE", newer_passage_id=new_p)
    out3 = run_mock_policy_proposal_pipeline(
        pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c3]))
    )
    assert out3["results"][0]["proposed_classification"] == "NEW_RULE"

    # 4. SCOPE_OR_TIME_DIFFERENCE (two-sided)
    c4 = _candidate("SCOPE_OR_TIME_DIFFERENCE", older_passage_id=old_p, newer_passage_id=new_p)
    out4 = run_mock_policy_proposal_pipeline(
        pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c4]))
    )
    assert out4["results"][0]["proposed_classification"] == "SCOPE_OR_TIME_DIFFERENCE"

    # 5. INCONCLUSIVE (abstention: abstain=True, empty hints)
    c5 = _candidate(
        "INCONCLUSIVE",
        abstain=True,
        uncertainty_reasons=["missing_evidence"],
    )
    out5 = run_mock_policy_proposal_pipeline(
        pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c5]))
    )
    assert out5["results"][0]["proposed_classification"] == "INCONCLUSIVE"


def test_wrong_or_missing_request_id() -> None:
    """Response with mismatched or absent request_id fails closed."""
    pair = make_synthetic_policy_pair()
    old_p = pair.older.passages[0].passage_id
    new_p = pair.newer.passages[0].passage_id
    cand = _candidate(older_passage_id=old_p, newer_passage_id=new_p)

    # Wrong request ID
    bad_payload = _response("req-syn-wrong-id-000000000000", [cand])
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(pair, DeterministicMockProposalAdapter(bad_payload))
    assert exc_info.value.code == "invalid_proposal"

    # Missing request ID key entirely
    missing_id_payload = {"schema_version": 1, "candidates": [cand]}
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(pair, DeterministicMockProposalAdapter(missing_id_payload))
    assert exc_info.value.code == "invalid_proposal"


def test_malformed_json_or_unsupported_shape() -> None:
    """Malformed syntax or root schema mismatch fails closed."""
    pair = make_synthetic_policy_pair()
    req = build_proposal_request(pair)

    # Broken JSON string
    broken_str_adapter = DeterministicMockProposalAdapter("{not valid json syntax")
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(pair, broken_str_adapter)
    assert exc_info.value.code == "invalid_proposal"

    # Non-dictionary / non-string type
    int_adapter = DeterministicMockProposalAdapter(12345)
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(pair, int_adapter)
    assert exc_info.value.code == "invalid_proposal"

    # Smuggled root key
    smuggled = {
        "schema_version": 1,
        "request_id": req["request_id"],
        "candidates": [],
        "extra_key": "smuggled_data",
    }
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(pair, DeterministicMockProposalAdapter(smuggled))
    assert exc_info.value.code == "invalid_proposal"


def test_fabricated_or_mismatched_citation_hints() -> None:
    """Citation hints that do not exist or mismatch source fail closed."""
    pair = make_synthetic_policy_pair()
    req = build_proposal_request(pair)
    old_p = pair.older.passages[0].passage_id
    new_p = pair.newer.passages[0].passage_id

    # Non-existent passage ID
    c_bad_pid = _candidate(older_passage_id="p999999-does-not-exist", newer_passage_id=new_p)
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_bad_pid]))
        )
    assert exc_info.value.code == "invalid_proposal"

    # Fabricated quote not in passage text
    c_bad_quote = _candidate(
        older_quote="This quote never appeared in any policy passage.",
        older_passage_id=old_p,
        newer_passage_id=new_p,
    )
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_bad_quote]))
        )
    assert exc_info.value.code == "invalid_proposal"

    # Swapped quote (quote from newer claimed under OLDER side)
    c_swapped = _candidate(
        older_quote="at shift start.",  # only exists in newer passage!
        newer_quote="at shift start.",
        older_passage_id=old_p,
        newer_passage_id=new_p,
    )
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_swapped]))
        )
    assert exc_info.value.code == "invalid_proposal"


def test_duplicate_or_ambiguous_quote_matching() -> None:
    """Quotes that occur multiple times or duplicate proposals fail closed."""
    # Create text where 'Front Office' occurs twice in the same passage
    ambiguous_text = "Front Office confirms with Front Office records.\n\nKeep the log complete."
    pair = make_synthetic_policy_pair(older_text=ambiguous_text)
    req = build_proposal_request(pair)
    old_p = pair.older.passages[0].passage_id
    new_p = pair.newer.passages[0].passage_id

    # Multi-occurrence substring quote (must count == 1)
    c_ambig = _candidate(
        older_quote="Front Office",
        older_passage_id=old_p,
        newer_passage_id=new_p,
    )
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_ambig]))
        )
    assert exc_info.value.code == "invalid_proposal"

    # Duplicate proposal candidates in the same response
    clean_pair = make_synthetic_policy_pair()
    clean_req = build_proposal_request(clean_pair)
    c_dup = _candidate(
        older_passage_id=clean_pair.older.passages[0].passage_id,
        newer_passage_id=clean_pair.newer.passages[0].passage_id,
    )
    dup_payload = _response(clean_req["request_id"], [c_dup, c_dup])
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            clean_pair, DeterministicMockProposalAdapter(dup_payload)
        )
    assert exc_info.value.code == "invalid_proposal"


def test_unsupported_relation_labels() -> None:
    """Unknown relations or relation arity violations fail closed."""
    pair = make_synthetic_policy_pair()
    req = build_proposal_request(pair)
    old_p = pair.older.passages[0].passage_id
    new_p = pair.newer.passages[0].passage_id

    # Non-canonical relation label
    c_bad_label = _candidate(
        "DIRECT_CONFLICT", older_passage_id=old_p, newer_passage_id=new_p
    )
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_bad_label]))
        )
    assert exc_info.value.code == "invalid_proposal"

    # Arity violation: CONTRADICTION with only newer-side citation
    c_one_sided = _candidate("CONTRADICTION", hints=[{
        "side": "NEWER",
        "passage_id": new_p,
        "quote": "at shift start.",
    }])
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_one_sided]))
        )
    assert exc_info.value.code == "invalid_proposal"

    # Arity violation: NEW_RULE citing older passage
    c_bad_new_rule = _candidate(
        "NEW_RULE",
        hints=[
            {"side": "OLDER", "passage_id": old_p, "quote": "before shift end."},
            {"side": "NEWER", "passage_id": new_p, "quote": "at shift start."},
        ],
    )
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_bad_new_rule]))
        )
    assert exc_info.value.code == "invalid_proposal"


def test_excessive_response_size_and_structural_limits() -> None:
    """Payloads violating byte size or count bounds fail closed."""
    pair = make_synthetic_policy_pair()
    req = build_proposal_request(pair)
    old_p = pair.older.passages[0].passage_id
    new_p = pair.newer.passages[0].passage_id

    # More than 20 candidates (limit is 20)
    too_many = [
        _candidate(
            older_quote="before shift end.",
            newer_quote="at shift start.",
            older_passage_id=old_p,
            newer_passage_id=new_p,
            reasoning=f"Candidate variation {i}",
        )
        for i in range(21)
    ]
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], too_many))
        )
    assert exc_info.value.code == "invalid_proposal"

    # Oversized raw JSON string exceeding 64,000 bytes
    huge_str = json.dumps(_response(req["request_id"], [])) + (" " * 65_000)
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(huge_str)
        )
    assert exc_info.value.code == "invalid_proposal"

    # Reasoning code point length > 500
    long_reasoning = "A" * 501
    c_long = _candidate(
        older_passage_id=old_p,
        newer_passage_id=new_p,
        reasoning=long_reasoning,
    )
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_long]))
        )
    assert exc_info.value.code == "invalid_proposal"


def test_rejected_response_never_produces_accepted_result() -> None:
    """Ensure invalid responses always fail closed and produce zero results."""
    pair = make_synthetic_policy_pair()
    req = build_proposal_request(pair)

    # Missing mandatory uncertainty reason 'semantic_support_unverified'
    c_unverified = _candidate(
        "CONTRADICTION",
        older_passage_id=pair.older.passages[0].passage_id,
        newer_passage_id=pair.newer.passages[0].passage_id,
        uncertainty_reasons=["missing_evidence"],  # missing semantic_support_unverified!
    )
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            pair, DeterministicMockProposalAdapter(_response(req["request_id"], [c_unverified]))
        )
    assert exc_info.value.code == "invalid_proposal"


def test_invalid_input_and_adapter_safety() -> None:
    """Verify input validation and strict adapter type checking."""
    pair = make_synthetic_policy_pair()

    # Invalid pair input
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(
            "not-a-valid-pair",
            DeterministicMockProposalAdapter({}),
        )
    assert exc_info.value.code == "invalid_policy_pair"

    # Invalid adapter instance (not DeterministicMockProposalAdapter)
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(pair, "invalid-adapter-object")  # type: ignore[arg-type]
    assert exc_info.value.code == "invalid_adapter"


def test_adapter_invocation_failure_sanitizes_canary_and_returns_no_result() -> None:
    """Ensure adapter execution exceptions fail closed without leaking canary details."""
    pair = make_synthetic_policy_pair()
    canary = "CANARY_SECRET_TOKEN_XYZ_987654"

    def _failing_generator(request_envelope: dict[str, Any]) -> Any:
        del request_envelope
        raise RuntimeError(f"Simulated adapter transport failure with secret: {canary}")

    # Use the existing constructor and exact type
    adapter = DeterministicMockProposalAdapter(response_payload=_failing_generator)

    # 1. Assert run_mock_policy_proposal_pipeline raises PolicyMockRunnerError
    with pytest.raises(PolicyMockRunnerError) as exc_info:
        run_mock_policy_proposal_pipeline(pair, adapter)

    # 2. Assert error code matches the existing sanitized contract for adapter invocation failures
    assert exc_info.value.code == "invalid_proposal"

    # 3. Assert exception message does not contain the canary
    error_message = str(exc_info.value)
    assert canary not in error_message
    assert exc_info.value.__cause__ is None

    # 4. Assert no result dictionary is returned
    result = None
    try:
        result = run_mock_policy_proposal_pipeline(pair, adapter)
    except PolicyMockRunnerError:
        pass
    assert result is None

    # 5. Assert the existing adapter type restriction remains unchanged
    assert type(adapter) is DeterministicMockProposalAdapter

