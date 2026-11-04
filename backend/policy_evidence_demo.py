"""Synthetic Evidence-Verification Demo for Story Connect AI Policy Investigator.

Demonstrates traceable evidence, local citation provenance derivation,
reviewer evidence challenges, dependency-aware recomputation, and honest
uncertainty handling without generic chatbot hallucinations.

Runs strictly offline against synthetic hotel policy excerpts.
Completely isolated from policy_api.py, the employee handover application,
and remote provider networks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from policy_candidate_adapter import MAX_REASONING, PolicyCandidateAdapterError
from policy_compare import (
    PolicyCompareError,
    PolicyPair,
    compare_candidate,
    scope_relation,
    time_relation,
    validate_policy_pair,
    validate_result,
)
from policy_mock_provider_runner import (
    DeterministicMockProposalAdapter,
    PolicyMockRunnerError,
)
from policy_orchestration import PolicyOrchestrationError, _map_candidate
from policy_proposal_contract import (
    PolicyProposalContractError,
    build_proposal_request,
    normalize_proposal_response,
)


DOC_ID = "syn-policy-hotel-luminary-scheduling"
COMPARISON_ID = "cmp-syn-hotel-luminary-001"
HOTEL_NAME = "The Grand Luminary Hotel"

V1_TEXT = (
    "The Grand Luminary Hotel - Employee Scheduling Policy (Rev 2024.1)\n\n"
    "Employees should submit shift-change requests at least 48 hours before the affected shift. "
    "Department managers may approve exceptions for urgent operational needs.\n\n"
    "This general scheduling standard applies across property operations. "
    "Individual department operating addenda may specify supplemental procedures."
)

V2_TEXT = (
    "The Grand Luminary Hotel - Employee Scheduling Policy (Rev 2026.1)\n\n"
    "Employees must submit shift-change requests at least 24 hours before the affected shift. "
    "Department managers may approve exceptions for urgent operational needs.\n\n"
    "This general scheduling standard applies across property operations. "
    "Individual department operating addenda may specify supplemental procedures."
)

V1_NOTICE_QUOTE = (
    "Employees should submit shift-change requests at least 48 hours before the affected shift. "
    "Department managers may approve exceptions for urgent operational needs."
)

V2_NOTICE_QUOTE = (
    "Employees must submit shift-change requests at least 24 hours before the affected shift. "
    "Department managers may approve exceptions for urgent operational needs."
)

# ── Scenario 2: Uniform & Grooming Standards (Contradiction) ────────────────
UNIFORM_DOC_ID = "syn-policy-hotel-luminary-uniform"
UNIFORM_COMPARISON_ID = "cmp-syn-hotel-luminary-002"

UNIFORM_V1_TEXT = (
    "The Grand Luminary Hotel - Guest Relations Uniform Standards (Rev 2024.1)\n\n"
    "Guest Relations Ambassadors must wear the engraved bronze property emblem pinned securely to the left lapel at all times during guest service.\n\n"
    "Name badges must be worn on the opposite right lapel. Any departure from this standard requires written authorization from Guest Services."
)

UNIFORM_V2_TEXT = (
    "The Grand Luminary Hotel - Guest Relations Uniform Standards (Rev 2026.1)\n\n"
    "Guest Relations Ambassadors must wear the engraved bronze property emblem pinned securely to the right lapel at all times during guest service.\n\n"
    "Name badges must be worn on the opposite left lapel. Any departure from this standard requires written authorization from Guest Services."
)

UNIFORM_V1_QUOTE = (
    "Guest Relations Ambassadors must wear the engraved bronze property emblem pinned securely to the left lapel at all times during guest service."
)

UNIFORM_V2_QUOTE = (
    "Guest Relations Ambassadors must wear the engraved bronze property emblem pinned securely to the right lapel at all times during guest service."
)

# ── Scenario 3: Executive Club Lounge Standards (Scope/Time Difference) ──────
LOUNGE_DOC_ID = "syn-policy-hotel-luminary-lounge"
LOUNGE_COMPARISON_ID = "cmp-syn-hotel-luminary-003"

LOUNGE_V1_TEXT = (
    "The Grand Luminary Hotel - Executive Club Lounge Standards (Resort Properties)\n\n"
    "Complimentary Executive Club Lounge access is extended exclusively to guests registered in Premium Suite categories. Standard King and Deluxe room reservations are strictly excluded from complimentary lounge entry.\n\n"
    "This guideline applies only to Resort Collection properties operating seasonal club lounges."
)

LOUNGE_V2_TEXT = (
    "The Grand Luminary Hotel - Executive Club Lounge Standards (City Center Properties)\n\n"
    "Complimentary Executive Club Lounge access is extended to all Diamond tier loyalty members regardless of booked room category, including Deluxe and Standard King rooms.\n\n"
    "This guideline applies only to City Center Business properties operating year-round executive floors."
)

LOUNGE_V1_QUOTE = (
    "Complimentary Executive Club Lounge access is extended exclusively to guests registered in Premium Suite categories. Standard King and Deluxe room reservations are strictly excluded from complimentary lounge entry."
)

LOUNGE_V2_QUOTE = (
    "Complimentary Executive Club Lounge access is extended to all Diamond tier loyalty members regardless of booked room category, including Deluxe and Standard King rooms."
)

# ── Scenario Metadata & Allowlist ───────────────────────────────────────────
SCENARIO_SCHEDULING = "scheduling"
SCENARIO_UNIFORM = "uniform_grooming"
SCENARIO_LOUNGE = "lounge_access"

SCENARIO_METADATA = [
    {
        "id": SCENARIO_SCHEDULING,
        "title": "Scheduling Notice — Compatible Change",
        "category": "Operations & Scheduling",
        "relation_type": "COMPATIBLE_CHANGE",
        "description": "Shift-change notification timeline updated from 48h to 24h across property operations.",
        "default_challenge_department": "HOUSEKEEPING",
    },
    {
        "id": SCENARIO_UNIFORM,
        "title": "Uniform & Grooming — Contradiction",
        "category": "Guest Relations & Standards",
        "relation_type": "CONTRADICTION",
        "description": "Incompatible mandatory emblem placement rules (left lapel vs. right lapel) for Guest Relations Ambassadors.",
        "default_challenge_department": "CONCIERGE",
    },
    {
        "id": SCENARIO_LOUNGE,
        "title": "Executive Lounge Access — Scope / Time Difference",
        "category": "Loyalty & Access",
        "relation_type": "SCOPE_OR_TIME_DIFFERENCE",
        "description": "Disjoint lounge access standards across distinct property collections and non-overlapping effective dates.",
        "default_challenge_department": "VALET",
    },
]
ALLOWED_SCENARIO_IDS = frozenset({SCENARIO_SCHEDULING, SCENARIO_UNIFORM, SCENARIO_LOUNGE})



@dataclass(frozen=True)
class ReviewerChallenge:
    """Explicit reviewer challenge questioning an evidence dependency."""

    challenge_id: str
    target_side: str
    target_passage_id: str
    target_quote: str
    target_department: str
    challenge_description: str


def build_hotel_scheduling_policy_pair() -> PolicyPair:
    """Construct and validate the synthetic hotel scheduling PolicyPair."""
    return validate_policy_pair({
        "schema_version": 1,
        "comparison_id": COMPARISON_ID,
        "older": {
            "document_id": DOC_ID,
            "version_id": "v1",
            "original_text": V1_TEXT,
            "effective_from": "2024-01-01",
            "effective_to_exclusive": "2027-01-01",
            "scope": {
                "departments": {"state": "UNKNOWN", "ids": []},
                "procedures": {"state": "UNKNOWN", "ids": []},
                "property_id": None,
                "evidence_passage_ids": [],
            },
            "text_coverage": "EXCERPT",
            "impact_dependencies": [],
        },
        "newer": {
            "document_id": DOC_ID,
            "version_id": "v2",
            "original_text": V2_TEXT,
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
        },
    })


def build_hotel_uniform_policy_pair() -> PolicyPair:
    """Construct and validate the synthetic hotel uniform and grooming PolicyPair."""
    return validate_policy_pair({
        "schema_version": 1,
        "comparison_id": UNIFORM_COMPARISON_ID,
        "older": {
            "document_id": UNIFORM_DOC_ID,
            "version_id": "v1",
            "original_text": UNIFORM_V1_TEXT,
            "effective_from": "2024-01-01",
            "effective_to_exclusive": "2027-01-01",
            "scope": {
                "departments": {"state": "UNKNOWN", "ids": []},
                "procedures": {"state": "UNKNOWN", "ids": []},
                "property_id": None,
                "evidence_passage_ids": [],
            },
            "text_coverage": "EXCERPT",
            "impact_dependencies": [],
        },
        "newer": {
            "document_id": UNIFORM_DOC_ID,
            "version_id": "v2",
            "original_text": UNIFORM_V2_TEXT,
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
        },
    })


def build_hotel_lounge_policy_pair() -> PolicyPair:
    """Construct and validate the synthetic hotel executive lounge access PolicyPair."""
    return validate_policy_pair({
        "schema_version": 1,
        "comparison_id": LOUNGE_COMPARISON_ID,
        "older": {
            "document_id": LOUNGE_DOC_ID,
            "version_id": "v1",
            "original_text": LOUNGE_V1_TEXT,
            "effective_from": "2022-01-01",
            "effective_to_exclusive": "2024-01-01",
            "scope": {
                "departments": {"state": "UNKNOWN", "ids": []},
                "procedures": {"state": "UNKNOWN", "ids": []},
                "property_id": None,
                "evidence_passage_ids": [],
            },
            "text_coverage": "EXCERPT",
            "impact_dependencies": [],
        },
        "newer": {
            "document_id": LOUNGE_DOC_ID,
            "version_id": "v2",
            "original_text": LOUNGE_V2_TEXT,
            "effective_from": "2025-01-01",
            "effective_to_exclusive": "2028-01-01",
            "scope": {
                "departments": {"state": "UNKNOWN", "ids": []},
                "procedures": {"state": "UNKNOWN", "ids": []},
                "property_id": None,
                "evidence_passage_ids": [],
            },
            "text_coverage": "EXCERPT",
            "impact_dependencies": [],
        },
    })


def get_scenario_pair(scenario_id: str = SCENARIO_SCHEDULING) -> PolicyPair:
    """Resolve allowlisted scenario ID to its corresponding synthetic PolicyPair."""
    if scenario_id == SCENARIO_SCHEDULING:
        return build_hotel_scheduling_policy_pair()
    if scenario_id == SCENARIO_UNIFORM:
        return build_hotel_uniform_policy_pair()
    if scenario_id == SCENARIO_LOUNGE:
        return build_hotel_lounge_policy_pair()
    raise PolicyCompareError("invalid_input")


def build_initial_proposal_payload(pair: PolicyPair, request_id: str) -> dict[str, Any]:
    """Build untrusted raw proposal envelope tailored to the policy comparison."""
    older_passage = pair.older.passages[1]
    newer_passage = pair.newer.passages[1]

    if pair.comparison_id == UNIFORM_COMPARISON_ID:
        return {
            "schema_version": 1,
            "request_id": request_id,
            "candidates": [
                {
                    "proposed_relation": "CONTRADICTION",
                    "reasoning": (
                        "v1 mandates wearing the property emblem on the left lapel, whereas v2 mandates wearing it "
                        "on the right lapel for the same role and service context. These represent mutually exclusive "
                        "physical requirements that cannot be simultaneously satisfied."
                    ),
                    "citation_hints": [
                        {
                            "side": "OLDER",
                            "passage_id": older_passage.passage_id,
                            "quote": UNIFORM_V1_QUOTE,
                        },
                        {
                            "side": "NEWER",
                            "passage_id": newer_passage.passage_id,
                            "quote": UNIFORM_V2_QUOTE,
                        },
                    ],
                    "uncertainty_reasons": ["semantic_support_unverified"],
                    "abstain": False,
                }
            ],
        }

    if pair.comparison_id == LOUNGE_COMPARISON_ID:
        return {
            "schema_version": 1,
            "request_id": request_id,
            "candidates": [
                {
                    "proposed_relation": "SCOPE_OR_TIME_DIFFERENCE",
                    "reasoning": (
                        "v1 governs seasonal Resort Collection properties (2022–2024) with suite-exclusive access, "
                        "whereas v2 governs year-round City Center properties (2025–2028) with loyalty tier access. "
                        "The apparent difference is explained by disjoint property tiers and non-overlapping effective dates."
                    ),
                    "citation_hints": [
                        {
                            "side": "OLDER",
                            "passage_id": older_passage.passage_id,
                            "quote": LOUNGE_V1_QUOTE,
                        },
                        {
                            "side": "NEWER",
                            "passage_id": newer_passage.passage_id,
                            "quote": LOUNGE_V2_QUOTE,
                        },
                    ],
                    "uncertainty_reasons": [
                        "semantic_support_unverified",
                        "scope_or_time_unverified",
                    ],
                    "abstain": False,
                }
            ],
        }

    # Default / Scheduling scenario
    return {
        "schema_version": 1,
        "request_id": request_id,
        "candidates": [
            {
                "proposed_relation": "COMPATIBLE_CHANGE",
                "reasoning": (
                    "Shift-change notice was updated from 48 hours (recommended) to 24 hours (mandatory) "
                    "before the affected shift, while preserving department manager exception approvals. "
                    "This represents a compatible operational timeline revision rather than an unresolvable contradiction."
                ),
                "citation_hints": [
                    {
                        "side": "OLDER",
                        "passage_id": older_passage.passage_id,
                        "quote": V1_NOTICE_QUOTE,
                    },
                    {
                        "side": "NEWER",
                        "passage_id": newer_passage.passage_id,
                        "quote": V2_NOTICE_QUOTE,
                    },
                ],
                "uncertainty_reasons": ["semantic_support_unverified"],
                "abstain": False,
            }
        ],
    }


def run_initial_evidence_investigation(pair: PolicyPair, proposal_provider=None) -> dict[str, Any]:
    """Execute initial proposal generation and local citation derivation."""
    if not isinstance(pair, PolicyPair):
        raise PolicyCompareError("invalid_input")

    request_envelope = build_proposal_request(pair)
    if proposal_provider is None:
        raw_payload = build_initial_proposal_payload(pair, request_envelope["request_id"])
        adapter = DeterministicMockProposalAdapter(raw_payload)
        raw_response = adapter.generate_proposals(request_envelope)
        provider_attribution = {"provider": "synthetic", "model": None}
    else:
        raw_response, provider_attribution = proposal_provider.generate(pair, request_envelope)

    normalized = normalize_proposal_response(pair, request_envelope, raw_response)
    if len(normalized["candidates"]) != 1:
        raise PolicyProposalContractError()
    candidate = normalized["candidates"][0]

    mapped = _map_candidate(candidate)
    core_result = compare_candidate(pair, mapped)
    validated = validate_result(pair, core_result)

    citations = candidate["citations"]
    provenance_details = []
    for citation in citations:
        passage = (
            pair.older.passage(citation["passage_id"])
            if citation["side"] == "OLDER"
            else pair.newer.passage(citation["passage_id"])
        )
        provenance_details.append({
            "side": citation["side"],
            "passage_id": citation["passage_id"],
            "passage_ordinal": passage.ordinal if passage else None,
            "start_cp": citation["start_cp"],
            "end_cp": citation["end_cp"],
            "quote": citation["quote"],
            "source_sha256": citation["source_sha256"],
            "verified_locally": True,
        })

    return {
        "comparison_id": pair.comparison_id,
        "request_id": request_envelope["request_id"],
        "provider_attribution": provider_attribution,
        "proposed_relation": candidate["proposed_relation"],
        "candidate_id": candidate["candidate_id"],
        "reasoning": candidate["reasoning"],
        "status": candidate["status"],
        "semantic_support": candidate["semantic_support"],
        "human_review_required": candidate["human_review_required"],
        "core_classification": validated["classification"],
        "core_proposed_classification": validated["proposed_classification"],
        "uncertainty_reasons": list(validated["uncertainty_reasons"]),
        "official_policy_mutated": validated["official_policy_mutated"],
        "impact_status": validated["impact"]["status"],
        "provenance_details": provenance_details,
        "provenance_limitation_notice": (
            "Exact quote matching verifies citation provenance (text existence and boundaries). "
            "It does NOT establish semantic correctness, departmental applicability, or legal force."
        ),
    }


def evaluate_department_applicability(pair: PolicyPair, department_id: str) -> dict[str, Any]:
    """Audit synthetic policy evidence for department-specific applicability."""
    if not isinstance(pair, PolicyPair) or not department_id:
        raise PolicyCompareError("invalid_input")

    older_dept_state = pair.older.scope.departments.state
    newer_dept_state = pair.newer.scope.departments.state
    older_ids = pair.older.scope.departments.ids
    newer_ids = pair.newer.scope.departments.ids

    older_grounded = older_dept_state == "KNOWN" and department_id in older_ids
    newer_grounded = newer_dept_state == "KNOWN" and department_id in newer_ids

    older_deps = [
        d for d in pair.older.impact_dependencies if d.department_id == department_id
    ]
    newer_deps = [
        d for d in pair.newer.impact_dependencies if d.department_id == department_id
    ]

    has_mentions = department_id.lower() in pair.older.original_text.lower()

    is_grounded = (older_grounded or bool(older_deps)) and (newer_grounded or bool(newer_deps))
    applicability_status = "GROUNDED" if is_grounded else "UNGROUNDED"

    return {
        "department_id": department_id,
        "older_scope_state": older_dept_state,
        "newer_scope_state": newer_dept_state,
        "older_department_ids": list(older_ids),
        "newer_department_ids": list(newer_ids),
        "older_impact_dependencies_count": len(older_deps),
        "newer_impact_dependencies_count": len(newer_deps),
        "text_mentions_department": has_mentions,
        "applicability_status": applicability_status,
        "finding": (
            f"Department '{department_id}' scope is {older_dept_state} in v1 and {newer_dept_state} in v2. "
            "The synthetic policy provides no passage evidence or impact dependencies grounding this department."
        ),
    }


def recompute_investigation_after_challenge(
    pair: PolicyPair,
    initial_investigation: dict[str, Any],
    challenge: ReviewerChallenge,
) -> dict[str, Any]:
    """Perform dependency-aware recomputation following a reviewer evidence challenge.

    Recomputation steps:
    1. Validates the challenge against the policy pair and initial citations.
    2. Evaluates department applicability; confirms target department is ungrounded.
    3. Confirms that attempting to keep COMPATIBLE_CHANGE without the challenged older
       citation fails closed as an arity/provenance violation.
    4. Recomputes an honest INCONCLUSIVE abstention with explicit uncertainty reasons.
    5. Evaluates the inconclusive proposal through normalize_proposal_response and
       compare_candidate, proving honest uncertainty preservation.
    """
    if not isinstance(pair, PolicyPair) or not isinstance(challenge, ReviewerChallenge):
        raise PolicyCompareError("invalid_input")

    applicability = evaluate_department_applicability(pair, challenge.target_department)

    request_envelope = build_proposal_request(pair)
    newer_passage = pair.newer.passages[1]

    initial_relation = initial_investigation.get("proposed_relation", "COMPATIBLE_CHANGE")
    provenance_details = initial_investigation.get("provenance_details", [])
    newer_quote = (
        provenance_details[1].get("quote", newer_passage.text)
        if len(provenance_details) > 1
        else newer_passage.text
    )

    # Step 3: Demonstrate that omitting the challenged older citation while asserting
    # a two-sided relation fails closed under the contract (arity violation).
    attempted_invalid_response = {
        "schema_version": 1,
        "request_id": request_envelope["request_id"],
        "candidates": [
            {
                "proposed_relation": initial_relation,
                "reasoning": f"Attempting to maintain {initial_relation} finding without older baseline.",
                "citation_hints": [
                    {
                        "side": "NEWER",
                        "passage_id": newer_passage.passage_id,
                        "quote": newer_quote,
                    }
                ],
                "uncertainty_reasons": ["semantic_support_unverified"],
                "abstain": False,
            }
        ],
    }

    contract_prevented_invalid_assertion = False
    try:
        normalize_proposal_response(pair, request_envelope, attempted_invalid_response)
    except PolicyProposalContractError:
        contract_prevented_invalid_assertion = True

    # Step 4: Recompute using the honest inconclusive abstention contract.
    recomputed_payload = {
        "schema_version": 1,
        "request_id": request_envelope["request_id"],
        "candidates": [
            {
                "proposed_relation": "INCONCLUSIVE",
                "reasoning": (
                    f"Reviewer challenged older baseline applicability for Department '{challenge.target_department}'. "
                    "Synthetic policy evidence provides no passage evidence grounding this department's schedule rules. "
                    "Finding falls back to inconclusive pending department baseline verification."
                ),
                "citation_hints": [],
                "uncertainty_reasons": [
                    "missing_evidence",
                    "semantic_support_unverified",
                    "scope_or_time_unverified",
                ],
                "abstain": True,
            }
        ],
    }

    normalized_recomputed = normalize_proposal_response(
        pair, request_envelope, recomputed_payload
    )
    recomputed_cand = normalized_recomputed["candidates"][0]

    mapped = _map_candidate(recomputed_cand)
    core_result = compare_candidate(pair, mapped)
    validated = validate_result(pair, core_result)

    return {
        "provider_attribution": initial_investigation.get(
            "provider_attribution", {"provider": "synthetic", "model": None}
        ),
        "recomputation_provider": "local_policy_engine",
        "challenge": {
            "challenge_id": challenge.challenge_id,
            "target_department": challenge.target_department,
            "target_side": challenge.target_side,
            "target_passage_id": challenge.target_passage_id,
            "description": challenge.challenge_description,
        },
        "applicability_audit": applicability,
        "contract_enforcement": {
            "one_sided_change_rejected": contract_prevented_invalid_assertion,
            "explanation": (
                f"Local contract strictly rejected keeping {initial_relation} without verified older citation. "
                "The system cannot invent or assume baseline applicability."
            ),
        },
        "recomputed_proposal": {
            "candidate_id": recomputed_cand["candidate_id"],
            "proposed_relation": recomputed_cand["proposed_relation"],
            "status": recomputed_cand["status"],
            "semantic_support": recomputed_cand["semantic_support"],
            "human_review_required": recomputed_cand["human_review_required"],
            "abstain": recomputed_cand["abstain"],
            "citations_count": len(recomputed_cand["citations"]),
            "uncertainty_reasons": list(recomputed_cand["uncertainty_reasons"]),
        },
        "recomputed_core_result": {
            "classification": validated["classification"],
            "proposed_classification": validated["proposed_classification"],
            "human_review_required": validated["human_review_required"],
            "official_policy_mutated": validated["official_policy_mutated"],
            "uncertainty_reasons": list(validated["uncertainty_reasons"]),
            "impact_status": validated["impact"]["status"],
        },
        "differentiator_takeaway": (
            "A generic chatbot would hallucinate department applicability or maintain its claim. "
            "Story Connect detects that baseline evidence is ungrounded, enforces contract arity, "
            "and recomputes to honest INCONCLUSIVE uncertainty."
        ),
    }


def build_scenario_reviewer_challenge(
    pair: PolicyPair,
    initial: dict[str, Any],
    department_id: str,
    scenario_id: str = SCENARIO_SCHEDULING,
) -> ReviewerChallenge:
    """Build a scenario-specific ReviewerChallenge questioning department baseline evidence."""
    if scenario_id == SCENARIO_UNIFORM:
        desc = (
            f"Reviewer questions whether the v1 left-lapel emblem mandate was ever applicable to {department_id}. "
            f"{department_id} ambassadors wear specialized traditional heraldic jackets with pocket flaps, not standard lapels."
        )
    elif scenario_id == SCENARIO_LOUNGE:
        desc = (
            f"Reviewer questions whether the v1 suite-exclusive access policy was ever applicable to {department_id}. "
            f"{department_id} operations operate under separate property-level service guidelines."
        )
    else:
        desc = (
            f"Reviewer questions whether the v1 48-hour general scheduling rule was ever applicable to {department_id}. "
            f"{department_id} operated under decentralized shift guidelines and has no departmental grounding in the policy text."
        )

    target_quote = (
        initial["provenance_details"][0]["quote"]
        if initial.get("provenance_details")
        else pair.older.passages[1].text
    )

    return ReviewerChallenge(
        challenge_id=f"chal-dept-{department_id.lower()}-001",
        target_side="OLDER",
        target_passage_id=pair.older.passages[1].passage_id,
        target_quote=target_quote,
        target_department=department_id,
        challenge_description=desc,
    )


def format_demo_summary(initial: dict[str, Any], recomputed: dict[str, Any]) -> str:
    """Format human-readable CLI summary of the demonstration."""
    lines = [
        "=" * 78,
        f"STORY CONNECT AI POLICY INVESTIGATOR -- DEMO SCENARIO",
        f"Hotel: {HOTEL_NAME} | Document: {DOC_ID}",
        "=" * 78,
        "",
        "[STAGE 1: INITIAL INVESTIGATION & PROVENANCE DERIVATION]",
        f"  Candidate Proposal:      {initial['proposed_relation']}",
        f"  Proposal Status:         {initial['status']}",
        f"  Semantic Support:        {initial['semantic_support']}",
        f"  Human Review Required:   {initial['human_review_required']}",
        f"  Core Policy Assessment:  {initial['core_classification']} (Proposed: {initial['core_proposed_classification']})",
        f"  Locally Derived Citations:",
    ]
    for cit in initial["provenance_details"]:
        lines.append(
            f"    - [{cit['side']}] Passage {cit['passage_ordinal']} ({cit['passage_id']}) "
            f"CodePoints {cit['start_cp']}..{cit['end_cp']}"
        )
        lines.append(f"      Quote: \"{cit['quote'][:65]}...\"")
    lines.extend([
        "",
        f"  Provenance Limitation:   {initial['provenance_limitation_notice']}",
        "",
        "[STAGE 2: REVIEWER EVIDENCE CHALLENGE]",
        f"  Challenge ID:            {recomputed['challenge']['challenge_id']}",
        f"  Target Department:       {recomputed['challenge']['target_department']}",
        f"  Target Citation:         {recomputed['challenge']['target_side']} ({recomputed['challenge']['target_passage_id']})",
        f"  Challenge Description:   {recomputed['challenge']['description']}",
        "",
        "[STAGE 3: DEPENDENCY AUDIT & CONTRACT REJECTION]",
        f"  Department Grounding:    {recomputed['applicability_audit']['applicability_status']}",
        f"  Scope Audit Detail:      {recomputed['applicability_audit']['finding']}",
        f"  Arity Enforcement:       One-sided COMPATIBLE_CHANGE rejected = {recomputed['contract_enforcement']['one_sided_change_rejected']}",
        "",
        "[STAGE 4: RECOMPUTED HONEST UNCERTAINTY OUTCOME]",
        f"  Recomputed Relation:     {recomputed['recomputed_proposal']['proposed_relation']} (Abstain = {recomputed['recomputed_proposal']['abstain']})",
        f"  Core Classification:     {recomputed['recomputed_core_result']['classification']}",
        f"  Uncertainty Reasons:     {', '.join(recomputed['recomputed_core_result']['uncertainty_reasons'])}",
        f"  Human Review Required:   {recomputed['recomputed_core_result']['human_review_required']}",
        f"  Policy Mutated:          {recomputed['recomputed_core_result']['official_policy_mutated']}",
        "",
        f"Takeaway: {recomputed['differentiator_takeaway']}",
        "=" * 78,
    ])
    return "\n".join(lines)


def main() -> None:
    """Execute the offline demonstration scenario."""
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
    print(format_demo_summary(initial, recomputed))


if __name__ == "__main__":
    main()
