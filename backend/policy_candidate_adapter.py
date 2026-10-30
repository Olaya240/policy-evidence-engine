"""Offline contract for untrusted policy comparison candidate generators.

The interface describes a future proposal-only generator. This module has no
transport or authentication implementation. Its only executable adapter is an
exact-type, fixture-backed fake for deterministic offline tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Protocol

from policy_compare import PolicyCompareError, PolicyPair, validate_citation


MAX_RESPONSE_BYTES = 64_000
MAX_CANDIDATES = 20
MAX_REASONING = 500
MAX_UNCERTAINTY_REASONS = 8
_RELATIONS = {
    "CONTRADICTION", "COMPATIBLE_CHANGE", "NEW_RULE",
    "SCOPE_OR_TIME_DIFFERENCE", "INCONCLUSIVE",
}
_REASONS = {
    "semantic_support_unverified", "precedence_unverified",
    "coverage_unverified", "scope_or_time_unverified",
    "missing_evidence", "unsupported_claim",
}
_TWO_SIDED_RELATIONS = {
    "CONTRADICTION", "COMPATIBLE_CHANGE", "SCOPE_OR_TIME_DIFFERENCE",
}
_MAX_JSON_DEPTH = 8
_MAX_JSON_ARRAY_ITEMS = 20
_MAX_JSON_OBJECT_ITEMS = 16


class PolicyCandidateAdapterError(ValueError):
    """Fixed, sanitized error for malformed candidate-generator output."""

    def __init__(self) -> None:
        super().__init__("Policy candidate response is invalid.")
        self.code = "invalid_response"


class PolicyCandidateGenerator(Protocol):
    """Future proposal-only interface; implementations are not activated here."""

    def generate(self, pair: PolicyPair) -> Any:
        """Return an untrusted JSON-shaped candidate response."""


@dataclass(frozen=True)
class FakePolicyCandidateAdapter:
    """A fixed synthetic response source; it has no network capability."""

    response_json: str

    def generate(self, pair: PolicyPair) -> str:
        del pair
        if type(self.response_json) is not str:
            raise PolicyCandidateAdapterError()
        return self.response_json


def _invalid() -> None:
    raise PolicyCandidateAdapterError()


def _exact_object(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _invalid()
    return value


def _serialized_string_size(value: str, *, limit: int = MAX_RESPONSE_BYTES) -> int:
    """Exact JSON string byte count for json.dumps(..., ensure_ascii=True)."""
    size = 2  # surrounding quotes
    short_escapes = {'"', "\\", "\b", "\t", "\n", "\f", "\r"}
    for character in value:
        codepoint = ord(character)
        if character in short_escapes:
            size += 2
        elif codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
            size += 6
        elif codepoint <= 0x7F:
            size += 1
        elif codepoint <= 0xFFFF:
            size += 6
        else:
            size += 12
        if size > limit:
            return limit + 1
    return size


def _precheck_json_value(value: Any, *, depth: int = 0,
                         budget: list[int] | None = None,
                         nodes: list[int] | None = None) -> None:
    """Bound a JSON-shaped object before making a serialized copy."""
    if budget is None:
        budget = [0]
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > MAX_RESPONSE_BYTES:
        _invalid()
    if depth > _MAX_JSON_DEPTH:
        _invalid()
    if value is None or type(value) is bool:
        budget[0] += 4
    elif type(value) is int:
        if value.bit_length() > MAX_RESPONSE_BYTES * 4:
            _invalid()
        budget[0] += max(1, (value.bit_length() + 2) // 3)
    elif type(value) is float:
        if not math.isfinite(value):
            _invalid()
        budget[0] += 32
    elif type(value) is str:
        budget[0] += _serialized_string_size(value, limit=MAX_RESPONSE_BYTES - budget[0])
    elif type(value) is list:
        if len(value) > _MAX_JSON_ARRAY_ITEMS:
            _invalid()
        budget[0] += 2 + len(value)
        if budget[0] > MAX_RESPONSE_BYTES:
            _invalid()
        for item in value:
            _precheck_json_value(item, depth=depth + 1, budget=budget, nodes=nodes)
    elif type(value) is dict:
        if len(value) > _MAX_JSON_OBJECT_ITEMS:
            _invalid()
        budget[0] += 2 + len(value)
        if budget[0] > MAX_RESPONSE_BYTES:
            _invalid()
        for key, item in value.items():
            if type(key) is not str:
                _invalid()
            budget[0] += _serialized_string_size(key, limit=MAX_RESPONSE_BYTES - budget[0])
            _precheck_json_value(item, depth=depth + 1, budget=budget, nodes=nodes)
    else:
        _invalid()
    if budget[0] > MAX_RESPONSE_BYTES:
        _invalid()


def _precheck_response_shape(value: Any) -> dict[str, Any]:
    if type(value) is not dict or len(value) != 2:
        _invalid()
    obj = _exact_object(value, {"schema_version", "candidates"})
    if type(obj["candidates"]) is not list or len(obj["candidates"]) > MAX_CANDIDATES:
        _invalid()
    _precheck_json_value(obj)
    return obj


def _decode_response(value: Any) -> dict[str, Any]:
    if type(value) is str:
        # UTF-8 uses at least one byte per code point, so this rejects clearly
        # oversized strings before allocating an encoded copy.
        if len(value) > MAX_RESPONSE_BYTES:
            _invalid()
        try:
            encoded = value.encode("utf-8", "strict")
        except UnicodeError:
            _invalid()
        if len(encoded) > MAX_RESPONSE_BYTES:
            _invalid()
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, RecursionError):
            _invalid()
    elif type(value) is dict:
        # Check allowed root shape, candidate count, JSON types, depth and
        # aggregate size before json.dumps allocates a serialized copy.
        _precheck_response_shape(value)
        try:
            if len(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")) > MAX_RESPONSE_BYTES:
                _invalid()
        except (TypeError, ValueError, RecursionError):
            _invalid()
    else:
        _invalid()
    return _precheck_response_shape(value)


def validate_candidate_response(pair: PolicyPair, response: Any) -> dict[str, Any]:
    """Validate schema and exact source provenance; never validate semantics."""
    if type(pair) is not PolicyPair:
        _invalid()
    try:
        obj = _decode_response(response)
        if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
            _invalid()
        candidates = obj["candidates"]
        if type(candidates) is not list or len(candidates) > MAX_CANDIDATES:
            _invalid()

        normalized = []
        seen_ids: set[str] = set()
        candidate_keys = {"candidate_id", "proposed_relation", "reasoning", "citations",
                          "uncertainty_reasons", "abstain"}
        for raw_candidate in candidates:
            candidate = _exact_object(raw_candidate, candidate_keys)
            candidate_id = candidate["candidate_id"]
            if (type(candidate_id) is not str
                    or re.fullmatch(r"cand-[a-z0-9]+(?:-[a-z0-9]+)*", candidate_id) is None
                    or candidate_id in seen_ids):
                _invalid()
            seen_ids.add(candidate_id)
            relation = candidate["proposed_relation"]
            reasoning = candidate["reasoning"]
            abstain = candidate["abstain"]
            if (type(relation) is not str or relation not in _RELATIONS
                    or type(reasoning) is not str or not reasoning.strip()
                    or len(reasoning) > MAX_REASONING or "\x00" in reasoning):
                _invalid()
            try:
                reasoning.encode("utf-8", "strict")
            except UnicodeEncodeError:
                _invalid()
            if type(abstain) is not bool or (abstain and relation != "INCONCLUSIVE"):
                _invalid()

            reasons = candidate["uncertainty_reasons"]
            if (type(reasons) is not list or len(reasons) > MAX_UNCERTAINTY_REASONS
                    or any(type(reason) is not str or reason not in _REASONS for reason in reasons)
                    or len(set(reasons)) != len(reasons)
                    or ((abstain or relation == "INCONCLUSIVE") and not reasons)):
                _invalid()
            if relation != "INCONCLUSIVE" and "semantic_support_unverified" not in reasons:
                _invalid()
            citations = candidate["citations"]
            if type(citations) is not list or len(citations) > 2:
                _invalid()
            if abstain and citations:
                _invalid()
            if not abstain and not citations:
                _invalid()
            canonical_citations = []
            seen_sides: set[str] = set()
            for raw_citation in citations:
                citation = _exact_object(raw_citation, {"side", "document_id", "version_id",
                    "source_sha256", "passage_id", "start_cp", "end_cp", "quote"})
                side = citation["side"]
                if type(side) is not str or side not in {"OLDER", "NEWER"} or side in seen_sides:
                    _invalid()
                seen_sides.add(side)
                source_fields = {key: value for key, value in citation.items() if key != "side"}
                try:
                    canonical = validate_citation(
                        pair, source_fields, expected_side=side
                    )
                except PolicyCompareError:
                    _invalid()
                canonical_citations.append({"side": side, **canonical})
            if (relation in _TWO_SIDED_RELATIONS
                    and seen_sides != {"OLDER", "NEWER"}):
                _invalid()

            normalized.append({
                "candidate_id": candidate_id,
                "proposed_relation": relation,
                "reasoning": reasoning,
                "citations": canonical_citations,
                "uncertainty_reasons": list(reasons),
                "abstain": abstain,
                "status": "PROPOSAL_ONLY",
                "semantic_support": "NOT_VERIFIED",
                "human_review_required": True,
            })
        return {"schema_version": 1, "candidates": normalized}
    except PolicyCandidateAdapterError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError):
        _invalid()


def generate_from_fake(adapter: FakePolicyCandidateAdapter, pair: PolicyPair) -> dict[str, Any]:
    """Test-only fake path. Exact type and controlled errors prevent transport injection."""
    if type(adapter) is not FakePolicyCandidateAdapter:
        _invalid()
    try:
        raw = adapter.generate(pair)
    except Exception:
        _invalid()
    return validate_candidate_response(pair, raw)
