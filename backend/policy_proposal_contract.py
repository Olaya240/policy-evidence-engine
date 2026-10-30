"""Provider-independent, offline contract for untrusted policy proposals.

This module defines a future model-facing request/response shape only. It has
no transport, credentials, or runtime dispatch. Citation provenance is rebuilt
locally and validated by :mod:`policy_compare`; semantic support remains
unverified. Python-level checks are application safeguards, not a sandbox
against hostile code running in the same process.
"""
from __future__ import annotations

import json
from hashlib import sha256
from datetime import date
from typing import Any

from policy_candidate_adapter import (
    MAX_CANDIDATES,
    MAX_REASONING,
    MAX_RESPONSE_BYTES,
    PolicyCandidateAdapterError,
    validate_candidate_response,
)
from policy_compare import (
    ImpactDependency,
    PolicyCompareError,
    PolicyPair,
    PolicyVersion,
    Scope,
    ScopeSet,
    validate_policy_pair,
)


MAX_REQUEST_BYTES = 512_000
MAX_REQUEST_NODES = 50_000
_SCHEMA_VERSION = 1
_RELATIONS = {
    "CONTRADICTION", "COMPATIBLE_CHANGE", "NEW_RULE",
    "SCOPE_OR_TIME_DIFFERENCE", "INCONCLUSIVE",
}
_REASONS = {
    "semantic_support_unverified", "precedence_unverified",
    "coverage_unverified", "scope_or_time_unverified",
    "missing_evidence", "unsupported_claim",
}
_TWO_SIDED = {"CONTRADICTION", "COMPATIBLE_CHANGE", "SCOPE_OR_TIME_DIFFERENCE"}
_MAX_DEPTH = 8
_MAX_ARRAY = 20
_MAX_OBJECT = 16
_MAX_NODES = 20_000
_MAX_STRING = 4_000


class PolicyProposalContractError(ValueError):
    """Fixed public error; never includes untrusted response content."""

    def __init__(self) -> None:
        self.code = "invalid_proposal_contract"
        super().__init__("Policy proposal contract is invalid.")


def _reject() -> None:
    raise PolicyProposalContractError()


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _reject()


def _validated_pair(pair: Any) -> PolicyPair:
    """Round-trip the frozen core object through its strict input validator."""
    if type(pair) is not PolicyPair:
        _reject()

    def check_record(item: Any) -> None:
        if type(item) is not PolicyVersion or type(item.scope) is not Scope:
            _reject()
        if ((item.effective_from is not None and type(item.effective_from) is not date)
                or (item.effective_to_exclusive is not None
                    and type(item.effective_to_exclusive) is not date)):
            _reject()
        if (type(item.scope.departments) is not ScopeSet
                or type(item.scope.procedures) is not ScopeSet
                or type(item.impact_dependencies) is not tuple
                or any(type(dep) is not ImpactDependency for dep in item.impact_dependencies)
                or type(item.scope.departments.ids) is not tuple
                or type(item.scope.procedures.ids) is not tuple
                or type(item.scope.evidence_passage_ids) is not tuple):
            _reject()

    def version(item: Any) -> dict[str, Any]:
        check_record(item)
        return {
            "document_id": item.document_id,
            "version_id": item.version_id,
            "original_text": item.original_text,
            "effective_from": item.effective_from.isoformat() if item.effective_from else None,
            "effective_to_exclusive": item.effective_to_exclusive.isoformat() if item.effective_to_exclusive else None,
            "scope": {
                "departments": {"state": item.scope.departments.state,
                                "ids": list(item.scope.departments.ids)},
                "procedures": {"state": item.scope.procedures.state,
                               "ids": list(item.scope.procedures.ids)},
                "property_id": item.scope.property_id,
                "evidence_passage_ids": list(item.scope.evidence_passage_ids),
            },
            "text_coverage": item.text_coverage,
            "impact_dependencies": [{
                "department_id": dep.department_id,
                "procedure_id": dep.procedure_id,
                "passage_ids": list(dep.passage_ids),
            } for dep in item.impact_dependencies],
        }

    try:
        check_record(pair.older)
        check_record(pair.newer)
        return validate_policy_pair({
            "schema_version": pair.schema_version,
            "comparison_id": pair.comparison_id,
            "older": version(pair.older),
            "newer": version(pair.newer),
        })
    except (AttributeError, PolicyCompareError, TypeError, ValueError, RecursionError):
        _reject()


def _decode(value: Any) -> dict[str, Any]:
    if type(value) is str:
        if len(value) > MAX_RESPONSE_BYTES:
            _reject()
        try:
            encoded = value.encode("utf-8", "strict")
        except UnicodeError:
            _reject()
        if len(encoded) > MAX_RESPONSE_BYTES:
            _reject()
        try:
            value = json.loads(value, object_pairs_hook=_pairs_no_duplicates,
                               parse_constant=_reject_constant)
        except PolicyProposalContractError:
            raise
        except (json.JSONDecodeError, RecursionError, ValueError):
            _reject()
    if type(value) is not dict:
        _reject()
    _bound(value)
    if type(value) is dict:
        _canonical_json_bytes(value, MAX_RESPONSE_BYTES)
    return value


def _canonical_json_bytes(value: dict[str, Any], limit: int) -> bytes:
    """Canonical parsed-object size: sorted keys, compact UTF-8, no ASCII escaping."""
    try:
        encoded = json.dumps(
            value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8", "strict")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _reject()
    if len(encoded) > limit:
        _reject()
    return encoded


def _bound(value: Any, depth: int = 0, nodes: list[int] | None = None,
           size: list[int] | None = None, *, max_string: int = _MAX_STRING,
           max_array: int = _MAX_ARRAY, max_bytes: int = MAX_RESPONSE_BYTES,
           max_nodes: int = _MAX_NODES) -> None:
    """Check structure and accumulate exact compact UTF-8 JSON token bytes."""
    if nodes is None:
        nodes = [0]
    if size is None:
        size = [0]
    nodes[0] += 1
    if nodes[0] > max_nodes or depth > _MAX_DEPTH or size[0] > max_bytes:
        _reject()

    def charge(amount: int) -> None:
        size[0] += amount
        if size[0] > max_bytes:
            _reject()

    def string_token_size(text: str) -> int:
        result = 2
        short_escapes = {'"', "\\", "\b", "\t", "\n", "\f", "\r"}
        for character in text:
            codepoint = ord(character)
            if character in short_escapes:
                result += 2
            elif codepoint < 0x20:
                result += 6
            else:
                result += len(character.encode("utf-8", "strict"))
        return result

    if value is None or type(value) is bool:
        charge(len("null") if value is None else (4 if value else 5))
        return
    if type(value) is int:
        if value.bit_length() > max_bytes * 4:
            _reject()
        try:
            token_size = len(str(value))
        except ValueError:
            _reject()
        charge(token_size)
        return
    if type(value) is float:
        try:
            token_size = len(json.dumps(value, allow_nan=False).encode("ascii"))
        except (TypeError, ValueError, OverflowError):
            _reject()
        charge(token_size)
        return
    if type(value) is str:
        if len(value) > max_string:
            _reject()
        try:
            token_size = string_token_size(value)
        except UnicodeError:
            _reject()
        charge(token_size)
        return
    if type(value) is list:
        if len(value) > max_array:
            _reject()
        charge(2 + max(0, len(value) - 1))
        for item in value:
            _bound(item, depth + 1, nodes, size, max_string=max_string,
                   max_array=max_array, max_bytes=max_bytes, max_nodes=max_nodes)
        return
    if type(value) is dict:
        if len(value) > _MAX_OBJECT:
            _reject()
        charge(2 + max(0, len(value) - 1) + len(value))
        for key, item in value.items():
            if type(key) is not str or len(key) > max_string:
                _reject()
            _bound(key, depth + 1, nodes, size, max_string=max_string,
                   max_array=max_array, max_bytes=max_bytes, max_nodes=max_nodes)
            _bound(item, depth + 1, nodes, size, max_string=max_string,
                   max_array=max_array, max_bytes=max_bytes, max_nodes=max_nodes)
        return
    _reject()


def _proposal_request_envelope(pair: PolicyPair) -> dict[str, Any]:
    request_material = "|".join((pair.comparison_id, pair.older.document_id,
                                  pair.older.version_id, pair.older.source_sha256,
                                  pair.newer.version_id, pair.newer.source_sha256))
    request_id = "req-syn-" + sha256(request_material.encode("utf-8", "strict")).hexdigest()[:24]

    def version(side: str, item: Any) -> dict[str, Any]:
        return {
            "side": side,
            "document_id": item.document_id,
            "version_id": item.version_id,
            "source_sha256": item.source_sha256,
            "effective_from": item.effective_from.isoformat() if item.effective_from else None,
            "effective_to_exclusive": item.effective_to_exclusive.isoformat() if item.effective_to_exclusive else None,
            "scope": {
                "departments": {"state": item.scope.departments.state, "ids": list(item.scope.departments.ids)},
                "procedures": {"state": item.scope.procedures.state, "ids": list(item.scope.procedures.ids)},
                "property_id": item.scope.property_id,
            },
            "text_coverage": item.text_coverage,
            "passages": [{"passage_id": p.passage_id, "start_cp": p.start_cp,
                          "end_cp": p.end_cp, "text": p.text} for p in item.passages],
        }

    envelope = {
        "schema_version": _SCHEMA_VERSION,
        "request_id": request_id,
        "comparison_id": pair.comparison_id,
        "versions": [version("OLDER", pair.older), version("NEWER", pair.newer)],
        "limitations": ["PROPOSALS_ONLY", "SEMANTIC_SUPPORT_UNVERIFIED",
                        "PRECEDENCE_UNVERIFIED", "COVERAGE_NOT_ESTABLISHED",
                        "HUMAN_REVIEW_REQUIRED"],
    }
    return envelope


def build_proposal_request(pair: PolicyPair) -> dict[str, Any]:
    """Build a deterministic, bounded request envelope from a validated pair."""
    pair = _validated_pair(pair)
    envelope = _proposal_request_envelope(pair)
    try:
        encoded = _canonical_json_bytes(envelope, MAX_REQUEST_BYTES)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _reject()
    return envelope


def normalize_proposal_response(pair: PolicyPair, request: dict[str, Any], response: Any) -> dict[str, Any]:
    """Validate untrusted proposal hints and derive all provenance locally.

    Accepted response schema: ``{schema_version, request_id, candidates}``;
    each candidate has exactly ``proposed_relation, reasoning, citation_hints,
    uncertainty_reasons, abstain``. A hint has exactly ``side, passage_id,
    quote``. The model cannot supply offsets, hashes, identities, or trusted
    result/status fields.
    """
    if type(request) is not dict:
        _reject()
    try:
        pair = _validated_pair(pair)
        _bound(request, max_string=100_000, max_array=1_000,
               max_bytes=MAX_REQUEST_BYTES, max_nodes=MAX_REQUEST_NODES)
        _canonical_json_bytes(request, MAX_REQUEST_BYTES)
        expected_request = build_proposal_request(pair)
        if request != expected_request:
            _reject()
        obj = _decode(response)
        if set(obj) != {"schema_version", "request_id", "candidates"}:
            _reject()
        if (type(obj["schema_version"]) is not int or obj["schema_version"] != _SCHEMA_VERSION
                or type(obj["request_id"]) is not str or obj["request_id"] != request["request_id"]):
            _reject()
        candidates = obj["candidates"]
        if type(candidates) is not list or len(candidates) > MAX_CANDIDATES:
            _reject()

        canonical: list[dict[str, Any]] = []
        seen_proposals: set[tuple[Any, ...]] = set()
        for index, raw in enumerate(candidates, 1):
            if type(raw) is not dict or set(raw) != {
                "proposed_relation", "reasoning", "citation_hints", "uncertainty_reasons", "abstain"
            }:
                _reject()
            relation, reasoning = raw["proposed_relation"], raw["reasoning"]
            reasons, abstain, hints = raw["uncertainty_reasons"], raw["abstain"], raw["citation_hints"]
            if (type(relation) is not str or relation not in _RELATIONS
                    or type(reasoning) is not str or not reasoning.strip()
                    or len(reasoning) > MAX_REASONING or "\x00" in reasoning
                    or type(abstain) is not bool):
                _reject()
            if (type(reasons) is not list or len(reasons) > 8
                    or any(type(reason) is not str or reason not in _REASONS for reason in reasons)
                    or len(set(reasons)) != len(reasons)):
                _reject()
            if relation != "INCONCLUSIVE" and "semantic_support_unverified" not in reasons:
                _reject()
            if (relation == "INCONCLUSIVE" and not reasons) or (abstain and relation != "INCONCLUSIVE"):
                _reject()
            if type(hints) is not list or len(hints) > 2 or (abstain and hints) or (not abstain and not hints):
                _reject()
            citations: list[dict[str, Any]] = []
            sides: set[str] = set()
            signature: list[tuple[str, str, str]] = []
            for hint in hints:
                if type(hint) is not dict or set(hint) != {"side", "passage_id", "quote"}:
                    _reject()
                side, passage_id, quote = hint["side"], hint["passage_id"], hint["quote"]
                if type(side) is not str or side not in {"OLDER", "NEWER"} or side in sides:
                    _reject()
                if type(passage_id) is not str or type(quote) is not str or not quote or len(quote) > MAX_REASONING:
                    _reject()
                sides.add(side)
                version = pair.older if side == "OLDER" else pair.newer
                passage = version.passage(passage_id)
                if passage is None or passage.text.count(quote) != 1:
                    _reject()
                relative = passage.text.find(quote)
                start, end = passage.start_cp + relative, passage.start_cp + relative + len(quote)
                locally_derived = {
                    "document_id": version.document_id,
                    "version_id": version.version_id,
                    "source_sha256": version.source_sha256,
                    "passage_id": passage.passage_id,
                    "start_cp": start,
                    "end_cp": end,
                    "quote": quote,
                }
                try:
                    checked = validate_candidate_response(pair, {"schema_version": 1, "candidates": [{
                        "candidate_id": f"cand-syn-check-{index}", "proposed_relation": "INCONCLUSIVE",
                        "reasoning": "Citation provenance check.", "citations": [
                            {"side": side, **locally_derived}],
                        "uncertainty_reasons": ["missing_evidence"], "abstain": False,
                    }]})
                except PolicyCandidateAdapterError:
                    _reject()
                citations.extend(checked["candidates"][0]["citations"])
                signature.append((side, passage_id, quote))
            if relation in _TWO_SIDED and sides != {"OLDER", "NEWER"}:
                _reject()
            if relation == "NEW_RULE" and sides != {"NEWER"}:
                _reject()
            proposal_signature = (relation, tuple(sorted(signature)))
            if proposal_signature in seen_proposals:
                _reject()
            seen_proposals.add(proposal_signature)
            canonical.append({
                "candidate_id": f"cand-syn-proposal-{index}",
                "proposed_relation": relation,
                "reasoning": reasoning,
                "citations": citations,
                "uncertainty_reasons": list(reasons),
                "abstain": abstain,
            })

        # Delegate the complete proposal contract and trusted metadata fields
        # to the existing adapter after deriving source references locally.
        return validate_candidate_response(pair, {"schema_version": 1, "candidates": canonical})
    except PolicyProposalContractError:
        raise
    except (PolicyCandidateAdapterError, PolicyCompareError, KeyError, TypeError,
            ValueError, RecursionError):
        _reject()
