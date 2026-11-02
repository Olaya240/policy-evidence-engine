"""Architecture invariants, not line contracts.

These are the properties the design claims to guarantee no matter which
hypothesis, which record or which clock is in play. They are the checks to run
before anyone says the architecture is safe:

1. A persisted claim always equals a fresh summarisation of its own evidence.
2. No restricted record — id or text — ever reaches the provider request.
3. The same records and the same clock always produce the same claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app import provider_safety
from app.engine import AssessmentEngine, _summarize_status_decision
from app.mock_provider import SEED_RECORDS
from app.models import HYPOTHESES, Evidence

CLOCK = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def engine():
    return AssessmentEngine(clock=lambda: CLOCK)


def test_every_claim_equals_a_fresh_summary_of_its_own_evidence():
    claims = engine().investigate(SEED_RECORDS)

    assert len(claims) == len(HYPOTHESES)
    for claim in claims:
        evidence = [Evidence.model_validate(entry) for entry in claim["evidence"]]
        decision = _summarize_status_decision(evidence)

        assert claim["status"] == decision.status.value, claim["hypothesis_id"]
        assert claim["confidence"] == decision.confidence, claim["hypothesis_id"]


def test_no_restricted_record_reaches_the_provider_request(monkeypatch):
    seen = []
    original = provider_safety.serialize_provider_request

    def recording(records, hypothesis_id):
        request = original(records, hypothesis_id)
        seen.append((list(records), json.dumps(getattr(request, "body", None), default=str),
                     repr(request)))
        return request

    monkeypatch.setattr(provider_safety, "serialize_provider_request", recording)

    engine().investigate(SEED_RECORDS)

    restricted = [record for record in SEED_RECORDS if record.restricted]
    assert restricted, "the seed corpus must contain a restricted record"
    assert seen, "the engine must have asked the provider at least once"

    for eligible, _body, rendered in seen:
        ids = {record.id for record in eligible}
        for record in restricted:
            assert record.id not in ids
            assert record.text not in rendered
            assert record.text not in _body


def test_the_same_records_and_clock_produce_the_same_claim():
    first = engine().investigate(SEED_RECORDS)
    second = engine().investigate(SEED_RECORDS)

    assert first == second


def test_a_challenged_claim_still_equals_its_own_reassessment():
    claims = engine().investigate(SEED_RECORDS)
    claim = next(entry for entry in claims if entry["hypothesis_id"] == "CHECKLIST_UNAVAILABLE")
    target = claim["evidence"][0]["source_record_id"]

    challenged = engine().challenge(claim, SEED_RECORDS, target, claim["evidence"][0]["quote"])
    evidence = [Evidence.model_validate(entry) for entry in challenged["evidence"]]
    decision = _summarize_status_decision(evidence)

    assert challenged["status"] == decision.status.value
    assert challenged["confidence"] == decision.confidence


def _body(request):
    return getattr(request, "body", None)
