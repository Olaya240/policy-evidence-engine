"""Contract tests for the signed evidence fields on a claim.

The engine keeps `confidence` as a non-negative magnitude and carries the
direction separately, because a magnitude alone cannot distinguish "one source
for" from "one source against" — both are 0.5. These tests pin the pairing:

    confidence == abs(evidence_score)
    evidence_direction == "FOR" | "AGAINST" | "NONE"
    evidence_score == (support_groups - contradiction_groups)
                       / (support_groups + contradiction_groups + 1)

Expected scores are computed from the rule rather than hardcoded, so a change to
the table shows up as a formula mismatch instead of a magic number drifting.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.engine import AssessmentEngine
from app.mock_provider import MockProvider
from app.models import Claim, HYPOTHESES, Status

HYPOTHESIS = "CHECKLIST_UNAVAILABLE"


def record(record_id, text):
    return {
        "id": record_id,
        "timestamp": datetime.now(timezone.utc) - timedelta(days=1),
        "department": "Front Office",
        "text": text,
        "tags": [],
        "restricted": False,
    }


def _provider(record_id, text, stance):
    """A provider proposal the semantic guard accepts, so review_state is ACCEPTED."""
    return MockProvider(assessment_overrides={
        HYPOTHESIS: [{
            "source_record_id": record_id,
            "quote": text,
            "stance": stance,
            "rationale": "synthetic signing fixture",
        }],
        **{hypothesis.id: [] for hypothesis in HYPOTHESES if hypothesis.id != HYPOTHESIS},
    })


def _claim(record_id, text, stance):
    from app.models import Record

    source = Record.model_validate(record(record_id, text))
    engine = AssessmentEngine(_provider(record_id, text, stance))
    return engine.assess_hypothesis([source], HYPOTHESIS)


def score(support_groups, contradiction_groups):
    return (support_groups - contradiction_groups) / (
        support_groups + contradiction_groups + 1
    )


def test_single_support_signs_positive():
    claim = _claim("SIGN-SUPPORT", "The checklist was unavailable during handover.", "SUPPORTS")

    assert claim["evidence_direction"] == "FOR"
    assert claim["evidence_score"] == pytest.approx(score(1, 0))
    assert claim["evidence_score"] > 0
    assert claim["confidence"] == pytest.approx(abs(claim["evidence_score"]))


def test_single_contradiction_signs_negative_with_the_same_magnitude():
    for_claim = _claim("SIGN-FOR", "The checklist was unavailable during handover.", "SUPPORTS")
    against = _claim("SIGN-AGAINST", "The checklist was available during handover.", "CONTRADICTS")

    assert against["evidence_direction"] == "AGAINST"
    assert against["evidence_score"] == pytest.approx(score(0, 1))
    assert against["evidence_score"] < 0

    # The defect this contract exists to prevent: equal magnitudes.
    assert against["confidence"] == pytest.approx(for_claim["confidence"])
    assert against["evidence_score"] != pytest.approx(for_claim["evidence_score"])


@pytest.mark.parametrize("record_id,text,stance,s,c", [
    ("MAG-NONE", "A desk lamp was replaced before dinner.", "SUPPORTS", 0, 0),
    ("MAG-ONE", "The checklist was unavailable during handover.", "SUPPORTS", 1, 0),
    ("MAG-AGAINST", "The checklist was available during handover.", "CONTRADICTS", 0, 1),
])
def test_confidence_is_always_the_magnitude_of_the_signed_score(record_id, text, stance, s, c):
    claim = _claim(record_id, text, stance)

    assert claim["confidence"] == pytest.approx(abs(claim["evidence_score"]))
    assert claim["confidence"] == pytest.approx(abs(score(s, c)))
    assert claim["evidence_direction"] == ("FOR" if s > c else "AGAINST" if s < c else "NONE")


def test_json_round_trip_preserves_the_sign():
    claim = _claim("SIGN-JSON", "The checklist was available during handover.", "CONTRADICTS")

    payload = json.loads(Claim.model_validate(claim).model_dump_json())

    assert payload["evidence_score"] < 0
    assert payload["evidence_score"] == pytest.approx(claim["evidence_score"])
    assert payload["evidence_direction"] == "AGAINST"
    # A magnitude coercion anywhere in serialisation would show up here.
    assert payload["confidence"] == pytest.approx(abs(payload["evidence_score"]))


def test_serialized_trace_and_claim_carry_the_same_signed_score():
    claim = _claim("SIGN-TRACE", "The checklist was available during handover.", "CONTRADICTS")
    trace = claim.get("explanation_trace")

    assert trace is not None
    assert trace["evidence_score"] == pytest.approx(claim["evidence_score"])
    assert trace["evidence_direction"] == claim["evidence_direction"]


def test_a_legacy_claim_without_the_signed_fields_still_validates():
    legacy = {
        "id": HYPOTHESIS,
        "hypothesis_id": HYPOTHESIS,
        "status": Status.PARTIAL.value,
        "confidence": 0.5,
        "uncertainty": "legacy claim",
        "summary": "legacy claim",
        "evidence": [{
            "source_record_id": "LEGACY-1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "quote": "checklist was unavailable",
            "stance": "SUPPORTS",
            "rationale": "legacy evidence",
            "department": "Front Office",
        }],
        "conflicts": [],
        "missing_evidence": [],
        "dependencies": ["LEGACY-1"],
        "version": 1,
    }

    model = Claim.model_validate(legacy)

    assert model.evidence_score is None
    assert model.evidence_direction is None
    assert model.confidence == 0.5
