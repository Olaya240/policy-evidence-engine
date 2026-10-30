"""Synthetic offline tests for the provider-independent proposal contract."""
from copy import deepcopy
import json

import pytest

from policy_compare import PolicyCompareError, PolicyPair, validate_policy_pair
from policy_proposal_contract import (
    MAX_REQUEST_BYTES,
    MAX_REQUEST_NODES,
    MAX_RESPONSE_BYTES,
    _MAX_DEPTH,
    _MAX_NODES,
    _MAX_OBJECT,
    _MAX_STRING,
    _decode,
    _bound,
    _proposal_request_envelope,
    PolicyProposalContractError,
    build_proposal_request,
    normalize_proposal_response,
)


def _version(version_id: str, text: str) -> dict:
    return {
        "document_id": "syn-policy-proposal-demo",
        "version_id": version_id,
        "original_text": text,
        "effective_from": "2026-01-01",
        "effective_to_exclusive": "2027-01-01",
        "scope": {
            "departments": {"state": "UNKNOWN", "ids": []},
            "procedures": {"state": "UNKNOWN", "ids": []},
            "property_id": None,
            "evidence_passage_ids": [],
        },
        "text_coverage": "EXCERPT",
        "impact_dependencies": [],
    }


def _pair():
    return validate_policy_pair({
        "schema_version": 1,
        "comparison_id": "cmp-syn-proposal-contract-01",
        "older": _version("v1", "Record requests before shift end.\n\nKeep the log complete."),
        "newer": _version("v2", "Record requests at shift start.\n\nKeep the log complete."),
    })


def _candidate(relation="CONTRADICTION", *, sides=("OLDER", "NEWER"),
               quote=None, reasons=None, abstain=False):
    pair = _pair()
    hints = []
    for side in sides:
        version = pair.older if side == "OLDER" else pair.newer
        selected_quote = quote or version.passages[0].text
        passage = next(p for p in version.passages if selected_quote in p.text)
        hints.append({"side": side, "passage_id": passage.passage_id, "quote": selected_quote})
    return {
        "proposed_relation": relation,
        "reasoning": "The candidate rules may differ; a reviewer must assess them.",
        "citation_hints": hints,
        "uncertainty_reasons": reasons or ["semantic_support_unverified", "precedence_unverified"],
        "abstain": abstain,
    }


def _normalize(candidates=None, *, response=None):
    pair = _pair()
    request = build_proposal_request(pair)
    raw = response if response is not None else {
        "schema_version": 1, "request_id": request["request_id"],
        "candidates": [_candidate()] if candidates is None else candidates,
    }
    return normalize_proposal_response(pair, request, raw)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _padded_response(target_bytes, character="A"):
    value = {
        "schema_version": 1,
        "request_id": "req-syn-" + "0" * 24,
        "candidates": [],
        "padding": [""] * 20,
    }
    unit = len(json.dumps(character, ensure_ascii=False).encode("utf-8")) - 2
    missing = target_bytes - len(_canonical(value))
    first_slot = 0
    if unit > 1 and missing % unit:
        value["padding"][0] = "x"
        missing -= 1
        first_slot = 1
    assert missing >= 0 and missing % unit == 0
    count = missing // unit
    for index in range(first_slot, len(value["padding"])):
        take = min(_MAX_STRING, count)
        value["padding"][index] = character * take
        count -= take
    assert count == 0
    assert len(_canonical(value)) == target_bytes
    return value


def _pair_with_request_bytes(target_bytes):
    def raw_pair(older_text, newer_text):
        return validate_policy_pair({
            "schema_version": 1,
            "comparison_id": "cmp-syn-request-boundary",
            "older": _version("v1", older_text),
            "newer": _version("v2", newer_text),
        })

    older, newer = "a" * 100_000, "b" * 100_000
    base = raw_pair(older, newer)
    delta = target_bytes - len(_canonical(build_proposal_request(base)))
    assert delta >= 0
    two_byte = delta % 3
    four_byte = (delta - two_byte) // 3
    chars = list(older + newer)
    for index in range(two_byte):
        chars[index] = "é"
    for index in range(four_byte):
        chars[two_byte + index] = "😀"
    combined = "".join(chars)
    pair = raw_pair(combined[:100_000], combined[100_000:])
    assert len(_canonical(_proposal_request_envelope(pair))) == target_bytes
    return pair


def _node_tree(total, depth=0):
    def capacity(level):
        if level >= _MAX_DEPTH:
            return 1
        return 1 + 20 * capacity(level + 1)

    if total == 1:
        return None
    assert depth < _MAX_DEPTH
    child_capacity = capacity(depth + 1)
    child_count = (total - 1 + child_capacity - 1) // child_capacity
    assert child_count <= 20
    remaining = total - 1
    children = []
    for index in range(child_count):
        slots_left = child_count - index - 1
        child_nodes = min(child_capacity, remaining - slots_left)
        children.append(_node_tree(child_nodes, depth + 1))
        remaining -= child_nodes
    assert remaining == 0
    return children


def test_request_contains_only_bounded_synthetic_source_context_and_stable_request_id():
    pair = _pair()
    request = build_proposal_request(pair)
    assert request["schema_version"] == 1
    assert request["request_id"].startswith("req-syn-")
    assert [version["side"] for version in request["versions"]] == ["OLDER", "NEWER"]
    assert request == build_proposal_request(pair)
    assert "PROPOSALS_ONLY" in request["limitations"]
    assert "HUMAN_REVIEW_REQUIRED" in request["limitations"]


def test_normalized_proposal_derives_offsets_hashes_and_trusted_status_locally():
    candidate = _normalize()["candidates"][0]
    assert candidate["candidate_id"] == "cand-syn-proposal-1"
    assert candidate["status"] == "PROPOSAL_ONLY"
    assert candidate["semantic_support"] == "NOT_VERIFIED"
    assert candidate["human_review_required"] is True
    pair = _pair()
    expected = []
    for side, version in (("OLDER", pair.older), ("NEWER", pair.newer)):
        quote = version.passages[0].text
        start = version.original_text.index(quote)
        expected.append({
            "side": side,
            "document_id": version.document_id,
            "version_id": version.version_id,
            "source_sha256": version.source_sha256,
            "passage_id": version.passages[0].passage_id,
            "start_cp": start,
            "end_cp": start + len(quote),
            "quote": quote,
        })
    assert candidate["citations"] == expected


@pytest.mark.parametrize("field,value", [
    ("classification", "CONTRADICTION"),
    ("semantic_support", "SUPPORTED"),
    ("precedence", "DEFINED"),
    ("coverage", "COMPLETE"),
    ("confirmed_impact", True),
    ("approved", True),
    ("offsets", [1, 2]),
    ("source_sha256", "0" * 64),
])
def test_authoritative_claims_and_caller_provenance_are_rejected(field, value):
    proposal = _candidate()
    proposal[field] = value
    with pytest.raises(PolicyProposalContractError):
        _normalize([proposal])


@pytest.mark.parametrize("response", [
    "boolean_version",
    "unsupported_version",
    "wrong_request_id",
    "extra_root_field",
    "non_record_candidate",
])
def test_wrong_schema_request_binding_and_shapes_reject_for_the_targeted_reason(response):
    request = build_proposal_request(_pair())
    cases = {
        "boolean_version": {"schema_version": True, "request_id": request["request_id"], "candidates": []},
        "unsupported_version": {"schema_version": 2, "request_id": request["request_id"], "candidates": []},
        "wrong_request_id": {"schema_version": 1, "request_id": "wrong", "candidates": []},
        "extra_root_field": {"schema_version": 1, "request_id": request["request_id"], "candidates": [], "extra": 1},
        "non_record_candidate": {"schema_version": 1, "request_id": request["request_id"], "candidates": [None]},
    }
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(_pair(), request, cases[response])


@pytest.mark.parametrize("version", [True, float("nan"), float("inf"), float("-inf")])
def test_non_integer_or_non_finite_schema_versions_reject(version):
    request = build_proposal_request(_pair())
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(_pair(), request, {
            "schema_version": version, "request_id": request["request_id"], "candidates": []
        })


@pytest.mark.parametrize("candidate", [
    {},
    {"proposed_relation": "INCONCLUSIVE", "reasoning": "x",
     "citation_hints": [], "uncertainty_reasons": ["missing_evidence"]},
    {"proposed_relation": "INCONCLUSIVE", "reasoning": "x",
     "citation_hints": [], "uncertainty_reasons": ["missing_evidence"],
     "abstain": True, "extra": False},
])
def test_missing_and_extra_candidate_fields_reject(candidate):
    with pytest.raises(PolicyProposalContractError):
        _normalize([candidate])


def test_duplicate_json_keys_and_malformed_json_reject_with_fixed_error():
    pair = _pair()
    request = build_proposal_request(pair)
    raw = ('{"schema_version":1,"request_id":"' + request["request_id"]
           + '","request_id":"forged","candidates":[]}')
    for value in (raw, "{bad json"):
        with pytest.raises(PolicyProposalContractError) as error:
            normalize_proposal_response(pair, request, value)
        assert str(error.value) == "Policy proposal contract is invalid."
        assert value not in str(error.value)
    nested_duplicate = ('{"schema_version":1,"request_id":"' + request["request_id"]
                        + '","candidates":[],"nested":{"x":1,"x":2}}')
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, request, nested_duplicate)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_constants_are_rejected(constant):
    request = build_proposal_request(_pair())
    raw = ('{"schema_version":1,"request_id":"' + request["request_id"]
           + '","candidates":[],"extra":' + constant + '}')
    with pytest.raises(PolicyProposalContractError) as error:
        normalize_proposal_response(_pair(), request, raw)
    assert str(error.value) == "Policy proposal contract is invalid."


def test_escaped_lone_surrogate_and_unsupported_byte_input_reject_safely():
    request = build_proposal_request(_pair())
    raw = ('{"schema_version":1,"request_id":"' + request["request_id"]
           + '","candidates":[],"extra":"\\ud800"}')
    for invalid in (raw, b'{"schema_version":1}'):
        with pytest.raises(PolicyProposalContractError) as error:
            normalize_proposal_response(_pair(), request, invalid)
        assert str(error.value) == "Policy proposal contract is invalid."


@pytest.mark.parametrize("raw", ["null", "true", "false", "[]", "\"text\"", "7"])
def test_unexpected_json_top_level_values_reject(raw):
    request = build_proposal_request(_pair())
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(_pair(), request, raw)


@pytest.mark.parametrize("character", ["A", "é", "\""])
def test_canonical_parsed_and_raw_json_byte_limit_exact_and_one_over(character):
    value = _padded_response(MAX_RESPONSE_BYTES, character)
    assert len(_canonical(value)) == MAX_RESPONSE_BYTES
    assert _decode(value) == value
    assert _decode(_canonical(value).decode("utf-8")) == value

    one_over = _padded_response(MAX_RESPONSE_BYTES + 1, character)
    assert len(_canonical(one_over)) == MAX_RESPONSE_BYTES + 1
    for oversized in (one_over, _canonical(one_over).decode("utf-8")):
        with pytest.raises(PolicyProposalContractError):
            _decode(oversized)


def test_depth_node_object_array_and_string_limits_at_and_over_boundary():
    at_depth = None
    for _ in range(_MAX_DEPTH):
        at_depth = [at_depth]
    over_depth = [at_depth]
    _bound(at_depth)
    with pytest.raises(PolicyProposalContractError):
        _bound(over_depth)

    _bound(_node_tree(_MAX_NODES), max_bytes=1_000_000)
    with pytest.raises(PolicyProposalContractError):
        _bound(_node_tree(_MAX_NODES + 1), max_bytes=1_000_000)
    _bound({str(index): None for index in range(_MAX_OBJECT)})
    with pytest.raises(PolicyProposalContractError):
        _bound({str(index): None for index in range(_MAX_OBJECT + 1)})
    _bound([None] * 20)
    with pytest.raises(PolicyProposalContractError):
        _bound([None] * 21)
    _bound("x" * _MAX_STRING)
    with pytest.raises(PolicyProposalContractError):
        _bound("x" * (_MAX_STRING + 1))


def test_request_node_limit_and_policy_passage_boundary_are_aligned():
    _bound(_node_tree(MAX_REQUEST_NODES), max_nodes=MAX_REQUEST_NODES,
           max_bytes=MAX_REQUEST_BYTES)
    with pytest.raises(PolicyProposalContractError):
        _bound(_node_tree(MAX_REQUEST_NODES + 1), max_nodes=MAX_REQUEST_NODES,
               max_bytes=MAX_REQUEST_BYTES)

    text_1000 = "\n\n".join(f"Synthetic passage {index:04d}." for index in range(1_000))
    pair = validate_policy_pair({
        "schema_version": 1, "comparison_id": "cmp-syn-passage-boundary",
        "older": _version("v1", text_1000), "newer": _version("v2", text_1000),
    })
    assert len(pair.older.passages) == 1_000
    assert len(build_proposal_request(pair)["versions"][0]["passages"]) == 1_000
    over_limit = "\n\n".join(f"Synthetic passage {index:04d}." for index in range(1_001))
    with pytest.raises(PolicyCompareError):
        validate_policy_pair({
            "schema_version": 1, "comparison_id": "cmp-syn-passage-over",
            "older": _version("v1", over_limit), "newer": _version("v2", "Newer."),
        })


@pytest.mark.parametrize("target", [MAX_REQUEST_BYTES, MAX_REQUEST_BYTES + 1])
def test_request_serialized_utf8_byte_limit_exact_and_one_over(target):
    pair = _pair_with_request_bytes(target)
    if target == MAX_REQUEST_BYTES:
        assert len(_canonical(build_proposal_request(pair))) == MAX_REQUEST_BYTES
    else:
        assert len(_canonical(_proposal_request_envelope(pair))) == MAX_REQUEST_BYTES + 1
        with pytest.raises(PolicyProposalContractError):
            build_proposal_request(pair)


def test_limits_reject_large_strings_candidate_lists_and_nested_or_unsupported_objects():
    pair, request = _pair(), build_proposal_request(_pair())
    too_long = " " * 64_001
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, request, too_long)
    with pytest.raises(PolicyProposalContractError):
        _normalize([_candidate() for _ in range(21)])
    oversized = {"schema_version": 1, "request_id": request["request_id"],
                 "candidates": [], "x" * 4_001: "value"}
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, request, oversized)
    aggregate_oversized = {
        "schema_version": 1, "request_id": request["request_id"],
        "candidates": [{"large": "z" * 3_500} for _ in range(20)],
    }
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, request, aggregate_oversized)
    recursive = {"schema_version": 1, "request_id": request["request_id"], "candidates": []}
    recursive["extra"] = recursive
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, request, recursive)
    oversized_request = deepcopy(request)
    oversized_request["versions"][0]["passages"][0]["text"] = object()
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, oversized_request, {
            "schema_version": 1, "request_id": request["request_id"], "candidates": []
        })


@pytest.mark.parametrize("relation,sides", [
    ("CONTRADICTION", ("OLDER",)),
    ("COMPATIBLE_CHANGE", ("NEWER",)),
    ("SCOPE_OR_TIME_DIFFERENCE", ("OLDER",)),
])
def test_comparison_relations_require_citations_from_both_versions(relation, sides):
    with pytest.raises(PolicyProposalContractError):
        _normalize([_candidate(relation, sides=sides)])


def test_new_rule_is_only_a_newer_side_proposal():
    result = _normalize([_candidate("NEW_RULE", sides=("NEWER",),
                                    quote="Record requests at shift start.")])
    assert result["candidates"][0]["proposed_relation"] == "NEW_RULE"
    assert result["candidates"][0]["status"] == "PROPOSAL_ONLY"
    with pytest.raises(PolicyProposalContractError):
        _normalize([_candidate("NEW_RULE", sides=("OLDER",))])


@pytest.mark.parametrize("hint_change", [
    {"side": "OLDER", "passage_id": "p000999-0000000000000000", "quote": "Record requests before shift end."},
    {"side": "OLDER", "passage_id": "p000001-0000000000000000", "quote": "not a source quote"},
    {"side": "OLDER", "passage_id": "p000001-0000000000000000", "quote": ""},
])
def test_fabricated_passage_and_nonmatching_quote_reject(hint_change):
    candidate = _candidate()
    candidate["citation_hints"][0] = hint_change
    with pytest.raises(PolicyProposalContractError):
        _normalize([candidate])


def test_valid_passage_from_wrong_version_and_boundary_shifted_quote_reject():
    pair = _pair()
    candidate = _candidate()
    newer_passage = pair.newer.passages[0]
    candidate["citation_hints"][0] = {
        "side": "OLDER", "passage_id": newer_passage.passage_id,
        "quote": newer_passage.text,
    }
    with pytest.raises(PolicyProposalContractError):
        _normalize([candidate])

    shifted = _candidate()
    shifted["citation_hints"][0]["quote"] += "x"
    with pytest.raises(PolicyProposalContractError):
        _normalize([shifted])


@pytest.mark.parametrize("hint", [
    {"passage_id": "p000001-0000000000000000", "quote": "quote"},
    {"side": "OLDER", "passage_id": "p000001-0000000000000000", "quote": "quote", "start_cp": 0},
    {"side": True, "passage_id": "p000001-0000000000000000", "quote": "quote"},
    {"side": "OLDER", "passage_id": [], "quote": "quote"},
    {"side": "OLDER", "passage_id": "p000001-0000000000000000", "quote": False},
])
def test_missing_extra_fields_and_wrong_hint_types_reject(hint):
    candidate = _candidate()
    candidate["citation_hints"][0] = hint
    with pytest.raises(PolicyProposalContractError):
        _normalize([candidate])


def test_quote_that_occurs_ambiguously_in_passage_rejects():
    pair_input = {
        "schema_version": 1, "comparison_id": "cmp-syn-proposal-contract-02",
        "older": _version("v1", "Repeat this phrase. Repeat this phrase."),
        "newer": _version("v2", "A different newer rule."),
    }
    pair = validate_policy_pair(pair_input)
    request = build_proposal_request(pair)
    response = {"schema_version": 1, "request_id": request["request_id"], "candidates": [{
        "proposed_relation": "INCONCLUSIVE", "reasoning": "Ambiguous quote location.",
        "citation_hints": [{"side": "OLDER", "passage_id": pair.older.passages[0].passage_id,
                            "quote": "Repeat this phrase."}],
        "uncertainty_reasons": ["missing_evidence"], "abstain": False,
    }]}
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, request, response)


def test_abstention_must_be_inconclusive_and_have_no_citations():
    valid = _candidate("INCONCLUSIVE", sides=(), reasons=["missing_evidence"], abstain=True)
    assert _normalize([valid])["candidates"][0]["abstain"] is True
    invalid = _candidate("CONTRADICTION", reasons=["semantic_support_unverified"], abstain=True)
    with pytest.raises(PolicyProposalContractError):
        _normalize([invalid])


def test_affirmative_proposals_require_semantic_uncertainty():
    candidate = _candidate(reasons=["precedence_unverified"])
    with pytest.raises(PolicyProposalContractError):
        _normalize([candidate])


def test_duplicate_candidate_proposals_reject_whole_response():
    candidate = _candidate()
    with pytest.raises(PolicyProposalContractError):
        _normalize([deepcopy(candidate), deepcopy(candidate)])


def test_invalid_frozen_pair_and_tampered_request_fail_closed():
    pair, request = _pair(), build_proposal_request(_pair())
    request["versions"][0]["source_sha256"] = "0" * 64
    with pytest.raises(PolicyProposalContractError):
        normalize_proposal_response(pair, request, {
            "schema_version": 1, "request_id": request["request_id"], "candidates": []
        })


def test_malformed_in_process_policy_pair_nested_record_is_sanitized():
    malformed = PolicyPair(1, "cmp-syn-malformed", object(), object())
    with pytest.raises(PolicyProposalContractError) as error:
        build_proposal_request(malformed)
    assert str(error.value) == "Policy proposal contract is invalid."


def test_contract_errors_do_not_expose_untrusted_strings():
    secretish = "synthetic-private-payload"
    response = {"schema_version": 1, "request_id": "wrong", "candidates": [], "detail": secretish}
    with pytest.raises(PolicyProposalContractError) as error:
        _normalize(response=response)
    assert str(error.value) == "Policy proposal contract is invalid."
    assert secretish not in str(error.value)

