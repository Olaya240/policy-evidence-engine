"""Advisory-only evidence coverage for the fixed Story Connect hypotheses.

Coverage describes what is present in a claim's evidence. It does not validate
evidence, calculate claim status, or define evidence sufficiency.
"""
from __future__ import annotations

from .models import Evidence, EvidenceReviewState, HYPOTHESES, Stance


# Association is deliberately limited to the engine's persisted semantic
# relation. It is separate from stance and review state, and it may be absent
# for legacy or intentionally unguarded evidence.
_HYPOTHESIS_CATEGORIES = {
    "CHECKLIST_UNAVAILABLE": (
        {
            "id": "checklist_access_context",
            "description": "checklist or binder availability during handover",
            "role": "PRIMARY",
            "relations": (Stance.SUPPORTS, Stance.CONTRADICTS),
            "indicators": ("semantic_relation=SUPPORTS", "semantic_relation=CONTRADICTS"),
            "limitation": "A phrase-level relation does not establish cause or completeness.",
        },
        {
            "id": "independent_checklist_support",
            "description": "independent supporting evidence about checklist availability",
            "role": "CORROBORATION",
            "relations": (Stance.SUPPORTS,),
            "indicators": ("semantic_relation=SUPPORTS", "distinct source_group (or source_record_id fallback)"),
            "limitation": "Source-group independence is advisory and does not define sufficiency.",
        },
    ),
    "TRAINING_GAP": (
        {
            "id": "handover_guidance_context",
            "description": "guidance or task-understanding context for handover",
            "role": "PRIMARY",
            "relations": (Stance.SUPPORTS, Stance.CONTRADICTS),
            "indicators": ("semantic_relation=SUPPORTS", "semantic_relation=CONTRADICTS"),
            "limitation": "The current phrase inventory is narrow and does not assess proficiency generally.",
        },
        {
            "id": "independent_guidance_support",
            "description": "independent supporting evidence about handover guidance needs",
            "role": "CORROBORATION",
            "relations": (Stance.SUPPORTS,),
            "indicators": ("semantic_relation=SUPPORTS", "distinct source_group (or source_record_id fallback)"),
            "limitation": "No training-specific corroboration requirement is established.",
        },
    ),
    "STAFFING_CONSTRAINTS": (
        {
            "id": "handover_coverage_context",
            "description": "staffing or desk-coverage context during handover",
            "role": "PRIMARY",
            "relations": (Stance.SUPPORTS, Stance.CONTRADICTS),
            "indicators": ("semantic_relation=SUPPORTS", "semantic_relation=CONTRADICTS"),
            "limitation": "A phrase-level relation does not establish operational impact.",
        },
        {
            "id": "independent_coverage_support",
            "description": "independent supporting evidence about handover coverage",
            "role": "CORROBORATION",
            "relations": (Stance.SUPPORTS,),
            "indicators": ("semantic_relation=SUPPORTS", "distinct source_group (or source_record_id fallback)"),
            "limitation": "A copied recap in the same source group is not independent.",
        },
    ),
    "PMS_SYSTEM_ISSUE": (
        {
            "id": "handover_system_context",
            "description": "property-system availability or interruption during handover",
            "role": "PRIMARY",
            "relations": (Stance.SUPPORTS, Stance.CONTRADICTS),
            "indicators": ("semantic_relation=SUPPORTS", "semantic_relation=CONTRADICTS"),
            "limitation": "The current cues do not define which systems or incidents qualify as PMS issues.",
        },
        {
            "id": "independent_system_support",
            "description": "independent supporting evidence about a handover system interruption",
            "role": "CORROBORATION",
            "relations": (Stance.SUPPORTS,),
            "indicators": ("semantic_relation=SUPPORTS", "distinct source_group (or source_record_id fallback)"),
            "limitation": "The seed fixture has no explicit independent corroborating system record.",
        },
    ),
    "TIME_PRESSURE": (
        {
            "id": "review_time_context",
            "description": "available time to review open handover items",
            "role": "PRIMARY",
            "relations": (Stance.SUPPORTS, Stance.CONTRADICTS),
            "indicators": ("semantic_relation=SUPPORTS", "semantic_relation=CONTRADICTS"),
            "limitation": "Workload and staffing mentions alone are not treated as time-pressure matches.",
        },
        {
            "id": "independent_time_support",
            "description": "independent supporting evidence about insufficient review time",
            "role": "CORROBORATION",
            "relations": (Stance.SUPPORTS,),
            "indicators": ("semantic_relation=SUPPORTS", "distinct source_group (or source_record_id fallback)"),
            "limitation": "No time-pressure-specific corroboration requirement is established.",
        },
    ),
}

_KNOWN_HYPOTHESES = frozenset(item.id for item in HYPOTHESES)


def evidence_coverage(hypothesis_id: str, evidence: list[Evidence]) -> dict:
    """Return deterministic advisory coverage without mutating evidence.

    Category associations use only ``semantic_relation`` on the evidence for
    the already-selected hypothesis. Missing relation metadata is surfaced as
    unclassified evidence rather than guessed from quote text or stance.
    """
    if type(hypothesis_id) is not str or hypothesis_id not in _KNOWN_HYPOTHESES:
        raise ValueError("Unknown hypothesis")
    if type(evidence) is not list or any(not isinstance(item, Evidence) for item in evidence):
        raise TypeError("Evidence coverage requires a list of Evidence objects")

    categories = []
    for definition in _HYPOTHESIS_CATEGORIES[hypothesis_id]:
        relevant = [
            item for item in evidence
            if item.semantic_relation in definition["relations"]
        ]
        neutral = [item for item in evidence if item.semantic_relation == Stance.NEUTRAL]
        unclassified = [item for item in evidence if item.semantic_relation is None]
        fresh_accepted = [
            item for item in relevant
            if item.review_state == EvidenceReviewState.ACCEPTED and not item.stale and not item.disputed
        ]
        fresh_support = [item for item in fresh_accepted if item.semantic_relation == Stance.SUPPORTS]
        fresh_contradiction = [item for item in fresh_accepted if item.semantic_relation == Stance.CONTRADICTS]
        source_groups = sorted({item.source_group or item.source_record_id for item in fresh_accepted})
        if definition["role"] == "CORROBORATION":
            covered = len(source_groups) >= 2
            non_independent = bool(fresh_accepted) and not covered
        else:
            covered = bool(fresh_accepted)
            non_independent = False

        categories.append({
            "category_id": definition["id"],
            "description": definition["description"],
            "role": definition["role"],
            "association": "semantic_relation",
            "indicators": list(definition["indicators"]),
            "limitation": definition["limitation"],
            "covered_by_fresh_accepted": covered,
            "non_independent": non_independent,
            "fresh_accepted_support_ids": sorted({item.source_record_id for item in fresh_support}),
            "fresh_accepted_contradiction_ids": sorted({item.source_record_id for item in fresh_contradiction}),
            "independent_source_groups": source_groups,
            "matching_evidence": [
                {
                    "source_record_id": item.source_record_id,
                    "review_state": item.review_state.value,
                    "stale": item.stale,
                    "disputed": item.disputed,
                    "source_group": item.source_group or item.source_record_id,
                }
                for item in relevant
            ],
            "neutral_evidence_ids": sorted({item.source_record_id for item in neutral}),
            "unclassified_evidence_ids": sorted({item.source_record_id for item in unclassified}),
        })
    return {"hypothesis_id": hypothesis_id, "categories": categories}


def advisory_missing_evidence(hypothesis_id: str, evidence: list[Evidence]) -> list[str]:
    """Create concise follow-up prompts from advisory coverage only."""
    coverage = evidence_coverage(hypothesis_id, evidence)
    prompts = []
    for category in coverage["categories"]:
        description = category["description"]
        matches = category["matching_evidence"]
        fresh = [item for item in matches if item["review_state"] == "ACCEPTED" and not item["stale"] and not item["disputed"]]
        unverified = sorted({item["source_record_id"] for item in matches if item["review_state"] == "UNVERIFIED"})
        stale = sorted({item["source_record_id"] for item in matches if item["stale"]})
        disputed = sorted({item["source_record_id"] for item in matches if item["disputed"]})
        if unverified:
            prompts.append(f"Review unverified evidence ({', '.join(unverified)}) about {description}.")
        if stale:
            prompts.append(f"Seek current evidence about {description}; matching evidence is stale ({', '.join(stale)}).")
        if disputed:
            prompts.append(f"Review challenged evidence ({', '.join(disputed)}) about {description}.")

        if category["role"] == "CORROBORATION":
            if category["non_independent"]:
                groups = ", ".join(category["independent_source_groups"])
                prompts.append(f"Consider an independent corroborating source for {description}; current fresh accepted support is limited to source group {groups}.")
            continue

        if category["covered_by_fresh_accepted"]:
            if (category["fresh_accepted_contradiction_ids"]
                    and not category["fresh_accepted_support_ids"]):
                ids = ", ".join(category["fresh_accepted_contradiction_ids"])
                prompts.append(f"Current reviewed evidence ({ids}) points against {description}; review the specific operational incidents or alternative explanations.")
            continue
        if not matches and not unverified and not stale and not disputed:
            neutral = category["neutral_evidence_ids"]
            unclassified = category["unclassified_evidence_ids"]
            if neutral:
                prompts.append(f"Only neutral evidence ({', '.join(neutral)}) is classified for {description}; review whether a direct record is available.")
            elif unclassified:
                prompts.append(f"Evidence ({', '.join(unclassified)}) lacks a reviewed relation to {description}; review its relevance.")
            else:
                prompts.append(f"No matching reviewed evidence is identified for {description}; consider a recent direct record.")
    return prompts
