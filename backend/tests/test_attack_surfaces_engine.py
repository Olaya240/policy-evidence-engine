"""Second probe batch: engine and store behaviour under hostile *shapes*, not bodies.

These are the attacks that arrive as valid JSON but hostile values: a huge corpus,
a quote made of spaces, a forged version number, an empty identifier.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app import store
from app.engine import AssessmentEngine
from app.mock_provider import SEED_RECORDS
from app.models import Evidence, HYPOTHESES, Record, Stance

CLOCK = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def engine():
    return AssessmentEngine(clock=lambda: CLOCK)


def synthetic(count: int) -> list[Record]:
    """Records that look like the seed corpus but at scale."""
    template = SEED_RECORDS[0]
    return [
        Record(
            id=f"SYN-{index:05d}",
            timestamp=template.timestamp,
            department=template.department,
            text=f"Checklist binder was missing at handover number {index}.",
            tags=[],
            source_group=f"g{index % 40}",
        )
        for index in range(count)
    ]


# 1. Capacity: measured at 43 records per call, refused above it — and refused
# fast, not by hanging. 44 is the first size the provider contract cannot carry
# (43 minimum-size proposals fill the 4 KiB body exactly).
def test_capacity_boundary_is_43_records_and_refused_fast_above_it():
    started = time.monotonic()
    claims = engine().investigate(synthetic(43))
    assert len(claims) == len(HYPOTHESES)
    assert time.monotonic() - started < 10.0

    started = time.monotonic()
    with pytest.raises(Exception) as excinfo:
        engine().investigate(synthetic(44))
    assert time.monotonic() - started < 10.0
    assert getattr(excinfo.value, "code", None) in {"malformed_output", "proposal_capacity_exceeded"}


# 2. An empty corpus must produce five honest claims, not an exception.
def test_an_empty_corpus_produces_one_claim_per_hypothesis():
    claims = engine().investigate([])

    assert [claim["hypothesis_id"] for claim in claims] == [entry.id for entry in HYPOTHESES]
    for claim in claims:
        assert claim["status"] == "INSUFFICIENT"
        assert claim["evidence"] == []


# 3. A whitespace quote passes `len(quote.strip()) < 3`? It must not.
def test_a_whitespace_only_quote_is_refused():
    claim = engine().assess_hypothesis(SEED_RECORDS, HYPOTHESES[0].id)
    record = next(record for record in SEED_RECORDS if not record.restricted)

    with pytest.raises(Exception) as excinfo:
        engine().challenge(claim, SEED_RECORDS, record.id, "     ")

    assert "quote" in str(excinfo.value).lower()


# 4. The store owns the version number: a caller cannot forge it.
def test_a_forged_claim_version_in_a_revised_claim_is_overwritten(tmp_path, monkeypatch):
    path = store.DATA_DIR / f".forged-{uuid4().hex}.sqlite3"
    monkeypatch.setenv("HACKATHON_DB_PATH", str(path))
    store.initialize_database()

    claims = [{"id": "claim-a", "hypothesis_id": "CHECKLIST_UNAVAILABLE",
               "version": 1, "dependencies": ["OPS-101"], "status": "PARTIAL"}]
    created = store.create_investigation("probe", claims)
    investigation_id = created["id"]

    snapshot = store.get_challenge_snapshot(investigation_id, "claim-a", "OPS-101")
    revised = {"claim-a": dict(snapshot["claims"]["claim-a"], version=999)}
    result = store.apply_challenge(
        investigation_id, "claim-a", "reason text", "OPS-101", "binder",
        expected_revision=snapshot["revision"],
        expected_claims=snapshot["claims"],
        revised_claims=revised,
    )

    assert result["after"]["claim-a"]["version"] == 2, "the caller's version was trusted"
    assert store.get_investigation(investigation_id)["version"] == 2


# 5. An empty evidence identifier must be refused rather than stored.
def test_an_evidence_with_no_source_record_id_is_refused():
    with pytest.raises(Exception):
        Evidence(
            source_record_id="",
            timestamp=CLOCK,
            quote="abc",
            stance=Stance.SUPPORTS,
            rationale="because",
            department="Front Office",
        )


# 6. One very large evidence list must not be quadratic.
def test_a_large_evidence_list_is_summarised_quickly():
    from app.engine import _summarize_status_decision

    template = Evidence(
        source_record_id="R0", timestamp=CLOCK, quote="abc", stance=Stance.SUPPORTS,
        rationale="because", department="Front Office", source_group="g0",
    )
    evidence = [
        template.model_copy(update={"source_record_id": f"R{index}", "source_group": f"g{index}"})
        for index in range(5_000)
    ]

    started = time.monotonic()
    decision = _summarize_status_decision(evidence)
    elapsed = time.monotonic() - started

    assert decision.status.value in {"SUPPORTED", "PARTIAL", "CONTRADICTED", "INSUFFICIENT"}
    assert elapsed < 2.0, f"summarising 5000 items took {elapsed:.2f}s"
