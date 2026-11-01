"""Pure tests for advisory-only hypothesis evidence coverage."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.evidence_coverage import advisory_missing_evidence, evidence_coverage
from app.models import Evidence, EvidenceReviewState, HYPOTHESES, Stance


def evidence(source_id, *, relation=Stance.SUPPORTS, state=EvidenceReviewState.ACCEPTED,
             stale=False, disputed=False, group=None):
    return Evidence(
        source_record_id=source_id,
        timestamp=datetime(2026, 10, 1, tzinfo=timezone.utc),
        quote=f"synthetic quote {source_id}",
        stance=relation,
        semantic_relation=relation,
        review_state=state,
        rationale="coverage fixture",
        stale=stale,
        department="Front Office",
        source_group=group,
        disputed=disputed,
    )


@pytest.mark.parametrize("hypothesis", HYPOTHESES, ids=lambda item: item.id)
def test_each_hypothesis_has_deterministic_primary_and_corroboration_categories(hypothesis):
    result = evidence_coverage(hypothesis.id, [evidence("SOURCE-A")])

    assert result["hypothesis_id"] == hypothesis.id
    assert [item["role"] for item in result["categories"]] == ["PRIMARY", "CORROBORATION"]
    assert result["categories"][0]["covered_by_fresh_accepted"] is True
    assert result["categories"][1]["covered_by_fresh_accepted"] is False
    assert result["categories"][1]["non_independent"] is True
    assert all(item["association"] == "semantic_relation" for item in result["categories"])


def test_unverified_stale_and_disputed_matching_evidence_are_distinguished():
    items = [
        evidence("UNVERIFIED", state=EvidenceReviewState.UNVERIFIED),
        evidence("STALE", stale=True),
        evidence("DISPUTED", disputed=True),
    ]
    primary = evidence_coverage("CHECKLIST_UNAVAILABLE", items)["categories"][0]

    assert primary["covered_by_fresh_accepted"] is False
    assert {item["source_record_id"] for item in primary["matching_evidence"]} == {
        "UNVERIFIED", "STALE", "DISPUTED",
    }
    by_id = {item["source_record_id"]: item for item in primary["matching_evidence"]}
    assert by_id["UNVERIFIED"]["review_state"] == "UNVERIFIED"
    assert by_id["STALE"]["stale"] is True
    assert by_id["DISPUTED"]["disputed"] is True
    prompts = advisory_missing_evidence("CHECKLIST_UNAVAILABLE", items)
    assert any("unverified" in prompt and "UNVERIFIED" in prompt for prompt in prompts)
    assert any("stale" in prompt and "STALE" in prompt for prompt in prompts)
    assert any("challenged" in prompt and "DISPUTED" in prompt for prompt in prompts)


def test_same_source_group_does_not_count_as_independent_corroboration():
    result = evidence_coverage("STAFFING_CONSTRAINTS", [
        evidence("SOURCE-A", group="ORIGINAL"),
        evidence("SOURCE-B", group="ORIGINAL"),
    ])
    corroboration = result["categories"][1]

    assert corroboration["covered_by_fresh_accepted"] is False
    assert corroboration["non_independent"] is True
    assert corroboration["independent_source_groups"] == ["ORIGINAL"]
    assert any("independent corroborating source" in item for item in advisory_missing_evidence(
        "STAFFING_CONSTRAINTS", [evidence("SOURCE-A", group="ORIGINAL"), evidence("SOURCE-B", group="ORIGINAL")]
    ))


def test_distinct_source_groups_count_as_independent_advisory_corroboration():
    result = evidence_coverage("STAFFING_CONSTRAINTS", [
        evidence("SOURCE-A", group="GROUP-A"),
        evidence("SOURCE-B", group="GROUP-B"),
    ])
    corroboration = result["categories"][1]

    assert corroboration["covered_by_fresh_accepted"] is True
    assert corroboration["non_independent"] is False
    assert corroboration["independent_source_groups"] == ["GROUP-A", "GROUP-B"]
    assert not any("independent corroborating source" in item for item in advisory_missing_evidence(
        "STAFFING_CONSTRAINTS", [evidence("SOURCE-A", group="GROUP-A"), evidence("SOURCE-B", group="GROUP-B")]
    ))


def test_neutral_and_unclassified_evidence_are_not_called_missing_or_covered():
    neutral = evidence("NEUTRAL", relation=Stance.NEUTRAL)
    unclassified = evidence("UNCLASSIFIED")
    unclassified.semantic_relation = None
    result = evidence_coverage("PMS_SYSTEM_ISSUE", [neutral, unclassified])["categories"][0]

    assert result["covered_by_fresh_accepted"] is False
    assert result["matching_evidence"] == []
    assert result["neutral_evidence_ids"] == ["NEUTRAL"]
    assert result["unclassified_evidence_ids"] == ["UNCLASSIFIED"]
    prompts = advisory_missing_evidence("PMS_SYSTEM_ISSUE", [neutral, unclassified])
    assert any("Only neutral evidence" in item for item in prompts)
    assert not any("No matching reviewed evidence" in item for item in prompts)


def test_no_matching_evidence_generates_hypothesis_specific_advisory_prompts():
    prompts = advisory_missing_evidence("TIME_PRESSURE", [])

    assert any("available time to review open handover items" in item for item in prompts)
    assert all("A recent handover record that directly addresses this hypothesis." not in item for item in prompts)


def test_coverage_is_deterministic_and_does_not_mutate_input():
    items = [evidence("SOURCE-B", group="GROUP-B"), evidence("SOURCE-A", group="GROUP-A")]
    before = deepcopy(items)

    first = evidence_coverage("TRAINING_GAP", items)
    second = evidence_coverage("TRAINING_GAP", items)

    assert first == second
    assert items == before


@pytest.mark.parametrize("hypothesis", [None, "UNKNOWN", [], 42])
def test_unknown_hypothesis_is_rejected(hypothesis):
    with pytest.raises(ValueError, match="Unknown hypothesis"):
        evidence_coverage(hypothesis, [])
