"""Offline synthetic tests for the policy candidate adapter contract."""
from copy import deepcopy
import json
from hashlib import sha256

import pytest

from policy_candidate_adapter import (
    FakePolicyCandidateAdapter,
    PolicyCandidateAdapterError,
    generate_from_fake,
    validate_candidate_response,
)
from policy_compare import validate_policy_pair


def _pair():
    text_old = "Front Office records requests before shift end.\n\nKeep the log complete."
    text_new = "Front Office records requests at shift start.\n\nKeep the log complete."

    def version(version_id, text):
        first = text.split("\n\n")[0]
        passage_id = f"p000001-{sha256(first.encode()).hexdigest()[:16]}"
        return {
            "document_id": "syn-policy-handover", "version_id": version_id,
            "original_text": text, "effective_from": "2026-01-01",
            "effective_to_exclusive": "2027-01-01",
            "scope": {"departments": {"state": "KNOWN", "ids": ["FRONT_OFFICE"]},
                      "procedures": {"state": "UNKNOWN", "ids": []},
                      "property_id": None, "evidence_passage_ids": [passage_id]},
            "text_coverage": "EXCERPT", "impact_dependencies": [],
        }

    return validate_policy_pair({
        "schema_version": 1, "comparison_id": "cmp-syn-muse-001",
        "older": version("v1", text_old), "newer": version("v2", text_new),
    })


def _citation(version, side):
    passage = version.passages[0]
    return {"side": side, "document_id": version.document_id,
            "version_id": version.version_id, "source_sha256": version.source_sha256,
            "passage_id": passage.passage_id, "start_cp": passage.start_cp,
            "end_cp": passage.end_cp, "quote": passage.text}


def _response(pair):
    return {"schema_version": 1, "candidates": [{
        "candidate_id": "cand-syn-001", "proposed_relation": "CONTRADICTION",
        "reasoning": "The excerpts appear to specify different recording times.",
        "citations": [_citation(pair.older, "OLDER"), _citation(pair.newer, "NEWER")],
        "uncertainty_reasons": ["semantic_support_unverified"], "abstain": False,
    }]}


def _via_fake(response):
    return generate_from_fake(FakePolicyCandidateAdapter(json.dumps(response)), _pair())


def test_valid_candidate_is_proposal_only_with_verified_source_provenance():
    pair = _pair()
    result = generate_from_fake(FakePolicyCandidateAdapter(json.dumps(_response(pair))), pair)
    candidate = result["candidates"][0]
    assert candidate["proposed_relation"] == "CONTRADICTION"
    assert candidate["status"] == "PROPOSAL_ONLY"
    assert candidate["semantic_support"] == "NOT_VERIFIED"
    assert candidate["human_review_required"] is True
    assert [item["side"] for item in candidate["citations"]] == ["OLDER", "NEWER"]
    assert "classification" not in candidate


@pytest.mark.parametrize("value", [
    {"schema_version": 1, "candidates": []},
    {"schema_version": 1, "candidates": [{
        "candidate_id": "cand-syn-abstain", "proposed_relation": "INCONCLUSIVE",
        "reasoning": "Insufficient source evidence.", "citations": [],
        "uncertainty_reasons": ["missing_evidence"], "abstain": True,
    }]},
])
def test_empty_list_and_explicit_abstention_are_valid(value):
    result = _via_fake(value)
    assert result["candidates"] == [] or result["candidates"][0]["abstain"] is True


@pytest.mark.parametrize("raw", ["not-json", "{\"schema_version\":", "null"])
def test_malformed_json_and_root_shapes_have_fixed_sanitized_error(raw):
    with pytest.raises(PolicyCandidateAdapterError) as error:
        generate_from_fake(FakePolicyCandidateAdapter(raw), _pair())
    assert error.value.code == "invalid_response"
    assert str(error.value) == "Policy candidate response is invalid."
    assert raw not in str(error.value)


def test_unknown_fields_invalid_enums_and_duplicate_ids_reject():
    pair = _pair()
    base = _response(pair)
    unknown = deepcopy(base)
    unknown["candidates"][0]["coverage"] = "FULL_DOCUMENT"
    bad_enum = deepcopy(base)
    bad_enum["candidates"][0]["proposed_relation"] = "VERIFIED_CONTRADICTION"
    duplicate = deepcopy(base)
    duplicate["candidates"].append(deepcopy(duplicate["candidates"][0]))
    for bad in (unknown, bad_enum, duplicate):
        with pytest.raises(PolicyCandidateAdapterError):
            validate_candidate_response(pair, bad)


def test_parsed_oversized_dictionary_and_candidate_count_reject_before_serializing(monkeypatch):
    pair = _pair()
    oversized = _response(pair)
    oversized["candidates"][0]["reasoning"] = "x" * 100_000
    excessive = {"schema_version": 1, "candidates": [
        {"candidate_id": f"cand-syn-{i}", "proposed_relation": "INCONCLUSIVE",
         "reasoning": "No evidence.", "citations": [],
         "uncertainty_reasons": ["missing_evidence"], "abstain": True}
        for i in range(21)]}

    def forbidden_serialize(*args, **kwargs):
        raise AssertionError("oversized structure reached serialization")

    monkeypatch.setattr("policy_candidate_adapter.json.dumps", forbidden_serialize)
    for bad in (oversized, excessive):
        with pytest.raises(PolicyCandidateAdapterError):
            validate_candidate_response(pair, bad)


@pytest.mark.parametrize("field,value", [
    ("document_id", "syn-policy-other"),
    ("version_id", "v9"),
    ("source_sha256", "0" * 64),
    ("passage_id", "p000999-0000000000000000"),
    ("start_cp", True),
    ("start_cp", -1),
    ("end_cp", 10000),
    ("quote", "fabricated quotation"),
])
def test_wrong_provenance_and_invalid_citation_boundaries_reject(field, value):
    pair = _pair()
    bad = _response(pair)
    bad["candidates"][0]["citations"][0][field] = value
    with pytest.raises(PolicyCandidateAdapterError) as error:
        validate_candidate_response(pair, bad)
    assert error.value.code == "invalid_response"


def test_cross_passage_citation_rejects():
    pair = _pair()
    bad = _response(pair)
    passage = pair.older.passages[0]
    end = pair.older.passages[1].end_cp
    bad["candidates"][0]["citations"][0].update(
        end_cp=end, quote=pair.older.original_text[passage.start_cp:end])
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, bad)


def test_candidate_count_and_string_limits_reject():
    pair = _pair()
    too_many = {"schema_version": 1, "candidates": [
        {"candidate_id": f"cand-syn-{i}", "proposed_relation": "INCONCLUSIVE",
         "reasoning": "No evidence.", "citations": [],
         "uncertainty_reasons": ["missing_evidence"], "abstain": True}
        for i in range(21)]}
    long_reason = _response(pair)
    long_reason["candidates"][0]["reasoning"] = "x" * 501
    huge = " " * 64_001
    for bad in (too_many, long_reason):
        with pytest.raises(PolicyCandidateAdapterError):
            validate_candidate_response(pair, bad)
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, huge)


@pytest.mark.parametrize("attempted", [True, False])
def test_human_review_is_trusted_normalized_metadata(attempted):
    pair = _pair()
    response = _response(pair)
    response["candidates"][0]["human_review_required"] = attempted
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, response)

    valid = validate_candidate_response(pair, _response(pair))
    assert valid["candidates"][0]["human_review_required"] is True


def test_affirmative_relation_requires_semantic_uncertainty_and_both_sides():
    pair = _pair()
    missing_uncertainty = _response(pair)
    missing_uncertainty["candidates"][0]["uncertainty_reasons"] = []
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, missing_uncertainty)

    one_side = _response(pair)
    one_side["candidates"][0]["citations"] = one_side["candidates"][0]["citations"][:1]
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, one_side)


def test_citation_cannot_substitute_other_valid_version_or_quote_elsewhere():
    pair = _pair()
    wrong_side = _response(pair)
    older_citation = wrong_side["candidates"][0]["citations"][0]
    newer_citation = _citation(pair.newer, "NEWER")
    for field in ("document_id", "version_id", "source_sha256", "passage_id",
                  "start_cp", "end_cp", "quote"):
        older_citation[field] = newer_citation[field]
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, wrong_side)

    misplaced_quote = _response(pair)
    citation = misplaced_quote["candidates"][0]["citations"][0]
    quote = "Keep the log complete."
    citation["start_cp"] = pair.older.original_text.index("Front Office")
    citation["end_cp"] = citation["start_cp"] + len(quote)
    citation["quote"] = quote
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, misplaced_quote)


def test_false_coverage_and_impact_claims_are_unknown_fields():
    pair = _pair()
    for key, value in (("coverage", "FULL_DOCUMENT"), ("comparison_coverage", "COMPLETE"),
                       ("impact", {"status": "CONFIRMED"}), ("impact_targets", ["FRONT_OFFICE"])):
        bad = _response(pair)
        bad["candidates"][0][key] = value
        with pytest.raises(PolicyCandidateAdapterError):
            validate_candidate_response(pair, bad)


def test_proposed_classification_cannot_be_promoted_and_fake_errors_are_sanitized():
    pair = _pair()
    forged = _response(pair)
    forged["candidates"][0]["classification"] = "CONTRADICTION"
    with pytest.raises(PolicyCandidateAdapterError):
        validate_candidate_response(pair, forged)

    # Raw provider-style error text remains data and is never reflected.
    raw = '{"error":"secret-like-token-do-not-leak"}'
    with pytest.raises(PolicyCandidateAdapterError) as error:
        generate_from_fake(FakePolicyCandidateAdapter(raw), pair)
    assert "secret-like-token-do-not-leak" not in str(error.value)


def test_fake_dispatch_rejects_custom_adapter_objects():
    calls = {"count": 0}

    class NetworkLookingObject:
        def generate(self, pair):
            calls["count"] += 1
            return '{"schema_version":1,"candidates":[]}'

    with pytest.raises(PolicyCandidateAdapterError):
        generate_from_fake(NetworkLookingObject(), _pair())
    assert calls["count"] == 0


def test_fake_adapter_exception_details_are_sanitized(monkeypatch):
    pair = _pair()
    adapter = FakePolicyCandidateAdapter('{"schema_version":1,"candidates":[]}')

    def fail_with_private_detail(self, pair):
        raise RuntimeError("synthetic-private-error-detail")

    monkeypatch.setattr(FakePolicyCandidateAdapter, "generate", fail_with_private_detail)
    with pytest.raises(PolicyCandidateAdapterError) as error:
        generate_from_fake(adapter, pair)
    assert error.value.code == "invalid_response"
    assert str(error.value) == "Policy candidate response is invalid."
    assert "synthetic-private-error-detail" not in str(error.value)
