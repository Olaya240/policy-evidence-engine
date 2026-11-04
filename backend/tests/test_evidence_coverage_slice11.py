"""Contracts of the advisory evidence-coverage table (slices 11-12).

Coverage is advisory: it describes what a claim's evidence already is. These
tests pin the parts a consumer can act on — the hypothesis guard, the two
coverage flags, direction, corroboration independence — and the parts the module
promises not to do (guess a relation from text, mutate its input).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.evidence_coverage import advisory_missing_evidence, evidence_coverage
from app.models import HYPOTHESES, Evidence, EvidenceReviewState, Stance

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def item(record_id, *, relation, review_state=EvidenceReviewState.ACCEPTED,
         stale=False, disputed=False, group=None):
    return Evidence(
        source_record_id=record_id,
        timestamp=NOW,
        quote="binder was missing",
        stance=relation or Stance.NEUTRAL,
        review_state=review_state,
        rationale="because",
        department="Front Office",
        source_group=group if group is not None else record_id,
        semantic_relation=relation,
        stale=stale,
        disputed=disputed,
    )


def test_every_hypothesis_in_the_model_has_a_category_table():
    for hypothesis in HYPOTHESES:
        coverage = evidence_coverage(hypothesis.id, [])
        assert coverage["categories"], hypothesis.id


def test_a_hypothesis_outside_the_table_is_a_value_error_not_a_key_error(monkeypatch):
    from app import evidence_coverage as module

    monkeypatch.setattr(module, "_KNOWN_HYPOTHESES", frozenset({"DECLARED_BUT_UNMAPPED"}))

    with pytest.raises(ValueError):
        evidence_coverage("DECLARED_BUT_UNMAPPED", [])


def test_a_non_list_or_foreign_element_is_a_type_error():
    with pytest.raises(TypeError):
        evidence_coverage("CHECKLIST_UNAVAILABLE", "not a list")
    with pytest.raises(TypeError):
        evidence_coverage("CHECKLIST_UNAVAILABLE", [{"source_record_id": "x"}])


def test_coverage_is_deterministic_and_does_not_mutate_its_input():
    evidence = [
        item("OPS-101", relation=Stance.SUPPORTS, group="g1"),
        item("OPS-110", relation=Stance.CONTRADICTS, group="g2"),
        item("OPS-108", relation=None),
    ]
    before = [entry.model_dump() for entry in evidence]

    first = evidence_coverage("CHECKLIST_UNAVAILABLE", evidence)
    second = evidence_coverage("CHECKLIST_UNAVAILABLE", evidence)

    assert first == second
    assert [entry.model_dump() for entry in evidence] == before


def test_a_contradiction_covers_the_category_but_points_against_it():
    coverage = evidence_coverage(
        "CHECKLIST_UNAVAILABLE", [item("OPS-110", relation=Stance.CONTRADICTS)]
    )
    primary = coverage["categories"][0]

    assert primary["role"] == "PRIMARY"
    assert primary["covered_by_fresh_accepted"] is True
    assert primary["covered_by_fresh_support"] is False
    assert primary["covered_by_fresh_contradiction"] is True
    assert primary["direction"] == "AGAINST"
    assert primary["fresh_accepted_contradiction_ids"] == ["OPS-110"]


def test_one_source_group_is_not_independent_corroboration_and_says_so():
    single = item("OPS-101", relation=Stance.SUPPORTS, group="g1")
    coverage = evidence_coverage("CHECKLIST_UNAVAILABLE", [single])
    corroboration = coverage["categories"][1]

    assert corroboration["role"] == "CORROBORATION"
    assert corroboration["covered_by_fresh_accepted"] is False
    assert corroboration["non_independent"] is True

    prompts = advisory_missing_evidence("CHECKLIST_UNAVAILABLE", [single])
    assert any("independent corroborating source" in prompt for prompt in prompts)

    two = [single, item("OPS-110", relation=Stance.SUPPORTS, group="g2")]
    corroboration = evidence_coverage("CHECKLIST_UNAVAILABLE", two)["categories"][1]
    assert corroboration["covered_by_fresh_accepted"] is True
    assert corroboration["non_independent"] is False


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"review_state": EvidenceReviewState.UNVERIFIED}, "Review unverified evidence"),
        ({"stale": True}, "matching evidence is stale"),
        ({"disputed": True}, "Review challenged evidence"),
    ],
)
def test_non_fresh_evidence_is_excluded_from_coverage_and_prompted_for(kwargs, needle):
    coverage = evidence_coverage(
        "CHECKLIST_UNAVAILABLE", [item("OPS-101", relation=Stance.SUPPORTS, **kwargs)]
    )
    primary = coverage["categories"][0]

    assert primary["covered_by_fresh_accepted"] is False
    assert primary["matching_evidence"][0]["source_record_id"] == "OPS-101"
    assert any(needle in prompt for prompt in
               advisory_missing_evidence("CHECKLIST_UNAVAILABLE",
                                         [item("OPS-101", relation=Stance.SUPPORTS, **kwargs)]))


def test_a_missing_relation_is_surfaced_not_guessed_from_stance():
    coverage = evidence_coverage(
        "CHECKLIST_UNAVAILABLE", [item("OPS-101", relation=None)]
    )
    primary = coverage["categories"][0]

    assert primary["covered_by_fresh_accepted"] is False
    assert primary["unclassified_evidence_ids"] == ["OPS-101"]
    prompts = advisory_missing_evidence("CHECKLIST_UNAVAILABLE", [item("OPS-101", relation=None)])
    assert any("lacks a reviewed relation" in prompt for prompt in prompts)


def test_neutral_evidence_is_reported_without_counting_as_coverage():
    coverage = evidence_coverage(
        "CHECKLIST_UNAVAILABLE", [item("OPS-101", relation=Stance.NEUTRAL)]
    )
    primary = coverage["categories"][0]

    assert primary["covered_by_fresh_accepted"] is False
    assert primary["direction"] == "NONE"
    assert primary["neutral_evidence_ids"] == ["OPS-101"]
    prompts = advisory_missing_evidence(
        "CHECKLIST_UNAVAILABLE", [item("OPS-101", relation=Stance.NEUTRAL)]
    )
    assert any("Only neutral evidence" in prompt for prompt in prompts)
