"""Pure offline orchestration for synthetic policy comparison proposals.

This module connects the fixture-backed candidate adapter to the policy core.
It performs source-provenance validation only; it does not establish semantic
support, precedence, complete coverage, or operational impact.
"""
from __future__ import annotations

from typing import Any

from policy_candidate_adapter import (
    FakePolicyCandidateAdapter,
    generate_from_fake,
)
from policy_compare import (
    PolicyCompareError,
    PolicyPair,
    compare_candidate,
    validate_policy_pair,
    validate_result,
)


class PolicyOrchestrationError(ValueError):
    """Fixed, sanitized orchestration error."""

    _MESSAGES = {
        "invalid_policy_pair": "Policy comparison input is invalid.",
        "invalid_proposal": "Policy comparison proposal is invalid.",
        "contract_mismatch": "Policy comparison proposal cannot be mapped safely.",
        "orchestration_failure": "Policy comparison could not be completed.",
    }

    def __init__(self, code: str) -> None:
        if code not in self._MESSAGES:
            code = "orchestration_failure"
        self.code = code
        super().__init__(self._MESSAGES[code])


def _requirement(candidate: dict[str, Any], side: str) -> dict[str, Any] | None:
    citations = [item for item in candidate["citations"] if item["side"] == side]
    if not citations:
        return None
    if len(citations) != 1:
        raise PolicyOrchestrationError("contract_mismatch")
    citation = citations[0]
    source_citation = {key: value for key, value in citation.items() if key != "side"}
    return {
        "text": citation["quote"],
        "support": "INSUFFICIENT",
        "citations": [source_citation],
    }


def _map_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Map validated proposal fields to the core's stricter input shape."""
    relation = candidate["proposed_relation"]
    older = _requirement(candidate, "OLDER")
    newer = _requirement(candidate, "NEWER")

    # NEW_RULE has a one-sided core contract. Reject, rather than discard,
    # unexpected old-side provenance or invent a comparison baseline.
    if relation == "NEW_RULE" and (older is not None or newer is None):
        raise PolicyOrchestrationError("contract_mismatch")

    return {
        "candidate_id": candidate["candidate_id"],
        "classification": relation,
        "summary": candidate["reasoning"],
        "older_requirement": older,
        "newer_requirement": newer,
        # These values are local conservative constants, never model claims.
        "comparison_coverage": "INCOMPLETE",
        "precedence": {
            "status": "UNRESOLVED",
            "support": "INSUFFICIENT",
            "citations": [],
        },
        "impact_coverage": "INCOMPLETE",
        "impact_targets": [],
        "resolution_draft": None,
    }


def orchestrate_policy_comparison(
    pair_input: Any,
    adapter: FakePolicyCandidateAdapter,
) -> dict[str, Any]:
    """Validate a pair, run the exact fixture fake, and normalize proposals.

    The adapter argument is intentionally restricted by ``generate_from_fake``
    to the exact fixture-backed fake type. This is an application boundary,
    not a same-process security sandbox.
    """
    try:
        pair: PolicyPair = validate_policy_pair(pair_input)
    except Exception:
        raise PolicyOrchestrationError("invalid_policy_pair") from None

    try:
        proposals = generate_from_fake(adapter, pair)
    except Exception:
        raise PolicyOrchestrationError("invalid_proposal") from None

    results: list[dict[str, Any]] = []
    try:
        for proposal in proposals["candidates"]:
            mapped = _map_candidate(proposal)
            result = compare_candidate(pair, mapped)
            normalized = validate_result(pair, result)
            # Keep adapter uncertainty visible as proposal metadata. It is
            # separate from the core's locally derived uncertainty reasons.
            results.append({
                **normalized,
                "proposal_status": proposal["status"],
                "proposal_semantic_support": proposal["semantic_support"],
                "proposal_uncertainty_reasons": list(proposal["uncertainty_reasons"]),
            })
    except PolicyOrchestrationError:
        raise
    except (PolicyCompareError, KeyError, TypeError, ValueError):
        raise PolicyOrchestrationError("contract_mismatch") from None
    except Exception:
        raise PolicyOrchestrationError("orchestration_failure") from None

    return {
        "schema_version": 1,
        "comparison_id": pair.comparison_id,
        "results": results,
    }
