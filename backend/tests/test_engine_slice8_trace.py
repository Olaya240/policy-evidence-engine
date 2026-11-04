"""Slice-8 contracts: the explanation trace covers every evidence item it describes.

`challenge` rebuilds a trace from the *previous* trace plus at most one new
assessment, and `_claim` builds one from scratch. Both walk the evidence by
position and copy prior rows by index, so a short or misaligned prior list
silently produced fewer guard decisions than dispositions, and a missing
evaluation time was indistinguishable from a preserved stale flag. These tests
pin the row cardinality, the appended item's own guard decision, and the clock
stamp.
"""
from datetime import datetime, timezone

from app.engine import AssessmentEngine
from app.mock_provider import MockProvider, SEED_RECORDS

FIXED = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
HYPOTHESIS = "CHECKLIST_UNAVAILABLE"

# Explicit `assess_pair` fixtures for HYPOTHESIS, one per stance, so the claim
# carries more than one evidence item without any provider override.
SUPPORTING = "OPS-101"
CONTRADICTING = "OPS-110"
APPENDED = "OPS-108"
APPENDED_QUOTE = "handover sheet listed two rooms"


def seed(record_id: str):
    return next(item for item in SEED_RECORDS if item.id == record_id)


def engine() -> AssessmentEngine:
    return AssessmentEngine(MockProvider(), clock=lambda: FIXED)


def trace_of(claim: dict) -> dict:
    return claim["explanation_trace"]


def test_claim_emits_one_guard_decision_row_per_evidence_item():
    claim = engine().assess_hypothesis([seed(SUPPORTING), seed(CONTRADICTING)], HYPOTHESIS)
    trace = trace_of(claim)

    assert len(claim["evidence"]) == 2, "fixture must produce two assessable items"
    assert [row["source_record_id"] for row in trace["semantic_guard"]["decisions"]] == [
        item["source_record_id"] for item in claim["evidence"]
    ]
    # One row per item is not enough; the rows must be real guard decisions.
    assert all(
        row["reason_code"] != "PRIOR_GUARD_DECISION_UNAVAILABLE"
        for row in trace["semantic_guard"]["decisions"]
    )


def test_challenge_appends_a_real_guard_decision_and_covers_every_item():
    records = [seed(SUPPORTING), seed(CONTRADICTING)]
    engine_instance = engine()
    claim = engine_instance.assess_hypothesis(records, HYPOTHESIS)
    assert len(claim["evidence"]) == 2
    assert APPENDED not in [item["source_record_id"] for item in claim["evidence"]]

    changed = engine_instance.challenge(
        claim, [*records, seed(APPENDED)], APPENDED, APPENDED_QUOTE
    )
    trace = trace_of(changed)
    decisions = trace["semantic_guard"]["decisions"]

    assert [item["source_record_id"] for item in changed["evidence"]][-1] == APPENDED
    assert len(changed["evidence"]) == 3
    # (a) one semantic decision row per evidence item, in evidence order.
    assert [row["source_record_id"] for row in decisions] == [
        item["source_record_id"] for item in changed["evidence"]
    ]
    # (b) the newly appended item carries its own decision, not a legacy stub.
    assert decisions[-1]["source_record_id"] == APPENDED
    assert decisions[-1]["reason_code"] != "PRIOR_GUARD_DECISION_UNAVAILABLE"
    assert decisions[-1]["guard_enabled"] is True
    assert decisions[-1]["decision_source"] == "ASSESSMENT_REVIEW"
    # Untouched prior rows keep the decision recorded by the original trace.
    assert decisions[0] == trace_of(claim)["semantic_guard"]["decisions"][0]
    assert decisions[1] == trace_of(claim)["semantic_guard"]["decisions"][1]


def test_staleness_table_has_one_row_per_evidence_item():
    claim = engine().assess_hypothesis([seed(SUPPORTING), seed(CONTRADICTING)], HYPOTHESIS)
    trace = trace_of(claim)
    rows = trace["staleness_policy"]["evidence_evaluation_times"]
    assert len(rows) == len(claim["evidence"])
    assert [row["source_record_id"] for row in rows] == [
        item["source_record_id"] for item in claim["evidence"]
    ]

    changed = engine().challenge(
        engine().assess_hypothesis([seed(SUPPORTING), seed(CONTRADICTING)], HYPOTHESIS),
        [seed(SUPPORTING), seed(CONTRADICTING), seed(APPENDED)],
        APPENDED,
        APPENDED_QUOTE,
    )
    changed_rows = trace_of(changed)["staleness_policy"]["evidence_evaluation_times"]
    assert len(changed_rows) == len(changed["evidence"]) == 3
    assert [row["source_record_id"] for row in changed_rows] == [
        item["source_record_id"] for item in changed["evidence"]
    ]


def test_fresh_claim_has_no_unknown_missing_evaluation_time_row():
    claim = engine().assess_hypothesis([seed(SUPPORTING), seed(CONTRADICTING)], HYPOTHESIS)
    rows = trace_of(claim)["staleness_policy"]["evidence_evaluation_times"]

    assert rows, "the fixture must produce a staleness table"
    assert [row["basis"] for row in rows] == ["ASSESSMENT_VALIDATION"] * len(rows)
    assert all(row["evaluated_at"] is not None for row in rows)


def test_fresh_claim_generated_at_is_the_injected_clock():
    claim = engine().assess_hypothesis([seed(SUPPORTING)], HYPOTHESIS)
    trace = trace_of(claim)

    assert trace["generated_at"] == "2026-06-01T12:00:00Z"
    # The staleness policy is stamped from the same instant, not a second read.
    assert trace["staleness_policy"]["decision_evaluated_at"] == trace["generated_at"]
