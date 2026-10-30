"""Isolated mock-only provider boundary prototype for policy proposals.

This module provides an offline-only runner that exercises the proposed
provider-neutral policy proposal boundary using a deterministic fake adapter.
It is NOT imported or invoked by the active policy API route (policy_api.py).
It has no network transports, HTTP clients, credentials, or remote endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from policy_candidate_adapter import PolicyCandidateAdapterError
from policy_compare import (
    PolicyCompareError,
    PolicyPair,
    compare_candidate,
    validate_policy_pair,
    validate_result,
)
from policy_orchestration import PolicyOrchestrationError, _map_candidate
from policy_proposal_contract import (
    PolicyProposalContractError,
    build_proposal_request,
    normalize_proposal_response,
)


class PolicyMockRunnerError(ValueError):
    """Sanitized error for mock-only policy proposal pipeline failures."""

    _MESSAGES = {
        "invalid_policy_pair": "Policy comparison input is invalid.",
        "invalid_adapter": "Policy proposal adapter is invalid or missing.",
        "invalid_request": "Policy proposal request could not be constructed.",
        "invalid_proposal": "Policy comparison proposal is invalid.",
        "contract_mismatch": "Policy comparison proposal cannot be mapped safely.",
        "pipeline_failure": "Policy comparison proposal pipeline could not be completed.",
    }

    def __init__(self, code: str) -> None:
        if code not in self._MESSAGES:
            code = "pipeline_failure"
        self.code = code
        super().__init__(self._MESSAGES[code])


@dataclass(frozen=True)
class DeterministicMockProposalAdapter:
    """Offline, in-memory fake adapter implementing the provider seam.

    Returns a fixed or dynamically generated response payload in the exact
    shape expected by policy_proposal_contract.normalize_proposal_response.
    Has no network capability, credentials, or remote dispatch.
    """

    response_payload: Any
    provider_id: str = "mock-proposal-provider"
    model_version: str = "synthetic-mock-v1"

    def generate_proposals(self, request_envelope: dict[str, Any]) -> Any:
        if callable(self.response_payload):
            return self.response_payload(request_envelope)
        return self.response_payload


def make_synthetic_policy_pair(
    older_text: str = "Front Office records guest requests before shift end.\n\nKeep the log complete.",
    newer_text: str = "Front Office records guest requests at shift start.\n\nKeep the log complete.",
    comparison_id: str = "cmp-syn-mock-001",
) -> PolicyPair:
    """Construct and validate a frozen synthetic PolicyPair for offline testing."""

    def make_version(version_id: str, text: str) -> dict[str, Any]:
        return {
            "document_id": "syn-policy-doc-001",
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

    return validate_policy_pair({
        "schema_version": 1,
        "comparison_id": comparison_id,
        "older": make_version("v1", older_text),
        "newer": make_version("v2", newer_text),
    })


def run_mock_policy_proposal_pipeline(
    pair_input: Any,
    adapter: DeterministicMockProposalAdapter,
) -> dict[str, Any]:
    """Execute the offline proposal contract seam using a deterministic fake adapter.

    End-to-end offline flow:
    1. Validates input pair (validate_policy_pair).
    2. Builds canonical bounded proposal request (build_proposal_request).
    3. Invokes deterministic mock adapter (adapter.generate_proposals).
    4. Normalizes untrusted response and derives source citation provenance
       locally (normalize_proposal_response).
    5. Maps candidates to policy core inputs (_map_candidate).
    6. Runs core candidate comparison (compare_candidate) and validates
       the result envelope (validate_result).
    7. Returns normalized results maintaining proposal-only status,
       unverified semantic support, and human-review requirement.

    Fails closed on any contract violation, malformed response, or invalid quote.
    """
    if type(adapter) is not DeterministicMockProposalAdapter:
        raise PolicyMockRunnerError("invalid_adapter")

    if isinstance(pair_input, PolicyPair):
        pair = pair_input
    elif isinstance(pair_input, dict):
        try:
            pair = validate_policy_pair(pair_input)
        except (PolicyCompareError, TypeError, ValueError):
            raise PolicyMockRunnerError("invalid_policy_pair") from None
    else:
        raise PolicyMockRunnerError("invalid_policy_pair")

    try:
        request_envelope = build_proposal_request(pair)
    except (PolicyProposalContractError, TypeError, ValueError):
        raise PolicyMockRunnerError("invalid_request") from None

    try:
        raw_response = adapter.generate_proposals(request_envelope)
    except Exception:
        raise PolicyMockRunnerError("invalid_proposal") from None

    try:
        normalized_proposals = normalize_proposal_response(
            pair, request_envelope, raw_response
        )
    except (PolicyProposalContractError, PolicyCandidateAdapterError, TypeError, ValueError):
        raise PolicyMockRunnerError("invalid_proposal") from None

    results: list[dict[str, Any]] = []
    try:
        for proposal in normalized_proposals["candidates"]:
            mapped = _map_candidate(proposal)
            core_result = compare_candidate(pair, mapped)
            validated = validate_result(pair, core_result)
            results.append({
                **validated,
                "proposal_status": proposal["status"],
                "proposal_semantic_support": proposal["semantic_support"],
                "proposal_uncertainty_reasons": list(proposal["uncertainty_reasons"]),
            })
    except PolicyOrchestrationError:
        raise PolicyMockRunnerError("contract_mismatch") from None
    except (PolicyCompareError, KeyError, TypeError, ValueError):
        raise PolicyMockRunnerError("contract_mismatch") from None
    except Exception:
        raise PolicyMockRunnerError("pipeline_failure") from None

    return {
        "schema_version": 1,
        "comparison_id": pair.comparison_id,
        "results": results,
    }
