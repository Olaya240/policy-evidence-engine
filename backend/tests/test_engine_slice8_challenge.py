"""Slice-8 contracts for `challenge`'s copy, delta and refusal behavior.

`challenge` receives the same dict the route later passes as `expected_claims`,
so any in-place write into it becomes a false `StaleRevision`; it must also be
exactly one evidence item and one version ahead, refuse three malformed
challenges and one inadmissible record without revealing which, and be
idempotent in evidence count when the same record is challenged twice.

All four refusals report `code="invalid_assessment"`; the values asserted below
are the observed ones, recorded so a code split is a deliberate change.
"""
import json
from copy import deepcopy

import pytest

from app.engine import AssessmentEngine, AssessmentError
from app.mock_provider import MockProvider, SEED_RECORDS

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"
SUPPORTING = "OPS-101"          # SUPPORTS HYPOTHESIS
APPENDED = "OPS-102"            # CONTRADICTS HYPOTHESIS, absent from the base claim
RESTRICTED = "CANARY-RESTRICTED-001"
CANARY_TEXT = "RESTRICTED_CANARY_DO_NOT_DISCLOSE_8f2b1d"
QUOTE = "binder was missing"


def by_id(record_id):
    return next(record for record in SEED_RECORDS if record.id == record_id)


def base_claim():
    """One SUPPORTS item only, so a challenge has room to append a second."""
    return AssessmentEngine().assess_hypothesis([by_id(SUPPORTING)], HYPOTHESIS)


def test_challenge_does_not_mutate_the_callers_claim_dict():
    engine = AssessmentEngine()
    claim = base_claim()
    snapshot = deepcopy(claim)
    snapshot_bytes = json.dumps(claim, sort_keys=True)

    challenged = engine.challenge(claim, SEED_RECORDS, SUPPORTING, QUOTE)

    # The caller reuses this exact object as `expected_claims`.
    assert claim == snapshot
    assert json.dumps(claim, sort_keys=True) == snapshot_bytes
    # Not aliasing is the sharper property: a shared dict would survive == only
    # until something wrote through it.
    caller_items = [id(item) for item in claim["evidence"]]
    assert all(id(item) not in caller_items for item in challenged["evidence"])
    assert [item["disputed"] for item in claim["evidence"]] == [False]


def test_challenge_appends_exactly_one_evidence_item_and_bumps_version():
    engine = AssessmentEngine()
    claim = base_claim()
    assert claim["version"] == 1
    assert [item["source_record_id"] for item in claim["evidence"]] == [SUPPORTING]

    challenged = engine.challenge(
        claim, SEED_RECORDS, APPENDED,
        "digital checklist opened normally",
    )

    assert challenged["version"] == claim["version"] + 1
    assert len(challenged["evidence"]) == len(claim["evidence"]) + 1
    assert [item["source_record_id"] for item in challenged["evidence"]] == [SUPPORTING, APPENDED]
    appended = challenged["evidence"][-1]
    assert appended["disputed"] is True
    assert challenged["dependencies"] == [SUPPORTING, APPENDED]
    # The pre-existing item is untouched, not re-stamped.
    assert challenged["evidence"][0]["disputed"] is False
    assert challenged["evidence"][0]["quote"] == claim["evidence"][0]["quote"]


def test_challenge_refuses_unknown_record_id():
    with pytest.raises(AssessmentError) as excinfo:
        AssessmentEngine().challenge(base_claim(), SEED_RECORDS, "NOPE-999", QUOTE)
    assert excinfo.value.code == "invalid_assessment"   # observed
    assert "Source record was not found" in str(excinfo.value)


def test_challenge_refuses_quote_absent_from_the_record():
    with pytest.raises(AssessmentError) as excinfo:
        AssessmentEngine().challenge(base_claim(), SEED_RECORDS, SUPPORTING, "fabricated quote")
    assert excinfo.value.code == "invalid_assessment"   # observed
    assert "Challenge quote must be an exact source substring" in str(excinfo.value)


def test_challenge_refuses_a_two_character_quote_that_does_occur():
    record = by_id(SUPPORTING)
    assert "we" in record.text          # present, so only the length floor can refuse it
    with pytest.raises(AssessmentError) as excinfo:
        AssessmentEngine().challenge(base_claim(), SEED_RECORDS, SUPPORTING, "we")
    assert excinfo.value.code == "invalid_assessment"   # observed
    assert "Challenge quote must be an exact source substring" in str(excinfo.value)


def test_challenge_does_not_double_count_an_already_disputed_record():
    engine = AssessmentEngine()
    first = engine.challenge(base_claim(), SEED_RECORDS, SUPPORTING, QUOTE)
    assert [(item["source_record_id"], item["disputed"]) for item in first["evidence"]] == [
        (SUPPORTING, True),
    ]

    second = engine.challenge(first, SEED_RECORDS, SUPPORTING, QUOTE)

    assert len(second["evidence"]) == len(first["evidence"])
    assert [item["source_record_id"] for item in second["evidence"]].count(SUPPORTING) == 1
    assert second["evidence"][0]["disputed"] is True
    # Only the version moves; the disputed item is not duplicated.
    assert second["version"] == first["version"] + 1


def test_challenge_refuses_a_restricted_record():
    with pytest.raises(AssessmentError) as excinfo:
        AssessmentEngine().challenge(base_claim(), SEED_RECORDS, RESTRICTED, CANARY_TEXT)
    assert excinfo.value.code == "invalid_assessment"   # observed
    # Same message as an unknown id, deliberately: no existence oracle.
    assert "Source record was not found" in str(excinfo.value)
    assert "CANARY" not in str(excinfo.value)


def test_challenge_refuses_when_the_provider_offers_no_matching_candidate():
    # OPS-111 (a lamp repair) carries no assessment for this hypothesis, so the
    # quote is valid and the record admissible but there is nothing to dispute.
    with pytest.raises(AssessmentError) as excinfo:
        AssessmentEngine().challenge(base_claim(), SEED_RECORDS, "OPS-111", "lamp")
    assert excinfo.value.code == "invalid_assessment"   # observed
    assert "not an assessed dependency" in str(excinfo.value)


def test_challenge_re_evaluates_staleness_at_its_own_clock():
    """A challenge is a re-assessment: the persisted `stale` flags describe the
    clock they were written under, not the clock the challenge is answered at."""
    from datetime import datetime, timezone

    record = by_id(SUPPORTING).model_copy(
        update={"timestamp": datetime(2025, 6, 1, tzinfo=timezone.utc)}
    )
    records = [record]

    late = AssessmentEngine(clock=lambda: datetime(2026, 10, 25, tzinfo=timezone.utc))
    stale_claim = late.assess_hypothesis(records, HYPOTHESIS)
    assert stale_claim["status"] == "INSUFFICIENT"
    assert all(item["stale"] for item in stale_claim["evidence"])

    early = AssessmentEngine(clock=lambda: datetime(2025, 6, 2, tzinfo=timezone.utc))
    challenged = early.challenge(stale_claim, records, SUPPORTING, QUOTE)
    fresh = early.assess_hypothesis(records, HYPOTHESIS)

    # The API persists the challenged claim, so it must not contradict what the
    # engine would say about the same records at the same instant.
    assert challenged["status"] == fresh["status"]
    assert challenged["confidence"] == fresh["confidence"]
    assert all(not item["stale"] for item in challenged["evidence"])
    rows = challenged["explanation_trace"]["staleness_policy"]["evidence_evaluation_times"]
    assert rows and all(row["evaluated_at"] == "2025-06-02T00:00:00Z" for row in rows)
