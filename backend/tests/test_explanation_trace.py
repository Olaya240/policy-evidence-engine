"""Versioned explanation trace tests using synthetic in-memory inputs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.engine import AssessmentEngine, summarize_status
from app.evidence_coverage import advisory_missing_evidence
from app.mock_provider import MockProvider
from app.models import Evidence, Record, Status, Stance
from app.semantic_guard import reviewed_relation, reviewed_relation_details


def _record(record_id, quote, *, days_old=1, department="Front Office", source_group=None):
    return Record(
        id=record_id,
        timestamp=datetime(2026, 10, 30, tzinfo=timezone.utc) - timedelta(days=days_old),
        department=department,
        text=quote,
        tags=[],
        source_group=source_group,
    )


def _claim(items):
    records = [
        _record(item["id"], item["quote"], days_old=item.get("days_old", 1),
                department=item.get("department", "Front Office"),
                source_group=item.get("source_group"))
        for item in items
    ]
    proposals = [
        {"source_record_id": item["id"], "quote": item["quote"],
         "stance": item["stance"], "rationale": "synthetic trace fixture"}
        for item in items
    ]
    provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": proposals})
    return AssessmentEngine(provider, semantic_guard=False).assess_hypothesis(
        records, "CHECKLIST_UNAVAILABLE"
    )


@pytest.mark.parametrize(
    "items,status,confidence,status_rule,confidence_rule",
    [
        ([{"id": "S", "quote": "support", "stance": "SUPPORTS"},
          {"id": "C", "quote": "contradiction", "stance": "CONTRADICTS"}],
         Status.PARTIAL, 0.0, "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED", "CONFIDENCE.V2_SIGNED_MARGIN"),
        ([{"id": "A", "quote": "fresh support", "stance": "SUPPORTS"},
          {"id": "B", "quote": "stale support", "stance": "SUPPORTS", "days_old": 120}],
         # The stale record is context: this is the single-fresh-support shape.
         Status.PARTIAL, 0.5, "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED", "CONFIDENCE.V2_SIGNED_MARGIN"),
        ([{"id": "A", "quote": "first support", "stance": "SUPPORTS", "department": "Front Office"},
          {"id": "B", "quote": "second support", "stance": "SUPPORTS", "department": "Housekeeping"}],
         Status.SUPPORTED, pytest.approx(2 / 3), "STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION", "CONFIDENCE.V2_SIGNED_MARGIN"),
        ([{"id": "A", "quote": "first support", "stance": "SUPPORTS", "department": "Front Office"},
          {"id": "B", "quote": "second support", "stance": "SUPPORTS", "department": "Front Office"}],
         Status.SUPPORTED, pytest.approx(2 / 3), "STATUS.V2_SUPPORT_OUTWEIGHS_CONTRADICTION", "CONFIDENCE.V2_SIGNED_MARGIN"),
        ([{"id": "A", "quote": "support", "stance": "SUPPORTS"}],
         Status.PARTIAL, 0.5, "STATUS.V2_DIRECTIONAL_EVIDENCE_BALANCED", "CONFIDENCE.V2_SIGNED_MARGIN"),
        ([{"id": "A", "quote": "contradiction", "stance": "CONTRADICTS"}],
         Status.CONTRADICTED, 0.5, "STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT", "CONFIDENCE.V2_SIGNED_MARGIN"),
        ([{"id": "A", "quote": "first contradiction", "stance": "CONTRADICTS"},
          {"id": "B", "quote": "second contradiction", "stance": "CONTRADICTS"}],
         Status.CONTRADICTED, pytest.approx(2 / 3), "STATUS.V2_CONTRADICTION_OUTWEIGHS_SUPPORT", "CONFIDENCE.V2_SIGNED_MARGIN"),
        ([{"id": "A", "quote": "stale support", "stance": "SUPPORTS", "days_old": 120}],
         Status.INSUFFICIENT, 0.0, "STATUS.V2_NO_DIRECTIONAL_EVIDENCE", "CONFIDENCE.V2_ZERO_MARGIN"),
        ([], Status.INSUFFICIENT, 0.0, "STATUS.V2_NO_DIRECTIONAL_EVIDENCE",
         "CONFIDENCE.V2_ZERO_MARGIN"),
        ([{"id": "A", "quote": "neutral", "stance": "NEUTRAL"}],
         Status.INSUFFICIENT, 0.0, "STATUS.V2_NO_DIRECTIONAL_EVIDENCE",
         "CONFIDENCE.V2_ZERO_MARGIN"),
    ],
    ids=["mixed", "fresh-and-stale", "diverse-support", "same-department-support",
         "single-support", "single-contradiction", "multiple-contradictions", "stale-only",
         "empty", "neutral-only"],
)
def test_trace_rule_ids_match_existing_status_branches(items, status, confidence, status_rule, confidence_rule):
    claim = _claim(items)
    trace = claim["explanation_trace"]
    assert claim["status"] == status.value
    assert claim["confidence"] == confidence
    assert trace["status_rule_id"] == status_rule
    assert trace["confidence_rule_id"] == confidence_rule
    assert trace["reasoning_rule_version"] == "story-connect-status-v2"
    assert trace["semantic_guard"]["rule_set_version"] == "phrase-guard-v1"
    assert trace["confidence_kind"] == "SIGNED_EVIDENCE_MARGIN_NOT_CALIBRATED_PROBABILITY"


def test_disputed_branch_has_stable_rule_id_and_original_stale_acceptance_behavior():
    source = _record("DISPUTED", "support")
    provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [
        {"source_record_id": source.id, "quote": source.text,
         "stance": "SUPPORTS", "rationale": "synthetic"},
    ]})
    engine = AssessmentEngine(provider, semantic_guard=False)
    before = engine.assess_hypothesis([source], "CHECKLIST_UNAVAILABLE")
    challenged = engine.challenge(before, [source], source.id, "support")
    assert before["confidence"] == .5
    assert challenged["status"] == Status.PARTIAL.value
    # The verdict is withheld, so the number describes the challenged
    # configuration: one source for, under review, is PARTIAL 0.5.
    assert challenged["confidence"] == .5
    assert challenged["explanation_trace"]["evidence_direction"] == "FOR"
    assert challenged["explanation_trace"]["status_rule_id"] == "STATUS.V2_DISPUTED_EVIDENCE_DECISION_RELEVANT"
    assert challenged["explanation_trace"]["confidence_rule_id"] == "CONFIDENCE.V2_ZERO_MARGIN"


def test_evidence_dispositions_cover_direction_neutral_unverified_stale_disputed_and_dependent():
    accepted = _claim([
        {"id": "SUP-A", "quote": "support a", "stance": "SUPPORTS", "source_group": "copy"},
        {"id": "SUP-B", "quote": "support b", "stance": "SUPPORTS", "source_group": "copy"},
        {"id": "CON", "quote": "contradiction", "stance": "CONTRADICTS"},
        {"id": "NEU", "quote": "neutral", "stance": "NEUTRAL"},
        {"id": "OLD", "quote": "old support", "stance": "SUPPORTS", "days_old": 120},
    ])
    by_id = {item["source_record_id"]: item["codes"]
             for item in accepted["explanation_trace"]["evidence_dispositions"]}
    assert by_id["SUP-A"] == ["COUNTED_SUPPORT", "DEPENDENT_SOURCE_GROUP"]
    assert by_id["SUP-B"] == ["COUNTED_SUPPORT"]
    assert by_id["CON"] == ["COUNTED_CONTRADICTION"]
    assert by_id["NEU"] == ["NEUTRAL_NOT_DIRECTIONAL"]
    assert by_id["OLD"] == ["STALE_HISTORICAL_CONTEXT"]
    assert accepted["explanation_trace"]["source_group_analysis"]["independent_support_group_count"] == 1
    assert accepted["explanation_trace"]["source_group_analysis"]["dependent_support_record_ids"] == ["SUP-A"]

    record = _record("UNVER", "A lamp was replaced.")
    mismatch_provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [
        {"source_record_id": record.id, "quote": record.text,
         "stance": "SUPPORTS", "rationale": "synthetic"},
    ]})
    unverified = AssessmentEngine(mismatch_provider).assess_hypothesis([record], "CHECKLIST_UNAVAILABLE")
    assert unverified["explanation_trace"]["evidence_dispositions"] == [
        {"source_record_id": "UNVER", "codes": ["UNVERIFIED_EXCLUDED"]}
    ]
    assert unverified["explanation_trace"]["semantic_guard"]["decisions"] == [{
        "source_record_id": "UNVER",
        "review_state": "UNVERIFIED",
        "proposed_stance": "SUPPORTS",
        "semantic_relation": None,
        "guard_enabled": True,
        "cue_ids": [],
        "reason_code": "NO_CUE_MATCH",
        "decision_source": "ASSESSMENT_REVIEW",
    }]

    source = _record("D", "support")
    dispute_provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [
        {"source_record_id": source.id, "quote": source.text,
         "stance": "SUPPORTS", "rationale": "synthetic"},
    ]})
    engine = AssessmentEngine(dispute_provider, semantic_guard=False)
    disputed = engine.challenge(engine.assess_hypothesis([source], "CHECKLIST_UNAVAILABLE"),
                                [source], source.id, "support")
    assert disputed["explanation_trace"]["evidence_dispositions"] == [
        {"source_record_id": "D", "codes": ["DISPUTED_REVIEW_REQUIRED"]}
    ]


@pytest.mark.parametrize(
    "quote,expected_relation,expected_cues,expected_reason",
    [
        ("The checklist was unavailable.", Stance.SUPPORTS,
         ["CHECKLIST_UNAVAILABLE.SUPPORTS.checklist_was_unavailable"], None),
        ("not checklist unavailable", None,
         ["CHECKLIST_UNAVAILABLE.SUPPORTS.checklist_unavailable"], "NEGATED_CUE"),
        ("There is no relevant phrase here.", None, [], "NO_CUE_MATCH"),
        ("The checklist was unavailable, but available now.", None,
         ["CHECKLIST_UNAVAILABLE.SUPPORTS.checklist_was_unavailable"],
         "CONTRAST_CHANGED_CURRENT_STATE"),
        ("checklist unavailable; checklist was available", None,
         ["CHECKLIST_UNAVAILABLE.CONTRADICTS.checklist_was_available",
          "CHECKLIST_UNAVAILABLE.SUPPORTS.checklist_unavailable"],
         "AMBIGUOUS_CUE_RELATIONS"),
    ],
)
def test_semantic_guard_trace_uses_only_actual_fixed_cues(quote, expected_relation, expected_cues, expected_reason):
    detail = reviewed_relation_details(quote, "CHECKLIST_UNAVAILABLE")
    assert reviewed_relation(quote, "CHECKLIST_UNAVAILABLE") == expected_relation
    assert detail["relation"] == expected_relation
    assert detail["cue_ids"] == expected_cues
    assert detail["reason_code"] == expected_reason


def test_trace_is_deterministic_except_time_and_does_not_mutate_inputs():
    record = _record("DET", "The checklist was unavailable.")
    provider = MockProvider(assessment_overrides={"CHECKLIST_UNAVAILABLE": [
        {"source_record_id": record.id, "quote": record.text,
         "stance": "SUPPORTS", "rationale": "synthetic"},
    ]})
    original = deepcopy(record.model_dump(mode="json"))
    engine = AssessmentEngine(provider)
    first = engine.assess_hypothesis([record], "CHECKLIST_UNAVAILABLE")["explanation_trace"]
    second = engine.assess_hypothesis([record], "CHECKLIST_UNAVAILABLE")["explanation_trace"]
    expected_cue = "CHECKLIST_UNAVAILABLE.SUPPORTS.checklist_was_unavailable"
    assert first["semantic_guard"]["decisions"][0]["cue_ids"] == [expected_cue]
    assert first["semantic_guard"]["decisions"][0]["reason_code"] == "CUE_MATCHES_PROPOSAL"
    assert first["staleness_policy"]["evidence_evaluation_times"][0]["evaluated_at"] == first["generated_at"]
    assert first["staleness_policy"]["comparison"] == "AGE_DAYS_GREATER_THAN_THRESHOLD"
    for trace in (first, second):
        trace["generated_at"] = None
        trace["staleness_policy"]["decision_evaluated_at"] = None
        for item in trace["staleness_policy"]["evidence_evaluation_times"]:
            item["evaluated_at"] = None
    assert first == second
    assert record.model_dump(mode="json") == original


def test_advisory_coverage_is_separate_from_status_and_confidence():
    claim = _claim([{"id": "SUP", "quote": "support", "stance": "SUPPORTS"}])
    trace = claim["explanation_trace"]
    evidence = [Evidence.model_validate(item) for item in claim["evidence"]]
    expected = summarize_status(evidence)
    assert trace["advisory_coverage"]["advisory_only"] is True
    assert trace["advisory_coverage"]["formal_evidence_sufficiency"] is False
    assert [category["category_id"] for category in trace["advisory_coverage"]["categories"]] == [
        "checklist_access_context", "independent_checklist_support",
    ]
    assert claim["status"] == Status.PARTIAL.value and claim["confidence"] == .5
    assert (claim["status"], claim["confidence"], claim["uncertainty"], claim["conflicts"]) == (
        expected[0].value, expected[1], expected[2], expected[3],
    )
    assert claim["missing_evidence"] == advisory_missing_evidence("CHECKLIST_UNAVAILABLE", evidence)
    assert claim["dependencies"] == ["SUP"]

