"""Deterministic offline tests for synthetic policy orchestration."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

import policy_orchestration
from policy_candidate_adapter import (
    FakePolicyCandidateAdapter,
    PolicyCandidateAdapterError,
)
from policy_orchestration import (
    PolicyOrchestrationError,
    orchestrate_policy_comparison,
)


def _version(version_id: str, text: str) -> dict:
    first = text.split("\n\n")[0]
    passage_id = f"p000001-{sha256(first.encode('utf-8')).hexdigest()[:16]}"
    return {
        "document_id": "syn-policy-handover",
        "version_id": version_id,
        "original_text": text,
        "effective_from": "2026-01-01",
        "effective_to_exclusive": "2027-01-01",
        "scope": {
            "departments": {"state": "KNOWN", "ids": ["FRONT_OFFICE"]},
            "procedures": {"state": "UNKNOWN", "ids": []},
            "property_id": None,
            "evidence_passage_ids": [passage_id],
        },
        "text_coverage": "EXCERPT",
        "impact_dependencies": [],
    }


def _pair_input() -> dict:
    return {
        "schema_version": 1,
        "comparison_id": "cmp-syn-orchestration-001",
        "older": _version("v1", "Record requests before shift end.\n\nKeep the log complete."),
        "newer": _version("v2", "Record requests at shift start.\n\nKeep the log complete."),
    }


def _citation(version: dict, side: str, phrase: str | None = None) -> dict:
    text = version["original_text"]
    quote = text.split("\n\n")[0] if phrase is None else phrase
    start = text.index(quote)
    passage_text = text.split("\n\n")[0]
    passage_id = f"p000001-{sha256(passage_text.encode('utf-8')).hexdigest()[:16]}"
    return {
        "side": side,
        "document_id": version["document_id"],
        "version_id": version["version_id"],
        "source_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "passage_id": passage_id,
        "start_cp": start,
        "end_cp": start + len(quote),
        "quote": quote,
    }


def _response(pair_input: dict | None = None) -> dict:
    raw_pair = _pair_input() if pair_input is None else pair_input
    return {
        "schema_version": 1,
        "candidates": [{
            "candidate_id": "cand-syn-orchestration-001",
            "proposed_relation": "CONTRADICTION",
            "reasoning": "The excerpts propose different recording times.",
            "citations": [
                _citation(raw_pair["older"], "OLDER"),
                _citation(raw_pair["newer"], "NEWER"),
            ],
            "uncertainty_reasons": ["semantic_support_unverified"],
            "abstain": False,
        }],
    }


def _run(pair_input: dict | None = None, response: dict | str | None = None) -> dict:
    raw_pair = _pair_input() if pair_input is None else pair_input
    raw_response = _response(raw_pair) if response is None else response
    serialized = raw_response if type(raw_response) is str else json.dumps(raw_response)
    return orchestrate_policy_comparison(raw_pair, FakePolicyCandidateAdapter(serialized))


def test_valid_pair_and_fixture_proposal_are_normalized_inconclusive(monkeypatch):
    raw_pair = _pair_input()
    before = deepcopy(raw_pair)
    response = _response(raw_pair)
    calls = []
    original = policy_orchestration.generate_from_fake

    def observe_fixture_path(adapter, pair):
        calls.append((type(adapter), pair.comparison_id))
        return original(adapter, pair)

    monkeypatch.setattr(policy_orchestration, "generate_from_fake", observe_fixture_path)
    result = orchestrate_policy_comparison(
        raw_pair, FakePolicyCandidateAdapter(json.dumps(response))
    )

    assert calls == [(FakePolicyCandidateAdapter, "cmp-syn-orchestration-001")]
    assert raw_pair == before
    assert result["schema_version"] == 1
    assert len(result["results"]) == 1
    normalized = result["results"][0]
    assert normalized["classification"] == "INCONCLUSIVE"
    assert normalized["proposed_classification"] == "CONTRADICTION"
    assert normalized["assessment_status"] == "INCONCLUSIVE"
    assert normalized["human_review_required"] is True
    assert normalized["official_policy_mutated"] is False
    assert normalized["proposal_status"] == "PROPOSAL_ONLY"
    assert normalized["proposal_semantic_support"] == "NOT_VERIFIED"
    assert normalized["evidence_checks"]["semantic_assessment_origin"] == "UNTRUSTED_CALLER_ASSERTION"
    assert normalized["impact"]["status"] == "INCONCLUSIVE"
    assert normalized["impact"]["departments"] == []
    assert normalized["impact"]["proposed_targets"] == []
    assert normalized["scope_time"]["precedence_assertion"] == "UNRESOLVED"


def test_invalid_policy_pair_is_rejected_before_fake_dispatch():
    calls = []

    class _MustNotRun(FakePolicyCandidateAdapter):
        def generate(self, pair):
            calls.append(pair)
            return '{"schema_version":1,"candidates":[]}'

    bad_pair = _pair_input()
    bad_pair["schema_version"] = True
    with pytest.raises(PolicyOrchestrationError) as error:
        orchestrate_policy_comparison(bad_pair, _MustNotRun("{}"))
    assert error.value.code == "invalid_policy_pair"
    assert str(error.value) == "Policy comparison input is invalid."
    assert calls == []


@pytest.mark.parametrize("bad_response", [
    "not-json",
    '{"schema_version":1,"candidates":[{"classification":"CONTRADICTION"}]}',
])
def test_malformed_or_unsupported_adapter_output_is_sanitized(bad_response):
    with pytest.raises(PolicyOrchestrationError) as error:
        _run(response=bad_response)
    assert error.value.code == "invalid_proposal"
    assert str(error.value) == "Policy comparison proposal is invalid."
    assert bad_response not in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("document_id", "syn-policy-other"),
    ("version_id", "v9"),
    ("source_sha256", "0" * 64),
    ("passage_id", "p000999-0000000000000000"),
    ("start_cp", True),
    ("end_cp", 10000),
    ("quote", "fabricated text"),
])
def test_adapter_citation_provenance_mismatches_are_rejected(field, value):
    pair_input = _pair_input()
    response = _response(pair_input)
    response["candidates"][0]["citations"][0][field] = value
    with pytest.raises(PolicyOrchestrationError) as error:
        _run(pair_input, response)
    assert error.value.code == "invalid_proposal"


def test_new_rule_with_old_side_evidence_is_a_mapping_mismatch():
    pair_input = _pair_input()
    response = _response(pair_input)
    candidate = response["candidates"][0]
    candidate["proposed_relation"] = "NEW_RULE"
    candidate["citations"] = [_citation(pair_input["older"], "OLDER")]
    with pytest.raises(PolicyOrchestrationError) as error:
        _run(pair_input, response)
    assert error.value.code == "contract_mismatch"


@pytest.mark.parametrize(("field", "value"), [
    ("classification", "VERIFIED_CONTRADICTION"),
    ("semantic_support", "VERIFIED"),
    ("precedence", "DEFINED"),
    ("comparison_coverage", "COMPLETE"),
    ("impact", {"status": "CONFIRMED"}),
    ("approved", True),
])
def test_unsupported_verification_and_approval_claims_are_rejected(field, value):
    pair_input = _pair_input()
    response = _response(pair_input)
    response["candidates"][0][field] = value
    with pytest.raises(PolicyOrchestrationError) as error:
        _run(pair_input, response)
    assert error.value.code == "invalid_proposal"


def test_adapter_exceptions_do_not_expose_arbitrary_error_text(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-private-detail")

    monkeypatch.setattr(policy_orchestration, "generate_from_fake", fail)
    with pytest.raises(PolicyOrchestrationError) as error:
        orchestrate_policy_comparison(
            _pair_input(), FakePolicyCandidateAdapter("{}")
        )
    assert error.value.code == "invalid_proposal"
    assert str(error.value) == "Policy comparison proposal is invalid."
    assert "synthetic-private-detail" not in str(error.value)


def test_custom_adapter_is_rejected_without_invoking_its_method():
    calls = []

    class CustomAdapter:
        def generate(self, pair):
            calls.append(pair)
            return '{"schema_version":1,"candidates":[]}'

    with pytest.raises(PolicyOrchestrationError) as error:
        orchestrate_policy_comparison(_pair_input(), CustomAdapter())
    assert error.value.code == "invalid_proposal"
    assert calls == []


def test_core_result_stays_proposal_only_and_repeated_runs_are_deterministic():
    pair_input = _pair_input()
    first = _run(pair_input)
    second = _run(pair_input)
    assert first == second
    result = first["results"][0]
    assert result["classification"] == "INCONCLUSIVE"
    assert result["proposed_classification"] == "CONTRADICTION"
    assert result["human_review_required"] is True
    assert result["official_policy_mutated"] is False


def test_new_rule_with_newer_citation_reaches_core_as_inconclusive_proposal():
    pair_input = _pair_input()
    response = _response(pair_input)
    candidate = response["candidates"][0]
    candidate["proposed_relation"] = "NEW_RULE"
    candidate["citations"] = [_citation(pair_input["newer"], "NEWER")]
    result = _run(pair_input, response)["results"][0]
    assert result["proposed_classification"] == "NEW_RULE"
    assert result["classification"] == "INCONCLUSIVE"
    assert result["uncertainty_reasons"]


